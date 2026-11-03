import asyncio
import sys
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from pptx import Presentation
from pydantic import ValidationError

from app.config import Settings
from app.errors import ErrorCode, classify_run_error
from app.skill_tools import SkillToolRegistry, _load_module
from app.skills import SkillRegistry
from app.tool_sse import artifacts_from_tool_trace


ppt_tools = _load_module(Path(__file__).resolve().parents[1] / "skills/ppt-generation/scripts/tools.py")
PresentationError = ppt_tools.PresentationError
PresentationService = ppt_tools.PresentationService


def settings(**overrides):
    instance = Settings()
    for name, value in {
        "ppt_generation_enabled": True, "ppt_upload_prefix": "presentations",
        "ppt_preview_enabled": False,
        "cos_bucket": "test-123", "cos_region": "ap-guangzhou",
        "cos_secret_id": "test-id", "cos_secret_key": "test-secret", **overrides,
    }.items():
        setattr(instance, name, value)
    return instance


@pytest.fixture
def uploaded(monkeypatch):
    captured = {}

    def upload(config, path, key):
        if path.suffix == ".pptx":
            captured.update(content=path.read_bytes(), path=path, key=key)
        return {"url": f"https://example.com/{key}", "mime_type": "application/pdf" if path.suffix == ".pdf" else "application/vnd.openxmlformats-officedocument.presentationml.presentation"}

    monkeypatch.setattr(ppt_tools, "upload_file", upload)
    return captured


