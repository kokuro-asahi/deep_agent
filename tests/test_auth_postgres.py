"""Opt-in database integration test; never changes the application's existing tables."""

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.auth import token_hash
from app.business_store import BusinessStore, business_store
from app.config import get_settings
from app.main import create_app
from app.passwords import hash_password, verify_password


def test_auth_tables_and_sessions_with_postgres(request, monkeypatch):
    if not request.config.getoption("--auth-postgres"):
        pytest.skip("Use --auth-postgres to test an isolated PostgreSQL schema")
    store = BusinessStore(get_settings())
    schema = f"auth_test_{uuid4().hex}"
    with psycopg.connect(store.database_uri(), autocommit=True, connect_timeout=5) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with ConnectionPool(
                conninfo=store.database_uri(), min_size=1, max_size=2,
                kwargs={"row_factory": dict_row, "options": f"-csearch_path={schema}", "connect_timeout": 5},
            ) as pool:
                store.pool = pool
                store.setup()
                store.setup()  # Startup DDL must remain idempotent.
                with store.connection() as conn:
                    conn.execute("""
                        INSERT INTO app_users (user_id, username, password, access_level)
                        VALUES ('integration-user', 'integration', %s, 2)
                    """, (hash_password("测试明文密码"),))
                    conn.commit()
                # Database constraints protect manual account expansion as well.
                with pytest.raises(psycopg.errors.CheckViolation):
                    with store.connection() as conn:
                        conn.execute("UPDATE app_users SET access_level = 4")
                with pytest.raises(psycopg.errors.UniqueViolation):
                    with store.connection() as conn:
                        conn.execute("INSERT INTO app_users (user_id, username, password) VALUES ('other', 'integration', 'p')")

                monkeypatch.setattr(business_store, "pool", pool)
                # Do not enter TestClient's lifespan: that would start the model runtime.
                client = TestClient(create_app())
                try:
                    credentials = {"username": "integration", "password": "测试明文密码"}
                    response = client.post("/v1/auth/login", json=credentials)
                    assert response.status_code == 200
                    token = response.json()["access_token"]
                    assert "password" not in response.json()["user"]
                    assert "display_name" not in response.json()["user"]
                    with store.connection() as conn:
                        session = conn.execute("SELECT * FROM auth_sessions").fetchone()
                        assert session["token_hash"] == token_hash(token)
                        assert conn.execute("SELECT last_login_at FROM app_users WHERE username = 'integration'").fetchone()["last_login_at"] is not None
                    assert client.get("/v1/auth/me").json()["access_level"] == 2
                    with store.connection() as conn:
                        conn.execute("UPDATE app_users SET is_active = false")
                        conn.commit()
                    assert client.get("/v1/auth/me").status_code == 401
                    assert client.post("/v1/auth/login", json=credentials).status_code == 401
                    with store.connection() as conn:
                        conn.execute("UPDATE app_users SET is_active = true")
                        conn.execute("UPDATE auth_sessions SET expires_at = now() - interval '1 second'")
                        conn.commit()
                    assert client.get("/v1/auth/me").status_code == 401
                    response = client.post("/v1/auth/login", json=credentials)
                    assert response.status_code == 200
                    assert client.post("/v1/auth/logout").status_code == 204
                    assert client.get("/v1/auth/me").status_code == 401
                    with store.connection() as conn:
                        assert conn.execute("SELECT count(*) AS n FROM auth_sessions").fetchone()["n"] == 0
                    response = client.post("/v1/auth/login", json=credentials)
                    assert response.status_code == 200
                    with store.connection() as conn:
                        conn.execute("DELETE FROM app_users")
                        conn.commit()
                        assert conn.execute("SELECT count(*) AS n FROM auth_sessions").fetchone()["n"] == 0
                    assert client.get("/v1/auth/me").status_code == 401
                finally:
                    client.close()
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def admin_database(request, monkeypatch):
    if not request.config.getoption('--auth-postgres'):
        pytest.skip('Use --auth-postgres for account administration integration tests')
    store = BusinessStore(get_settings())
    schema = f'admin_test_{uuid4().hex}'
    with psycopg.connect(store.database_uri(), autocommit=True, connect_timeout=5) as owner:
        owner.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with ConnectionPool(conninfo=store.database_uri(), min_size=1, max_size=2,
                                kwargs={'row_factory': dict_row, 'options': f'-csearch_path={schema}', 'connect_timeout': 5}) as pool:
                store.pool = pool
                store.setup()
                monkeypatch.setattr(business_store, 'pool', pool)
                client = TestClient(create_app())
                other = TestClient(create_app())
                try:
                    yield store, client, other
                finally:
                    client.close()
                    other.close()
        finally:
            owner.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_admin_account_lifecycle_and_permission_revocation(admin_database):
    store, client, other = admin_database
    result = client.post('/v1/auth/login', json={'username': 'admin', 'password': 'admin'})
    assert result.status_code == 200
    assert result.json()['user']['is_admin'] is True
    admin_id = result.json()['user']['user_id']
    result = client.get('/v1/admin/users')
    assert result.status_code == 200 and result.json()['total'] == 1
    result = client.post('/v1/admin/users', json={'username': 'alice', 'password': '0000'})
    assert result.status_code == 201
    account = result.json()
    uid = account['user_id']
    assert account['access_level'] == 1 and account['is_active'] and not account['is_admin']
    assert 'password' not in account
    with store.connection() as conn:
        saved = conn.execute('SELECT password FROM app_users WHERE user_id = %s', (uid,)).fetchone()['password']
        assert saved != '0000' and verify_password('0000', saved)
    assert client.post('/v1/admin/users', json={'username': 'alice', 'password': 'different'}).status_code == 409
    assert client.get('/v1/admin/users?q=alice').json()['total'] == 1
    assert client.get('/v1/admin/users?limit=1&offset=1').json()['total'] == 2
    assert other.post('/v1/auth/login', json={'username': 'alice', 'password': '0000'}).status_code == 200
    assert other.get('/v1/admin/users').status_code == 403
    with store.connection() as conn:
        conn.execute("INSERT INTO agent_threads (user_id, thread_id, checkpoint_thread_id) VALUES (%s, 'old-thread', 'old-checkpoint')", (uid,))
        conn.commit()
    result = client.patch(f'/v1/admin/users/{uid}', json={'username': 'alice-renamed', 'access_level': 3, 'is_admin': True})
    assert result.status_code == 200 and result.json()['user_id'] == uid
    assert other.get('/v1/auth/me').json()['username'] == 'alice-renamed'
    assert other.get('/v1/admin/users').status_code == 200
    with store.connection() as conn:
        assert conn.execute('SELECT user_id FROM agent_threads').fetchone()['user_id'] == uid
    assert client.patch(f'/v1/admin/users/{uid}', json={'username': 'admin'}).status_code == 409
    assert client.patch(f'/v1/admin/users/{uid}', json={'is_admin': False}).status_code == 200
    assert other.get('/v1/admin/users').status_code == 403
    assert client.patch(f'/v1/admin/users/{admin_id}', json={'is_admin': False}).status_code == 403
    assert client.patch(f'/v1/admin/users/{admin_id}', json={'is_active': False}).status_code == 403
    assert client.patch('/v1/admin/users/missing', json={'access_level': 2}).status_code == 404
    # Disabling an account revokes its session; reenabling must not revive old tokens.
    assert client.patch(f'/v1/admin/users/{uid}', json={'is_active': False}).status_code == 200
    assert other.get('/v1/auth/me').status_code == 401
    assert other.post('/v1/auth/login', json={'username': 'alice-renamed', 'password': '0000'}).status_code == 401
    assert client.patch(f'/v1/admin/users/{uid}', json={'is_active': True}).status_code == 200
    assert other.get('/v1/auth/me').status_code == 401
    assert other.post('/v1/auth/login', json={'username': 'alice-renamed', 'password': '0000'}).status_code == 200
    assert client.patch(f'/v1/admin/users/{uid}', json={'password': 'new-password'}).status_code == 200
    assert other.get('/v1/auth/me').status_code == 401
    assert other.post('/v1/auth/login', json={'username': 'alice-renamed', 'password': '0000'}).status_code == 401
    assert other.post('/v1/auth/login', json={'username': 'alice-renamed', 'password': 'new-password'}).status_code == 200
    # The database write path also rechecks the acting administrator.
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as forbidden:
        store.update_account(admin_id, uid, {'is_admin': False})
    assert forbidden.value.status_code == 403
    # Changing the administrator's own password revokes their session as well.
    assert client.patch(f'/v1/admin/users/{admin_id}', json={'password': 'changed-admin-password', 'username': 'root-admin'}).status_code == 200
    assert client.get('/v1/auth/me').status_code == 401
    store.setup()
    assert client.post('/v1/auth/login', json={'username': 'admin', 'password': 'admin'}).status_code == 401
    assert client.post('/v1/auth/login', json={'username': 'root-admin', 'password': 'changed-admin-password'}).status_code == 200
    assert client.get('/v1/admin/users').json()['total'] == 2
