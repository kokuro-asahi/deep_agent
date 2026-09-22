"""Record one enterprise-policy streaming run as raw SSE, JSONL, and a summary."""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


DEFAULT_PROMPT = "我准备请几天假会不会扣钱"
DEFAULT_AGENT_ROLE = "enterprise_policy_advisor"
DEFAULT_ACTIVE_SKILL_IDS = ["enterprise-policy"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Record one enterprise-policy streaming /v1/runs response.")
    parser.add_argument("--url", default="http://127.0.0.1:8089/v1/runs")
    parser.add_argument("--user-id", default="stream_recorder")
    parser.add_argument("--thread-id", default=None, help="Reuse an existing thread and its saved skill configuration.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--out-dir", default="stream_records")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    asyncio.run(record_stream(args))


async def record_stream(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = out_dir / f"stream_{stamp}"
    raw_path = prefix.with_suffix(".sse")
    events_path = prefix.with_suffix(".jsonl")
    summary_path = prefix.with_suffix(".summary.json")

    payload: dict[str, Any] = {
        "user_id": args.user_id,
        "stream": True,
        "content": [{"type": "text", "text": args.prompt}],
    }
    if args.thread_id:
        payload["thread_id"] = args.thread_id
    else:
        # Skills are configured only while creating a thread. The server persists
        # this selection and reuses it on later requests for the same thread.
        payload["agent_role"] = DEFAULT_AGENT_ROLE
        payload["active_skill_ids"] = DEFAULT_ACTIVE_SKILL_IDS

    started = time.perf_counter()
    records: list[dict[str, Any]] = []
    assistant_parts: list[str] = []
    buffer = ""

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        async with client.stream("POST", args.url, json=payload) as response:
            if response.is_error:
                error_body = await response.aread()
                raise SystemExit(
                    f"HTTP {response.status_code} from {args.url}\n"
                    f"request body:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
                    f"response body:\n{error_body.decode('utf-8', errors='replace')}"
                )
            with raw_path.open("w", encoding="utf-8") as raw_file, events_path.open("w", encoding="utf-8") as events_file:
                async for chunk in response.aiter_text():
                    raw_file.write(chunk)
                    raw_file.flush()
                    buffer += chunk
                    events = buffer.split("\n\n")
                    buffer = events.pop() or ""
                    for raw_event in events:
                        record_event(raw_event, started, records, assistant_parts, events_file)

                if buffer.strip():
                    record_event(buffer, started, records, assistant_parts, events_file)

    summary = {
        "url": args.url,
        "prompt": args.prompt,
        "agent_role": None if args.thread_id else DEFAULT_AGENT_ROLE,
        "active_skill_ids": [] if args.thread_id else DEFAULT_ACTIVE_SKILL_IDS,
        "user_id": args.user_id,
        "thread_id": last_value(records, "thread_id"),
        "run_id": last_value(records, "run_id"),
        "event_count": len(records),
        "events": [record["event"] for record in records],
        "assistant_text": "".join(assistant_parts),
        "raw_sse_path": str(raw_path),
        "events_jsonl_path": str(events_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nSaved:")
    print(f"- raw SSE: {raw_path}")
    print(f"- events JSONL: {events_path}")
    print(f"- summary: {summary_path}")


def record_event(
    raw_event: str,
    started: float,
    records: list[dict[str, Any]],
    assistant_parts: list[str],
    events_file: Any,
) -> None:
    record = parse_sse_event(raw_event, started)
    if record is None:
        return
    records.append(record)
    events_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    events_file.flush()
    if record["event"] == "message.delta":
        assistant_parts.append(record["data"].get("text", ""))
    print_event(record)


def parse_sse_event(raw_event: str, started: float) -> dict[str, Any] | None:
    event_name = "message"
    data_lines: list[str] = []
    for line in raw_event.splitlines():
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    if not data_lines:
        return None

    data_text = "\n".join(data_lines)
    try:
        data = json.loads(data_text)
    except json.JSONDecodeError:
        data = {"raw": data_text}
    return {
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "event": event_name,
        "data": data,
    }


def print_event(record: dict[str, Any]) -> None:
    event = record["event"]
    data = record["data"]
    if event == "message.delta":
        preview = data.get("text", "").replace("\n", "\\n")[:80]
    elif event.startswith("tool.call."):
        preview = data.get("arguments", {}).get("query") or data.get("tool_type") or ""
    elif event == "run.failed":
        preview = data.get("error", {}).get("message", "")
    else:
        preview = data.get("status", "") or data.get("run_id", "")
    print(f"{record['elapsed_ms']:>9.2f} ms  {event:<20} {preview}")


def last_value(records: list[dict[str, Any]], key: str) -> Any:
    for record in reversed(records):
        data = record.get("data")
        if isinstance(data, dict) and data.get(key):
            return data[key]
    return None


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
