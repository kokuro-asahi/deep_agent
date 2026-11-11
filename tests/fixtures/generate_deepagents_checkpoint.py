"""Regenerate with the pre-migration Python environment (DeepAgents 0.7.0b2).

Contains synthetic data only. JSON preserves the original serialized bytes and
ancestor writes, including the delta-channel history needed to resume a thread.
"""

import base64
import importlib.metadata
import json
from pathlib import Path

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent_middleware import RolePromptMiddleware
from app.model_messages import model_messages


class LegacyModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def encode(value):
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {"entries": [[encode(k), encode(v)] for k, v in value.items()]}
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    return value


if __name__ == "__main__":
    assert importlib.metadata.version("deepagents") == "0.7.0b2"
    saver = InMemorySaver()
    graph = create_deep_agent(
        model=LegacyModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "write_todos", "id": "legacy-plan",
                "args": {"todos": [{"content": "整理历史方案", "status": "completed"}]},
            }]),
            AIMessage(content="历史方案已完成"),
        ]),
        checkpointer=saver,
        middleware=[RolePromptMiddleware(), TodoListMiddleware()],
    )
    config = {"configurable": {"thread_id": "migration-user:legacy:v1"}}
    graph.invoke({"messages": model_messages(
        None, "你是迁移验证助手。", [{"type": "text", "text": "整理历史方案"}],
    )}, config)
    fixture = {
        "versions": {name: importlib.metadata.version(name) for name in (
            "deepagents", "langchain", "langchain-core", "langgraph", "langgraph-checkpoint",
        )},
        "config": config,
        "storage": encode(saver.storage),
        "writes": encode(saver.writes),
        "blobs": encode(saver.blobs),
    }
    Path(__file__).with_name("deepagents-0.7.0b2-checkpoint.json").write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
