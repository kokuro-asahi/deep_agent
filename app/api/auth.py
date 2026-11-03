import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from app.auth import (
    SESSION_COOKIE, auth_error, get_current_user, session_token, token_hash,
    validate_browser_origin,
)
from app.business_store import business_store
from app.config import get_settings
from app.passwords import DUMMY_PASSWORD_HASH, verify_password
from app.schemas import CurrentUser, LoginRequest, LoginResponse


router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, response: Response):
    validate_browser_origin(request)
    row = await run_in_threadpool(business_store.get_login_user, body.username)
    password = body.password.get_secret_value()
    valid = await run_in_threadpool(
        verify_password, password, row["password"] if row else DUMMY_PASSWORD_HASH,
    )
    if row is None or not row["is_active"] or not valid:
        raise auth_error(401, "INVALID_CREDENTIALS", "账号或密码错误")

    settings = get_settings()
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.auth_session_ttl_seconds)
    created = await run_in_threadpool(
        business_store.create_auth_session, row["user_id"], row["password"], token_hash(token), expires_at,
    )
    if not created:
        raise auth_error(401, "INVALID_CREDENTIALS", "账号或密码错误")
    # Rotate the browser's existing session on successful login.
    previous = request.cookies.get(SESSION_COOKIE)
    if previous and len(previous) <= 512:
        await run_in_threadpool(business_store.delete_auth_session, token_hash(previous))
    response.set_cookie(
        SESSION_COOKIE, token, max_age=settings.auth_session_ttl_seconds,
        httponly=True, secure=settings.auth_cookie_secure, samesite="lax", path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(access_token=token, expires_at=expires_at, user=CurrentUser.model_validate(row))


@router.get("/me", response_model=CurrentUser)
async def me(response: Response, user: CurrentUser = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request):
    # Revocation is idempotent, including an already expired or disabled session.
    token = session_token(request)
    await run_in_threadpool(business_store.delete_auth_session, token_hash(token))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=get_settings().auth_cookie_secure,
        httponly=True, samesite="lax",
    )
    return response
