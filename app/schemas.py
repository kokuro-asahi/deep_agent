from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.role_prompts import SUPPORTED_AGENT_ROLES, is_supported_agent_role


class TextContent(BaseModel):
    type: Literal["text"]
    text: str = Field(min_length=1)


class ImageContent(BaseModel):
    type: Literal["image"]
    url: str = Field(min_length=1)
    object_key: str | None = None
    mime_type: str | None = None
    file_name: str | None = None


ContentBlock = TextContent | ImageContent


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str = Field(min_length=1)
    thread_id: str | None = None
    stream: bool = True
    content: list[ContentBlock] = Field(min_length=1)
    agent_role: str | None = None
    agent_prompt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent_role")
    @classmethod
    def validate_agent_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        role = value.strip()
        if not role:
            return None
        if not is_supported_agent_role(role):
            allowed = "、".join(SUPPORTED_AGENT_ROLES)
            raise ValueError(f"agent_role must be one of: {allowed}")
        return role

    @field_validator("agent_prompt")
    @classmethod
    def validate_agent_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        prompt = value.strip()
        return prompt or None

    @model_validator(mode="after")
    def require_role_for_new_thread(self) -> "RunRequest":
        if not self.thread_id and not self.agent_role and not self.agent_prompt:
            raise ValueError("agent_role or agent_prompt is required when thread_id is empty")
        return self


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool = False


class RunResponse(BaseModel):
    run_id: str
    user_id: str
    thread_id: str
    status: Literal["pending", "running", "completed", "failed"]
    message: str = ""
    usage: Usage = Field(default_factory=Usage)
    error: ErrorInfo | None = None


class ContextResetRequest(BaseModel):
    user_id: str = Field(min_length=1)


class ContextResetResponse(BaseModel):
    user_id: str
    thread_id: str
    context_start_sequence: int


class MessageSide(BaseModel):
    content: list[dict[str, Any]]
    created_at: datetime | None = None


class ConversationMessage(BaseModel):
    message_id: str
    run_id: str
    sequence: int
    user: MessageSide | None = None
    assistant: MessageSide | None = None


class ThreadMessagesResponse(BaseModel):
    user_id: str
    thread_id: str
    page: int
    page_size: int
    total_pages: int
    total_messages: int
    has_more: bool
    messages: list[ConversationMessage]
