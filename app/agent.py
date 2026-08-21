import json
from collections.abc import AsyncIterator
from asyncio import to_thread
from typing import Any

from app.config import Settings
from app.runtime import extract_text, runtime
from app.usage import add_usage, empty_usage, usage_from_message, usage_from_messages


_STREAM_DONE = object()


class AgentClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._agent = None

    def _ensure_agent(self) -> Any:
        if self.settings.agent_backend == "echo":
            return None
        if self.settings.agent_backend != "deepagents":
            raise ValueError(f"Unsupported AGENT_BACKEND: {self.settings.agent_backend}")
        if runtime.agent is None:
            runtime.start()
        return runtime.agent

    async def ainvoke(
        self,
        messages: list[dict[str, Any]],
        user_id: str,
        thread_id: str,
        context_version: int,
    ) -> dict[str, Any]:
        if self.settings.agent_backend == "echo":
            text = _last_user_text(messages)
            return {
                "message": f"Echo: {text}",
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            }

        agent = self._ensure_agent()
        result = await to_thread(
            agent.invoke,
            {"messages": messages},
            runtime.config(user_id, thread_id, context_version),
        )
        return _normalize_agent_result(result)

    async def astream_text(
        self,
        messages: list[dict[str, Any]],
        user_id: str,
        thread_id: str,
        context_version: int,
    ) -> AsyncIterator[str]:
        async for event in self.astream_events(messages, user_id, thread_id, context_version):
            if event["type"] == "text":
                yield event["text"]

    async def astream_events(
        self,
        messages: list[dict[str, Any]],
        user_id: str,
        thread_id: str,
        context_version: int,
    ) -> AsyncIterator[dict[str, Any]]:
        if self.settings.agent_backend == "echo":
            response = f"Echo: {_last_user_text(messages)}"
            for chunk in _chunk_text(response):
                yield {"type": "text", "text": chunk}
            return

        agent = self._ensure_agent()
        stream = agent.stream(
            {"messages": messages},
            runtime.config(user_id, thread_id, context_version),
            stream_mode="messages",
        )
        tool_call_chunks: dict[str, dict[str, Any]] = {}
        emitted_tool_calls: set[str] = set()
        total_usage = empty_usage()
        while True:
            event = await to_thread(_next_stream_item, stream)
            if event is _STREAM_DONE:
                break
            candidate = _candidate_message(event)
            usage = usage_from_message(candidate)
            if any(usage.values()):
                add_usage(total_usage, usage)
                yield {"type": "usage", "usage": usage}
            text = _extract_stream_text(candidate)
            if text:
                yield {"type": "text", "text": text}
            for record in _extract_stream_tool_calls(candidate, tool_call_chunks):
                key = _trace_key(record)
                if key in emitted_tool_calls:
                    continue
                emitted_tool_calls.add(key)
                yield {"type": "trace", "message": {"role": "tool_call", "content": [record]}}
            callback = _tool_callback_record(candidate)
            if callback:
                tool_call_id = callback.get("tool_call_id")
                if tool_call_id:
                    record = _tool_call_record_from_chunks(tool_call_chunks, tool_call_id)
                    key = _trace_key(record) if record else ""
                    if record and key not in emitted_tool_calls:
                        emitted_tool_calls.add(key)
                        yield {"type": "trace", "message": {"role": "tool_call", "content": [record]}}
                yield {"type": "trace", "message": {"role": "tool_callback", "content": [callback]}}

        for record in _flush_tool_call_chunks(tool_call_chunks):
            key = _trace_key(record)
            if key in emitted_tool_calls:
                continue
            emitted_tool_calls.add(key)
            yield {"type": "trace", "message": {"role": "tool_call", "content": [record]}}
        if any(total_usage.values()):
            yield {"type": "usage_total", "usage": total_usage}


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [block.get("text", "") for block in content if block.get("type") == "text"]
            return " ".join(texts).strip()
    return ""


def _chunk_text(text: str, size: int = 24) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


def _normalize_agent_result(result: Any) -> dict[str, Any]:
    messages = result.get("messages", []) if isinstance(result, dict) else []
    if messages:
        last = messages[-1]
        return {
            "message": extract_text(last),
            "usage": usage_from_messages(messages),
            "trace_messages": _extract_trace_messages(messages),
        }
    return {
        "message": "",
        "usage": empty_usage(),
        "trace_messages": [],
    }