def test_generates_editable_deck_and_cleans_temporary_files(uploaded):
    result = PresentationService(settings()).generate_and_upload("季度汇报 / 草案", [
        {"layout": "cover", "title": "季度汇报", "subtitle": "产品与研发"},
        {"title": "工作成果", "bullets": ["完成 PPT 工具接入", "交付可编辑文稿"], "notes": "补充演讲内容"},
        {"layout": "closing", "title": "谢谢", "subtitle": "欢迎交流"},
    ])
    deck = Presentation(BytesIO(uploaded["content"]))
    assert len(deck.slides) == 3
    assert round(deck.slide_width / deck.slide_height, 3) == 1.778
    text = "\n".join(shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
    assert "完成 PPT 工具接入" in text
    assert "补充演讲内容" not in text
    assert "补充演讲内容" in deck.slides[1].notes_slide.notes_text_frame.text
    assert deck.core_properties.title == "季度汇报 / 草案"
    assert result["files"][0]["slide_count"] == 3
    assert result["files"][0]["size_bytes"] == len(uploaded["content"])
    assert result["files"][0]["file_name"].endswith(".pptx")
    assert uploaded["key"].startswith("presentations/ppt_")
    assert not uploaded["path"].exists()


@pytest.mark.parametrize("theme", ["business", "forest", "sunset", "ink"])
def test_themes_preserve_content_and_use_distinct_backgrounds(theme, uploaded):
    result = PresentationService(settings()).generate_and_upload("主题测试", [
        {"title": "主题封面", "layout": "cover", "subtitle": "可编辑的视觉主题"},
        {"title": "主题正文", "bullets": ["核心内容保留"]},
    ], theme=theme)
    deck = Presentation(BytesIO(uploaded["content"]))
    assert str(deck.slides[0].background.fill.fore_color.rgb) == ppt_tools.THEMES[theme]["hero"]
    assert str(deck.slides[1].background.fill.fore_color.rgb) == ppt_tools.THEMES[theme]["background"]
    assert any("核心内容保留" in shape.text for shape in deck.slides[1].shapes if shape.has_text_frame)
    assert result["files"][0]["theme"] == theme
    assert result["files"][0]["theme_name"] == ppt_tools.THEMES[theme]["name"]


def test_invalid_theme_is_rejected(uploaded):
    with pytest.raises(ValidationError):
        PresentationService(settings()).generate_and_upload("主题测试", [{"title": "正文"}], theme="unknown")
    assert uploaded == {}


def test_preview_is_uploaded_and_attached_to_ppt(monkeypatch):
    uploads = []

    def convert(self, local_file):
        preview = local_file.with_suffix(".pdf")
        preview.write_bytes(b"%PDF-1.7 test")
        return preview

    def upload(config, path, key):
        uploads.append((path.suffix, key))
        return {"url": f"https://example.com/{key}", "mime_type": "application/pdf" if path.suffix == ".pdf" else "application/vnd.openxmlformats-officedocument.presentationml.presentation"}

    monkeypatch.setattr(PresentationService, "convert_to_pdf", convert)
    monkeypatch.setattr(ppt_tools, "upload_file", upload)
    result = PresentationService(settings(ppt_preview_enabled=True)).generate_and_upload("预览测试", [{"title": "正文"}])
    assert [suffix for suffix, _ in uploads] == [".pptx", ".pdf"]
    file = result["files"][0]
    assert file["preview_status"] == "ready"
    assert file["preview_url"].endswith("/preview.pdf")
    artifact = artifacts_from_tool_trace(callback(result))[0]
    assert artifact["metadata"]["preview_url"] == file["preview_url"]
    assert artifact["metadata"]["preview_mime_type"] == "application/pdf"


@pytest.mark.parametrize("stage", ["conversion", "upload"])
def test_preview_failure_keeps_the_editable_ppt(monkeypatch, stage):
    def convert(self, local_file):
        if stage == "conversion":
            raise FileNotFoundError("libreoffice")
        preview = local_file.with_suffix(".pdf")
        preview.write_bytes(b"%PDF-1.7 test")
        return preview

    def upload(config, path, key):
        if path.suffix == ".pdf":
            raise RuntimeError("private details")
        return {"url": f"https://example.com/{key}", "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}

    monkeypatch.setattr(PresentationService, "convert_to_pdf", convert)
    monkeypatch.setattr(ppt_tools, "upload_file", upload)
    result = PresentationService(settings(ppt_preview_enabled=True)).generate_and_upload("预览测试", [{"title": "正文"}])
    file = result["files"][0]
    assert result["status"] == "succeeded"
    assert file["url"].endswith(".pptx")
    assert file["preview_status"] == "unavailable"
    assert "preview_url" not in file
    assert "private details" not in file["preview_message"]


def test_converter_uses_isolated_profile_and_checks_pdf(monkeypatch, tmp_path):
    source = tmp_path / "slides.pptx"
    source.write_bytes(b"pptx")
    calls = []

    def convert(command, **kwargs):
        calls.append((command, kwargs))
        target = tmp_path / "preview" / "slides.pdf"
        target.write_bytes(b"%PDF-1.7 test")

    monkeypatch.setattr(ppt_tools.subprocess, "run", convert)
    preview = PresentationService(settings()).convert_to_pdf(source)
    assert preview.read_bytes().startswith(b"%PDF-")
    assert any("UserInstallation=file:" in argument for argument in calls[0][0])
    assert calls[0][1]["timeout"] > 0
    assert calls[0][1].get("shell", False) is False


@pytest.mark.parametrize("preview_url", ["javascript:alert(1)", "https://other.example/preview.pdf", "https://example.com/preview.html"])
def test_artifacts_reject_unsafe_preview_urls(preview_url):
    result = {"status": "succeeded", "files": [{"url": "https://example.com/a.pptx",
        "preview_status": "ready", "preview_mime_type": "application/pdf", "preview_url": preview_url}]}
    assert "preview_url" not in artifacts_from_tool_trace(callback(result))[0]["metadata"]


@pytest.mark.parametrize("slides", [[], [{"title": " "}], [{"title": "a", "layout": "invalid"}],
    [{"title": "a", "layout": "image"}], [{"title": "a", "bullets": ["a"] * 7}],
    [{"title": "a\x00"}], [{"title": "a", "image_url": "https://example.com/a.png"}],
    [{"title": "a"}] * 51])
def test_rejects_invalid_content(slides, uploaded):
    with pytest.raises(ValidationError):
        PresentationService(settings()).generate_and_upload("标题", slides)
    assert uploaded == {}


def test_dense_slide_fails_without_silently_truncating(uploaded):
    with pytest.raises(PresentationError, match="拆分"):
        PresentationService(settings()).generate_and_upload("标题", [{
            "layout": "cover", "title": "标题", "bullets": ["长" * 160] * 6,
        }])
    assert uploaded == {}


@pytest.mark.parametrize("overrides, message", [
    ({"ppt_generation_enabled": False}, "未启用"), ({"cos_bucket": None}, "COS_BUCKET"),
])
def test_missing_configuration_has_tool_error(overrides, message, uploaded):
    with pytest.raises(PresentationError, match=message) as error:
        PresentationService(settings(**overrides)).generate_and_upload("标题", [{"title": "正文"}])
    assert classify_run_error(error.value)["code"] == ErrorCode.TOOL_CALL_FAILED.value
    assert uploaded == {}


def test_upload_failure_does_not_return_a_success(monkeypatch):
    def fail(*args):
        raise RuntimeError("private credentials")
    monkeypatch.setattr(ppt_tools, "upload_file", fail)
    with pytest.raises(PresentationError, match="PPT 上传失败") as error:
        PresentationService(settings()).generate_and_upload("标题", [{"title": "正文"}])
    assert "private credentials" not in str(error.value)
    assert error.value.retryable is True


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://127.0.0.1/a.png", "https://example.com/a.png",
    "https://test-123.cos.ap-guangzhou.myqcloud.com.evil.com/a.png",
    "https://user@test-123.cos.ap-guangzhou.myqcloud.com/a.png",
])
def test_image_urls_are_restricted_to_configured_cos(url, tmp_path):
    with pytest.raises(PresentationError, match="当前 COS"):
        PresentationService(settings())._download_image(url, tmp_path / "image.png")


