"""Serve generated PDF previews inline when COS forces attachment downloads."""

import re
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.auth import get_current_user
from app.config import get_settings


router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"], dependencies=[Depends(get_current_user)])
MAX_PREVIEW_BYTES = 50 * 1024 * 1024


@router.get("/ppt-preview")
def ppt_preview(url: str = Query(min_length=1, max_length=8192)) -> Response:
    settings = get_settings()
    host = f"{settings.cos_bucket}.cos.{settings.cos_region}.myqcloud.com"
    prefix = quote(settings.ppt_upload_prefix.strip("/"), safe="/")
    path_prefix = f"/{prefix}/" if prefix else "/"
    try:
        parsed = urlparse(url)
        valid = (parsed.scheme == "https" and parsed.netloc == host
                 and not parsed.query and not parsed.fragment and not parsed.username and not parsed.password
                 and re.fullmatch(re.escape(path_prefix) + r"ppt_[0-9a-f]{32}/preview\.pdf", parsed.path))
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(status_code=400, detail="预览地址无效")

    try:
        content = bytearray()
        # Only our generated PDF objects can be fetched; never follow redirects.
        with httpx.stream("GET", url, timeout=30, follow_redirects=False) as upstream:
            upstream.raise_for_status()
            for chunk in upstream.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_PREVIEW_BYTES:
                    raise ValueError("Preview exceeds size limit")
        if not content.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF")
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="预览加载失败，请稍后重试或下载 PPT") from exc
    return Response(bytes(content), media_type="application/pdf", headers={
        "Content-Disposition": 'inline; filename="preview.pdf"',
        "Cache-Control": "private, max-age=300",
        "X-Content-Type-Options": "nosniff",
    })
