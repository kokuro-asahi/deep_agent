from fastapi import APIRouter

from app.skills import skill_registry

router = APIRouter(prefix="/v1", tags=["skills"])


@router.get("/skills")
async def list_skills() -> dict[str, list[dict[str, str | bool]]]:
    """Return skill metadata safe to show in the client skill picker."""
    return {"skills": [skill.public_dict() for skill in skill_registry.list()]}
