from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from app.config import Settings, get_settings
from app.tools import get_agent_tools


class AgentRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._checkpointer_pool: Any | None = None
        self.checkpointer: Any | None = None
        self.agent: Any | None = None
        self._agents_by_skill_set: dict[tuple[str, ...], Any] = {}

    def start(self) -> None:
        if self.settings.agent_backend == "echo":
            return
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        database_uri = self.build_database_uri()
        self._checkpointer_pool = ConnectionPool(
            conninfo=database_uri,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=True,
        )
        self.checkpointer = PostgresSaver(self._checkpointer_pool)
        self.checkpointer.setup()
        # Agent graphs are built lazily per selected skill set. This keeps skills
        # that were not selected for a thread out of that thread's discovery scope.

    def deep_agent_kwargs(self, skill_paths: list[str] | None = None, active_skill_ids: tuple[str, ...] = ()) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.create_model(),
            "tools": get_agent_tools(active_skill_ids),
            "checkpointer": self.checkpointer,
        }
        skills = skill_paths or []
        if skills:
            from deepagents.backends.composite import CompositeBackend
            from deepagents.backends.filesystem import FilesystemBackend
            from deepagents.backends.state import StateBackend

            kwargs["backend"] = CompositeBackend(
                default=StateBackend(),
                routes={path: FilesystemBackend(root_dir=self.filesystem_root() / path.strip("/")) for path in skills},
            )
            # DeepAgents discovers child directories of each source, not the source itself.
            kwargs["skills"] = ["/"]
        return kwargs

    def get_agent(self, active_skill_ids: list[str]) -> Any:
        if self.settings.agent_backend == "echo":
            return None
        if self.checkpointer is None:
            self.start()
        from app.skills import SkillRegistry
        from deepagents import create_deep_agent

        key = tuple(sorted(set(active_skill_ids)))
        if key not in self._agents_by_skill_set:
            self._agents_by_skill_set[key] = create_deep_agent(
                **self.deep_agent_kwargs(SkillRegistry(self.settings).paths_for(key), key)
            )
        return self._agents_by_skill_set[key]

    def filesystem_root(self) -> Path:
        return Path(self.settings.agent_filesystem_root).expanduser().resolve()

    def skill_paths(self) -> list[str]:
        """Return configured skill directories as safe DeepAgents virtual paths."""
        root = self.filesystem_root()
        paths: list[str] = []
        for raw_path in self.settings.agent_skills_paths:
            path = raw_path.strip().replace("\\", "/")
            if not path:
                continue
            candidate = Path(path).expanduser()
            if candidate.is_absolute():
                try:
                    path = candidate.resolve().relative_to(root).as_posix()
                except ValueError as exc:
                    raise ValueError(
                        "AGENT_SKILLS_PATHS entries must be relative to AGENT_FILESYSTEM_ROOT "
                        "or absolute paths inside it"
                    ) from exc
            path = path.strip("/")
            if not path:
                continue
            if not (root / path).is_dir():
                raise RuntimeError(
                    f"DeepAgents skill path does not exist under AGENT_FILESYSTEM_ROOT: {path}"
                )
            paths.append(f"/{path}/")
        return paths

    def stop(self) -> None:
        if self._checkpointer_pool:
            self._checkpointer_pool.close()
        self._checkpointer_pool = None
        self.checkpointer = None
        self.agent = None
        self._agents_by_skill_set.clear()

    def create_model(self, *, temperature: float = 0.2) -> Any:
        from langchain_openai import ChatOpenAI

        if not self.settings.openai_api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY 或 OPENAI_API_KEY")
        if not self.settings.openai_base_url:
            raise RuntimeError("缺少 BASE_URL 或 OPENAI_BASE_URL")
        return ChatOpenAI(
            model=self.settings.agent_model,
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            temperature=temperature,
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
