from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE, token_hash
from app.business_store import business_store
from app.passwords import hash_password, verify_password
from app.main import create_app
from app.services import RunService


@pytest.fixture
def auth_client(monkeypatch):
    accounts = {
        "alice": {
            "user_id": "user_alice", "username": "alice", "password": "测试密码",
            "access_level": 1, "is_admin": False, "is_active": True,
        },
        "admin": {
            "user_id": "user_admin", "username": "admin", "password": "admin-password",
            "access_level": 3, "is_admin": True, "is_active": True,
        },
    }
    for account in accounts.values():
        account["password"] = hash_password(account["password"])
    sessions = {}

    def create_session(user_id, password, digest, expires_at):
        account = next(row for row in accounts.values() if row["user_id"] == user_id)
        if not account["is_active"] or account["password"] != password:
            return False
        sessions[digest] = {"user_id": user_id, "expires_at": expires_at}
        return True

    def get_session(digest):
        session = sessions.get(digest)
        if session is None or session["expires_at"] <= datetime.now(timezone.utc):
            return None
        account = next(row for row in accounts.values() if row["user_id"] == session["user_id"])
        return account if account["is_active"] else None

    monkeypatch.setattr(business_store, "get_login_user", accounts.get)
    monkeypatch.setattr(business_store, "create_auth_session", create_session)
    monkeypatch.setattr(business_store, "get_session_user", get_session)
    monkeypatch.setattr(business_store, "delete_auth_session", lambda digest: sessions.pop(digest, None))
    monkeypatch.setattr(business_store, "start_api_request_log", lambda **kwargs: None)
    client = TestClient(create_app())  # No lifespan: tests must not start the production DB/model.
    yield SimpleNamespace(client=client, accounts=accounts, sessions=sessions)
    client.close()


def login(state, username="alice", password="测试密码"):
    return state.client.post("/v1/auth/login", json={"username": username, "password": password})


def test_login_cookie_and_bearer_never_expose_password(auth_client):
    state = auth_client
    response = login(state)
    assert response.status_code == 200
    body = response.json()
    assert "password" not in body["user"]
    assert "display_name" not in body["user"]
    token = body["access_token"]
    assert token not in state.sessions
    assert token_hash(token) in state.sessions
    assert body["token_type"] == "bearer"
    assert body["user"]["access_level"] == 1
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert state.client.get("/v1/auth/me").json() == body["user"]
    state.client.cookies.clear()
    assert state.client.get("/v1/auth/me").status_code == 401
    response = state.client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.json() == body["user"]


@pytest.mark.parametrize("username,password", [("missing", "测试密码"), ("alice", "wrong")])
def test_invalid_login_is_generic(auth_client, username, password):
    response = login(auth_client, username, password)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert not auth_client.sessions
    assert SESSION_COOKIE not in response.cookies


def test_disabled_account_and_session_expiry(auth_client):
    state = auth_client
    login(state)
    state.accounts["alice"]["is_active"] = False
    assert state.client.get("/v1/auth/me").status_code == 401
    assert login(state).status_code == 401
    state.accounts["alice"]["is_active"] = True
    next(iter(state.sessions.values()))["expires_at"] = datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert state.client.get("/v1/auth/me").status_code == 401


def test_logout_revokes_copied_token_and_clears_cookie(auth_client):
    state = auth_client
    token = login(state).json()["access_token"]
    response = state.client.post("/v1/auth/logout")
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert state.client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert state.client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 204


def test_relogin_rotates_browser_session(auth_client):
    first = login(auth_client).json()["access_token"]
    second = login(auth_client).json()["access_token"]
    assert first != second
    assert token_hash(first) not in auth_client.sessions
    assert token_hash(second) in auth_client.sessions


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/v1/artifacts/ppt-preview?url=https://example.com/preview.pdf", None),
    ("GET", "/v1/auth/me", None),
    ("GET", "/v1/skills", None),
    ("GET", "/v1/threads/users", None),
    ("GET", "/v1/threads/mine", None),
    ("GET", "/v1/threads/by-user/user_alice", None),
    ("GET", "/v1/threads/thread/messages?user_id=user_alice", None),
    ("POST", "/v1/threads/thread/context", {}),
    ("POST", "/v1/runs", {"agent_role": "director", "content": [{"type": "text", "text": "hello"}]}),
])
def test_business_endpoints_require_login(auth_client, method, path, body):
    response = auth_client.client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert "text/event-stream" not in response.headers.get("content-type", "")


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/v1/threads/by-user/user_bob", None),
    ("GET", "/v1/threads/thread/messages?user_id=user_bob", None),
    ("POST", "/v1/threads/thread/context", {"user_id": "user_bob"}),
    ("POST", "/v1/runs", {"user_id": "user_bob", "agent_role": "director", "content": [{"type": "text", "text": "hello"}]}),
])
def test_user_id_cannot_impersonate_another_user(auth_client, method, path, body):
    login(auth_client)
    response = auth_client.client.request(method, path, json=body)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCESS_DENIED"


