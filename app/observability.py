import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any


logger = logging.getLogger("app.observability")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
thread_id_var: ContextVar[str | None] = ContextVar("thread_id", default=None)


def set_request_id(request_id: str | None) -> Token[str | None]:
    return request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    request_id_var.reset(token)


def current_request_id() -> str | None:
    return request_id_var.get()


@contextmanager
def run_context(
    *,
    run_id: str | None = None,
    user_id: str | None = None,
    thread_id: str | None = None,
):
    tokens = (
        run_id_var.set(run_id),
        user_id_var.set(user_id),
        thread_id_var.set(thread_id),
    )
    try:
        yield
    finally:
        run_id_var.reset(tokens[0])
        user_id_var.reset(tokens[1])
        thread_id_var.reset(tokens[2])


def log_agent_event(
    *,
    event_type: str,
    event_name: str,
    status: str,
    duration_ms: int | None = None,
    attempt: int | None = None,
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    error: BaseException | dict[str, Any] | None = None,
) -> None:
    try:
        from app.business_store import business_store

        business_store.record_agent_event(
            request_id=request_id_var.get(),
            run_id=run_id_var.get(),
            user_id=user_id_var.get(),
            thread_id=thread_id_var.get(),
            event_type=event_type,
            event_name=event_name,
            status=status,
            duration_ms=duration_ms,
            attempt=attempt,
            input_summary=input_summary,
            output_summary=output_summary,
            error=_error_payload(error),
        )
    except Exception:
        logger.exception("failed to record agent event")


def duration_ms(start_time: float) -> int:
    return max(0, round((perf_counter() - start_time) * 1000))


def _error_payload(error: BaseException | dict[str, Any] | None) -> dict[str, Any] | None:
    if error is None:
        return None
    if isinstance(error, dict):
        return error
    return {"type": error.__class__.__name__, "message": str(error)}
