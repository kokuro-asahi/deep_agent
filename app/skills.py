"""Discovery and validation for locally configured DeepAgents skills."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from app.config import Settings, get_settings


@dataclass(frozen=True)
class SkillDefinition:
    id: str
    name: str
    description: str
    path: str
    enabled_by_default: bool = False

    def public_dict(self) -> dict[str, str | bool]:
        result = asdict(self)
        result.pop("path")
        return result


class SkillRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings

    def list(self) -> list[SkillDefinition]:
        root = Path(self.settings.agent_filesystem_root).expanduser().resolve()
        skills: dict[str, SkillDefinition] = {}
        for configured_path in self.settings.agent_skills_paths:
            source = (root / configured_path).resolve()
            try:
                source.relative_to(root)
            except ValueError as exc:
                raise ValueError("Skill directory must be inside AGENT_FILESYSTEM_ROOT") from exc
            if not source.is_dir():
                continue
            for skill_file in source.rglob("SKILL.md"):
                definition = self._parse(skill_file, root)
                if definition.id in skills:
                    raise RuntimeError(f"Duplicate skill id: {definition.id}")
                skills[definition.id] = definition
        return sorted(skills.values(), key=lambda skill: skill.id)

    def paths_for(self, active_skill_ids: list[str] | tuple[str, ...]) -> list[str]:
        available = {skill.id: skill for skill in self.list()}
        missing = [skill_id for skill_id in active_skill_ids if skill_id not in available]
        if missing:
            raise ValueError(f"Unknown active_skill_ids: {', '.join(missing)}")
        return [available[skill_id].path for skill_id in active_skill_ids]

    @staticmethod
    def _parse(skill_file: Path, root: Path) -> SkillDefinition:
        content = skill_file.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            raise ValueError(f"Skill frontmatter is required: {skill_file}")
        _, frontmatter, _ = content.split("---", 2)
        metadata = yaml.safe_load(frontmatter) or {}
        name = metadata.get("name")
        description = metadata.get("description")
        if not isinstance(name, str) or not name.strip() or not isinstance(description, str) or not description.strip():
            raise ValueError(f"Skill name and description are required: {skill_file}")
        directory = skill_file.parent.resolve()
        virtual_path = "/" + directory.relative_to(root).as_posix().strip("/") + "/"
        return SkillDefinition(
            id=name.strip(),
            name=name.strip(),
            description=description.strip(),
            path=virtual_path,
        )


skill_registry = SkillRegistry(get_settings())
