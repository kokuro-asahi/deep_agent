from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import get_current_user, require_own_user
from app.schemas import CurrentUser, RunCreateRequest, RunRequest, RunResponse
from app.services import RunService
from app.skills import skill_registry
from app.sse import stream_events

router = APIRouter(prefix="/v1", tags=["runs"])


@router.post("/runs", response_model=RunResponse)
async def create_run(body: RunCreateRequest, user: CurrentUser = Depends(get_current_user)):
    user_id = require_own_user(user, body.user_id)
    request = RunRequest.model_validate({**body.model_dump(), "user_id": user_id})
    if not request.thread_id:
        try:
            skill_registry.paths_for(request.active_skill_ids)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    service = RunService()
    if request.stream:
        await service.validate_thread_exists(request)
        return StreamingResponse(
            stream_events(service.run_stream(request)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return await service.run_json(request)
