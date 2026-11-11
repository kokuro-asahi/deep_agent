# DeepAgents 0.7.35 迁移记录

核对日期：2026-11-11。迁移目标为 PyPI 最新稳定版 `deepagents==0.7.35`，
支持 Python `>=3.11,<4.0`，不要求升级到 Python 3.14。

- [PyPI 发布包](https://pypi.org/project/deepagents/0.7.35/)
- [官方变更记录](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.35/libs/deepagents/CHANGELOG.md)

## 依赖与兼容调整

| 依赖 | 原版本 | 迁移版本 |
| --- | --- | --- |
| deepagents | 0.7.0b2 | 0.7.35 |
| langchain | 1.3.14 | 1.4.10 |
| langchain-core | 1.5.1 | 1.7.7 |
| langgraph | 1.2.9 | 1.2.20 |
| langgraph-checkpoint | 4.1.1 | 4.3.1 |
| langgraph-sdk | 0.4.2 | 0.4.14 |
| langsmith | 0.10.10 | 0.14.17 |
| langchain-anthropic | 1.5.2 | 1.7.10 |
| langchain-google-genai | 4.3.2 | 4.4.3 |
| langchain-protocol | 0.0.18 | 0.0.21 |
| google-genai | 2.12.1 | 3.1.0 |
| google-auth | 2.55.2 | 2.62.2 |
| certifi | 2026.6.17 | 2026.10.23 |

`requirements.txt` 锁定上述版本，`environment.yml` 创建专用环境并直接引用该清单，
避免维护两份容易漂移的版本列表。补全测试环境使用的间接依赖锁定，
保证全新安装不会依赖共享 Conda 环境中偶然存在的软件包。
`langchain-openai==1.3.5`、`langgraph-checkpoint-postgres==3.1.0` 和现有 MCP 版本继续兼容。

0.7.33 起，框架默认将提供商的显式拒答转成 `ModelRefusalError`。
`app/errors.py` 将该异常映射为现有 `MODEL_PROVIDER_FAILED`，并设置 `retryable=false`；
即使拒答内容提到工具，也不会误归类为工具故障。JSON 与 SSE 的事件结构保持现有协议。

现有角色中间件、显式 `TodoListMiddleware`、按会话选择技能和工具的方式均通过新版验证。
此次不引入异步子 Agent、技能工具延迟加载或其他产品功能。

## 历史会话与数据库

新旧版本均使用消息增量检查点。继续保留原数据库、检查点表、
`user_id:thread_id:v{context_version}` 标识、角色字段和技能选择，不清空历史数据。
业务表和 PostgresSaver 版本未改变，无需新增业务数据库迁移。

`tests/fixtures/deepagents-0.7.0b2-checkpoint.json` 是原环境实际生成的合成会话，
包含序列化字节、祖先检查点和增量写入。测试在新版内存 saver 和真实 PostgreSQL
临时 schema 中恢复该会话，验证历史消息、角色、工具结果、计划和重建 Agent 后的续聊。
样本没有真实用户内容或凭证。其生成脚本只能在旧依赖环境运行：

```bash
PYTHONPATH=. /path/to/old/python tests/fixtures/generate_deepagents_checkpoint.py
```

## 专用运行环境

本机旧的 `/opt/miniconda3/envs/deepagent` 还供另一个项目使用，必须保持不变。
使用全新、独立的 Conda 环境：

```bash
conda create -n deepagent_0734 python=3.11 pip -y
conda run -n deepagent_0734 python -m pip install -r requirements.txt
conda run -n deepagent_0734 python -m pip install pytest==9.1.1
conda run -n deepagent_0734 python -m pip check
```

也可在项目根目录直接运行 `conda env create -f environment.yml`。
环境文件不再携带旧共享环境中与项目无关的 Daytona 等软件包。

迁移验证命令：

```bash
conda run --no-capture-output -n deepagent_0734 python -m pytest -q --agent-postgres --auth-postgres
node tests/frontend.test.cjs
```

两个 PostgreSQL 开关仅操作独立临时 schema，结束后清理；需配置有效的数据库连接和
创建 schema 权限。不使用开关时，数据库集成测试会跳过。

用户要求停止原有 8083、8089 两个实例；完成环境准备后保持停止。
已核对两端口停止，其他项目的 8086 实例仍在运行；共享 `deepagent` 环境的
`pip freeze` 清单与迁移前完全一致。
需要恢复服务时，从项目目录按需要启动：

```bash
bash start.sh
```

默认端口为 8089；启动另一个端口使用 `PORT=8083 bash start.sh`。
脚本默认使用 `deepagent_0734` Conda 环境；可用
`AGENT_PYTHON=/path/to/python bash start.sh` 指定其他解释器。
其他服务器也可按 README 使用普通 venv，再设置此覆盖变量。
如果部署由 systemd、Supervisor 或容器管理，应同步更新其解释器或镜像并由原管理器启动。

恢复服务后检查 `/health`，再用有权限的测试账号验证 JSON、SSE、旧会话续聊、
技能选择和文件产物。健康检查仅说明 HTTP 服务可达，不代表真实模型或外部 MCP 可用。

## 验证结果

- 原版本：151 项后端测试通过，2 项 PostgreSQL 测试按默认配置跳过。
- 升级隔离环境：原有 151 项后端测试通过。
- 全新 Python 3.11 环境、完整锁定依赖：`pip check` 通过；包含新增迁移测试及
  PostgreSQL 集成测试共 159 项全部通过。
- 最终专用 `deepagent_0734` Conda 环境（Python 3.11.18）：同样 159 项全部通过，
  `pip check` 通过。
- 前端：41 项测试通过。
- FastAPI `on_event` 弃用提示为现有警告，与本次迁移无关。

这些测试使用确定性模型和替代的外部工具；不代表真实提供商、知识库、生图或 COS
服务的端到端验收。停止的两个实例尚不提供新版在线服务。

## 回退

部署前应保留原代码、原环境和数据库完整备份。恢复数据库时必须包含检查点相关全部表，
不能仅恢复业务消息或最新一条检查点。
本次操作的原始代码快照与共享环境依赖清单位于：

- `/tmp/deepagents-pre-migration-source-20261111.tar`
- `/tmp/deepagents-pre-migration-freeze-20261111.txt`

这两个文件为本机临时备份，长期部署前应另行归档。
原项目依赖清单另存为 `docs/migrations/requirements-deepagents-0.7.0b2.txt`。

需要回退时停止新版进程，恢复迁移前的代码，再指定仍保留的原环境解释器启动。
不要只把 `deepagents` 降级而保留新版 LangChain 组合，也不要将旧依赖安装进其他项目
正在使用的共享环境。若新版已经写入生产检查点，应先在数据库副本验证旧代码可恢复，
不能因旧到新的恢复测试通过就假设反向恢复也兼容；必要时使用部署前完整备份，
并处理备份后的新增会话数据。
