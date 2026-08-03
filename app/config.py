from functools import lru_cache
from os import getenv
from urllib.parse import quote_plus

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is optional at import time
    load_dotenv = None


if load_dotenv:
    load_dotenv()


class Settings:
    pg_user: str = getenv("PG_USER", "agent")
    pg_password: str = getenv("PG_PASSWORD", "agent")
    pg_database: str = getenv("PG_DATABASE", "agent_backend")
    pg_host: str = getenv("PG_HOST", "127.0.0.1")
    pg_port: str = getenv("PG_PORT", "5432")
    agent_backend: str = getenv("AGENT_BACKEND", "echo")
    agent_model: str = getenv("AGENT_MODEL") or getenv("MODEL", "qwen-plus")
    openai_api_key: str | None = getenv("OPENAI_API_KEY") or getenv("DASHSCOPE_API_KEY")
    openai_base_url: str | None = getenv("OPENAI_BASE_URL") or getenv("BASE_URL")
    public_base_url: str = getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    bocha_api_key: str | None = getenv("BOCHA_API_KEY")
    bocha_api_url: str = getenv("BOCHA_API_URL", "https://api.bocha.cn/v1/ai-search")

    cos_secret_id: str | None = getenv("COS_SECRET_ID")
    cos_secret_key: str | None = getenv("COS_SECRET_KEY")
    cos_region: str = getenv("COS_REGION", "ap-guangzhou")
    cos_bucket: str | None = getenv("COS_BUCKET")


@lru_cache
def get_settings() -> Settings:
    return Settings()
