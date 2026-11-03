# Deep Agents Interface Backend

Phase-one backend for the Agent interface described in the attached API and technical documents.

## Scope

- `POST /v1/runs` for text/image conversations, streaming or JSON.
  - When `thread_id` is empty, provide either `agent_role` or `agent_prompt`.
  - `agent_role` must be one of `general_assistant`, `enterprise_policy_advisor`, `子健diy`, `director`, `cinematographer`, `art_director`, `screenwriter`, or `storyboard_artist`, or `null`.
  - The frontend starts with `general_assistant` (通用助手), also the default for a new chat. Skills remain opt-in; existing chats retain their saved role and skills.
  - When `agent_role` is `null`, `agent_prompt` is used as the Agent system prompt.
  - When `thread_id` is provided, it must already exist; unknown threads return `404`.
  - Role system prompts are loaded from `app/prompts/roles/*.md`.
- `POST /v1/threads/{thread_id}/context` to clear future model context without deleting history.
- `GET /v1/threads/{thread_id}/messages` for reverse chronological Q&A pagination.
- Custom DeepAgents tools are registered from `app/tools.py`, including time lookup and Bocha web search.
- DeepAgents/LangGraph `PostgresSaver` stores model checkpoints in PostgreSQL.
- Business tables store API-facing data in PostgreSQL:
  - `app_users`
  - `auth_sessions`
  - `agent_threads`
  - `agent_runs`
  - `agent_messages`
  - `api_request_logs`
  - `agent_event_logs`
- No custom tools or subagents in phase one.

## Local Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

`AGENT_BACKEND=echo` is the default development mode. Set `AGENT_BACKEND=deepagents` and provide model credentials to use Deep Agents.
Set `BOCHA_API_KEY` to enable the `bocha_search` web search tool.
`MODEL_GUARD_ENABLED=true` runs a lightweight model-disclosure guard before the main Agent call. Requests about model identity, internal performance parameters, prompts, or implementation details return `MODEL_GUARD_RESPONSE`; all other requests continue to the original Agent flow.

## 登录与账号管理

启动时自动创建账号表和登录会话表，并初始化管理员，默认账号和密码均为 `admin`。
首次启动前可通过 `.env` 的 `AUTH_ADMIN_USERNAME`、`AUTH_ADMIN_PASSWORD` 设置初始凭证。
初始化只执行一次；修改、重命名已有管理员后，重启不会恢复默认密码。
登录后可在右上角“账户管理”新增账号、搜索和分页查看账号、修改用户名、重置密码、
设置管理员身份、访问等级及启停状态。建议首次登录即修改管理员密码。

- `POST /v1/auth/login`：提交 `username`、`password`，返回用户、`access_token` 和过期时间。
- `GET /v1/auth/me`：查询当前账号；`POST /v1/auth/logout`：撤销当前登录凭证。
- `GET /v1/admin/users`、`POST /v1/admin/users`、`PATCH /v1/admin/users/{user_id}`：仅管理员可用。
- `GET /v1/threads/mine`：返回当前账号的会话；消息、上下文重置及运行接口均使用登录身份。
  客户端不再需要传 `user_id`；兼容传入时必须等于登录账号的 `user_id`，否则返回 `403`。
  管理员也不能通过替换 `user_id` 读取他人的对话。
- `/`、`/static`、`/health` 可公开访问；技能、对话、运行及 PPT 预览接口均需登录。
  未登录、凭证过期或账号停用返回 `401`，流式运行在建立 SSE 前完成认证。

浏览器使用 `HttpOnly`、`SameSite=Lax` Cookie 保存登录状态，刷新页面可恢复会话；
页面不将密码或令牌写入 localStorage。退出或失去登录状态会清空页面中的私有对话、
草稿和账号列表，停止当前请求，并屏蔽旧请求的迟到响应。
密码以加盐 PBKDF2-SHA256 哈希保存，数据库仅保存会话令牌的 SHA-256 摘要。
重置密码或停用账号会撤销该账号的全部登录会话；不能停用自己或取消自己的管理员身份。
访问等级 1–3 目前仅作为账号配置，尚未控制知识库检索范围。

