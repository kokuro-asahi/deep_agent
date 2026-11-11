# macOS 本地启动

使用 Homebrew 在 Mac 上运行 PostgreSQL，通过阿里云百炼调用模型，再用 Uvicorn 启动网页和 API。整个流程无需 Docker。开始前请准备 Homebrew、Python 3.13 和百炼 API Key。

## 1. 安装并启动 PostgreSQL

```bash
brew install postgresql@16
brew services start postgresql@16
"$(brew --prefix postgresql@16)/bin/pg_isready" -h 127.0.0.1 -p 5432
```

等 `pg_isready` 显示 `accepting connections` 后，创建项目的数据库账号和数据库。已有同名账号和数据库时，跳过创建并使用已有的连接配置。 [Homebrew PostgreSQL 16](https://formulae.brew.sh/formula/postgresql@16)

```bash
"$(brew --prefix postgresql@16)/bin/psql" -d postgres \
  -c "CREATE ROLE agent WITH LOGIN PASSWORD 'agent';" \
  -c "CREATE DATABASE agent_backend OWNER agent;"
```

## 2. 安装 Python 依赖并配置 `.env`

进入项目根目录，执行以下命令。已有 `.env` 时会保留原文件。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
```

打开 `.env`，修改下面五项。示例使用百炼华北 2（北京）的 OpenAI 兼容地址和 `qwen-plus`。请填入自己的 `DASHSCOPE_API_KEY`，并按密钥所属地域和开通的模型调整地址与模型名。 [百炼 Base URL 总览](https://help.aliyun.com/zh/model-studio/base-url)

```dotenv
DASHSCOPE_API_KEY=your-dashscope-api-key
BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL=qwen-plus
AGENT_MODEL=qwen-plus
AGENT_BACKEND=deepagents
```

应用优先读取 `AGENT_MODEL`，未设置时回退到 `MODEL`。`OPENAI_API_KEY` 和 `OPENAI_BASE_URL` 优先于上述百炼配置。若之前在 `.env` 或终端环境中设置过这两项，启动前请清除对应的值。

如果按第一步新建了数据库，数据库配置沿用模板的默认值。使用已有数据库时，填写实际连接信息。

```dotenv
PG_HOST=127.0.0.1
PG_PORT=5432
PG_USER=agent
PG_PASSWORD=agent
PG_DATABASE=agent_backend
```

## 3. 创建网页登录账号

在项目根目录运行以下命令，把 `alice` 替换成你要使用的登录用户名。

```bash
.venv/bin/python -m scripts.create_user alice
```

按提示输入两次密码。终端会隐藏密码输入。脚本读取 `.env` 的数据库配置并创建一个已启用的普通账号，同名时会提示失败。PostgreSQL 在线即可执行这一步，首次运行时会初始化所需的业务表。

## 4. 启动服务并登录

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

终端显示 `Application startup complete` 后，打开工作区，用第三步的账号和密码登录。发送一条消息确认模型配置生效。 [工作区](http://127.0.0.1:8000/) · [健康检查](http://127.0.0.1:8000/health) · [API 文档](http://127.0.0.1:8000/docs)

以后启动时，确认 PostgreSQL 在运行，再从项目根目录执行第四步的命令。按 `Ctrl+C` 可停止 Uvicorn。
