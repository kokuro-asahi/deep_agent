from types import SimpleNamespace

import pytest

from app.image_generation import GeneratedImage, ImageGenerationService


def _settings(**overrides):
    values = {
        "image_generation_enabled": True,
        "image_api_key": "key",
        "image_api_base_url": "https://example.com/v1",
        "image_model": "image-model",
        "image_response_format": None,
        "image_output_extension": "png",
        "image_default_size": "1024x1024",
        "image_allowed_sizes": ("1024x1024", "1536x1024", "1024x1536"),
        "image_aspect_ratio_sizes": {
            "1:1": "1024x1024",
            "16:9": "1536x1024",
            "9:16": "1024x1536",
        },
        "image_default_watermark": True,
        "image_watermark_field": "watermark",
        "image_download_timeout_seconds": 120,
        "image_upload_prefix": "generated",
        "image_upload_part_size_mb": 10,
        "image_upload_max_threads": 5,
        "image_upload_acl": "public-read",
        "cos_secret_id": "id",
        "cos_secret_key": "secret",
        "cos_bucket": "bucket-123",
        "cos_region": "ap-guangzhou",
        "cos_scheme": "https",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _stub_images(monkeypatch, service, images=None):
    captured = {}
    monkeypatch.setattr(
        service,
        "_generate_images",
        lambda prompt, size, **options: captured.update({"prompt": prompt, "size": size, **options})
        or (images or [GeneratedImage(".png", content=b"image-bytes")]),
    )
    monkeypatch.setattr(
        service,
        "_upload",
        lambda _, key: {"url": f"https://example.com/{key}", "mime_type": "image/png"},
    )
    return captured


def test_image_generation_rejects_unconfigured_size():
    service = ImageGenerationService(_settings())

    with pytest.raises(ValueError, match="不支持的图片尺寸"):
        service.generate_and_upload("一只猫", size="2048x2048")


def test_image_generation_maps_aspect_ratio_to_actual_size(monkeypatch):
    service = ImageGenerationService(_settings())
    captured = _stub_images(monkeypatch, service)

    service.generate_and_upload("城市夜景", aspect_ratio="16:9")

    assert captured["prompt"] == "城市夜景"
    assert captured["size"] == "1536x1024"


def test_image_generation_rejects_ambiguous_size_and_aspect_ratio():
    service = ImageGenerationService(_settings())

    with pytest.raises(ValueError, match="不能同时指定"):
        service.generate_and_upload("城市夜景", size="1024x1024", aspect_ratio="1:1")


def test_image_generation_forwards_standard_generation_options(monkeypatch):
    service = ImageGenerationService(_settings())
    captured = _stub_images(monkeypatch, service)

    result = service.generate_and_upload(
        "透明背景的产品图",
        quality="high",
        n=2,
        output_format="webp",
        output_compression=80,
        background="transparent",
        watermark=False,
    )

    assert captured == {
        "prompt": "透明背景的产品图",
        "size": None,
        "quality": "high",
        "n": 2,
        "output_format": "webp",
        "output_compression": 80,
        "background": "transparent",
        "watermark": False,
    }
    assert result["parameters"] == {
        "size": None,
        "aspect_ratio": None,
        "quality": "high",
        "n": 2,
        "output_format": "webp",
        "output_compression": 80,
        "background": "transparent",
    }


def test_image_generation_rejects_invalid_compression_options():
    service = ImageGenerationService(_settings())

    with pytest.raises(ValueError, match="仅支持"):
        service.generate_and_upload("一只猫", output_compression=80)
    with pytest.raises(ValueError, match="0 到 100"):
        service.generate_and_upload("一只猫", output_format="webp", output_compression=101)


def test_image_generation_uploads_each_returned_image(monkeypatch):
    service = ImageGenerationService(_settings())
    generated_images = [
        GeneratedImage(".png", content=b"first"),
        GeneratedImage(".webp", content=b"second"),
    ]
    _stub_images(monkeypatch, service, generated_images)
    uploads = []

    def fake_upload(local_file, object_key):
        uploads.append((local_file.read_bytes(), object_key))
        return {"url": f"https://example.com/{object_key}", "mime_type": "image/png"}

    monkeypatch.setattr(service, "_upload", fake_upload)

    result = service.generate_and_upload("一只猫", n=2, watermark=False)

    assert uploads[0][0] == b"first"
    assert uploads[1][0] == b"second"
    assert uploads[0][1].endswith("/generated-1.png")
    assert uploads[1][1].endswith("/generated-2.webp")
    assert len(result["images"]) == 2
    assert result["images"][0]["watermark_requested"] is False


def test_configured_endpoint_uses_its_configured_resolution_preset(monkeypatch):
    service = ImageGenerationService(
        _settings(
            image_model="doubao-seedream-5-0-260128",
            image_default_size="2K",
            image_allowed_sizes=("1K", "1.5K", "2K"),
            image_aspect_ratio_sizes={"16:9": "2K"},
        )
    )
    captured = _stub_images(monkeypatch, service)

    result = service.generate_and_upload("春日香水广告", aspect_ratio="16:9", n=3, watermark=False)

    assert captured["prompt"] == "春日香水广告"
    assert captured["size"] == "2K"
    assert captured["n"] == 3
    assert result["images"][0]["watermark_applied"] is False