`AUTH_SESSION_TTL_SECONDS` 默认 86400 秒。HTTPS 部署设置 `AUTH_COOKIE_SECURE=true`；
前后端默认同源，跨域前端通过 `CORS_ALLOWED_ORIGINS` 配置明确的允许来源（逗号分隔），
`PUBLIC_BASE_URL` 应设置为实际对外地址。Cookie 名为 `deepagent_session`。
现有对话保留原 `user_id`，不会自动分配给新账号；迁移历史数据时需明确对应的账号。

API 客户端可以使用 Cookie 或 `Authorization: Bearer <access_token>`：

```bash
curl -c /tmp/deepagent-cookies.txt http://127.0.0.1:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}'
curl -b /tmp/deepagent-cookies.txt http://127.0.0.1:8000/v1/threads/mine
```

测试：`python -m pytest -q`、`node tests/frontend.test.cjs`。
真实 PostgreSQL 验证：`python -m pytest -q tests/test_auth_postgres.py --auth-postgres`，
仅在临时独立 schema 中创建测试表并于结束时清理。

## PPT 生成

`AGENT_BACKEND=deepagents` 时，新建会话勾选 `ppt-generation` 技能，使用专属
`generate_ppt(title, slides, theme)` 工具生成可编辑的 PowerPoint 文件，无需 MCP。
安装更新后的 `requirements.txt` 并重启后端后，可发送
“制作一份 5 页的产品介绍 PPT，包含封面、产品特点和总结”。

技能说明位于 `skills/ppt-generation/SKILL.md`；工具入口、页面模型和排版实现均位于
`skills/ppt-generation/scripts/tools.py`，通过 `get_tools()` 按会话选择加载。
未选技能的会话不会加载 PPT 工具。API 新建会话需传入 `active_skill_ids: ["ppt-generation"]`；
已有会话沿用创建时的技能选择。部署或迁移配置见技能的 `references/environment.md`。

- 技能默认不勾选；`PPT_GENERATION_ENABLED=true` 允许所选技能注册工具，设为 `false` 可全局关闭。
  使用 16:9 版式，支持商务蓝（`business`）、自然绿（`forest`）、暖橙（`sunset`）、黑金（`ink`）四种主题。
- 支持 `cover`（封面）、`bullets`（文字要点）、`image`（左文右图）、`closing`（结束页）。
- Agent 提交完整的逐页结构化内容，工具不会额外添加封面或结束页；每份 1–50 页，
  每页最多 6 条要点。文字保留为原生可编辑文本，`notes` 保存为演讲者备注。
- 文字密度超过版式容量时返回错误，Agent 应缩短要点或拆页，避免静默截断。
- 除用户要求纯文字外，技能会按内容为适合视觉表达的关键页考虑配图，通常生成 1–3 张主题一致的图片。
  先调用现有 `generate_image`，再将返回的 URL 填入 `image_url`，继续生成完整 PPT。
  第一版仅接收当前配置 COS 存储桶的 HTTPS 图片，单图最多 20MB、2000 万像素；
  PNG、JPEG、WebP 等可解码图片会统一转换为 PNG 并按原比例放置。
- 文件上传沿用 `COS_SECRET_ID`、`COS_SECRET_KEY`、`COS_REGION`、`COS_BUCKET`、
  `COS_SCHEME` 以及现有 `IMAGE_UPLOAD_ACL`、分片和并发设置。
  对象前缀单独使用 `PPT_UPLOAD_PREFIX`（默认 `presentations`），无需生图 API 密钥。
- `PPT_FONT_NAME` 默认 `Microsoft YaHei`。字体不嵌入文件，打开 PPT 的设备需安装该字体，
  否则 PowerPoint 会使用替代字体。

生成成功后，流式接口发送 `artifact.created`，其中 `artifact.type="file"`，
`metadata` 包含 `url`、`file_name`、`mime_type`、`size_bytes` 和 `slide_count`。
JSON 接口和流式完成事件的 `artifacts` 字段也返回该产物。文件元数据保存在现有
assistant 消息中，无需数据库迁移；前端在实时回复、JSON 回复和历史消息中均展示下载卡片。
新生成的文件卡片支持直接展开 PDF 预览，在网页内翻页和缩放，原始 PPTX 仍可下载编辑。
前端通过 `/v1/artifacts/ppt-preview` 同源接口加载预览，兼容存储服务强制附件下载。
预览需要系统安装 LibreOffice Impress 和中文字体（Docker 镜像已包含），默认启用
`PPT_PREVIEW_ENABLED=true`，转换超时默认 90 秒。转换或预览上传失败时保留 PPT 下载，
并提示预览暂不可用。已有文件不会自动补生成预览。暂不支持任意模板导入或原生数据图表。