def _extract_stream_text(event: Any) -> str:
    candidate = _candidate_message(event)
    message_type = getattr(candidate, "type", None)
    class_name = candidate.__class__.__name__
    if message_type not in {"ai", "AIMessageChunk"} and class_name not in {"AIMessage", "AIMessageChunk"}:
        return ""
    content = getattr(candidate, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return ""


def _candidate_message(event: Any) -> Any:
    if isinstance(event, tuple) and event:
        return event[0]
    return event


def _extract_trace_messages(messages: list[Any]) -> list[dict[str, Any]]:
    trace_messages: list[dict[str, Any]] = []
    for message in messages:
        for record in _tool_call_records(message):
            trace_messages.append({"role": "tool_call", "content": [record]})
        callback = _tool_callback_record(message)
        if callback:
            trace_messages.append({"role": "tool_callback", "content": [callback]})
    return trace_messages


def _tool_call_records(message: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    tool_calls = getattr(message, "tool_calls", None) or []
    for tool_call in tool_calls:
        name = _get_value(tool_call, "name")
        args = _get_value(tool_call, "args")
        tool_call_id = _get_value(tool_call, "id") or _get_value(tool_call, "tool_call_id")
        if not name:
            continue
        records.append(
            {
                "type": "tool_call",
                "tool_call_id": tool_call_id,
                "tool_name": name,
                "arguments": _jsonable(args),
            }
        )
    if records:
        return records

    raw_tool_calls = getattr(message, "additional_kwargs", {}).get("tool_calls", [])
    for tool_call in raw_tool_calls:
        function = tool_call.get("function", {})
        name = function.get("name")
        if not name:
            continue
        records.append(
            {
                "type": "tool_call",
                "tool_call_id": tool_call.get("id"),
                "tool_name": name,
                "arguments": _parse_json_object(function.get("arguments")),
            }
        )
    return records


def _extract_stream_tool_calls(
    message: Any,
    tool_call_chunks: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records = _tool_call_records(message)

    chunks = getattr(message, "tool_call_chunks", None) or []
    for index, chunk in enumerate(chunks):
        chunk_id = _get_value(chunk, "id")
        chunk_index = _get_value(chunk, "index")
        key = str(chunk_id or chunk_index or index)
        current = tool_call_chunks.setdefault(key, {"tool_call_id": chunk_id, "tool_name": "", "arguments": ""})
        if chunk_id:
            current["tool_call_id"] = chunk_id
        name = _get_value(chunk, "name")
        if name:
            current["tool_name"] = name
        args = _get_value(chunk, "args")
        if isinstance(args, str):
            current["arguments"] += args
        elif isinstance(args, dict):
            current["arguments"] = json.dumps(args, ensure_ascii=False)

    if records:
        return [record for record in records if _stream_tool_call_arguments_ready(record)]
    return []


def _tool_call_record_from_chunks(tool_call_chunks: dict[str, dict[str, Any]], tool_call_id: str) -> dict[str, Any] | None:
    for chunk in tool_call_chunks.values():
        if chunk.get("tool_call_id") != tool_call_id:
            continue
        if not chunk.get("tool_name"):
            return None
        record = _tool_call_record_from_chunk(chunk)
        if not _stream_tool_call_arguments_ready(record):
            return None
        return record
    return None


def _flush_tool_call_chunks(tool_call_chunks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for chunk in tool_call_chunks.values():
        if chunk.get("tool_name"):
            record = _tool_call_record_from_chunk(chunk)
            if _stream_tool_call_arguments_ready(record):
                records.append(record)
    return records


def _tool_call_record_from_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    raw_arguments = chunk.get("arguments") or ""
    return {
        "type": "tool_call",
        "tool_call_id": chunk.get("tool_call_id"),
        "tool_name": chunk.get("tool_name"),
        "arguments": _parse_json_object(raw_arguments),
    }


def _stream_tool_call_arguments_ready(record: dict[str, Any]) -> bool:
    arguments = record.get("arguments")
    if record.get("tool_name") == "bocha_search":
        return isinstance(arguments, dict) and bool(arguments)
    return arguments is not None


def _tool_callback_record(message: Any) -> dict[str, Any] | None:
    message_type = getattr(message, "type", None)
    class_name = message.__class__.__name__
    if message_type != "tool" and class_name != "ToolMessage":
        return None
    content = getattr(message, "content", "")
    status = getattr(message, "status", None) or "completed"
    return {
        "type": "tool_callback",
        "tool_call_id": getattr(message, "tool_call_id", None),
        "tool_name": getattr(message, "name", None),
        "status": status,
        "result": _result_payload(content),
        "error": _result_payload(content) if status == "error" else None,
    }


def _result_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        parsed = _parse_json_object(content)
        if parsed != content:
            return {"type": "json", "content": parsed}
        return {"type": "text", "content": content}
    return {"type": "json", "content": _jsonable(content)}


def _parse_json_object(value: Any) -> Any:
    if not isinstance(value, str):
        return _jsonable(value)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _trace_key(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)


def _next_stream_item(stream: Any) -> Any:
    try:
        return next(stream)
    except StopIteration:
        return _STREAM_DONE
