"""Exercise serialized pre-upgrade checkpoints against the current agent stack."""

import asyncio
import base64
import json
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.exceptions import ModelRefusalError
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from app.agent import AgentClient
from app.config import Settings
from app.errors import classify_run_error
from app.runtime import AgentRuntime


class MigrationModel(FakeMessagesListChatModel):
    received: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        self.received.append(list(messages))
        result = super()._generate(messages, **kwargs)
        for generation in result.generations:
            generation.message = generation.message.model_copy(update={"id": None})
        return result


def _decode(value):
    if isinstance(value, dict):
        if "base64" in value:
            return base64.b64decode(value["base64"])
        return {_decode(key): _decode(item) for key, item in value["entries"]}
    if isinstance(value, list):
        return tuple(_decode(item) for item in value)
    return value


def _legacy_saver():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "deepagents-0.7.0b2-checkpoint.json").read_text())
    assert fixture["versions"]["deepagents"] == "0.7.0b2"
    saver = InMemorySaver()
    for thread_id, namespaces in _decode(fixture["storage"]).items():
        for namespace, checkpoints in namespaces.items():
            saver.storage[thread_id][namespace].update(checkpoints)
    saver.writes.update(_decode(fixture["writes"]))
    saver.blobs.update(_decode(fixture["blobs"]))
    return saver


@pytest.fixture(params=["memory", "postgres"])
def legacy_checkpointer(request):
    source = _legacy_saver()
    if request.param == "memory":
        yield source
        return
    if not request.config.getoption("--agent-postgres"):
        pytest.skip("Use --agent-postgres to verify legacy checkpoints in PostgreSQL")

    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import sql
    from psycopg.rows import dict_row

    schema = f"agent_migration_test_{uuid4().hex}"
    uri = AgentRuntime(Settings()).build_database_uri()
    with psycopg.connect(uri, autocommit=True, connect_timeout=5) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with psycopg.connect(
                uri, autocommit=True, prepare_threshold=0, row_factory=dict_row,
                connect_timeout=5, options=f"-csearch_path={schema}",
            ) as conn:
                target = PostgresSaver(conn)
                target.setup()
                # Copy every ancestor and its pending writes; a latest-only copy
                # would miss delta history and could silently lose messages.
                for item in reversed(list(source.list(None))):
                    config = item.parent_config or {
                        "configurable": {**item.config["configurable"], "checkpoint_id": None},
                    }
                    target.put(config, item.checkpoint, item.metadata, item.checkpoint["channel_versions"])
                    key = tuple(item.config["configurable"][k] for k in ("thread_id", "checkpoint_ns", "checkpoint_id"))
                    grouped = defaultdict(list)
                    for task_id, channel, value, task_path in source.writes.get(key, {}).values():
                        grouped[(task_id, task_path)].append((channel, source.serde.loads_typed(value)))
                    for (task_id, task_path), writes in grouped.items():
                        target.put_writes(item.config, writes, task_id, task_path)
                yield target
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.parametrize("stream", [False, True])
def test_legacy_checkpoint_resumes_with_role_history_and_plan(monkeypatch, legacy_checkpointer, stream):
    model = MigrationModel(responses=[AIMessage(content="迁移后继续回复")])
    settings = Settings()
    settings.agent_backend = "deepagents"
    runtime = AgentRuntime(settings)
    runtime.checkpointer = legacy_checkpointer
    monkeypatch.setattr(runtime, "create_model", lambda: model)
    monkeypatch.setattr("app.runtime.get_agent_tools", lambda skills: [])
    monkeypatch.setattr("app.agent.runtime", runtime)
    client = AgentClient(SimpleNamespace(agent_backend="deepagents", max_tool_calls=10))

    async def run(text):
        messages = [{"role": "user", "content": text}]
        if stream:
            events = [event async for event in client.astream_events(messages, "migration-user", "legacy", 1, [])]
            assert "".join(event["text"] for event in events if event["type"] == "text") == "迁移后继续回复"
        else:
            result = await client.ainvoke(messages, "migration-user", "legacy", 1, [])
            assert result["message"] == "迁移后继续回复"

    for text in ("迁移后继续", "重建 Agent 后继续"):
        runtime._agents_by_skill_set.clear()
        asyncio.run(run(text))
    assert len(model.received) == 2
    for messages in model.received:
        assert "你是迁移验证助手。" in messages[0].text
        assert messages[0].type == "system"
        assert all(message.type != "system" for message in messages[1:])
        assert [message.text for message in messages if message.type == "human"][:2] == ["整理历史方案", "迁移后继续"]
        assert any(message.type == "tool" and message.tool_call_id == "legacy-plan" for message in messages)
        assert any(message.type == "ai" and message.text == "历史方案已完成" for message in messages)
    assert runtime.get_todos("migration-user", "legacy", 1) == [{"content": "整理历史方案", "status": "completed"}]
    assert runtime.get_todos("migration-user", "legacy", 2) == []


@pytest.mark.parametrize("stream", [False, True])
def test_explicit_model_refusal_is_a_nonretryable_provider_failure(monkeypatch, stream):
    model = MigrationModel(responses=[AIMessage(content=[{
        "type": "refusal", "refusal": "无法执行该 tool 请求。",
    }])])
    settings = Settings()
    settings.agent_backend = "deepagents"
    runtime = AgentRuntime(settings)
    runtime.checkpointer = InMemorySaver()
    monkeypatch.setattr(runtime, "create_model", lambda: model)
    monkeypatch.setattr("app.runtime.get_agent_tools", lambda skills: [])
    monkeypatch.setattr("app.agent.runtime", runtime)
    client = AgentClient(SimpleNamespace(agent_backend="deepagents", max_tool_calls=10))

    async def run():
        args = ([{"role": "user", "content": "测试拒答"}], "user", "refusal", 1, [])
        if stream:
            return [event async for event in client.astream_events(*args)]
        return await client.ainvoke(*args)

    with pytest.raises(ModelRefusalError) as raised:
        asyncio.run(run())
    error = classify_run_error(raised.value)
    assert error["code"] == "MODEL_PROVIDER_FAILED"
    assert error["retryable"] is False
    assert "无法执行" in error["message"]
