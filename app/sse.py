import json
from collections.abc import AsyncIterator
from typing import Any


def encode_sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


async def stream_events(events: AsyncIterator[tuple[str, dict[str, Any]]]) -> AsyncIterator[str]:
    async for event, data in events:
        yield encode_sse(event, data)