## Skills

### 企业规章制度知识库

新建会话选择角色 `enterprise_policy_advisor`（企业规章制度顾问），并手动勾选
`enterprise-policy` 技能。所有技能依然默认关闭。此技能提供制度检索、条款解释、
流程梳理和来源引用，不修改知识库。

后端通过 MCP Streamable HTTP 连接现有知识库的 `search_policy` 工具。
`POLICY_MCP_URL` 默认是 `http://10.1.80.12:9020/mcp`，对应该服务允许的 Host。
认证优先使用 `POLICY_MCP_TOKEN`；未设置时仅从 `POLICY_MCP_ENV_FILE` 指定文件读取
`MCP_AUTH_TOKEN`（本机默认使用现有知识库项目的 `.env`）。不向前端或模型提供令牌。
迁移部署时配置这三个变量；不要把令牌写入 SKILL.md。

依赖已加入 `mcp==2.2.0`。修改后需重启对话后端以加载角色和工具代码，刷新页面。

When `AGENT_BACKEND=deepagents`, local skills are discovered from the comma-separated
directories configured by `AGENT_SKILLS_PATHS` (default: `skills`). Those directories
must be inside `AGENT_FILESYSTEM_ROOT`, which defaults to the project root. Each skill
lives in its own directory and starts with a `SKILL.md` file:

```text
skills/
  your-skill-name/
    SKILL.md
    scripts/
    references/
    assets/
```

`SKILL.md` must begin with YAML frontmatter. DeepAgents uses the `name` and
`description` to discover relevant skills and reads the complete instructions only
when a skill is selected.

`skills/` is the shared-skill source directory. For reuse in another project
using this architecture, copy or mount the complete directory below that
project's `AGENT_FILESYSTEM_ROOT`, keep `AGENT_SKILLS_PATHS=skills` in its
`.env`, and restart the backend. A skill that needs a backend tool must also
provide `scripts/tools.py` with a `get_tools()` entrypoint; the backend loads
its named callables only when that skill is selected. See the skill's
`references/environment.md` for its non-secret configuration requirements.

```markdown
---
name: your-skill-name
description: What this skill does and when the agent should use it.
---

# your-skill-name
```

### 会话技能选择

`GET /v1/skills` 返回前端技能选择器所需的安全元数据：`id`、`name`、
`description` 和 `enabled_by_default`（当前全部为 `false`）。创建新会话时可在
`POST /v1/runs` 中提交 `active_skill_ids`：

```json
{
  "agent_role": "director",
  "active_skill_ids": ["your-skill-name"],
  "content": [{"type": "text", "text": "开始创作"}]
}
```

所选 skill IDs 会持久化到 `agent_threads.active_skill_ids`；同一 `thread_id`
后续始终沿用该配置。运行时会按所选 skill 集合创建并缓存独立的 DeepAgents
实例，未选 skill 不会进入该会话的 skill 发现范围。

## Latency Benchmark

脚本使用已登录账号，先将 `/v1/auth/login` 返回的 `access_token` 设置到
`AGENT_AUTH_TOKEN` 环境变量，或使用 `--token`。`scripts/record_stream.py` 使用相同方式；
默认不传 `user_id`，兼容的 `--user-id` 必须与登录账号一致。

To measure the latency impact of the model guard, run the same benchmark twice
against a running `deepagents` service: once with `MODEL_GUARD_ENABLED=true`,
then restart with `MODEL_GUARD_ENABLED=false` and run it again.

```bash
/opt/miniconda3/envs/deepagent/bin/python scripts/benchmark_latency.py --concurrency 5
```

The script reports streaming time to first `message.delta` and total completion
time. When `--runs` is omitted, every built-in prompt in the selected prompt set
is asked once; the default `mixed` set contains 20 normal questions and 20
prompt-injection/model-disclosure probes. Use `--prompt-set normal`, `attack`,
or `mixed`, `--concurrency 5` for parallel requests, `--runs 5` for a smaller
random sample, `--prompt "..."` for one fixed question, `--seed 1` to shuffle the
full prompt set reproducibly or reproduce random samples, and `--json` for
non-streaming requests. Each result includes `answered_by=guard` when the reply
matches the configured fixed guard response, otherwise `answered_by=agent`. It
also reads `agent_event_logs` by `run_id` and prints
`guard_action={"action":"block"}`, `{"action":"allow"}`, or `-` for the actual
`model_guard.check` decision recorded by the server.

