"""Load opt-in tool entrypoints supplied by local skills."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType

from app.config import Settings, get_settings
from app.skills import SkillRegistry


class SkillToolRegistry:
    """Discover ``scripts/tools.py`` entrypoints for enabled skills only."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def tools_for(self, active_skill_ids: tuple[str, ...] = ()) -> list[Callable[..., object]]:
        available = {skill.id: skill for skill in SkillRegistry(self.settings).list()}
        tools: list[Callable[..., object]] = []
        seen_names: set[str] = set()
        root = Path(self.settings.agent_filesystem_root).expanduser().resolve()

        for skill_id in active_skill_ids:
            skill = available.get(skill_id)
            if skill is None:
                raise ValueError(f"Unknown active skill id: {skill_id}")
            entrypoint = root / skill.path.strip("/") / "scripts" / "tools.py"
            if not entrypoint.is_file():
                continue
            for tool in _tools_from_module(_load_module(entrypoint)):
                if tool.__name__ in seen_names:
                    raise RuntimeError(f"Duplicate skill tool name: {tool.__name__}")
                seen_names.add(tool.__name__)
                tools.append(tool)
        return tools


def _load_module(entrypoint: Path) -> ModuleType:
    digest = hashlib.sha256(str(entrypoint.resolve()).encode()).hexdigest()[:16]
    module_name = f"local_skill_tools_{digest}"
    cached = sys.modules.get(module_name)
    if isinstance(cached, ModuleType):
        return cached
    spec = importlib.util.spec_from_file_location(module_name, entrypoint)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load skill tool entrypoint: {entrypoint}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _tools_from_module(module: ModuleType) -> list[Callable[..., object]]:
    factory = getattr(module, "get_tools", None)
    if not callable(factory):
        raise ValueError(f"Skill tool entrypoint must define get_tools(): {module.__file__}")
    result = factory()
    if not isinstance(result, Iterable):
        raise ValueError(f"get_tools() must return an iterable: {module.__file__}")
    tools = list(result)
    if not all(callable(tool) and getattr(tool, "__name__", "") for tool in tools):
        raise ValueError(f"get_tools() must return named callables: {module.__file__}")
    return tools


skill_tool_registry = SkillToolRegistry(get_settings())
