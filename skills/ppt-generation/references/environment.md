# 环境配置

本技能用于本项目的 DeepAgents 技能加载机制。复制整个 `ppt-generation/` 目录到同架构项目
的技能根目录后，新建会话选择 `ppt-generation`，后端通过 `scripts/tools.py:get_tools()`
注册 `generate_ppt`。技能默认不勾选，不依赖 MCP。

## 依赖

- Python 3.11+；`python-pptx==1.0.2` 及其 Pillow、lxml、XlsxWriter 依赖。
- 宿主提供 Pydantic、httpx、COS Python SDK，以及 `app.config.get_settings`、
  `app.errors`、`app.object_storage.upload_file` 公共接口。
- 本项目的 `requirements.txt` 已包含所需直接依赖。后端统一读取环境变量，技能不自行读取 `.env`。
- 网页内预览需要系统安装 LibreOffice Impress 和中文字体（Debian/Ubuntu 可安装
  `libreoffice-impress fonts-noto-cjk`）；项目 Docker 镜像已加入这些系统依赖。
  PDF 根据实际生成的 PPT 转换，文字在 PDF 中不可像 PPT 一样编辑；字体替代可能造成少量排版差异。

## 配置变量

| 变量 | 含义 |
| --- | --- |
| `AGENT_BACKEND` | 使用 `deepagents` 执行工具；`echo` 模式不会生成 PPT |
| `AGENT_SKILLS_PATHS` | 包含此技能的目录，默认 `skills`，位于 `AGENT_FILESYSTEM_ROOT` 内 |
| `PPT_GENERATION_ENABLED` | 默认为 `true`；`false` 时即使选择技能也不注册 PPT 工具 |
| `PPT_UPLOAD_PREFIX` | COS 对象前缀，默认 `presentations` |
| `PPT_FONT_NAME` | 默认 `Microsoft YaHei`；字体不嵌入文件，查看设备需安装或使用替代字体 |
| `PPT_PREVIEW_ENABLED` | 默认为 `true`，生成网页内 PDF 预览；关闭后仅交付 PPTX |
| `PPT_PREVIEW_COMMAND` | LibreOffice 可执行程序，默认 `libreoffice`，也可配置绝对路径 |
| `PPT_PREVIEW_TIMEOUT_SECONDS` | 单次预览转换超时，默认 90 秒；每次转换使用独立临时配置目录 |
| `COS_SECRET_ID`、`COS_SECRET_KEY`、`COS_BUCKET` | 必填的存储凭据和存储桶，由部署环境提供，禁止写入技能文件 |
| `COS_REGION`、`COS_SCHEME` | 沿用宿主存储配置 |
| `IMAGE_UPLOAD_ACL`、`IMAGE_UPLOAD_PART_SIZE_MB`、`IMAGE_UPLOAD_MAX_THREADS` | 与生图工具共用的 COS 上传参数 |

纯文字 PPT 不需要生图 API 密钥。需要生成配图时，宿主还需启用并配置 `generate_image`。
PPT 配图仅接受当前 COS 桶的 HTTPS URL，禁止重定向，单图最多 20MB、2000 万像素。

输出沿用宿主的文件产物协议：工具返回 `files` 列表，宿主通过 `artifact.created`
和 JSON `artifacts` 返回文件信息，并存入 assistant 消息以便恢复历史下载卡片。
`theme` 支持 `business`、`forest`、`sunset`、`ink`。预览就绪时，`files` 包含
`preview_status=ready`、`preview_url` 和 `preview_mime_type=application/pdf`，预览上传到同一
COS 桶的 `preview.pdf`。网页中点击“预览 PPT”即可展开翻页、缩放，不必下载 PPTX。
预览通过宿主 `/v1/artifacts/ppt-preview` 接口提供同源的内联 PDF 响应，兼容 COS 默认域名
强制附件下载的行为；接口仅接受当前存储桶、配置前缀下工具生成的 `ppt_<uuid>/preview.pdf`，
拒绝重定向，单次读取最多 50MB。
转换或预览上传失败时，PPT 下载仍然有效，前端提示预览暂不可用；不回填以前生成文件的预览。

更新技能或配置后重启后端。会话的技能选择在创建时固定；已有未选择此技能的会话需新建会话启用。
