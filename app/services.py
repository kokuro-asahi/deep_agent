from collections.abc import AsyncIterator
from asyncio import to_thread
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.agent import AgentClient
from app.business_store import business_store
from app.config import get_settings
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
        self.agent = AgentClient(get_settings())

    async def validate_thread_exists(self, request: RunRequest) -> None:
        if not request.thread_id:
            return
        thread = await to_thread(business_store.get_thread, request.user_id, request.thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="thread not found")

    async def run_json(self, request: RunRequest) -> RunResponse:
        existing_run = await to_thread(
            business_store.get_run_by_client_message,
            request.user_id,
            request.client_message_id,
        )
        if existing_run:
            return _response_from_run(existing_run)

        thread = await to_thread(
            business_store.get_or_create_thread,
            request.user_id,
            request.thread_id,
            request.agent_role,
        )
        if not thread:
            raise HTTPException(status_code=404, detail="thread not found")
        thread_id = thread["thread_id"]
        context_version = int(thread["context_version"])
        agent_role = thread.get("agent_role")
        run_id = f"run_{uuid4().hex}"
        sequence = await to_thread(business_store.next_sequence, request.user_id, thread_id)
        content = _content(request)
        await to_thread(
            business_store.create_run,
            run_id,
            request.user_id,
            thread_id,
            request.client_message_id,
            request.metadata,
        )
        await to_thread(
            business_store.save_message,
            run_id,
            request.user_id,
            thread_id,
            sequence,
            "user",
            content,
            0,
        )
        try:
            result = await self.agent.ainvoke(
                _model_messages(agent_role, content),
                request.user_id,
                thread_id,
                context_version,
            )
            await to_thread(
                business_store.save_trace_messages,
                run_id,
                request.user_id,
                thread_id,
                sequence,
                result.get("trace_messages", []),
            )
            await to_thread(
                business_store.save_message,
                run_id,
                request.user_id,
                thread_id,
                sequence,
                "assistant",
                [{"type": "text", "text": result["message"]}],
                1000,
            )
            await to_thread(business_store.complete_run, run_id, result["message"], result.get("usage"))
            return RunResponse(
                run_id=run_id,
                user_id=request.user_id,
                thread_id=thread_id,
                status="completed",
                message=result["message"],
                usage=Usage(**result.get("usage", {})),
            )
        except Exception as exc:
            error = await to_thread(business_store.fail_run, run_id, "AGENT_RUN_FAILED", str(exc), True)
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
            yield "run.completed", _response_from_run(existing_run).model_dump(mode="json")
            return

        thread = await to_thread(
            business_store.get_or_create_thread,
            request.user_id,
            request.thread_id,
            request.agent_role,
        )
        if not thread:
            raise HTTPException(status_code=404, detail="thread not found")
        run_id = f"run_{uuid4().hex}"
        thread_id = thread["thread_id"]
        context_version = int(thread["context_version"])
        agent_role = thread.get("agent_role")
        sequence = await to_thread(business_store.next_sequence, request.user_id, thread_id)
        content = _content(request)
        await to_thread(
            business_store.create_run,
            run_id,
            request.user_id,
            thread_id,
            request.client_message_id,
            request.metadata,
        )
        await to_thread(
            business_store.save_message,
            run_id,
            request.user_id,
            thread_id,
            sequence,
            "user",
            content,
            0,
        )

        yield "run.started", {"run_id": run_id, "user_id": request.user_id, "thread_id": thread_id, "status": "running"}

        chunks: list[str] = []
        trace_messages: list[dict[str, Any]] = []
        usage = empty_usage()
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

            message = "".join(chunks)
            await to_thread(
                business_store.save_trace_messages,
                run_id,
                request.user_id,
                thread_id,
                sequence,
                trace_messages,
            )
            await to_thread(
                business_store.save_message,
                run_id,
                request.user_id,
                thread_id,
                sequence,
                "assistant",
                [{"type": "text", "text": message}],
                1000,
            )
            await to_thread(business_store.complete_run, run_id, message, usage)
            yield "run.completed", RunResponse(
                run_id=run_id,
                user_id=request.user_id,
                thread_id=thread_id,
                status="completed",
                message=message,
                usage=Usage(**usage),
            ).model_dump(mode="json")
        except Exception as exc:
            error = await to_thread(business_store.fail_run, run_id, "AGENT_RUN_FAILED", str(exc), True)
            yield "run.failed", {
                "run_id": run_id,
                "status": "failed",
                "error": error,
            }

    async def reset_context(self, user_id: str, thread_id: str) -> ContextResetResponse:
        thread = await to_thread(business_store.reset_context, user_id, thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="thread not found")
        return ContextResetResponse(
            user_id=user_id,
            thread_id=thread_id,
            context_start_sequence=thread["last_sequence"] + 1,
        )

    async def messages(self, user_id: str, thread_id: str, page: int, page_size: int) -> ThreadMessagesResponse:
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
