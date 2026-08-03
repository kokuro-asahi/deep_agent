from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.api.runs import router as runs_router
from app.api.threads import router as threads_router
from app.business_store import business_store
from app.errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from app.request_logging import request_log_middleware
from app.runtime import runtime


def create_app() -> FastAPI:
    app = FastAPI(title="Deep Agents Interface Backend", version="0.1.0")
    static_dir = Path(__file__).resolve().parent / "static"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(request_log_middleware)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(runs_router)
    app.include_router(threads_router)

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.on_event("startup")
    def startup() -> None:
        business_store.start()
        runtime.start()

    @app.on_event("shutdown")
    def shutdown() -> None:
        runtime.stop()
        business_store.stop()

    return app


app = create_app()
