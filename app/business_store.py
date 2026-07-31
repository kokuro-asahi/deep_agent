from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.config import Settings, get_settings


class BusinessStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pool: ConnectionPool | None = None

    def start(self) -> None:
        if self.pool is not None:
            return
        self.pool = ConnectionPool(conninfo=self.database_uri(), kwargs={"row_factory": dict_row}, open=True)
        self.setup()

    def stop(self) -> None:
        if self.pool is not None:
            self.pool.close()
        self.pool = None

    def database_uri(self) -> str:
        from urllib.parse import quote_plus

        user = quote_plus(self.settings.pg_user)
        password = quote_plus(self.settings.pg_password)
        return (
            f"postgresql://{user}:{password}"
            f"@{self.settings.pg_host}:{self.settings.pg_port}/{self.settings.pg_database}"
        )

    def setup(self) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_threads (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    checkpoint_thread_id TEXT NOT NULL,
                    agent_role TEXT,
                    context_version INTEGER NOT NULL DEFAULT 1,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (user_id, thread_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    client_message_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    usage JSONB,
                    error JSONB,
                    metadata JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    completed_at TIMESTAMPTZ,
                    UNIQUE (user_id, client_message_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id BIGSERIAL PRIMARY KEY,
                    message_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    message_order INTEGER NOT NULL DEFAULT 0,
                    role TEXT NOT NULL,
                    content JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (user_id, thread_id, sequence, message_order)
                )
                """
            )
            conn.execute("ALTER TABLE agent_messages ADD COLUMN IF NOT EXISTS message_order INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                UPDATE agent_messages
                SET message_order = CASE role
                    WHEN 'user' THEN 0
                    WHEN 'tool_call' THEN 100
                    WHEN 'tool_callback' THEN 200
                    WHEN 'assistant' THEN 1000
                    ELSE 900
                END
                WHERE message_order = 0 AND role <> 'user'
                """
            )
            conn.execute("ALTER TABLE agent_messages DROP CONSTRAINT IF EXISTS agent_messages_user_id_thread_id_sequence_role_key")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_messages_sequence_order
                ON agent_messages (user_id, thread_id, sequence, message_order)
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_threads_user ON agent_threads (user_id, updated_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_thread ON agent_runs (user_id, thread_id, created_at DESC)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_messages_thread ON agent_messages "
                "(user_id, thread_id, sequence DESC)"
            )
            conn.commit()

    def get_run_by_client_message(self, user_id: str, client_message_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT run_id, user_id, thread_id, client_message_id, status, message, usage, error, metadata
                FROM agent_runs
                WHERE user_id = %s AND client_message_id = %s
                """,
                (user_id, client_message_id),
            ).fetchone()

    def get_thread(self, user_id: str, thread_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT user_id, thread_id, checkpoint_thread_id, agent_role, context_version, last_sequence
                FROM agent_threads
                WHERE user_id = %s AND thread_id = %s
                """,
                (user_id, thread_id),
            ).fetchone()

    def get_or_create_thread(self, user_id: str, thread_id: str | None, agent_role: str | None) -> dict[str, Any] | None:
        if thread_id:
            return self.get_thread(user_id, thread_id)

        new_thread_id = f"thread_{uuid4().hex}"
        checkpoint_thread_id = self.checkpoint_thread_id(user_id, new_thread_id, 1)
        with self.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO agent_threads (
                    user_id, thread_id, checkpoint_thread_id, agent_role, context_version
                )
                VALUES (%s, %s, %s, %s, 1)
                ON CONFLICT (user_id, thread_id) DO UPDATE
                SET updated_at = now()
                RETURNING user_id, thread_id, checkpoint_thread_id, agent_role, context_version, last_sequence
                """,
                (user_id, new_thread_id, checkpoint_thread_id, agent_role),
            ).fetchone()
            conn.commit()
            return row

    def create_run(
        self,
        run_id: str,
        user_id: str,
        thread_id: str,
        client_message_id: str,
        metadata: dict[str, Any],
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    run_id, user_id, thread_id, client_message_id, status, usage, metadata
                )
                VALUES (%s, %s, %s, %s, 'running', %s, %s)
                """,
                (
                    run_id,
                    user_id,
                    thread_id,
                    client_message_id,
                    Jsonb({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}),
                    Jsonb(metadata),
                ),
            )
            conn.commit()

    def complete_run(self, run_id: str, message: str, usage: dict[str, Any] | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE agent_runs
                SET status = 'completed', message = %s, usage = %s, completed_at = %s
                WHERE run_id = %s
                """,
                (
                    message,
                    Jsonb(usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}),
                    datetime.now(timezone.utc),
                    run_id,
                ),
            )
            conn.commit()

    def fail_run(self, run_id: str, code: str, message: str, retryable: bool) -> dict[str, Any]:
        error = {"code": code, "message": message, "retryable": retryable}
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE agent_runs
                SET status = 'failed', error = %s, completed_at = %s
                WHERE run_id = %s
                """,
                (Jsonb(error), datetime.now(timezone.utc), run_id),
            )
            conn.commit()
        return error

    def next_sequence(self, user_id: str, thread_id: str) -> int:
        with self.connection() as conn:
            row = conn.execute(
                """
                UPDATE agent_threads
                SET last_sequence = last_sequence + 1, updated_at = now()
                WHERE user_id = %s AND thread_id = %s
                RETURNING last_sequence
                """,
                (user_id, thread_id),
            ).fetchone()
            conn.commit()
            return int(row["last_sequence"])

    def save_message(
        self,
        run_id: str,
        user_id: str,
        thread_id: str,
        sequence: int,
        role: str,
        content: list[dict[str, Any]],
        message_order: int = 0,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_messages (
                    message_id, run_id, user_id, thread_id, sequence, message_order, role, content
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, thread_id, sequence, message_order) DO UPDATE
                SET
                    role = EXCLUDED.role,
                    content = EXCLUDED.content
                """,
                (
                    f"message_{uuid4().hex}",
                    run_id,
                    user_id,
                    thread_id,
                    sequence,
                    message_order,
                    role,
                    Jsonb(content),
                ),
            )
            conn.commit()

    def save_trace_messages(
        self,
        run_id: str,
        user_id: str,
        thread_id: str,
        sequence: int,
        messages: list[dict[str, Any]],
        start_order: int = 100,
    ) -> None:
        if not messages:
            return
        with self.connection() as conn:
            for index, message in enumerate(messages):
                conn.execute(
                    """
                    INSERT INTO agent_messages (
                        message_id, run_id, user_id, thread_id, sequence, message_order, role, content
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, thread_id, sequence, message_order) DO UPDATE
                    SET
                        role = EXCLUDED.role,
                        content = EXCLUDED.content
                    """,
                    (
                        f"message_{uuid4().hex}",
                        run_id,
                        user_id,
                        thread_id,
                        sequence,
                        start_order + index,
                        message["role"],
                        Jsonb(message["content"]),
                    ),
                )
            conn.commit()

    def reset_context(self, user_id: str, thread_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                UPDATE agent_threads
                SET
                    context_version = context_version + 1,
                    checkpoint_thread_id = %s || ':' || %s || ':v' || (context_version + 1)::text,
                    updated_at = now()
                WHERE user_id = %s AND thread_id = %s
                RETURNING user_id, thread_id, checkpoint_thread_id, context_version, last_sequence
                """,
                (user_id, thread_id, user_id, thread_id),
            ).fetchone()
            conn.commit()
            return row

    def paged_conversations(
        self, user_id: str, thread_id: str, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        with self.connection() as conn:
            total = conn.execute(
                """
                SELECT count(DISTINCT sequence) AS total
                FROM agent_messages
                WHERE user_id = %s AND thread_id = %s AND role IN ('user', 'assistant')
                """,
                (user_id, thread_id),
            ).fetchone()["total"]
            sequences = conn.execute(
                """
                SELECT sequence
                FROM agent_messages
                WHERE user_id = %s AND thread_id = %s AND role IN ('user', 'assistant')
                GROUP BY sequence
                ORDER BY sequence DESC
                OFFSET %s LIMIT %s
                """,
                (user_id, thread_id, (page - 1) * page_size, page_size),
            ).fetchall()
            if not sequences:
                return [], int(total)
            sequence_values = [row["sequence"] for row in sequences]
            messages = conn.execute(
                """
                SELECT run_id, sequence, role, content, created_at
                FROM agent_messages
                WHERE user_id = %s
                    AND thread_id = %s
                    AND sequence = ANY(%s)
                    AND role IN ('user', 'assistant')
                ORDER BY sequence DESC, message_order ASC, id ASC
                """,
                (user_id, thread_id, sequence_values),
            ).fetchall()

        grouped: dict[int, list[dict[str, Any]]] = {}
        for message in messages:
            grouped.setdefault(message["sequence"], []).append(message)

        conversations = []
        for sequence in sequence_values:
            items = grouped.get(sequence, [])
            user_msg = next((item for item in items if item["role"] == "user"), None)
            assistant_msg = next((item for item in items if item["role"] == "assistant"), None)
            first = items[0] if items else {"run_id": ""}
            conversations.append(
                {
                    "message_id": f"conversation_{sequence:03d}",
                    "run_id": first["run_id"],
                    "sequence": sequence,
                    "user": self._message_side(user_msg),
                    "assistant": self._message_side(assistant_msg),
                }
            )
        return conversations, int(total)

    def checkpoint_thread_id(self, user_id: str, thread_id: str, context_version: int) -> str:
        return f"{user_id}:{thread_id}:v{context_version}"

    def connection(self):
        if self.pool is None:
            self.start()
        if self.pool is None:
            raise RuntimeError("business store is not started")
        return self.pool.connection()

    @staticmethod
    def _message_side(message: dict[str, Any] | None) -> dict[str, Any] | None:
        if not message:
            return None
        return {"content": message["content"], "created_at": message["created_at"]}


business_store = BusinessStore(get_settings())
