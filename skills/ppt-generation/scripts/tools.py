"""PPT generation tool, schema and renderer owned by the ppt-generation skill."""

from __future__ import annotations

import math
import os
import re
import subprocess
import tempfile
import unicodedata
import uuid
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.config import Settings, get_settings
from app.errors import AppError, ErrorCode
from app.object_storage import upload_file


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
ThemeName = Literal["business", "forest", "sunset", "ink"]
THEMES = {
    "business": dict(name="商务蓝", background="EDF3FC", surface="FFFFFF", ink="193454", muted="60748E",
                     accent="3267E3", hero="142B50", hero_ink="FFFFFF", hero_muted="BED0EC", motif="244475"),
    "forest": dict(name="自然绿", background="F0F3EB", surface="FBFCF7", ink="25473B", muted="61776B",
                   accent="58836B", hero="24473B", hero_ink="FAF7EA", hero_muted="CBD7C5", motif="3C6150"),
    "sunset": dict(name="暖橙", background="FAF0E8", surface="FFFBF6", ink="57372F", muted="937365",
                   accent="D46541", hero="F2DBCB", hero_ink="57372F", hero_muted="856251", motif="E7B69B"),
    "ink": dict(name="黑金", background="1A1D24", surface="232730", ink="F3EFE4", muted="A5A9B2",
                accent="CDA86D", hero="13161C", hero_ink="F3EFE4", hero_muted="BBB19F", motif="292B30"),
}


class PresentationSlide(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=80, description="本页标题")
    layout: Literal["cover", "bullets", "image", "closing"] = Field(
        default="bullets", description="封面、文字要点、左文右图、结束页"
    )
    subtitle: str = Field(default="", max_length=240, description="可选副标题")
    bullets: list[ShortText] = Field(default_factory=list, max_length=6, description="最多六条简短要点")
    image_url: str | None = Field(default=None, max_length=2048, description="image 版式必填，使用生图工具返回的 COS 图片 URL")
    notes: str = Field(default="", max_length=4000, description="演讲者备注，不显示在页面上")

    @model_validator(mode="after")
    def validate_content(self) -> PresentationSlide:
        if self.layout == "image" and not self.image_url:
            raise ValueError("image 版式需要 image_url")
        if self.image_url and self.layout != "image":
            raise ValueError("包含 image_url 时请使用 image 版式")
        for text in (self.title, self.subtitle, self.notes, *self.bullets):
            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
                raise ValueError("PPT 文本不能包含控制字符")
        return self


