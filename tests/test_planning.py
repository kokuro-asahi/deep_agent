import asyncio
from types import SimpleNamespace

import pytest
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from app.agent import AgentClient
from app.model_messages import model_messages
from app.runtime import AgentRuntime
from app.schemas import RunRequest


class PlanningModel(FakeMessagesListChatModel):
    received: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        assert 'write_todos' in {tool.name for tool in tools}
        return self

    def _generate(self, messages, **kwargs):
        assert messages[0].type == 'system'
        assert all(message.type != 'system' for message in messages[1:])
        assert '美术指导' in messages[0].text
        assert 'write_todos' in messages[0].text
        self.received.append(messages)
        return super()._generate(messages, **kwargs)


@pytest.mark.parametrize('stream', [False, True])
def test_planning_preserves_role_prompt_and_checkpoint(monkeypatch, stream):
    def update(status, call_id):
        return AIMessage(content='', tool_calls=[{
            'name': 'write_todos', 'args': {'todos': [{'content': '整理创作方案', 'status': status}]},
            'id': call_id,
        }])

    model = PlanningModel(responses=[update('in_progress', 'plan-1'), update('completed', 'plan-2'), AIMessage(content='这是创作方案')])
    runtime = AgentRuntime(SimpleNamespace())
    runtime.checkpointer = InMemorySaver()
    monkeypatch.setattr(runtime, 'create_model', lambda: model)
    kwargs = runtime.deep_agent_kwargs()
    assert [middleware.name for middleware in kwargs['middleware']] == ['RolePromptMiddleware', 'TodoListMiddleware']
    graph = create_deep_agent(**kwargs)
    monkeypatch.setattr(runtime, 'get_agent', lambda skills: graph)
    monkeypatch.setattr('app.agent.runtime', runtime)
    client = AgentClient(SimpleNamespace(agent_backend='deepagents', max_tool_calls=50))
    messages = model_messages(None, '你是美术指导。', [{'type': 'text', 'text': '请制定创作方案'}])

    async def run():
        if stream:
            events = [event async for event in client.astream_events(messages, 'user', 'thread', 1, [])]
            assert [event['todos'][0]['status'] for event in events if event['type'] == 'plan'] == ['in_progress', 'completed']
            assert ''.join(event['text'] for event in events if event['type'] == 'text') == '这是创作方案'
        else:
            result = await client.ainvoke(messages, 'user', 'thread', 1, [])
            assert result['message'] == '这是创作方案'
            assert result['todos'] == [{'content': '整理创作方案', 'status': 'completed'}]

    asyncio.run(run())
    assert runtime.get_todos('user', 'thread', 1) == [{'content': '整理创作方案', 'status': 'completed'}]
    assert runtime.get_todos('another-user', 'thread', 1) == []
    assert runtime.get_todos('user', 'thread', 2) == []


def test_history_restores_plan_and_terminal_run_status(monkeypatch):
    from app.services import RunService, business_store, runtime

    monkeypatch.setattr(business_store, 'get_thread', lambda *args: {'context_version': 2})
    monkeypatch.setattr(business_store, 'paged_conversations', lambda *args: ([], 0))
    monkeypatch.setattr(business_store, 'latest_run_status', lambda *args: 'completed')

    def get_todos(user_id, thread_id, context_version):
        assert (user_id, thread_id, context_version) == ('user', 'thread', 2)
        return [{'content': '整理方案', 'status': 'in_progress'}]

    monkeypatch.setattr(runtime, 'get_todos', get_todos)
    result = asyncio.run(RunService().messages('user', 'thread', 1, 100))
    assert result.run_status == 'completed'
    assert result.todos[0].status == 'in_progress'


@pytest.mark.parametrize('fail', [False, True])
def test_run_service_forwards_plan_and_preserves_it_on_termination(monkeypatch, fail):
    from app.services import RunService, business_store

    todos = [{'content': '整理方案', 'status': 'in_progress'}]
    monkeypatch.setattr(business_store, 'get_or_create_thread', lambda *args: {'thread_id': 'thread', 'context_version': 1})
    monkeypatch.setattr('app.services.log_agent_event', lambda **kwargs: None)

    async def db_event(name, operation, *args, **kwargs):
        if name == 'next_sequence':
            return 1
        if name == 'fail_run':
            return {'code': 'AGENT_RUN_FAILED', 'message': 'test failure', 'retryable': False}

    async def attach(*args):
        return None

    async def guard(*args):
        return {'blocked': False, 'action': 'allow'}

    async def stream(*args):
        yield {'type': 'plan', 'todos': todos}
        if fail:
            raise RuntimeError('test failure')
        yield {'type': 'text', 'text': '这是创作方案'}

    monkeypatch.setattr('app.services._db_event', db_event)
    monkeypatch.setattr('app.services._attach_request_context', attach)
    service = RunService()
    service.agent = SimpleNamespace(astream_events=stream)
    service.model_guard = SimpleNamespace(check=guard)
    request = RunRequest(user_id='user', agent_role='art_director', content=[{'type': 'text', 'text': '请制定创作方案'}])

    async def collect():
        return [event async for event in service.run_stream(request)]

    events = asyncio.run(collect())
    plan = next(data for event, data in events if event == 'plan.updated')
    assert plan['thread_id'] == 'thread'
    assert plan['todos'] == todos
    assert events[-1][0] == ('run.failed' if fail else 'run.completed')
    assert events[-1][1]['todos'] == todos
