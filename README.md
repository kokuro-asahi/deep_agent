# Deep Agents Interface Backend

Phase-one backend for the Agent interface described in the attached API and technical documents.

## Scope

- `POST /v1/runs` for text/image conversations, streaming or JSON.
  - When `thread_id` is empty, `agent_role` is required and must be one of `director`, `cinematographer`, `art_director`, or `screenwriter`.
  - When `thread_id` is provided, it must already exist; unknown threads return `404`.
  - Role system prompts are loaded from `app/prompts/roles/*.md`.
- `POST /v1/threads/{thread_id}/context` to clear future model context without deleting history.
- `GET /v1/threads/{thread_id}/messages` for reverse chronological Q&A pagination.
- Custom DeepAgents tools are registered from `app/tools.py`, including time lookup and Bocha web search.
- DeepAgents/LangGraph `PostgresSaver` stores model checkpoints in PostgreSQL.
- Business tables store API-facing data in PostgreSQL:
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

## Request Logs

Every HTTP request is recorded in `api_request_logs` with a generated `request_id`,
method, path, route, status code, duration, response size, client host, user agent,
and error payload when the request fails. `/v1/runs` requests also attach `run_id`,
`user_id`, `thread_id`, and `client_message_id` when those values become available.
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
