from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas import RunRequest, RunResponse
from app.services import RunService
from app.sse import stream_events

router = APIRouter(prefix="/v1", tags=["runs"])


@router.post("/runs", response_model=RunResponse)
async def create_run(request: RunRequest):
    service = RunService()
    if request.stream:
        return StreamingResponse(
            stream_events(service.run_stream(request)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return await service.run_json(request)
