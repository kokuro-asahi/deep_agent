import logging
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any
from uuid import uuid4

from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.business_store import business_store
from app.observability import reset_request_id, set_request_id


logger = logging.getLogger("app.request")


async def request_log_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
    request_id_token = set_request_id(request_id)
    start_time = perf_counter()
    log_id = _start_request_log(request, request_id)
    response_size = 0
    status_code = 500
    error: dict[str, Any] | None = None

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        error = {"type": exc.__class__.__name__, "message": str(exc)}
        _complete_request_log(
            log_id,
            status_code,
            _duration_ms(start_time),
            response_size,
            "failed",
            error,
        )
        reset_request_id(request_id_token)
        raise

    response.headers["X-Request-ID"] = request_id
    original_body_iterator = response.body_iterator
    reset_request_id(request_id_token)

    async def logging_body_iterator() -> AsyncIterator[bytes]:
        nonlocal response_size, error
        body_request_id_token = set_request_id(request_id)
        try:
            async for chunk in original_body_iterator:
                response_size += len(chunk)
                yield chunk
        except Exception as exc:
            error = {"type": exc.__class__.__name__, "message": str(exc)}
            raise
        finally:
            final_status = "failed" if error or status_code >= 500 else "completed"
            _complete_request_log(
                log_id,
                status_code,
                _duration_ms(start_time),
                response_size,
                final_status,
                error,
            )
            reset_request_id(body_request_id_token)

    response.body_iterator = logging_body_iterator()
    return response


def _start_request_log(request: Request, request_id: str) -> int | None:
    try:
        return business_store.start_api_request_log(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            route=_route_path(request),
            query_string=request.url.query,
            client_host=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception:
        logger.exception("failed to create api request log")
        return None


def _complete_request_log(
    log_id: int | None,
    status_code: int,
    duration_ms: int,
    response_size_bytes: int,
    status: str,
    error: dict[str, Any] | None,
) -> None:
    if log_id is None:
        return
    try:
        business_store.complete_api_request_log(
            log_id=log_id,
            status_code=status_code,
            duration_ms=duration_ms,
            response_size_bytes=response_size_bytes,
            status=status,
            error=error,
        )
    except Exception:
        logger.exception("failed to complete api request log")


def _duration_ms(start_time: float) -> int:
    return max(0, round((perf_counter() - start_time) * 1000))


def _route_path(request: Request) -> str | None:
    route = request.scope.get("route")
    return getattr(route, "path", None)
