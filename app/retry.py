from collections.abc import Callable
from time import sleep
from typing import Any, TypeVar


T = TypeVar("T")


def retry_sync(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    initial_delay: float = 0.2,
    backoff: float = 2.0,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Callable[[int, BaseException, float], Any] | None = None,
) -> T:
    last_error: BaseException | None = None
    delay = initial_delay
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except retry_exceptions as exc:
            last_error = exc
            if attempt >= attempts:
                break
            if on_retry:
                on_retry(attempt, exc, delay)
            sleep(delay)
            delay *= backoff
    if last_error:
        raise last_error
    raise RuntimeError("retry operation failed without an exception")
