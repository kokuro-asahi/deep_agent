from collections.abc import Awaitable, Callable
from typing import Any, NotRequired

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import RemoveMessage, SystemMessage
from langgraph.runtime import Runtime


class RolePromptState(AgentState):
    role_system_message: NotRequired[SystemMessage]


class RolePromptMiddleware(AgentMiddleware):
    """Keep role instructions out of checkpointed conversation messages."""

    state_schema = RolePromptState

    def before_agent(self, state: RolePromptState, runtime: Runtime) -> dict[str, Any] | None:
        system_messages = [message for message in state["messages"] if message.type == "system"]
        if not system_messages:
            return None
        # Older checkpoints may contain a fresh role prompt after every turn.
        # Keep the latest instructions and remove only those system messages.
        return {
            "role_system_message": system_messages[-1],
            "messages": [RemoveMessage(id=message.id) for message in system_messages],
        }

    async def abefore_agent(self, state: RolePromptState, runtime: Runtime) -> dict[str, Any] | None:
        return self.before_agent(state, runtime)

    def _with_role_prompt(self, request: ModelRequest) -> ModelRequest:
        role_prompt = request.state.get("role_system_message")
        if role_prompt is None:
            return request
        if request.system_message is None:
            return request.override(system_message=role_prompt)
        # Preserve DeepAgents' tool/skill instructions and their content blocks,
        # but send exactly one system message at the beginning of the request.
        system_message = request.system_message.model_copy(
            update={
                "content": [
                    *role_prompt.content_blocks,
                    {"type": "text", "text": "\n\n"},
                    *request.system_message.content_blocks,
                ]
            }
        )
        return request.override(system_message=system_message)

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        return handler(self._with_role_prompt(request))

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        return await handler(self._with_role_prompt(request))
