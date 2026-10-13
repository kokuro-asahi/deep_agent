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


def _mapping_env(value: str | None, default: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for pair in _csv_env(value, default):
        ratio, separator, size = pair.partition("=")
        if not separator or not ratio.strip() or not size.strip():
            raise ValueError("IMAGE_ASPECT_RATIO_SIZES 必须使用 画幅=尺寸 格式")
        mapping[ratio.strip()] = size.strip()
    return mapping


def _int_env(name: str, default: int) -> int:
    value = getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


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
    cos_scheme: str = getenv("COS_SCHEME", "https")

    image_generation_enabled: bool = _bool_env("IMAGE_GENERATION_ENABLED", False)
    # Any OpenAI-compatible image endpoint. No provider-specific environment
    # variables are required; vendor extensions are opt-in below.
    image_api_key: str | None = getenv("IMAGE_API_KEY")
    image_api_base_url: str = getenv("IMAGE_API_BASE_URL", "https://api.openai.com/v1")
    image_model: str = getenv("IMAGE_MODEL", "gpt-image-1")
    image_response_format: str | None = getenv("IMAGE_RESPONSE_FORMAT") or None
    image_output_extension: str = getenv("IMAGE_OUTPUT_EXTENSION", "png")
    image_default_size: str = getenv("IMAGE_DEFAULT_SIZE", "1024x1024")
    image_allowed_sizes: tuple[str, ...] = tuple(
        _csv_env(getenv("IMAGE_ALLOWED_SIZES"), "1024x1024,1536x1024,1024x1536")
    )
    image_aspect_ratio_sizes: dict[str, str] = _mapping_env(
        getenv("IMAGE_ASPECT_RATIO_SIZES"),
        "1:1=1024x1024,16:9=1536x1024,9:16=1024x1536",
    )
    image_default_watermark: bool = _bool_env("IMAGE_DEFAULT_WATERMARK", True)
    image_watermark_field: str | None = getenv("IMAGE_WATERMARK_FIELD") or None
    image_download_timeout_seconds: int = _int_env("IMAGE_DOWNLOAD_TIMEOUT_SECONDS", 120)
    image_upload_prefix: str = getenv("IMAGE_UPLOAD_PREFIX", "generated")
    image_upload_part_size_mb: int = _int_env("IMAGE_UPLOAD_PART_SIZE_MB", 10)
    image_upload_max_threads: int = _int_env("IMAGE_UPLOAD_MAX_THREADS", 5)
    image_upload_acl: str = getenv("IMAGE_UPLOAD_ACL", "public-read")


@lru_cache
def get_settings() -> Settings:
    return Settings()
