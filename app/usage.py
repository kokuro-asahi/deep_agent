from typing import Any


def empty_usage() -> dict[str, int]:
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def usage_from_messages(messages: list[Any]) -> dict[str, int]:
    usage = empty_usage()
    for message in messages:
        add_usage(usage, usage_from_message(message))
    return usage


def usage_from_message(message: Any) -> dict[str, int]:
    usage_metadata = getattr(message, "usage_metadata", None)
    usage = normalize_usage(usage_metadata)
    if any(usage.values()):
        return usage

    response_metadata = getattr(message, "response_metadata", None) or {}
    for key in ("token_usage", "usage", "usage_metadata"):
        usage = normalize_usage(_get_value(response_metadata, key))
        if any(usage.values()):
            return usage
    return empty_usage()


def normalize_usage(raw_usage: Any) -> dict[str, int]:
    if not raw_usage:
        return empty_usage()
    input_tokens = usage_int(
        _get_value(raw_usage, "input_tokens")
        or _get_value(raw_usage, "prompt_tokens")
        or _get_value(raw_usage, "input_token_count")
    )
    output_tokens = usage_int(
        _get_value(raw_usage, "output_tokens")
        or _get_value(raw_usage, "completion_tokens")
        or _get_value(raw_usage, "output_token_count")
    )
    total_tokens = usage_int(
        _get_value(raw_usage, "total_tokens")
        or _get_value(raw_usage, "total_token_count")
        or _get_value(raw_usage, "total")
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens or input_tokens + output_tokens,
    }


def add_usage(total: dict[str, int], usage: dict[str, Any]) -> None:
    input_tokens = usage_int(usage.get("input_tokens"))
    output_tokens = usage_int(usage.get("output_tokens"))
    total_tokens = usage_int(usage.get("total_tokens")) or input_tokens + output_tokens
    total["input_tokens"] += input_tokens
    total["output_tokens"] += output_tokens
    total["total_tokens"] += total_tokens


def usage_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)
