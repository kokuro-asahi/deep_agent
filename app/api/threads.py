from fastapi import APIRouter, Depends, Query

from app.auth import get_admin_user, get_current_user, require_own_user

from app.schemas import (
    ContextResetRequest,
    ContextResetResponse,
    CurrentUser,
    ThreadMessagesResponse,
    UserListResponse,
    UserThreadsResponse,
)
from app.services import RunService

router = APIRouter(prefix="/v1/threads", tags=["threads"])


@router.get("/users", response_model=UserListResponse)
async def users(limit: int = Query(default=100, ge=1, le=500), user: CurrentUser = Depends(get_admin_user)):
    return await RunService().users(limit)


@router.get("/mine", response_model=UserThreadsResponse)
async def my_threads(
    limit: int = Query(default=100, ge=1, le=500),
    user: CurrentUser = Depends(get_current_user),
):
    return await RunService().threads(user.user_id, limit)


@router.get("/by-user/{user_id}", response_model=UserThreadsResponse)
async def user_threads(
    user_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    user: CurrentUser = Depends(get_current_user),
):
    return await RunService().threads(require_own_user(user, user_id), limit)


@router.post("/{thread_id}/context", response_model=ContextResetResponse)
async def reset_context(
    thread_id: str,
    request: ContextResetRequest = ContextResetRequest(),
    user: CurrentUser = Depends(get_current_user),
):
    return await RunService().reset_context(require_own_user(user, request.user_id), thread_id)


@router.get("/{thread_id}/messages", response_model=ThreadMessagesResponse)
async def messages(
    thread_id: str,
    user_id: str | None = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
):
    return await RunService().messages(require_own_user(user, user_id), thread_id, page, page_size)
