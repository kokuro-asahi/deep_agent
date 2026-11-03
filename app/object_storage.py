"""COS delivery shared by generated images and documents."""

import mimetypes
from pathlib import Path
from urllib.parse import quote

from app.config import Settings


def upload_file(settings: Settings, local_file: Path, object_key: str) -> dict[str, str]:
    from qcloud_cos import CosConfig, CosS3Client

    client = CosS3Client(CosConfig(
        Region=settings.cos_region,
        SecretId=settings.cos_secret_id,
        SecretKey=settings.cos_secret_key,
        Scheme=settings.cos_scheme,
    ))
    mime_type = mimetypes.guess_type(local_file.name)[0] or "application/octet-stream"
    options = {}
    if local_file.suffix.lower() == ".pptx":
        mime_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        options["ContentDisposition"] = f"attachment; filename*=UTF-8''{quote(local_file.name, safe='')}"
    elif local_file.suffix.lower() == ".pdf":
        mime_type = "application/pdf"
        options["ContentDisposition"] = f"inline; filename*=UTF-8''{quote(local_file.name, safe='')}"
    client.upload_file(
        Bucket=settings.cos_bucket,
        Key=object_key,
        LocalFilePath=str(local_file),
        PartSize=settings.image_upload_part_size_mb,
        MAXThread=settings.image_upload_max_threads,
        EnableMD5=False,
        ContentType=mime_type,
        ACL=settings.image_upload_acl,
        **options,
    )
    encoded_key = quote(object_key, safe="/")
    return {
        "url": f"{settings.cos_scheme}://{settings.cos_bucket}.cos."
        f"{settings.cos_region}.myqcloud.com/{encoded_key}",
        "mime_type": mime_type,
    }