@pytest.mark.parametrize("invalid", [False, True])
def test_image_download_and_powerpoint_embedding(monkeypatch, uploaded, invalid):
    image_bytes = BytesIO()
    Image.new("RGB", (160, 90), "blue").save(image_bytes, format="WEBP")
    url = "https://test-123.cos.ap-guangzhou.myqcloud.com/image.webp"

    @contextmanager
    def stream(method, requested_url, **kwargs):
        assert requested_url == url
        assert kwargs["follow_redirects"] is False
        yield httpx.Response(200, content=b"invalid" if invalid else image_bytes.getvalue(), request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "stream", stream)
    service = PresentationService(settings())
    slides = [{"title": "配图", "layout": "image", "image_url": url, "bullets": ["原生文字"]}]
    if invalid:
        with pytest.raises(PresentationError, match="下载或解码失败"):
            service.generate_and_upload("图文测试", slides)
        assert uploaded == {}
    else:
        service.generate_and_upload("图文测试", slides)
        deck = Presentation(BytesIO(uploaded["content"]))
        pictures = [shape for shape in deck.slides[0].shapes if shape.shape_type == 13]
        assert len(pictures) == 1
        assert pictures[0].image.ext == "png"
        assert abs(pictures[0].width / pictures[0].height - 160 / 90) < .01


def callback(result, status="completed"):
    return {"role": "tool_callback", "content": [{"tool_name": "generate_ppt", "tool_call_id": "call-ppt",
        "status": status, "result": {"type": "json", "content": result}}]}


def test_failed_callbacks_never_expose_file_artifacts():
    result = {"status": "succeeded", "files": [{"url": "https://example.com/a.pptx"}]}
    assert artifacts_from_tool_trace(callback(result, "error")) == []
    assert artifacts_from_tool_trace(callback({**result, "status": "failed"})) == []
    assert artifacts_from_tool_trace(callback({**result, "files": [{"url": "javascript:alert(1)"}]})) == []


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("with_images", [False, True])
def test_agent_tool_to_api_delivery_and_history(monkeypatch, uploaded, stream, with_images):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from app.agent import AgentClient
    from app.runtime import AgentRuntime
    from app.schemas import RunRequest
    from app.services import RunService, business_store

    class ToolModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            assert "generate_ppt" in {tool.name for tool in tools}
            return self

    image_url = "https://test-123.cos.ap-guangzhou.myqcloud.com/generated/illustration.png"
    slides = [{"title": "正文", "bullets": ["关键成果"]}]
    responses = []
    if with_images:
        slides[0].update(layout="image", image_url=image_url)
        responses.append(AIMessage(content="", tool_calls=[{"name": "generate_image", "args": {"prompt": "科技办公场景，横向构图"}, "id": "call-image"}]))
        image = BytesIO()
        Image.new("RGB", (160, 90), "blue").save(image, format="PNG")
        def download(self, url, destination):
            assert url == image_url
            destination.write_bytes(image.getvalue())
        monkeypatch.setattr(PresentationService, "_download_image", download)
        monkeypatch.setattr("app.tools.ImageGenerationService.generate_and_upload", lambda self, prompt, n=1: {
            "request_id": "image-1", "status": "succeeded", "images": [{"id": "image-1", "url": image_url, "mime_type": "image/png"}],
        })
    responses.extend([AIMessage(content="", tool_calls=[{
        "name": "generate_ppt", "args": {"title": "示例汇报", "slides": slides},
        "id": "call-ppt",
    }]), AIMessage(content="PPT 已生成，请下载。")])
    model = ToolModel(responses=responses)
    config = settings(agent_backend="deepagents", ppt_preview_enabled=True, image_generation_enabled=with_images)
    def convert(self, local_file):
        path = local_file.with_suffix(".pdf")
        path.write_bytes(b"%PDF-1.7 test")
        return path
    monkeypatch.setattr(PresentationService, "convert_to_pdf", convert)
    monkeypatch.setattr("app.tools.get_settings", lambda: config)
    monkeypatch.setattr(ppt_tools, "get_settings", lambda: config)
    monkeypatch.setattr("app.tools.skill_tool_registry", SkillToolRegistry(config))
    runtime = AgentRuntime(config)
    runtime.checkpointer = InMemorySaver()
    monkeypatch.setattr(runtime, "create_model", lambda: model)
    monkeypatch.setattr("app.agent.runtime", runtime)
    monkeypatch.setattr("app.services.log_agent_event", lambda **kwargs: None)
    monkeypatch.setattr(business_store, "get_or_create_thread", lambda *args: {
        "thread_id": "thread", "context_version": 1, "active_skill_ids": ["ppt-generation"],
    })
    saved = {}

    async def db_event(name, operation, *args, **kwargs):
        if name == "next_sequence":
            return 1
        if name == "save_assistant_message":
            saved["content"] = args[5]

    async def attach(*args):
        pass

    async def guard(*args):
        return {"blocked": False, "action": "allow"}

    monkeypatch.setattr("app.services._db_event", db_event)
    monkeypatch.setattr("app.services._attach_request_context", attach)
    service = RunService()
    service.agent = AgentClient(config)
    service.model_guard = SimpleNamespace(check=guard)
    request = RunRequest(user_id="user", agent_prompt="你是演示文稿助手。",
                         active_skill_ids=["ppt-generation"], content=[{"type": "text", "text": "生成 PPT"}])

    async def run():
        if stream:
            events = [event async for event in service.run_stream(request)]
            assert events[-1][0] == "run.completed", events[-1]
            artifact_events = [data for event, data in events if event == "artifact.created"]
            assert len(artifact_events) == (2 if with_images else 1)
            assert artifact_events[-1]["tool_call_id"] == "call-ppt"
            return events[-1][1]
        result = await service.run_json(request)
        assert result.status == "completed", result
        return result.model_dump()

    response = asyncio.run(run())
    file = response["artifacts"][-1]
    assert file["type"] == "file"
    assert file["metadata"]["slide_count"] == 1
    assert file["metadata"]["preview_url"].endswith("/preview.pdf")
    assert saved["content"][-1]["metadata"] == file["metadata"]
    assert saved["content"][-1]["type"] == "file"
    deck = Presentation(BytesIO(uploaded["content"]))
    assert len(deck.slides) == 1
    assert sum(shape.shape_type == 13 for shape in deck.slides[0].shapes) == int(with_images)
    assert tuple(runtime._agents_by_skill_set) == (("ppt-generation",),)


