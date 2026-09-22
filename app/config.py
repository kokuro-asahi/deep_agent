from functools import lru_cache
from os import getenv
from pathlib import Path
from urllib.parse import quote_plus

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is optional at import time
    load_dotenv = None


if load_dotenv:
    load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _csv_env(value: str | None, default: str = "") -> list[str]:
    source = default if value is None else value
    return [item.strip() for item in source.split(",") if item.strip()]


def _int_env(name: str, default: int) -> int:
    value = getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class Settings:
    pg_user: str = getenv("PG_USER", "agent")
    pg_password: str = getenv("PG_PASSWORD", "agent")
    pg_database: str = getenv("PG_DATABASE", "agent_backend")
    pg_host: str = getenv("PG_HOST", "127.0.0.1")
    pg_port: str = getenv("PG_PORT", "5432")
    agent_backend: str = getenv("AGENT_BACKEND", "echo")
    policy_mcp_url: str = getenv("POLICY_MCP_URL", "http://10.1.80.12:9020/mcp")
    policy_mcp_token: str | None = getenv("POLICY_MCP_TOKEN")
    policy_mcp_env_file: str = getenv(
        "POLICY_MCP_ENV_FILE", "/opt/Workspace/CRX/enterprice_policy_kb/.env"
    )
    agent_model: str = getenv("AGENT_MODEL") or getenv("MODEL", "qwen-plus")
    agent_filesystem_root: str = getenv("AGENT_FILESYSTEM_ROOT", str(PROJECT_ROOT))
    agent_skills_paths: tuple[str, ...] = tuple(_csv_env(getenv("AGENT_SKILLS_PATHS"), "skills"))
    max_tool_calls: int = _int_env("MAX_TOOL_CALLS", 10)
    openai_api_key: str | None = getenv("OPENAI_API_KEY") or getenv("DASHSCOPE_API_KEY")
    openai_base_url: str | None = getenv("OPENAI_BASE_URL") or getenv("BASE_URL")
    public_base_url: str = getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    bocha_api_key: str | None = getenv("BOCHA_API_KEY")
    bocha_api_url: str = getenv("BOCHA_API_URL", "https://api.bocha.cn/v1/ai-search")
    model_guard_enabled: bool = getenv("MODEL_GUARD_ENABLED", "true").lower() not in {"0", "false", "no"}
    model_guard_response: str | None = getenv("MODEL_GUARD_RESPONSE")

    cos_secret_id: str | None = getenv("COS_SECRET_ID")
    cos_secret_key: str | None = getenv("COS_SECRET_KEY")
    cos_region: str = getenv("COS_REGION", "ap-guangzhou")
    cos_bucket: str | None = getenv("COS_BUCKET")


@lru_cache
def get_settings() -> Settings:
    return Settings()