class PresentationSpec(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    slides: list[PresentationSlide] = Field(min_length=1, max_length=50)
    theme: ThemeName = "business"


class PresentationError(AppError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(ErrorCode.TOOL_CALL_FAILED, message, retryable=retryable)


class PresentationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate_and_upload(self, title: str, slides: list[PresentationSlide | dict[str, Any]],
                            theme: ThemeName = "business") -> dict[str, Any]:
        spec = PresentationSpec(title=title, slides=slides, theme=theme)
        if not self.settings.ppt_generation_enabled:
            raise PresentationError("PPT 生成功能未启用")
        for name, value in (
            ("COS_SECRET_ID", self.settings.cos_secret_id),
            ("COS_SECRET_KEY", self.settings.cos_secret_key),
            ("COS_BUCKET", self.settings.cos_bucket),
        ):
            if not value:
                raise PresentationError(f"缺少配置：{name}")

        request_id = f"ppt_{uuid.uuid4().hex}"
        safe_title = re.sub(r"[^\w\u4e00-\u9fff .-]", "_", spec.title)[:60].strip(" .") or "presentation"
        file_name = f"{safe_title}.pptx"
        prefix = self.settings.ppt_upload_prefix.strip("/")
        key = "/".join(part for part in (prefix, request_id, file_name) if part)
        with tempfile.TemporaryDirectory(prefix="ppt-generation-") as directory:
            local_file = Path(directory) / file_name
            try:
                self.render(spec, local_file)
            except (PresentationError, ValueError):
                raise
            except ImportError as exc:
                raise PresentationError("缺少 PPT 生成依赖，请安装 requirements.txt 并重启服务") from exc
            except Exception as exc:
                raise PresentationError("PPT 文件生成失败，请检查页面内容后重试") from exc
            size = local_file.stat().st_size
            try:
                uploaded = upload_file(self.settings, local_file, key)
            except Exception as exc:
                raise PresentationError("PPT 上传失败，请检查 COS 配置后重试", retryable=True) from exc
            preview = self._preview(local_file, key.rsplit("/", 1)[0] + "/preview.pdf")
        return {
            "request_id": request_id,
            "status": "succeeded",
            "files": [{
                "id": request_id,
                "url": uploaded["url"],
                "mime_type": uploaded["mime_type"],
                "file_name": file_name,
                "size_bytes": size,
                "slide_count": len(spec.slides),
                "theme": spec.theme,
                "theme_name": THEMES[spec.theme]["name"],
                **preview,
            }],
        }

    def _preview(self, local_file: Path, object_key: str) -> dict[str, Any]:
        if not self.settings.ppt_preview_enabled:
            return {"preview_status": "disabled"}
        try:
            preview_file = self.convert_to_pdf(local_file)
            uploaded = upload_file(self.settings, preview_file, object_key)
            return {"preview_status": "ready", "preview_url": uploaded["url"], "preview_mime_type": "application/pdf"}
        except Exception:
            # The editable PPT remains deliverable when the renderer or preview
            # upload is unavailable. Never expose renderer output or credentials.
            return {"preview_status": "unavailable", "preview_message": "预览暂不可用，仍可下载 PPT；请检查预览转换服务。"}

    def convert_to_pdf(self, local_file: Path) -> Path:
        output_dir = local_file.parent / "preview"
        output_dir.mkdir(exist_ok=True)
        profile = (local_file.parent / "libreoffice-profile").as_uri()
        subprocess.run([
            self.settings.ppt_preview_command, f"-env:UserInstallation={profile}",
            "--headless", "--convert-to", "pdf:impress_pdf_Export", "--outdir", str(output_dir), str(local_file),
        ], check=True, timeout=self.settings.ppt_preview_timeout_seconds,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "SAL_USE_VCLPLUGIN": "svp", "GSETTINGS_BACKEND": "memory"})
        preview_file = output_dir / f"{local_file.stem}.pdf"
        with preview_file.open("rb") as content:
            if content.read(5) != b"%PDF-":
                raise ValueError("无效的 PDF 预览")
        return preview_file

    def render(self, spec: PresentationSpec, destination: Path) -> None:
        """Build a real .pptx with native text, shapes, images and speaker notes."""
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.util import Inches

        presentation = Presentation()
        presentation.slide_width = Inches(13.333333)
        presentation.slide_height = Inches(7.5)
        presentation.core_properties.title = spec.title
        presentation.core_properties.author = "Deep Agent"
        palette = THEMES[spec.theme]
        images: dict[str, Path] = {}
        for index, page in enumerate(spec.slides, start=1):
            slide = presentation.slides.add_slide(presentation.slide_layouts[6])
            hero = page.layout in {"cover", "closing"}
            foreground = palette["hero_ink"] if hero else palette["ink"]
            secondary = palette["hero_muted"] if hero else palette["muted"]
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = RGBColor.from_string(palette["hero"] if hero else palette["background"])
            self._decorate(slide, spec.theme, palette, hero, index)
            title_width = 9.2 if hero else 11.7
            self._text(slide, [page.title], .8, 1.55 if hero else .85, title_width, 1.8 if hero else 1.05,
                       size=44 if hero else 32, minimum=24, color=foreground, bold=True)
            if page.subtitle:
                self._text(slide, [page.subtitle], .8 if hero else 1.15, 3.6 if hero else 2.15, 9.2 if hero else 10.9, .7,
                           size=22 if hero else 20, minimum=16, color=secondary)
            body_y = 4.75 if hero else (3.05 if page.subtitle else 2.2)
            body_height = 6.65 - body_y
            body_width = 5.15 if page.layout == "image" else (9.2 if hero else 10.9)
            if page.bullets:
                self._text(slide, [f"•  {text}" for text in page.bullets], .8 if hero else 1.15, body_y, body_width, body_height,
                           size=24, minimum=16, color=foreground, spacing=12)
            if page.image_url:
                if page.image_url not in images:
                    image_file = destination.parent / f"asset-{index}.png"
                    self._download_image(page.image_url, image_file)
                    images[page.image_url] = image_file
                self._picture(slide, images[page.image_url], 6.95, body_y, 5.55, body_height)
            self._text(slide, [f"{index:02d} / {len(spec.slides):02d}"], 11.25, 7.02, 1.3, .25,
                       size=10, minimum=10, color=secondary)
            if page.notes:
                slide.notes_slide.notes_text_frame.text = page.notes
        presentation.save(str(destination))

    @staticmethod
    def _shape(slide, kind, x, y, width, height, color):
        from pptx.dml.color import RGBColor
        from pptx.oxml.xmlchemy import OxmlElement
        from pptx.util import Inches

        shape = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(width), Inches(height))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(color)
        shape.line.fill.background()
        shape._element.spPr.append(OxmlElement("a:effectLst"))
        for effect in shape._element.xpath("./p:style/a:effectRef"):
            effect.set("idx", "0")
        return shape

    def _decorate(self, slide, theme, palette, hero, index):
        from pptx.enum.shapes import MSO_SHAPE

        rectangle, circle = MSO_SHAPE.RECTANGLE, MSO_SHAPE.OVAL
        if hero:
            if theme == "business":
                self._shape(slide, rectangle, 10.5, 0, 2.83, 7.5, palette["motif"])
                for offset in range(4):
                    self._shape(slide, rectangle, 10.9 + offset * .5, .9 + offset * .65, .15, 4.7 - offset * .65, palette["accent"])
            elif theme == "forest":
                for x, y, size in [(10.3, .9, 2.5), (10.7, 3.7, 1.7), (9.8, 5.8, .7)]:
                    self._shape(slide, circle, x, y, size, size, palette["motif"])
                self._shape(slide, rectangle, 0, 7.36, 13.33, .14, palette["accent"])
            elif theme == "sunset":
                for x, y, size, color in [(10.1, .55, 2.9, "E7B69B"), (10.7, 1.1, 1.7, "D46541"), (11.3, 5.5, 1.5, "E7B69B")]:
                    self._shape(slide, circle, x, y, size, size, color)
            else:
                for offset in range(5):
                    self._shape(slide, rectangle, 10.5 + offset * .5, .8, .025, 5.7, palette["accent"])
                self._shape(slide, rectangle, .8, 6.75, 9.2, .015, palette["accent"])
            self._text(slide, ["PRESENTATION" if index == 1 else "KEY TAKEAWAYS"], .8, .65, 6, .3,
                       size=12, minimum=12, color=palette["hero_muted"], bold=True)
        else:
            self._shape(slide, rectangle, .8, 2.08, 11.7, 4.7, palette["surface"])
            self._shape(slide, rectangle, .8, 2.08, .045, 4.7, palette["accent"])
            self._shape(slide, rectangle, 0, 0, 13.33, .075, palette["accent"])
            if theme in {"forest", "sunset"}:
                self._shape(slide, circle, 12.45, .65, .4, .4, palette["accent"])
                self._shape(slide, circle, 11.95, .8, .16, .16, palette["accent"])
            else:
                for offset in range(3):
                    self._shape(slide, rectangle, 11.95 + offset * .2, .5, .08, .25 + offset * .12, palette["accent"])

    def _text(self, slide, paragraphs: list[str], x: float, y: float, width: float, height: float,
              *, size: int, minimum: int, color: str, bold: bool = False, spacing: int = 0) -> None:
        from pptx.dml.color import RGBColor
        from pptx.enum.text import MSO_AUTO_SIZE
        from pptx.oxml.xmlchemy import OxmlElement
        from pptx.util import Inches, Pt

        # Conservative CJK-aware fitting avoids silent truncation. Dense slides
        # fail with an actionable error so the agent can split the content.
        for font_size in range(size, minimum - 1, -1):
            units_per_line = (width * 72 - 4) / font_size
            lines = sum(sum(max(1, math.ceil(self._text_units(line) / units_per_line))
                            for line in text.split("\n")) for text in paragraphs)
            required = lines * font_size * 1.25 + spacing * max(0, len(paragraphs) - 1)
            if required <= height * 72 - 4:
                break
        else:
            raise PresentationError("页面文字过多，请缩短标题、要点或拆分为多页后重新生成")
        frame = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(width), Inches(height)).text_frame
        frame.word_wrap = True
        frame.auto_size = MSO_AUTO_SIZE.NONE
        frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = Pt(2)
        for index, text in enumerate(paragraphs):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = text
            paragraph.line_spacing = 1.25
            paragraph.space_after = Pt(spacing if index < len(paragraphs) - 1 else 0)
            paragraph.font.name = self.settings.ppt_font_name
            paragraph.font.size = Pt(font_size)
            paragraph.font.bold = bold
            paragraph.font.color.rgb = RGBColor.from_string(color)
            # PowerPoint uses a separate East Asian typeface for Chinese text.
            east_asian = OxmlElement("a:ea")
            east_asian.set("typeface", self.settings.ppt_font_name)
            paragraph._p.get_or_add_pPr().get_or_add_defRPr().append(east_asian)

    @staticmethod
    def _text_units(text: str) -> float:
        return sum(1.0 if unicodedata.east_asian_width(char) in {"W", "F"} or char in "WM@" else .65 for char in text)

    @staticmethod
    def _picture(slide, image_file: Path, x: float, y: float, width: float, height: float) -> None:
        from PIL import Image
        from pptx.util import Inches

        with Image.open(image_file) as image:
            image_width, image_height = image.size
        scale = min(width / image_width, height / image_height)
        fitted_width, fitted_height = image_width * scale, image_height * scale
        slide.shapes.add_picture(str(image_file), Inches(x + (width - fitted_width) / 2),
                                Inches(y + (height - fitted_height) / 2),
                                width=Inches(fitted_width), height=Inches(fitted_height))

    def _download_image(self, url: str, destination: Path) -> None:
        import httpx
        from PIL import Image, ImageOps

        parsed = urlparse(url)
        expected_host = f"{self.settings.cos_bucket}.cos.{self.settings.cos_region}.myqcloud.com"
        if (parsed.scheme != "https" or parsed.netloc != expected_host or parsed.username or parsed.password):
            raise PresentationError("PPT 配图仅支持当前 COS 存储桶的 HTTPS 图片地址，请使用 generate_image 返回的 URL")
        try:
            content = bytearray()
            # Redirects are deliberately disabled to keep downloads on COS.
            with httpx.stream("GET", url, timeout=30, follow_redirects=False) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 20 * 1024 * 1024:
                        raise PresentationError("PPT 配图不能超过 20MB")
            with Image.open(BytesIO(content)) as source:
                if source.width * source.height > 20_000_000:
                    raise PresentationError("PPT 配图像素过大，请使用较小的图片")
                # PNG also normalizes WebP and EXIF rotation for PowerPoint.
                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.save(destination, format="PNG")
        except PresentationError:
            raise
        except Exception as exc:
            raise PresentationError("PPT 配图下载或解码失败，请检查图片地址", retryable=True) from exc