def test_tool_can_be_disabled(monkeypatch):
    from app import tools
    config = settings(ppt_generation_enabled=False)
    monkeypatch.setattr(ppt_tools, "get_settings", lambda: config)
    monkeypatch.setattr(tools, "skill_tool_registry", SkillToolRegistry(config))
    assert "generate_ppt" not in {tool.__name__ for tool in tools.get_agent_tools(("ppt-generation",))}


def test_skill_is_discoverable_opt_in_and_owns_its_tool(monkeypatch):
    from app import tools

    config = settings()
    registry = SkillToolRegistry(config)
    monkeypatch.setattr(tools, "skill_tool_registry", registry)
    monkeypatch.setattr(ppt_tools, "get_settings", lambda: config)
    skill = next(skill for skill in SkillRegistry(config).list() if skill.id == "ppt-generation")
    assert skill.enabled_by_default is False
    assert "generate_ppt" not in {tool.__name__ for tool in tools.get_agent_tools()}
    selected = {tool.__name__: tool for tool in tools.get_agent_tools(("ppt-generation",))}
    assert Path(sys.modules[selected["generate_ppt"].__module__].__file__).resolve() == (
        Path(config.agent_filesystem_root) / "skills/ppt-generation/scripts/tools.py"
    ).resolve()


def test_unselected_ppt_module_is_not_loaded(monkeypatch):
    from app import skill_tools

    def fail_if_loaded(path):
        pytest.fail(f"Unselected tool entrypoint was imported: {path}")

    monkeypatch.setattr(skill_tools, "_load_module", fail_if_loaded)
    assert SkillToolRegistry(settings()).tools_for(()) == []


def test_shared_cos_uploader_sets_ppt_mime_and_download_filename(monkeypatch, tmp_path):
    import qcloud_cos
    from app.object_storage import upload_file

    captured = {}
    monkeypatch.setattr(qcloud_cos, "CosS3Client", lambda config: SimpleNamespace(upload_file=lambda **kwargs: captured.update(kwargs)))
    path = tmp_path / "季度报告.pptx"
    path.write_bytes(b"pptx")
    result = upload_file(settings(), path, "presentations/季度报告.pptx")
    assert captured["ContentType"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    assert captured["ContentDisposition"].startswith("attachment; filename*=UTF-8''")
    assert "%E5" in captured["ContentDisposition"]
    assert result["url"].endswith("%E5%AD%A3%E5%BA%A6%E6%8A%A5%E5%91%8A.pptx")
