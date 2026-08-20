from typing import Any

from app.errors import ErrorCode, error_info


def tool_trace_sse_event(run_id: str, message: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    role = message.get("role")
    content = message.get("content", [])
    if not isinstance(content, list) or not content:
        return None
    record = content[0]
    if not isinstance(record, dict):
        return None

    tool_call_id = record.get("tool_call_id")
    tool_type = record.get("tool_name")
    if role == "tool_call":
        return (
            "tool.call.started",
            {
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "tool_type": tool_type,
                "arguments": record.get("arguments") or {},
            },
        )
    if role != "tool_callback":
        return None

    if record.get("status") == "error":
        payload = tool_result_content(record.get("error") or record.get("result"))
        message_text = payload if isinstance(payload, str) else "工具调用失败"
        return (
            "tool.call.failed",
            {
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "tool_type": tool_type,
                "error": error_info(ErrorCode.TOOL_CALL_FAILED, message_text, retryable=True),
            },
        )
    return (
        "tool.call.completed",
        {
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "tool_type": tool_type,
            "result": tool_result_content(record.get("result")),
        },
    )


def tool_result_content(payload: Any) -> Any:
    if isinstance(payload, dict) and payload.get("type") in {"json", "text"} and "content" in payload:
        return payload["content"]
    return payload
