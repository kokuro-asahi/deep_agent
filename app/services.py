from collections.abc import AsyncIterator
from asyncio import to_thread
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.agent import AgentClient
from app.business_store import business_store
from app.config import get_settings
from app.errors import classify_run_error, preflight_image_downloads, raise_thread_not_found
from app.model_guard import ModelDisclosureGuard
from app.observability import current_request_id, duration_ms, log_agent_event, run_context
from app.role_prompts import load_role_prompt
from app.runtime import runtime
from app.schemas import (
    ContextResetResponse,
    RunRequest,
    RunResponse,
    ThreadMessagesResponse,
    Usage,
)
from app.usage import add_usage, empty_usage


class RunService:
    def __init__(self):
        settings = get_settings()
        self.agent = AgentClient(settings)
        self.model_guard = ModelDisclosureGuard(settings)

    async def validate_thread_exists(self, request: RunRequest) -> None:
        if not request.thread_id:
            return
        thread = await to_thread(business_store.get_thread, request.user_id, request.thread_id)
        if not thread:
            raise_thread_not_found()

    async def run_json(self, request: RunRequest) -> RunResponse:
        existing_run = await to_thread(
            business_store.get_run_by_client_message,
            request.user_id,
            request.client_message_id,
        )
        if existing_run:
            await _attach_request_context(
                existing_run.get("run_id"),
                request.user_id,
                existing_run.get("thread_id"),
                request.client_message_id,
            )
            return _response_from_run(existing_run)

        thread = await to_thread(
            business_store.get_or_create_thread,
            request.user_id,
            request.thread_id,
            request.agent_role,
        )
        if not thread:
            raise_thread_not_found()
        thread_id = thread["thread_id"]
        context_version = int(thread["context_version"])
        agent_role = thread.get("agent_role")
        run_id = f"run_{uuid4().hex}"
        content = _content(request)
        await _attach_request_context(run_id, request.user_id, thread_id, request.client_message_id)
        with run_context(
            run_id=run_id,
            user_id=request.user_id,
            thread_id=thread_id,
            client_message_id=request.client_message_id,
        ):
            sequence = await _db_event(
                "next_sequence",
                business_store.next_sequence,
                request.user_id,
                thread_id,
                input_summary={"thread_id": thread_id},
            )
            await _db_event(
                "create_run",
                business_store.create_run,
                run_id,
                request.user_id,
                thread_id,
                request.client_message_id,
                request.metadata,
                input_summary={"metadata_keys": sorted(request.metadata.keys())},
            )
            await _db_event(
                "save_user_message",
                business_store.save_message,
                run_id,
                request.user_id,
                thread_id,
                sequence,
                "user",
                content,
                0,
                input_summary=_content_summary(content),
            )
        try:
            with run_context(
                run_id=run_id,
                user_id=request.user_id,
                thread_id=thread_id,
                client_message_id=request.client_message_id,
            ):
                await to_thread(preflight_image_downloads, content)
                guard_result = await _model_guard_event(
                    self.model_guard.check,
                    content,
                    input_summary={
                        "mode": "json",
                        "agent_role": agent_role,
                        "context_version": context_version,
                        **_content_summary(content),
                    },
                )
                if guard_result["blocked"]:
                    message = guard_result["message"]
                    await _db_event(
                        "save_trace_messages",
                        business_store.save_trace_messages,
                        run_id,
                        request.user_id,
                        thread_id,
                        sequence,
                        [],
                        input_summary=_trace_summary([]),
                    )
                    await _db_event(
                        "save_assistant_message",
                        business_store.save_message,
                        run_id,
                        request.user_id,
                        thread_id,
                        sequence,
                        "assistant",
                        [{"type": "text", "text": message}],
                        1000,
                        input_summary={"text_length": len(message), "blocked_by_model_guard": True},
                    )
                    await _db_event(
                        "complete_run",
                        business_store.complete_run,
                        run_id,
                        message,
                        empty_usage(),
                        input_summary={"usage": empty_usage(), "blocked_by_model_guard": True},
                    )
                    log_agent_event(
                        event_type="run",
                        event_name="run_json",
                        status="completed",
                        output_summary={"text_length": len(message), "blocked_by_model_guard": True},
                    )
                    return RunResponse(
                        run_id=run_id,
                        user_id=request.user_id,
                        thread_id=thread_id,
                        status="completed",
                        message=message,
                        usage=Usage(**empty_usage()),
                    )
                result = await _agent_invoke_event(
                    self.agent.ainvoke,
                    _model_messages(agent_role, content),
                    request.user_id,
                    thread_id,
                    context_version,
                    input_summary={
                        "mode": "json",
                        "agent_role": agent_role,
                        "context_version": context_version,
                        **_content_summary(content),
                    },
                )
                trace_messages = result.get("trace_messages", [])
                await _db_event(
                    "save_trace_messages",
                    business_store.save_trace_messages,
                    run_id,
                    request.user_id,
                    thread_id,
                    sequence,
                    trace_messages,
                    input_summary=_trace_summary(trace_messages),
                )
                await _db_event(
                    "save_assistant_message",
                    business_store.save_message,
                    run_id,
                    request.user_id,
                    thread_id,
                    sequence,
                    "assistant",
                    [{"type": "text", "text": result["message"]}],
                    1000,
                    input_summary={"text_length": len(result["message"])},
                )
                await _db_event(
                    "complete_run",
                    business_store.complete_run,
                    run_id,
                    result["message"],
                    result.get("usage"),
                    input_summary={"usage": result.get("usage", {})},
                )
                log_agent_event(
                    event_type="run",
                    event_name="run_json",
                    status="completed",
                    output_summary={
                        "text_length": len(result["message"]),
                        "usage": result.get("usage", {}),
                    },
                )
            return RunResponse(
                run_id=run_id,
                user_id=request.user_id,
                thread_id=thread_id,
                status="completed",
                message=result["message"],
                usage=Usage(**result.get("usage", {})),
            )
        except Exception as exc:
            with run_context(
                run_id=run_id,
                user_id=request.user_id,
                thread_id=thread_id,
                client_message_id=request.client_message_id,
            ):
                log_agent_event(event_type="run", event_name="run_json", status="failed", error=exc)
                error_info = classify_run_error(exc)
                error = await _db_event(
                    "fail_run",
                    business_store.fail_run,
                    run_id,
                    error_info["code"],
                    error_info["message"],
                    error_info["retryable"],
                    input_summary={"code": error_info["code"]},
                )
            return RunResponse(
                run_id=run_id,
                user_id=request.user_id,
                thread_id=thread_id,
                status="failed",
                error=error,
            )

    async def run_stream(self, request: RunRequest) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        existing_run = await to_thread(
            business_store.get_run_by_client_message,
            request.user_id,
            request.client_message_id,
        )
        if existing_run:
            await _attach_request_context(
                existing_run.get("run_id"),
                request.user_id,
                existing_run.get("thread_id"),
                request.client_message_id,
            )
            response = _response_from_run(existing_run).model_dump(mode="json")
            event_name = "run.failed" if response["status"] == "failed" else "run.completed"
            yield event_name, response
            return

        thread = await to_thread(
            business_store.get_or_create_thread,
            request.user_id,
            request.thread_id,
            request.agent_role,
        )
        if not thread:
            raise_thread_not_found()
        run_id = f"run_{uuid4().hex}"
        thread_id = thread["thread_id"]
        context_version = int(thread["context_version"])
        agent_role = thread.get("agent_role")
        content = _content(request)
        await _attach_request_context(run_id, request.user_id, thread_id, request.client_message_id)
        with run_context(
            run_id=run_id,
            user_id=request.user_id,
            thread_id=thread_id,
            client_message_id=request.client_message_id,
        ):
            sequence = await _db_event(
                "next_sequence",
                business_store.next_sequence,
                request.user_id,
                thread_id,
                input_summary={"thread_id": thread_id},
            )
            await _db_event(
                "create_run",
                business_store.create_run,
                run_id,
                request.user_id,
                thread_id,
                request.client_message_id,
                request.metadata,
                input_summary={"metadata_keys": sorted(request.metadata.keys())},
            )
            await _db_event(
                "save_user_message",
                business_store.save_message,
                run_id,
                request.user_id,
                thread_id,
                sequence,
                "user",
                content,
                0,
                input_summary=_content_summary(content),
            )

        yield "run.started", {"run_id": run_id, "user_id": request.user_id, "thread_id": thread_id, "status": "running"}

        chunks: list[str] = []
        trace_messages: list[dict[str, Any]] = []
        usage = empty_usage()
        try:
            with run_context(
                run_id=run_id,
                user_id=request.user_id,
                thread_id=thread_id,
                client_message_id=request.client_message_id,
            ):
                await to_thread(preflight_image_downloads, content)
                guard_result = await _model_guard_event(
                    self.model_guard.check,
                    content,
                    input_summary={
                        "mode": "stream",
                        "agent_role": agent_role,
                        "context_version": context_version,
                        **_content_summary(content),
                    },
                )
                if guard_result["blocked"]:
                    message = guard_result["message"]
                    chunks.append(message)
                    yield "message.delta", {"run_id": run_id, "text": message}
                    await _db_event(
                        "save_trace_messages",
                        business_store.save_trace_messages,
                        run_id,
                        request.user_id,
                        thread_id,
                        sequence,
                        trace_messages,
                        input_summary=_trace_summary(trace_messages),
                    )
                    await _db_event(
                        "save_assistant_message",
                        business_store.save_message,
                        run_id,
                        request.user_id,
                        thread_id,
                        sequence,
                        "assistant",
                        [{"type": "text", "text": message}],
                        1000,
                        input_summary={"text_length": len(message), "blocked_by_model_guard": True},
                    )
                    await _db_event(
                        "complete_run",
                        business_store.complete_run,
                        run_id,
                        message,
                        usage,
                        input_summary={"usage": usage, "blocked_by_model_guard": True},
                    )
                    log_agent_event(
                        event_type="run",
                        event_name="run_stream",
                        status="completed",
                        output_summary={"text_length": len(message), "usage": usage, "blocked_by_model_guard": True},
                    )
                    yield "run.completed", RunResponse(
                        run_id=run_id,
                        user_id=request.user_id,
                        thread_id=thread_id,
                        status="completed",
                        message=message,
                        usage=Usage(**usage),
                    ).model_dump(mode="json")
                    return
                stream_start = perf_counter()
                log_agent_event(
                    event_type="model",
                    event_name="agent.stream",
                    status="started",
                    input_summary={
                        "mode": "stream",
                        "agent_role": agent_role,
                        "context_version": context_version,
                        **_content_summary(content),
                    },
                )
                try:
                    async for event in self.agent.astream_events(
                        _model_messages(agent_role, content),
                        request.user_id,
                        thread_id,
                        context_version,
                    ):
                        if event["type"] == "text":
                            text = event["text"]
                            chunks.append(text)
                            yield "message.delta", {"run_id": run_id, "text": text}
                        elif event["type"] == "trace":
                            trace_messages.append(event["message"])
                        elif event["type"] == "usage":
                            add_usage(usage, event["usage"])
                        elif event["type"] == "usage_total":
                            usage = event["usage"]
                except Exception as exc:
                    log_agent_event(
                        event_type="model",
                        event_name="agent.stream",
                        status="failed",
                        duration_ms=duration_ms(stream_start),
                        error=exc,
                    )
                    raise
                log_agent_event(
                    event_type="model",
                    event_name="agent.stream",
                    status="completed",
                    duration_ms=duration_ms(stream_start),
                    output_summary={
                        "text_length": sum(len(chunk) for chunk in chunks),
                        "trace": _trace_summary(trace_messages),
                        "usage": usage,
                    },
                )

            message = "".join(chunks)
            with run_context(
                run_id=run_id,
                user_id=request.user_id,
                thread_id=thread_id,
                client_message_id=request.client_message_id,
            ):
                await _db_event(
                    "save_trace_messages",
                    business_store.save_trace_messages,
                    run_id,
                    request.user_id,
                    thread_id,
                    sequence,
                    trace_messages,
                    input_summary=_trace_summary(trace_messages),
                )
                await _db_event(
                    "save_assistant_message",
                    business_store.save_message,
                    run_id,
                    request.user_id,
                    thread_id,
                    sequence,
                    "assistant",
                    [{"type": "text", "text": message}],
                    1000,
                    input_summary={"text_length": len(message)},
                )
                await _db_event(
                    "complete_run",
                    business_store.complete_run,
                    run_id,
                    message,
                    usage,
                    input_summary={"usage": usage},
                )
                log_agent_event(
                    event_type="run",
                    event_name="run_stream",
                    status="completed",
                    output_summary={"text_length": len(message), "usage": usage},
                )
            yield "run.completed", RunResponse(
                run_id=run_id,
                user_id=request.user_id,
                thread_id=thread_id,
                status="completed",
                message=message,
                usage=Usage(**usage),
            ).model_dump(mode="json")
        except Exception as exc:
            with run_context(
                run_id=run_id,
                user_id=request.user_id,
                thread_id=thread_id,
                client_message_id=request.client_message_id,
            ):
                log_agent_event(event_type="run", event_name="run_stream", status="failed", error=exc)
                error_info = classify_run_error(exc)
                error = await _db_event(
                    "fail_run",
                    business_store.fail_run,
                    run_id,
                    error_info["code"],
                    error_info["message"],
                    error_info["retryable"],
                    input_summary={"code": error_info["code"]},
                )
            yield "run.failed", {
                "run_id": run_id,
                "status": "failed",
                "error": error,
            }

    async def reset_context(self, user_id: str, thread_id: str) -> ContextResetResponse:
        thread = await to_thread(business_store.reset_context, user_id, thread_id)
        if not thread:
            raise_thread_not_found()
        return ContextResetResponse(
            user_id=user_id,
            thread_id=thread_id,
            context_start_sequence=thread["last_sequence"] + 1,
        )

    async def messages(self, user_id: str, thread_id: str, page: int, page_size: int) -> ThreadMessagesResponse:
        thread = await to_thread(business_store.get_thread, user_id, thread_id)
        if not thread:
            raise_thread_not_found()
        rows, total = await to_thread(business_store.paged_conversations, user_id, thread_id, page, page_size)
        pages = (total + page_size - 1) // page_size if total else 0
        return ThreadMessagesResponse(
            user_id=user_id,
            thread_id=thread_id,
            page=page,
            page_size=page_size,
            total_pages=pages,
            total_messages=total,
            has_more=page < pages,
            messages=rows,
        )


