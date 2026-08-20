from typing import Any

from app.role_prompts import load_role_prompt


def to_model_message(role: str, content: list[dict[str, Any]]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for block in content:
        if block.get("type") == "text":
            blocks.append({"type": "text", "text": block.get("text", "")})
        elif block.get("type") == "image":
            blocks.append({"type": "image_url", "image_url": {"url": block.get("url", "")}})
    return {"role": role, "content": blocks}


def model_messages(
    agent_role: str | None,
    agent_prompt: str | None,
    content: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if agent_role:
        prompt = load_role_prompt(agent_role)
        if prompt:
            messages.append({"role": "system", "content": prompt})
    elif agent_prompt:
        messages.append({"role": "system", "content": agent_prompt})
    messages.append(to_model_message("user", content))
    return messages
