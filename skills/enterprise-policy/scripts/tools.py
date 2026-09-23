"""Read-only MCP tool supplied by the enterprise-policy skill."""

import asyncio
import json
from typing import Any

from app.config import get_settings


async def _search_policy(arguments: dict[str, Any]) -> dict[str, Any]:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    settings = get_settings()
    token = settings.policy_mcp_token
    if not token and settings.policy_mcp_env_file:
        from dotenv import dotenv_values

        token = dotenv_values(settings.policy_mcp_env_file).get("MCP_AUTH_TOKEN")
    if not token:
        raise RuntimeError("企业制度知识库未配置访问令牌")
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=150,
        trust_env=False,
    ) as client:
        async with streamable_http_client(settings.policy_mcp_url, http_client=client) as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=150) as session:
                await session.initialize()
                result = await session.call_tool("search_policy", arguments)
                if result.is_error:
                    raise RuntimeError("企业制度知识库检索失败，请检查 MCP 服务日志")
                if result.structured_content is not None:
                    return result.structured_content
                for block in result.content:
                    if block.type == "text":
                        data = json.loads(block.text)
                        if isinstance(data, dict):
                            return data
                raise RuntimeError("企业制度知识库返回了无法解析的检索结果")


def search_enterprise_policy(
    query: str, top_k: int = 5, candidates: int = 20, file_id: str | None = None,
) -> dict[str, Any]:
    """检索企业内部规章制度原文，返回标题、条款、页码、文件 ID 和内容。

    file_id 可限定制度文件。仅用于查询，不能修改或发布制度。
    """
    if not query.strip():
        raise ValueError("query 不能为空")
    if not 1 <= top_k <= 20 or not top_k <= candidates <= 100:
        raise ValueError("需要 1 <= top_k <= 20 且 top_k <= candidates <= 100")
    if file_id is not None and not file_id.strip():
        raise ValueError("file_id 不能为空字符串")
    arguments = {"query": query.strip(), "top_k": top_k, "candidates": candidates}
    if file_id is not None:
        arguments["file_id"] = file_id.strip()
    try:
        return asyncio.run(_search_policy(arguments))
    except Exception as exc:
        # Do not expose authentication headers or upstream configuration in tool output.
        raise RuntimeError("企业制度知识库暂时无法查询，请检查 MCP 连接、认证和服务日志") from exc


def get_tools() -> list[object]:
    """Return the tool functions to register when this skill is enabled."""
    return [search_enterprise_policy]
