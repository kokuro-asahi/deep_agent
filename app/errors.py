from enum import Enum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

try:
    from psycopg import Error as PsycopgError
except ImportError:  # pragma: no cover - optional in lightweight test environments
    PsycopgError = None


class ErrorCode(str, Enum):
    VALIDATION_FAILED = "VALIDATION_FAILED"
    THREAD_NOT_FOUND = "THREAD_NOT_FOUND"
    IMAGE_DOWNLOAD_FAILED = "IMAGE_DOWNLOAD_FAILED"
    MODEL_PROVIDER_FAILED = "MODEL_PROVIDER_FAILED"
    TOOL_CALL_FAILED = "TOOL_CALL_FAILED"
    DB_OPERATION_FAILED = "DB_OPERATION_FAILED"
    AGENT_RUN_FAILED = "AGENT_RUN_FAILED"


DEFAULT_ERROR_MESSAGES = {
    ErrorCode.VALIDATION_FAILED: "请求参数校验失败",
    ErrorCode.THREAD_NOT_FOUND: "会话不存在",
    ErrorCode.IMAGE_DOWNLOAD_FAILED: "图片下载失败",
    ErrorCode.MODEL_PROVIDER_FAILED: "模型服务调用失败",
    ErrorCode.TOOL_CALL_FAILED: "工具调用失败",
    ErrorCode.DB_OPERATION_FAILED: "数据存储失败",
    ErrorCode.AGENT_RUN_FAILED: "Agent 执行失败",
}


class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str | None = None, retryable: bool = False):
        self.code = code
        self.message = message or DEFAULT_ERROR_MESSAGES[code]
        self.retryable = retryable
        super().__init__(self.message)

    def to_error_info(self) -> dict[str, Any]:
        return error_info(self.code, self.message, self.retryable)


def error_info(code: ErrorCode, message: str | None = None, retryable: bool = False) -> dict[str, Any]:
    return {
        "code": code.value,
        "message": message or DEFAULT_ERROR_MESSAGES[code],
        "retryable": retryable,
    }


def raise_thread_not_found() -> None:
    raise HTTPException(status_code=404, detail={"error": error_info(ErrorCode.THREAD_NOT_FOUND)})


def classify_run_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, AppError):
        return exc.to_error_info()

    module = exc.__class__.__module__.lower()
    class_name = exc.__class__.__name__.lower()
    message = str(exc)
    message_lower = message.lower()

    if (PsycopgError and isinstance(exc, PsycopgError)) or "psycopg" in module or "database" in message_lower:
        return error_info(ErrorCode.DB_OPERATION_FAILED, message, retryable=True)
    if "tool" in class_name or "tool" in message_lower or "博查" in message:
        return error_info(ErrorCode.TOOL_CALL_FAILED, message, retryable=True)
    if "openai" in module or "langchain" in module or "dashscope" in message_lower or "model" in message_lower:
        return error_info(ErrorCode.MODEL_PROVIDER_FAILED, message, retryable=True)
    return error_info(ErrorCode.AGENT_RUN_FAILED, message, retryable=True)


def validate_image_inputs(content: list[dict[str, Any]]) -> None:
    for block in content:
        if block.get("type") != "image":
            continue
        url = block.get("url", "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AppError(ErrorCode.IMAGE_DOWNLOAD_FAILED, "图片 URL 无效", retryable=False)


def preflight_image_downloads(content: list[dict[str, Any]]) -> None:
    validate_image_inputs(content)
    for block in content:
        if block.get("type") != "image":
            continue
        url = block.get("url", "")
        try:
            request = Request(
                url,
                headers={
                    "Range": "bytes=0-0",
                    "User-Agent": "deepagent-interface/0.1",
                },
                method="GET",
            )
            with urlopen(request, timeout=10) as response:
                response.read(1)
        except HTTPError as exc:
            raise AppError(
                ErrorCode.IMAGE_DOWNLOAD_FAILED,
                f"图片下载失败：HTTP {exc.code}",
                retryable=exc.code >= 500 or exc.code in {408, 429},
            ) from exc
        except (TimeoutError, URLError) as exc:
            raise AppError(ErrorCode.IMAGE_DOWNLOAD_FAILED, DEFAULT_ERROR_MESSAGES[ErrorCode.IMAGE_DOWNLOAD_FAILED], True) from exc
        except Exception as exc:
            raise AppError(ErrorCode.IMAGE_DOWNLOAD_FAILED, DEFAULT_ERROR_MESSAGES[ErrorCode.IMAGE_DOWNLOAD_FAILED], True) from exc


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    if exc.status_code == 404 and "thread" in str(exc.detail).lower():
        return JSONResponse(
            status_code=404,
            content={"error": error_info(ErrorCode.THREAD_NOT_FOUND, str(exc.detail) or None)},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error_info(ErrorCode.AGENT_RUN_FAILED, str(exc.detail) or None)},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": error_info(ErrorCode.VALIDATION_FAILED),
            "details": jsonable_encoder(exc.errors()),
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": classify_run_error(exc)})
