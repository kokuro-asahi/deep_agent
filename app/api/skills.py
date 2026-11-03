from app.auth import get_current_user

from fastapi import APIRouter, Depends

from app.skills import skill_registry

router = APIRouter(prefix="/v1", tags=["skills"], dependencies=[Depends(get_current_user)])


@router.get("/skills")
async def list_skills() -> dict[str, list[dict[str, str | bool]]]:
    """Return skill metadata safe to show in the client skill picker."""
    return {"skills": [skill.public_dict() for skill in skill_registry.list()]}