def test_admin_is_separate_from_knowledge_level(auth_client, monkeypatch):
    async def users(self, limit):
        return {"users": ["user_alice", "user_admin"]}

    monkeypatch.setattr(RunService, "users", users)
    auth_client.accounts["alice"]["access_level"] = 3
    login(auth_client)
    assert auth_client.client.get("/v1/threads/users").status_code == 403
    login(auth_client, "admin", "admin-password")
    assert auth_client.client.get("/v1/threads/users").status_code == 200
    # Administrators still cannot impersonate another user's conversation identity.
    assert auth_client.client.get("/v1/threads/by-user/user_alice").status_code == 403


def test_run_binds_authenticated_identity_for_json_and_stream(auth_client, monkeypatch):
    seen = []

    async def run_json(self, request):
        seen.append(request.user_id)
        return {"run_id": "run", "user_id": request.user_id, "thread_id": "thread", "status": "completed"}

    async def validate(self, request):
        seen.append(request.user_id)

    async def stream(self, request):
        yield "run.started", {"user_id": request.user_id}

    monkeypatch.setattr(RunService, "run_json", run_json)
    monkeypatch.setattr(RunService, "validate_thread_exists", validate)
    monkeypatch.setattr(RunService, "run_stream", stream)
    login(auth_client)
    body = {"agent_role": "director", "content": [{"type": "text", "text": "hello"}]}
    response = auth_client.client.post("/v1/runs", json={**body, "stream": False})
    assert response.status_code == 200
    assert response.json()["user_id"] == "user_alice"
    response = auth_client.client.post("/v1/runs", json=body)
    assert response.status_code == 200
    assert '"user_id":"user_alice"' in response.text
    assert seen == ["user_alice", "user_alice"]


def test_my_threads_and_history_use_session_identity(auth_client, monkeypatch):
    async def threads(self, user_id, limit):
        assert user_id == "user_alice"
        return {"user_id": user_id, "threads": []}

    monkeypatch.setattr(RunService, "threads", threads)
    monkeypatch.setattr(business_store, "get_thread", lambda user_id, thread_id: None)
    login(auth_client)
    assert auth_client.client.get("/v1/threads/mine").json()["user_id"] == "user_alice"
    # A known thread ID owned by somebody else remains inaccessible.
    assert auth_client.client.get("/v1/threads/other-users-thread/messages").status_code == 404
    assert auth_client.client.post("/v1/threads/other-users-thread/context", json={}).status_code == 404


def test_cross_origin_cookie_writes_rejected_bearer_clients_supported(auth_client):
    state = auth_client
    assert state.client.post("/v1/auth/login", json={"username": "alice", "password": "测试密码"},
                             headers={"Origin": "https://untrusted.example"}).status_code == 403
    token = login(state).json()["access_token"]
    assert state.client.post("/v1/auth/logout", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert state.client.post("/v1/auth/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert state.client.post("/v1/auth/logout", headers={"Origin": "http://testserver"}).status_code == 204
    # Explicit invalid credentials must never fall back to an otherwise valid cookie.
    login(state)
    assert state.client.get("/v1/auth/me", headers={"Authorization": "Basic bad"}).status_code == 401
    assert state.client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 204


def test_login_validation_never_echoes_password(auth_client):
    password = "secret-that-must-not-appear" * 100
    response = login(auth_client, password=password)
    assert response.status_code == 422
    assert password not in response.text
    assert "input" not in response.json()["details"][0]


def test_cookie_secure_setting(auth_client, monkeypatch):
    import app.api.auth as auth_api
    monkeypatch.setattr(auth_api, "get_settings", lambda: SimpleNamespace(
        auth_session_ttl_seconds=3600, auth_cookie_secure=True,
    ))
    response = login(auth_client)
    assert "Secure" in response.headers["set-cookie"]
    assert "Max-Age=3600" in response.headers["set-cookie"]


def test_health_and_static_shell_remain_public(auth_client):
    assert auth_client.client.get("/health").status_code == 200
    assert auth_client.client.get("/").status_code == 200


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/v1/admin/users", None),
    ("POST", "/v1/admin/users", {"username": "new", "password": "0000"}),
    ("PATCH", "/v1/admin/users/user_alice", {"access_level": 3}),
])
def test_account_management_is_admin_only(auth_client, method, path, body):
    assert auth_client.client.request(method, path, json=body).status_code == 401
    login(auth_client)
    assert auth_client.client.request(method, path, json=body).status_code == 403


