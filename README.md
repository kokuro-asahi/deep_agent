# Deep Agents Interface Backend

Phase-one backend for the Agent interface described in the attached API and technical documents.

## Scope

- `POST /v1/runs` for text/image conversations, streaming or JSON.
  - When `thread_id` is empty, `agent_role` is required and must be one of `director`, `cinematographer`, `art_director`, or `screenwriter`.
  - When `thread_id` is provided, it must already exist; unknown threads return `404`.
  - Role system prompts are loaded from `app/prompts/roles/*.md`.
- `POST /v1/threads/{thread_id}/context` to clear future model context without deleting history.
- `GET /v1/threads/{thread_id}/messages` for reverse chronological Q&A pagination.
- Custom DeepAgents tools are registered from `app/tools.py`.
- DeepAgents/LangGraph `PostgresSaver` stores model checkpoints in PostgreSQL.
- Business tables store API-facing data in PostgreSQL:
  - `agent_threads`
  - `agent_runs`
  - `agent_messages`
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

## Database

DeepAgents creates its own LangGraph checkpoint tables:

```bash
uvicorn app.main:app --reload
```

Application startup also creates the business tables above if they do not already exist.
