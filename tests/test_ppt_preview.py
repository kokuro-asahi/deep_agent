from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import artifacts
from app.auth import get_current_user


URL = "https://test-123.cos.ap-guangzhou.myqcloud.com/presentations/ppt_" + "a" * 32 + "/preview.pdf"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(artifacts, "get_settings", lambda: SimpleNamespace(
        cos_bucket="test-123", cos_region="ap-guangzhou", ppt_upload_prefix="presentations"))
    app = FastAPI()
    app.include_router(artifacts.router)
    app.dependency_overrides[get_current_user] = lambda: object()
    with TestClient(app) as client:
        yield client


def stub_upstream(monkeypatch, *, content=b"%PDF-1.7 preview", status=200):
    @contextmanager
    def stream(method, url, **kwargs):
        assert url == URL
        assert kwargs["follow_redirects"] is False
        yield httpx.Response(status, content=content, headers={"Content-Disposition": "attachment"}, request=httpx.Request(method, url))
    monkeypatch.setattr(artifacts.httpx, "stream", stream)


def test_generated_pdf_is_served_inline_even_when_storage_forces_download(client, monkeypatch):
    stub_upstream(monkeypatch)
    response = client.get("/v1/artifacts/ppt-preview", params={"url": URL})
    assert response.status_code == 200
    assert response.content == b"%PDF-1.7 preview"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://127.0.0.1/preview.pdf", "https://other.example/preview.pdf",
    URL.replace("/presentations/", "/private/"), URL.replace("preview.pdf", "file.pdf"),
    URL + "?redirect=anything", URL.replace("https://", "https://user@"),
])
def test_preview_proxy_rejects_unrelated_sources_without_fetching(client, monkeypatch, url):
    monkeypatch.setattr(artifacts.httpx, "stream", lambda *args, **kwargs: pytest.fail("Invalid source was fetched"))
    assert client.get("/v1/artifacts/ppt-preview", params={"url": url}).status_code == 400


@pytest.mark.parametrize("status, content", [(404, b"missing"), (200, b"<html>Not a PDF</html>")])
def test_preview_proxy_reports_invalid_or_missing_files(client, monkeypatch, status, content):
    stub_upstream(monkeypatch, content=content, status=status)
    assert client.get("/v1/artifacts/ppt-preview", params={"url": URL}).status_code == 502


def test_preview_proxy_bounds_download_size(client, monkeypatch):
    stub_upstream(monkeypatch)
    monkeypatch.setattr(artifacts, "MAX_PREVIEW_BYTES", 5)
    assert client.get("/v1/artifacts/ppt-preview", params={"url": URL}).status_code == 502