def _to_model_message(role: str, content: list[dict[str, Any]]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for block in content:
        if block.get("type") == "text":
            blocks.append({"type": "text", "text": block.get("text", "")})
        elif block.get("type") == "image":
            blocks.append({"type": "image_url", "image_url": {"url": block.get("url", "")}})
    return {"role": role, "content": blocks}


def _model_messages(agent_role: str | None, content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if agent_role:
        prompt = load_role_prompt(agent_role)
        if prompt:
            messages.append({"role": "system", "content": prompt})
    messages.append(_to_model_message("user", content))
    return messages


def _content(request: RunRequest) -> list[dict[str, Any]]:
    return [block.model_dump(exclude_none=True) for block in request.content]


async def _attach_request_context(
    run_id: str | None,
    user_id: str | None,
    thread_id: str | None,
    client_message_id: str | None,
) -> None:
    request_id = current_request_id()
    if not request_id:
        return
    try:
        await to_thread(
            business_store.attach_api_request_context,
            request_id,
            run_id,
            user_id,
            thread_id,
            client_message_id,
        )
    except Exception as exc:
        log_agent_event(
            event_type="db",
            event_name="attach_api_request_context",
            status="failed",
            error=exc,
        )


async def _db_event(event_name: str, operation, *args, input_summary: dict[str, Any] | None = None):
    start_time = perf_counter()
    try:
        result = await to_thread(operation, *args)
    except Exception as exc:
        log_agent_event(
            event_type="db",
            event_name=event_name,
            status="failed",
            duration_ms=duration_ms(start_time),
            input_summary=input_summary,
            error=exc,
        )
        raise
    log_agent_event(
        event_type="db",
        event_name=event_name,
        status="completed",
        duration_ms=duration_ms(start_time),
        input_summary=input_summary,
    )
    return result


async def _agent_invoke_event(operation, messages, user_id: str, thread_id: str, context_version: int, input_summary):
    start_time = perf_counter()
    log_agent_event(
        event_type="model",
        event_name="agent.invoke",
        status="started",
        input_summary=input_summary,
    )
    try:
        result = await operation(messages, user_id, thread_id, context_version)
    except Exception as exc:
        log_agent_event(
            event_type="model",
            event_name="agent.invoke",
            status="failed",
            duration_ms=duration_ms(start_time),
            input_summary=input_summary,
            error=exc,
        )
        raise
    log_agent_event(
        event_type="model",
        event_name="agent.invoke",
        status="completed",
        duration_ms=duration_ms(start_time),
        output_summary={
            "text_length": len(result.get("message", "")),
            "trace": _trace_summary(result.get("trace_messages", [])),
            "usage": result.get("usage", {}),
        },
    )
    return result


async def _model_guard_event(operation, content: list[dict[str, Any]], input_summary):
    start_time = perf_counter()
    log_agent_event(
        event_type="model",
        event_name="model_guard.check",
        status="started",
        input_summary=input_summary,
    )
    try:
        result = await operation(content)
    except Exception as exc:
        log_agent_event(
            event_type="model",
            event_name="model_guard.check",
            status="failed",
            duration_ms=duration_ms(start_time),
            input_summary=input_summary,
            error=exc,
        )
        raise
    log_agent_event(
        event_type="model",
        event_name="model_guard.check",
        status="completed",
        duration_ms=duration_ms(start_time),
        output_summary={
            "blocked": result.get("blocked", False),
            "action": result.get("action", "allow"),
        },
    )
    return result


def _content_summary(content: list[dict[str, Any]]) -> dict[str, Any]:
    text_length = sum(len(block.get("text", "")) for block in content if block.get("type") == "text")
    image_count = sum(1 for block in content if block.get("type") == "image")
    return {
        "content_blocks": len(content),
        "text_length": text_length,
        "image_count": image_count,
    }


def _trace_summary(trace_messages: list[dict[str, Any]]) -> dict[str, Any]:
    tool_calls = 0
    callbacks = 0
    tool_names: list[str] = []
    for message in trace_messages:
        role = message.get("role")
        content = message.get("content", [])
        if role == "tool_call":
            tool_calls += len(content)
        elif role == "tool_callback":
            callbacks += len(content)
        for item in content:
            if isinstance(item, dict) and item.get("tool_name"):
                tool_names.append(item["tool_name"])
    return {
        "messages": len(trace_messages),
        "tool_calls": tool_calls,
        "tool_callbacks": callbacks,
        "tool_names": sorted(set(tool_names)),
    }


def _response_from_run(run: dict[str, Any]) -> RunResponse:
    return RunResponse(
        run_id=run["run_id"],
        user_id=run["user_id"],
        thread_id=run["thread_id"],
        status=run["status"],
        message=run.get("message") or "",
        usage=Usage(**(run.get("usage") or {})),
        error=run.get("error"),
    )
