from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

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
    active_skill_ids: list[str] = Field(default_factory=list)
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

    @field_validator("active_skill_ids")
    @classmethod
    def validate_active_skill_ids(cls, value: list[str]) -> list[str]:
        normalized = [skill_id.strip() for skill_id in value if skill_id.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("active_skill_ids must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def require_role_for_new_thread(self) -> "RunRequest":
        if not self.thread_id and not self.agent_role and not self.agent_prompt:
            raise ValueError("agent_role or agent_prompt is required when thread_id is empty")
        return self


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class RunCreateRequest(RunRequest):
    # Optional legacy field; the API binds the actual identity from the session.
    user_id: str | None = Field(default=None, min_length=1)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=1024)


class CurrentUser(BaseModel):
    user_id: str
    username: str
    access_level: int = Field(ge=1, le=3)
    is_admin: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: CurrentUser


class ManagedUser(CurrentUser):
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None


class ManagedUserList(BaseModel):
    users: list[ManagedUser]
    total: int


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=1024)
    access_level: int = Field(default=1, ge=1, le=3, strict=True)
    is_admin: bool = False
    is_active: bool = True

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("账号不能为空")
        return value


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str | None = Field(default=None, min_length=1, max_length=100)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=1024)
    access_level: int | None = Field(default=None, ge=1, le=3, strict=True)
    is_admin: bool | None = None
    is_active: bool | None = None

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return AccountCreate.normalize_username(value)

    @model_validator(mode="after")
    def require_changes(self) -> "AccountUpdate":
        if not self.model_fields_set or any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("请提供需要修改的字段，字段值不能为 null")
        return self


class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool = False


class TodoItem(BaseModel):
    content: str
    status: Literal["pending", "in_progress", "completed"]


class RunResponse(BaseModel):
    run_id: str
    user_id: str
    thread_id: str
    status: Literal["pending", "running", "completed", "failed"]
    message: str = ""
    usage: Usage = Field(default_factory=Usage)
    error: ErrorInfo | None = None
    todos: list[TodoItem] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class ContextResetRequest(BaseModel):
    user_id: str | None = Field(default=None, min_length=1)


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
    todos: list[TodoItem] = Field(default_factory=list)
    run_status: Literal["pending", "running", "completed", "failed"] | None = None


class UserListResponse(BaseModel):
    users: list[str]


class ThreadSummary(BaseModel):
    thread_id: str
    title: str
    agent_role: str | None = None
    updated_at: datetime


class UserThreadsResponse(BaseModel):
    user_id: str
    threads: list[ThreadSummary]
