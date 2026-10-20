import asyncio
from types import SimpleNamespace

import pytest
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from app.agent import AgentClient
from app.model_messages import model_messages
from app.runtime import AgentRuntime


class StrictSystemModel(FakeMessagesListChatModel):
    received: list[list] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        self.received.append(list(messages))
        if any(message.type == "system" for message in messages[1:]):
            raise ValueError("System message must be at the beginning.")
        result = super()._generate(messages, **kwargs)
        # Real provider responses get a new message ID for every generation.
        for generation in result.generations:
            generation.message = generation.message.model_copy(update={"id": None})
        return result


def _graph(monkeypatch, *, with_middleware=True):
    def echo_tool(text: str) -> str:
        """Return the supplied text."""
        return text

    model = StrictSystemModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "echo_tool", "args": {"text": "ok"}, "id": "call_test"}]),
            AIMessage(content="回复成功"),
        ]
    )
    runtime = AgentRuntime(SimpleNamespace())
    runtime.checkpointer = InMemorySaver()
    monkeypatch.setattr(runtime, "create_model", lambda: model)
    monkeypatch.setattr("app.runtime.get_agent_tools", lambda skills: [echo_tool])
    kwargs = runtime.deep_agent_kwargs()
    kwargs["system_prompt"] = "Framework tool instructions: use echo_tool when needed."
    if not with_middleware:
        kwargs.pop("middleware")
    return create_deep_agent(**kwargs), model


def test_original_message_layout_reproduces_provider_error(monkeypatch):
    graph, _ = _graph(monkeypatch, with_middleware=False)
    with pytest.raises(ValueError, match="System message must be at the beginning"):
        graph.invoke(
            {"messages": model_messages(None, "你是美术指导。", [{"type": "text", "text": "你是谁"}])},
            {"configurable": {"thread_id": "original"}},
        )


@pytest.mark.parametrize("stream", [False, True])
def test_role_prompt_works_across_turns_and_tool_calls(monkeypatch, stream):
    graph, model = _graph(monkeypatch)
    monkeypatch.setattr("app.agent.runtime.get_agent", lambda skills: graph)
    client = AgentClient(SimpleNamespace(agent_backend="deepagents", max_tool_calls=10))

    async def run():
        for text in ("你是谁", "继续"):
            messages = model_messages(None, "你是美术指导。", [{"type": "text", "text": text}])
            if stream:
                events = [event async for event in client.astream_events(messages, "u", "multi", 1, [])]
                assert "".join(event["text"] for event in events if event["type"] == "text") == "回复成功"
                assert any(event["type"] == "trace" for event in events)
            else:
                result = await client.ainvoke(messages, "u", "multi", 1, [])
                assert result["message"] == "回复成功"

    asyncio.run(run())
    assert len(model.received) == 4
    for messages in model.received:
        assert messages[0].type == "system"
        assert messages[0].text.count("你是美术指导。") == 1
        assert "echo_tool" in messages[0].text  # Framework tool instructions survive.
        assert all(message.type != "system" for message in messages[1:])
    state = graph.get_state({"configurable": {"thread_id": "u:multi:v1"}}).values
    assert [message.text for message in state["messages"] if message.type == "human"] == ["你是谁", "继续"]
    assert all(message.type != "system" for message in state["messages"])


def test_old_checkpoint_is_repaired_without_losing_history(monkeypatch):
    graph, model = _graph(monkeypatch)
    config = {"configurable": {"thread_id": "legacy"}}
    history = [
        SystemMessage(content="旧角色"),
        HumanMessage(content="上一轮问题"),
        AIMessage(content="", tool_calls=[{"name": "echo_tool", "args": {"text": "历史结果"}, "id": "old_call"}]),
        ToolMessage(content="历史结果", tool_call_id="old_call"),
        AIMessage(content="上一轮回复"),
        SystemMessage(content="旧角色"),
    ]
    graph.update_state(config, {"messages": [
        message.model_copy(update={"id": f"legacy-{index}"}) for index, message in enumerate(history)
    ]})
    graph.invoke(
        {"messages": model_messages(None, "当前角色", [{"type": "text", "text": "你是谁"}])}, config
    )
    messages = model.received[0]
    assert "当前角色" in messages[0].text
    assert "旧角色" not in messages[0].text
    assert [message.type for message in messages[1:]] == ["human", "ai", "tool", "ai", "human"]
    assert messages[3].content == "历史结果"
    # The prompt remains available when a later invocation sends only user input.
    graph.invoke({"messages": [HumanMessage(content="继续")]}, config)
    assert "当前角色" in model.received[-1][0].text


def test_no_role_prompt_still_uses_framework_system_message(monkeypatch):
    graph, model = _graph(monkeypatch)
    graph.invoke({"messages": [HumanMessage(content="你好")]}, {"configurable": {"thread_id": "no-role"}})
    assert model.received[0][0].type == "system"
    assert all(message.type != "system" for message in model.received[0][1:])
