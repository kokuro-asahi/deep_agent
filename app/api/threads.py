from fastapi import APIRouter, Query

from app.schemas import (
    ContextResetRequest,
    ContextResetResponse,
    ThreadMessagesResponse,
    UserListResponse,
    UserThreadsResponse,
)
from app.services import RunService

router = APIRouter(prefix="/v1/threads", tags=["threads"])


@router.get("/users", response_model=UserListResponse)
async def users(limit: int = Query(default=100, ge=1, le=500)):
    return await RunService().users(limit)


@router.get("/by-user/{user_id}", response_model=UserThreadsResponse)
async def user_threads(
    user_id: str,
    limit: int = Query(default=100, ge=1, le=500),
):
    return await RunService().threads(user_id, limit)


@router.post("/{thread_id}/context", response_model=ContextResetResponse)
async def reset_context(
    thread_id: str,
    request: ContextResetRequest,
):
    return await RunService().reset_context(request.user_id, thread_id)


@router.get("/{thread_id}/messages", response_model=ThreadMessagesResponse)
async def messages(
    thread_id: str,
    user_id: str = Query(min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    return await RunService().messages(user_id, thread_id, page, page_size)
