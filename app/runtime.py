from contextlib import AbstractContextManager
from typing import Any
from urllib.parse import quote_plus

from app.config import Settings, get_settings
from app.tools import get_agent_tools


class AgentRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._checkpointer_cm: AbstractContextManager[Any] | None = None
        self.checkpointer: Any | None = None
        self.agent: Any | None = None

    def start(self) -> None:
        if self.settings.agent_backend == "echo":
            return
        from deepagents import create_deep_agent
        from langgraph.checkpoint.postgres import PostgresSaver

        database_uri = self.build_database_uri()
        self._checkpointer_cm = PostgresSaver.from_conn_string(database_uri)
        self.checkpointer = self._checkpointer_cm.__enter__()
        self.checkpointer.setup()
        self.agent = create_deep_agent(
            model=self.create_model(),
            tools=get_agent_tools(),
            checkpointer=self.checkpointer,
        )

    def stop(self) -> None:
        if self._checkpointer_cm:
            self._checkpointer_cm.__exit__(None, None, None)
        self._checkpointer_cm = None
        self.checkpointer = None
        self.agent = None

    def create_model(self) -> Any:
        from langchain_openai import ChatOpenAI

        if not self.settings.openai_api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY 或 OPENAI_API_KEY")
        if not self.settings.openai_base_url:
            raise RuntimeError("缺少 BASE_URL 或 OPENAI_BASE_URL")
        return ChatOpenAI(
            model=self.settings.agent_model,
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            temperature=0.2,
            stream_usage=True,
            max_retries=2,
            timeout=60,
        )

    def build_database_uri(self) -> str:
        user = quote_plus(self.settings.pg_user)
        password = quote_plus(self.settings.pg_password)
        return (
            f"postgresql://{user}:{password}"
            f"@{self.settings.pg_host}:{self.settings.pg_port}/{self.settings.pg_database}"
        )

    def storage_thread_id(self, user_id: str, thread_id: str, context_version: int = 1) -> str:
        return f"{user_id}:{thread_id}:v{context_version}"

    def config(self, user_id: str, thread_id: str, context_version: int = 1) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.storage_thread_id(user_id, thread_id, context_version)}}


runtime = AgentRuntime(get_settings())


def extract_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "\n".join(parts)
    return str(content)