def test_admin_can_create_list_and_update_accounts(auth_client, monkeypatch):
    from psycopg.errors import UniqueViolation

    calls = []
    row = {"user_id": "new-id", "username": "new", "access_level": 1,
           "is_admin": False, "is_active": True, "created_at": datetime.now(timezone.utc),
           "updated_at": datetime.now(timezone.utc), "last_login_at": None, "password": "must-not-return"}

    def create(values):
        assert values["password"] == "0000"
        calls.append(values)
        return row

    def update(uid, actor, values):
        assert (uid, actor) == ("new-id", "user_admin")
        assert values == {"access_level": 3, "is_active": False}
        return {**row, **values}

    monkeypatch.setattr(business_store, "create_account", create)
    monkeypatch.setattr(business_store, "update_account", update)
    monkeypatch.setattr(business_store, "list_accounts", lambda q, limit, offset: {"users": [row], "total": 1})
    login(auth_client, "admin", "admin-password")
    response = auth_client.client.post("/v1/admin/users", json={"username": " new ", "password": "0000"})
    assert response.status_code == 201
    assert calls[0]["username"] == "new"
    assert "password" not in response.json()
    response = auth_client.client.get("/v1/admin/users?q=new&limit=20&offset=0")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "password" not in response.json()["users"][0]
    response = auth_client.client.patch("/v1/admin/users/new-id", json={"access_level": 3, "is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    monkeypatch.setattr(business_store, "update_account", lambda *args: None)
    assert auth_client.client.patch("/v1/admin/users/missing", json={"access_level": 2}).status_code == 404

    def duplicate(*args):
        raise UniqueViolation()

    monkeypatch.setattr(business_store, "create_account", duplicate)
    monkeypatch.setattr(business_store, "update_account", duplicate)
    assert auth_client.client.post("/v1/admin/users", json={"username": "new", "password": "0000"}).status_code == 409
    assert auth_client.client.patch("/v1/admin/users/new-id", json={"username": "new"}).status_code == 409


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/v1/admin/users", {"username": "   ", "password": "sensitive"}),
    ("POST", "/v1/admin/users", {"username": "new", "password": "sensitive", "access_level": 4}),
    ("POST", "/v1/admin/users", {"username": "new", "password": "sensitive", "access_level": True}),
    ("POST", "/v1/admin/users", {"username": "new", "password": "sensitive", "user_id": "victim"}),
    ("PATCH", "/v1/admin/users/id", {}),
    ("PATCH", "/v1/admin/users/id", {"is_admin": None}),
    ("PATCH", "/v1/admin/users/id", {"password": ""}),
    ("PATCH", "/v1/admin/users/id", {"user_id": "victim"}),
])
def test_admin_validation_rejects_invalid_changes_without_echoing_password(auth_client, method, path, body):
    login(auth_client, "admin", "admin-password")
    response = auth_client.client.request(method, path, json=body)
    assert response.status_code == 422
    assert "sensitive" not in response.text
    assert all("input" not in item for item in response.json()["details"])


def test_password_hashes_are_salted_and_reject_invalid_values():
    first = hash_password("测试密码")
    second = hash_password("测试密码")
    assert first != second
    assert "测试密码" not in first
    assert verify_password("测试密码", first)
    assert not verify_password("wrong", first)
    assert not verify_password("测试密码", "测试密码")
    assert not verify_password("测试密码", "pbkdf2_sha256$bad$salt$digest")
