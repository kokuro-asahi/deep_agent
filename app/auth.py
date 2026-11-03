"""Session authentication shared by HTTP business endpoints."""

import hashlib
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.business_store import business_store
from app.config import get_settings
from app.schemas import CurrentUser


SESSION_COOKIE = "deepagent_session"


def auth_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {
        "code": code, "message": message, "retryable": False,
    }})


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validate_browser_origin(request: Request) -> None:
    """Block cross-origin cookie writes, including login CSRF, without affecting API clients."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin:
        settings = get_settings()
        public = urlsplit(settings.public_base_url)
        allowed = {
            str(request.base_url).rstrip("/"),
            f"{public.scheme}://{public.netloc}",
            *settings.cors_allowed_origins,
        }
        if origin not in allowed:
            raise auth_error(403, "ORIGIN_NOT_ALLOWED", "请求来源不受信任")
    elif request.headers.get("sec-fetch-site") == "cross-site":
        raise auth_error(403, "ORIGIN_NOT_ALLOWED", "请求来源不受信任")


def session_token(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip() or len(token) > 512:
            raise auth_error(401, "AUTH_REQUIRED", "登录凭证无效或已过期")
        return token.strip()
    validate_browser_origin(request)
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 512:
        raise auth_error(401, "AUTH_REQUIRED", "请先登录")
    return token


async def get_current_user(request: Request) -> CurrentUser:
    token = session_token(request)
    row = await run_in_threadpool(business_store.get_session_user, token_hash(token))
    if row is None:
        raise auth_error(401, "AUTH_REQUIRED", "登录凭证无效或已过期")
    user = CurrentUser.model_validate(row)
    request.state.current_user = user
    return user


def require_own_user(user: CurrentUser, supplied_user_id: str | None) -> str:
    if supplied_user_id is not None and supplied_user_id != user.user_id:
        raise auth_error(403, "ACCESS_DENIED", "不能访问其他用户的会话")
    return user.user_id


async def get_admin_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise auth_error(403, "ACCESS_DENIED", "需要管理员权限")
    return user
