from typing import Any
from urllib.parse import urlparse

from app.errors import ErrorCode, error_info


def tool_trace_sse_event(run_id: str, message: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    role = message.get("role")
    content = message.get("content", [])
    if not isinstance(content, list) or not content:
        return None
    record = content[0]
    if not isinstance(record, dict):
        return None

    tool_call_id = record.get("tool_call_id")
    tool_type = record.get("tool_name")
    if role == "tool_call":
        return (
            "tool.call.started",
            {
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "tool_type": tool_type,
                "arguments": record.get("arguments") or {},
            },
        )
    if role != "tool_callback":
        return None

    if record.get("status") == "error":
        payload = tool_result_content(record.get("error") or record.get("result"))
        message_text = payload if isinstance(payload, str) else "工具调用失败"
        return (
            "tool.call.failed",
            {
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "tool_type": tool_type,
                "error": error_info(ErrorCode.TOOL_CALL_FAILED, message_text, retryable=True),
            },
        )
    return (
        "tool.call.completed",
        {
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "tool_type": tool_type,
            "result": tool_result_content(record.get("result")),
        },
    )


def tool_result_content(payload: Any) -> Any:
    if isinstance(payload, dict) and payload.get("type") in {"json", "text"} and "content" in payload:
        return payload["content"]
    return payload


def artifacts_from_tool_trace(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose generated images and downloadable presentations to API clients."""
    return [*image_artifacts_from_tool_trace(message), *file_artifacts_from_tool_trace(message)]


def file_artifacts_from_tool_trace(message: dict[str, Any]) -> list[dict[str, Any]]:
    if message.get("role") != "tool_callback":
        return []
    content = message.get("content", [])
    if not isinstance(content, list) or not content or not isinstance(content[0], dict):
        return []
    record = content[0]
    if record.get("status") == "error" or record.get("tool_name") != "generate_ppt":
        return []
    result = tool_result_content(record.get("result"))
    if not isinstance(result, dict) or result.get("status") != "succeeded":
        return []
    files = result.get("files")
    if not isinstance(files, list):
        return []
    artifacts = []
    for index, file in enumerate(files):
        if not isinstance(file, dict) or not isinstance(file.get("url"), str):
            continue
        if urlparse(file["url"]).scheme not in {"https", "http"}:
            continue
        artifacts.append({
            "artifact_id": str(file.get("id") or f"{result.get('request_id', 'ppt')}_{index + 1}"),
            "type": "file",
            "metadata": {
                "url": file["url"],
                "file_name": file.get("file_name") or "presentation.pptx",
                "mime_type": file.get("mime_type") or "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "size_bytes": file.get("size_bytes"),
                "slide_count": file.get("slide_count"),
                "theme": file.get("theme"),
                "theme_name": file.get("theme_name"),
                **_file_preview_metadata(file),
                "expires_at": None,
            },
        })
    return artifacts


def _file_preview_metadata(file: dict[str, Any]) -> dict[str, Any]:
    metadata = {"preview_status": file.get("preview_status")}
    preview_url = file.get("preview_url")
    if isinstance(preview_url, str):
        try:
            preview = urlparse(preview_url)
            source = urlparse(file["url"])
            if (file.get("preview_status") == "ready" and file.get("preview_mime_type") == "application/pdf"
                    and preview.scheme in {"http", "https"} and preview.netloc == source.netloc
                    and not preview.username and not preview.password and preview.path.lower().endswith(".pdf")):
                metadata.update(preview_url=preview_url, preview_mime_type="application/pdf")
        except ValueError:
            pass
    return metadata


def image_artifacts_from_tool_trace(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract public image artifacts from a successful generate_image callback."""
    if message.get("role") != "tool_callback":
        return []
    content = message.get("content", [])
    if not isinstance(content, list) or not content:
        return []
    record = content[0]
    if not isinstance(record, dict) or record.get("status") == "error":
        return []
    if record.get("tool_name") != "generate_image":
        return []

    result = tool_result_content(record.get("result"))
    images = result.get("images") if isinstance(result, dict) else None
    if not isinstance(images, list):
        return []

    artifacts: list[dict[str, Any]] = []
    for index, image in enumerate(images):
        if not isinstance(image, dict) or not isinstance(image.get("url"), str):
            continue
        url = image["url"]
        image_id = image.get("id") or result.get("request_id") or f"image_{index + 1}"
        metadata = {
            "url": url,
            "preview_url": url,
            "mime_type": image.get("mime_type") or "image/png",
            "file_name": _file_name_from_url(url),
            "watermark_requested": image.get("watermark_requested"),
            "watermark_applied": image.get("watermark_applied"),
            "expires_at": None,
        }
        artifacts.append(
            {
                "artifact_id": str(image_id),
                "type": "image",
                "metadata": metadata,
            }
        )
    return artifacts


def _file_name_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", maxsplit=1)[-1] or "generated.png"
