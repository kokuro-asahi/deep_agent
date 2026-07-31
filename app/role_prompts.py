from functools import lru_cache
from pathlib import Path


ROLE_PROMPT_DIR = Path(__file__).resolve().parent / "prompts" / "roles"

ROLE_PROMPT_FILES = {
    "director": "director.md",
    "cinematographer": "cinematographer.md",
    "art_director": "art_director.md",
    "screenwriter": "screenwriter.md",
}

SUPPORTED_AGENT_ROLES = tuple(ROLE_PROMPT_FILES)


def is_supported_agent_role(agent_role: str) -> bool:
    return agent_role in ROLE_PROMPT_FILES


@lru_cache
def load_role_prompt(agent_role: str) -> str:
    filename = ROLE_PROMPT_FILES.get(agent_role)
    if not filename:
        raise ValueError(f"Unsupported agent_role: {agent_role}")
    path = ROLE_PROMPT_DIR / filename
    return path.read_text(encoding="utf-8").strip()
