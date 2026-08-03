import json
from collections.abc import Callable
from datetime import datetime
from http.client import HTTPResponse
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.observability import duration_ms, log_agent_event
from app.retry import retry_sync


def get_current_time(timezone_name: str = "Asia/Shanghai") -> str:
    """Get the current time for an IANA timezone, such as Asia/Shanghai or UTC."""
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return f"Unknown timezone: {timezone_name}"
    return datetime.now(timezone).isoformat(timespec="seconds")


def bocha_search(query: str, count: int = 5, freshness: str = "noLimit") -> dict[str, Any]:
    """Search the web with Bocha AI Search and return concise web results for current facts."""
    query = query.strip()
    if not query:
        raise ValueError("搜索内容不能为空")

    count = max(1, min(count, 10))
    settings = get_settings()
    if not settings.bocha_api_key:
        raise RuntimeError("缺少 BOCHA_API_KEY，无法调用博查搜索")

    payload = {
        "query": query,
        "freshness": freshness,
        "summary": True,
        "count": count,
    }
    request = Request(
        settings.bocha_api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.bocha_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    start_time = perf_counter()
    input_summary = {"query": query, "count": count, "freshness": freshness}
    try:
        result = retry_sync(
            lambda: _send_bocha_request(request),
            attempts=3,
            initial_delay=0.5,
            retry_exceptions=(_RetryableBochaError,),
            on_retry=lambda attempt, exc, delay: log_agent_event(
                event_type="retry",
                event_name="bocha_search",
                status="retrying",
                attempt=attempt,
                input_summary={**input_summary, "next_delay_seconds": delay},
                error=exc,
            ),
        )
    except _RetryableBochaError as exc:
        log_agent_event(
            event_type="tool",
            event_name="bocha_search",
            status="failed",
            duration_ms=duration_ms(start_time),
            input_summary=input_summary,
            error=exc,
        )
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        log_agent_event(
            event_type="tool",
            event_name="bocha_search",
            status="failed",
            duration_ms=duration_ms(start_time),
            input_summary=input_summary,
            error=exc,
        )
        raise

    normalized = _normalize_bocha_result(query, result)
    log_agent_event(
        event_type="tool",
        event_name="bocha_search",
        status="completed",
        duration_ms=duration_ms(start_time),
        input_summary=input_summary,
        output_summary={
            "count": normalized["count"],
            "titles": [item.get("title", "") for item in normalized["results"][:3]],
        },
    )
    return normalized


class _RetryableBochaError(RuntimeError):
    pass


def _send_bocha_request(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=30) as response:
            return _read_json_response(response)
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        if exc.code >= 500:
            raise _RetryableBochaError(f"博查 API 请求失败：HTTP {exc.code}，{error_body}") from exc
        raise RuntimeError(f"博查 API 请求失败：HTTP {exc.code}，{error_body}") from exc
    except URLError as exc:
        raise _RetryableBochaError(f"博查 API 网络请求失败：{exc.reason}") from exc
    except TimeoutError as exc:
        raise _RetryableBochaError("博查 API 请求超时") from exc


def _read_json_response(response: HTTPResponse) -> dict[str, Any]:
    body = response.read().decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("博查 API 响应不是 JSON 对象")
    return parsed


def _normalize_bocha_result(query: str, result: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in _extract_bocha_web_pages(result):
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "site_name": item.get("siteName", ""),
                "date_published": item.get("datePublished", ""),
                "snippet": item.get("summary") or item.get("snippet", ""),
            }
        )

    return {
        "query": query,
        "count": len(items),
        "results": items,
    }


def _extract_bocha_web_pages(result: dict[str, Any]) -> list[Any]:
    legacy_web_pages = result.get("data", {}).get("webPages", {}).get("value", [])
    if isinstance(legacy_web_pages, list) and legacy_web_pages:
        return legacy_web_pages

    pages: list[Any] = []
    messages = result.get("messages", [])
    if not isinstance(messages, list):
        return pages

    for message in messages:
        if not isinstance(message, dict) or message.get("content_type") != "webpage":
            continue
        content = _parse_bocha_content(message.get("content"))
        value = content.get("value") if isinstance(content, dict) else None
        if isinstance(value, list):
            pages.extend(value)
    return pages


def _parse_bocha_content(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}
    return content


def get_agent_tools() -> list[Callable[..., Any]]:
    return [
        get_current_time,
        bocha_search,
    ]
