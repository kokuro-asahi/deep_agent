from fastapi import APIRouter, Query

from app.schemas import ContextResetRequest, ContextResetResponse, ThreadMessagesResponse
from app.services import RunService

router = APIRouter(prefix="/v1/threads", tags=["threads"])


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