def generate_ppt(title: str, slides: list[PresentationSlide], theme: ThemeName = "business") -> dict[str, Any]:
    """生成可编辑的 16:9 PowerPoint (.pptx)，上传 COS 并生成网页 PDF 预览。

    title 是文件标题；slides 是按顺序排列的 1–50 页，每页含 title、layout、subtitle、
    bullets、image_url、notes。layout 支持 cover、bullets（默认）、image、closing；
    每页最多六条简短要点。封面和结束页需显式放进 slides，不会自动添加。
    image 页必须提供当前 COS 存储桶的 HTTPS 图片 URL，可使用 generate_image 返回的地址。
    详细内容放 notes；文字过多时缩短要点或拆页重试。成功后前端自动展示下载卡片。
    theme 可选 business（商务蓝，默认）、forest（自然绿）、sunset（暖橙）、ink（黑金）。
    根据用户指定风格或内容选择主题；预览失败不会影响 PPT 下载。
    除用户要求纯文字外，适合配图的关键页可先用可用的 generate_image 生成 1–3 张主题一致的图片，
    取真实 images[].url 填入 image 页，再调用本工具；不能在只生成配图后结束 PPT 任务。
    """
    return PresentationService(get_settings()).generate_and_upload(title, slides, theme=theme)


def get_tools() -> list[object]:
    """Register this tool only for selected skills when the feature is enabled."""
    return [generate_ppt] if get_settings().ppt_generation_enabled else []