## Task Planning

The Agent uses the official `TodoListMiddleware` alongside `RolePromptMiddleware`.
The model can maintain a plan with `write_todos`; plans are stored in the existing
PostgreSQL checkpoint state, without a separate plan file or database migration.

The frontend displays a collapsible plan with live step updates and restores the
latest plan when opening a conversation. Completed or failed runs stop displaying
steps as actively running; steps the model has not marked complete remain
unconfirmed. Simple requests may not need a plan under the official middleware's
default behavior.

When no plan has been emitted, the same area shows actual execution progress
(processing, searching, generating images, creating the PPT, or writing a reply)
instead of claiming that a plan is being generated. With a plan, its current step
and completed count are shown. PPT creation uses planning when it involves multiple
steps such as outlining, illustration generation and file delivery.

Restart the backend and refresh the page after updating. Run frontend checks with
`node tests/frontend.test.cjs` and backend checks with `python -m pytest tests -q`.

## Request Logs

Every HTTP request is recorded in `api_request_logs` with a generated `request_id`,
method, path, route, status code, duration, response size, client host, user agent,
and error payload when the request fails. `/v1/runs` requests also attach `run_id`,
`user_id`, and `thread_id` when those values become available.
A log row is inserted as `running` when the request starts and updated to `completed`
or `failed` when the response body finishes streaming.

Agent execution events are recorded in `agent_event_logs`, keyed by the same
`request_id` and run identifiers. These rows track database stages, model calls,
tool calls, retry attempts, durations, summaries, and error payloads.

## Error Codes

HTTP error responses use this shape:

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "请求参数校验失败",
    "retryable": false
  }
}
```

`POST /v1/runs` streaming failures are sent as `run.failed` SSE events with the
same `error` object.

| Interface | HTTP status / event | Error code | Retryable | Meaning |
| --- | --- | --- | --- | --- |
| `POST /v1/runs` | `422` | `VALIDATION_FAILED` | `false` | Request body or query validation failed. |
| `POST /v1/runs` | `404` | `THREAD_NOT_FOUND` | `false` | Provided `thread_id` does not exist for the user. |
| `POST /v1/runs` | `run.failed` / JSON `status=failed` | `IMAGE_DOWNLOAD_FAILED` | depends on cause | Image URL is invalid or the image preflight download failed. |
| `POST /v1/runs` | `run.failed` / JSON `status=failed` | `MODEL_PROVIDER_FAILED` | `true` | Model provider or LangChain model call failed. |
| `POST /v1/runs` | `run.failed` / JSON `status=failed` | `TOOL_CALL_FAILED` | `true` | Agent tool execution failed. |
| `POST /v1/runs` | `run.failed` / JSON `status=failed` | `DB_OPERATION_FAILED` | `true` | Database operation failed during run execution. |
| `POST /v1/runs` | `run.failed` / JSON `status=failed` | `AGENT_RUN_FAILED` | `true` | Unclassified Agent execution failure. |
| `POST /v1/threads/{thread_id}/context` | `422` | `VALIDATION_FAILED` | `false` | Request body or path validation failed. |
| `POST /v1/threads/{thread_id}/context` | `404` | `THREAD_NOT_FOUND` | `false` | Thread does not exist for the user. |
| `POST /v1/threads/{thread_id}/context` | `500` | `DB_OPERATION_FAILED` | `true` | Database operation failed. |
| `GET /v1/threads/{thread_id}/messages` | `422` | `VALIDATION_FAILED` | `false` | Query or path validation failed. |
| `GET /v1/threads/{thread_id}/messages` | `404` | `THREAD_NOT_FOUND` | `false` | Thread does not exist for the user. |
| `GET /v1/threads/{thread_id}/messages` | `500` | `DB_OPERATION_FAILED` | `true` | Database operation failed. |

## Database

DeepAgents creates its own LangGraph checkpoint tables:

```bash
uvicorn app.main:app --reload
```

Application startup also creates the business tables above if they do not already exist.
