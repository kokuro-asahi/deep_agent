"""Provider-backed image generation and COS delivery for the agent tool."""

from __future__ import annotations

import mimetypes
import tempfile
import uuid
from base64 import b64decode
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.config import Settings


class ImageGenerationError(RuntimeError):
    """A safe, user-facing error raised by the image generation tool."""


@dataclass(frozen=True)
class GeneratedImage:
    suffix: str
    source_url: str | None = None
    content: bytes | None = None


class ImageGenerationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate_and_upload(
        self,
        prompt: str,
        *,
        size: str | None = None,
        aspect_ratio: str | None = None,
        quality: str | None = None,
        n: int = 1,
        output_format: str | None = None,
        output_compression: int | None = None,
        background: str | None = None,
        watermark: bool | None = None,
    ) -> dict[str, Any]:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("生图提示词不能为空")
        self._validate_settings()
        if size and aspect_ratio:
            raise ValueError("size 和 aspect_ratio 不能同时指定")
        selected_size = size or self._size_for_aspect_ratio(aspect_ratio)
        if selected_size is not None and selected_size not in self.settings.image_allowed_sizes:
            allowed = ", ".join(self.settings.image_allowed_sizes)
            raise ValueError(f"不支持的图片尺寸：{selected_size}；可选值：{allowed}")
        selected_quality = self._validate_choice(
            quality, "quality", {"low", "medium", "high", "xhigh", "max", "auto"}
        )
        selected_count = self._validate_count(n, maximum=10)
        selected_output_format = self._validate_choice(
            output_format, "output_format", {"png", "jpeg", "webp"}
        )
        selected_background = self._validate_choice(
            background, "background", {"auto", "opaque", "transparent"}
        )
        self._validate_compression(output_compression, selected_output_format)
        selected_watermark = (
            self.settings.image_default_watermark if watermark is None else watermark
        )

        generated_images = self._generate_images(
            prompt,
            selected_size,
            quality=selected_quality,
            n=selected_count,
            output_format=selected_output_format,
            output_compression=output_compression,
            background=selected_background,
            watermark=selected_watermark,
        )
        request_id = f"img_{uuid.uuid4().hex}"
        images = self._upload_generated_images(
            request_id, generated_images, selected_watermark
        )

        return {
            "request_id": request_id,
            "status": "succeeded",
            "images": images,
            "provider": {
                "model": self.settings.image_model,
            },
            "parameters": {
                "size": selected_size,
                "aspect_ratio": aspect_ratio.strip() if aspect_ratio else None,
                "quality": selected_quality,
                "n": selected_count,
                "output_format": selected_output_format or self._output_suffix().lstrip("."),
                "output_compression": output_compression,
                "background": selected_background,
            },
        }

    def _validate_settings(self) -> None:
        if not self.settings.image_generation_enabled:
            raise ImageGenerationError("生图功能未启用，请设置 IMAGE_GENERATION_ENABLED=true")
        for name, value in (
            ("IMAGE_API_KEY", self.settings.image_api_key),
            ("COS_SECRET_ID", self.settings.cos_secret_id),
            ("COS_SECRET_KEY", self.settings.cos_secret_key),
            ("COS_BUCKET", self.settings.cos_bucket),
        ):
            if not value:
                raise ImageGenerationError(f"缺少配置：{name}")

    def _size_for_aspect_ratio(self, aspect_ratio: str | None) -> str | None:
        if aspect_ratio is None:
            return None
        normalized = aspect_ratio.strip()
        size = self.settings.image_aspect_ratio_sizes.get(normalized)
        if not size:
            allowed = ", ".join(self.settings.image_aspect_ratio_sizes)
            raise ValueError(f"不支持的图片画幅：{normalized}；可选值：{allowed}")
        return size

    @staticmethod
    def _validate_choice(value: str | None, name: str, allowed: set[str]) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError(f"不支持的 {name}：{value}；可选值：{', '.join(sorted(allowed))}")
        return normalized

    @staticmethod
    def _validate_count(n: int, *, maximum: int) -> int:
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= maximum:
            raise ValueError(f"n 必须是 1 到 {maximum} 之间的整数")
        return n

    @staticmethod
    def _validate_compression(output_compression: int | None, output_format: str | None) -> None:
        if output_compression is None:
            return
        if isinstance(output_compression, bool) or not isinstance(output_compression, int) or not 0 <= output_compression <= 100:
            raise ValueError("output_compression 必须是 0 到 100 之间的整数")
        if output_format not in {"jpeg", "webp"}:
            raise ValueError("output_compression 仅支持 output_format 为 jpeg 或 webp")

    def _generate_images(
        self,
        prompt: str,
        size: str | None,
        *,
        quality: str | None,
        n: int,
        output_format: str | None,
        output_compression: int | None,
        background: str | None,
        watermark: bool,
    ) -> list[GeneratedImage]:
        try:
            from openai import OpenAI

            client = OpenAI(
                base_url=self.settings.image_api_base_url,
                api_key=self.settings.image_api_key,
            )
            request_options: dict[str, Any] = {
                "model": self.settings.image_model,
                "prompt": prompt,
            }
            if size is not None:
                request_options["size"] = size
            if n != 1:
                request_options["n"] = n
            if quality:
                request_options["quality"] = quality
            if output_format:
                request_options["output_format"] = output_format
            if output_compression is not None:
                request_options["output_compression"] = output_compression
            if background:
                request_options["background"] = background
            if self.settings.image_response_format:
                request_options["response_format"] = self.settings.image_response_format
            extra_body: dict[str, Any] = {}
            if self.settings.image_watermark_field:
                extra_body[self.settings.image_watermark_field] = watermark
            if extra_body:
                request_options["extra_body"] = extra_body
            response = client.images.generate(**request_options)
            response_images = response.data or []
        except Exception as exc:
            raise ImageGenerationError("生图服务请求失败") from exc
        images: list[GeneratedImage] = []
        for image in response_images:
            source_url = getattr(image, "url", None)
            if source_url:
                images.append(GeneratedImage(suffix=self._suffix_from_url(source_url), source_url=source_url))
                continue
            image_base64 = getattr(image, "b64_json", None)
            if image_base64:
                try:
                    content = b64decode(image_base64, validate=True)
                except (ValueError, TypeError) as exc:
                    raise ImageGenerationError("生图服务返回了无效的图片内容") from exc
                suffix = f".{output_format}" if output_format else self._output_suffix()
                images.append(GeneratedImage(suffix=suffix, content=content))
        if not images:
            raise ImageGenerationError("生图服务没有返回图片内容")
        return images

    def _upload_generated_images(
        self,
        request_id: str,
        generated_images: list[GeneratedImage],
        watermark: bool,
    ) -> list[dict[str, Any]]:
        images: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="image-generation-") as temp_dir:
            for index, generated_image in enumerate(generated_images, start=1):
                local_file = Path(temp_dir) / f"generated-{index}{generated_image.suffix}"
                if generated_image.content is not None:
                    local_file.write_bytes(generated_image.content)
                elif generated_image.source_url:
                    self._download(generated_image.source_url, local_file)
                else:  # pragma: no cover - protected by _generate_images
                    raise ImageGenerationError("生图服务没有返回图片内容")
                uploaded = self._upload(local_file, self._object_key(request_id, index, generated_image.suffix))
                images.append(
                    {
                        "id": f"{request_id}_{index}",
                        "url": uploaded["url"],
                        "mime_type": uploaded["mime_type"],
                        "watermark_requested": watermark,
                        # Watermark is a configured extension; standard OpenAI
                        # Images does not report whether it was applied.
                        "watermark_applied": watermark if self.settings.image_watermark_field else None,
                    }
                )
        return images

    def _download(self, source_url: str, destination: Path) -> None:
        request = Request(source_url, headers={"User-Agent": "DeepAgent image tool/1.0"})
        try:
            with urlopen(request, timeout=self.settings.image_download_timeout_seconds) as response:
                with destination.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
        except Exception as exc:
            raise ImageGenerationError("生成的图片下载失败") from exc

    def _upload(self, local_file: Path, object_key: str) -> dict[str, str]:
        try:
            from qcloud_cos import CosConfig, CosS3Client
            from qcloud_cos.cos_exception import CosClientError, CosServiceError

            client = CosS3Client(
                CosConfig(
                    Region=self.settings.cos_region,
                    SecretId=self.settings.cos_secret_id,
                    SecretKey=self.settings.cos_secret_key,
                    Scheme=self.settings.cos_scheme,
                )
            )
            mime_type = mimetypes.guess_type(local_file.name)[0] or "image/png"
            client.upload_file(
                Bucket=self.settings.cos_bucket,
                Key=object_key,
                LocalFilePath=str(local_file),
                PartSize=self.settings.image_upload_part_size_mb,
                MAXThread=self.settings.image_upload_max_threads,
                EnableMD5=False,
                ContentType=mime_type,
                ACL=self.settings.image_upload_acl,
            )
        except (CosClientError, CosServiceError) as exc:
            raise ImageGenerationError("生成的图片上传失败") from exc
        except Exception as exc:
            raise ImageGenerationError("生成的图片上传失败") from exc

        encoded_key = quote(object_key, safe="/")
        return {
            "url": f"{self.settings.cos_scheme}://{self.settings.cos_bucket}.cos."
            f"{self.settings.cos_region}.myqcloud.com/{encoded_key}",
            "mime_type": mime_type,
        }

    def _object_key(self, request_id: str, index: int, suffix: str) -> str:
        prefix = self.settings.image_upload_prefix.strip("/")
        name = f"generated-{index}{suffix}"
        return f"{prefix}/{request_id}/{name}" if prefix else f"{request_id}/{name}"

    @staticmethod
    def _suffix_from_url(source_url: str) -> str:
        suffix = Path(source_url.split("?", maxsplit=1)[0]).suffix.lower()
        return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp"} else ".png"

    def _output_suffix(self) -> str:
        suffix = self.settings.image_output_extension.strip().lower().lstrip(".")
        if suffix not in {"png", "jpg", "jpeg", "webp"}:
            raise ImageGenerationError("IMAGE_OUTPUT_EXTENSION 必须是 png、jpg、jpeg 或 webp")
        return f".{suffix}"
