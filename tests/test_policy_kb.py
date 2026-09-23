import asyncio
import importlib
from unittest.mock import patch

import pytest

from app.config import Settings
from app.role_prompts import load_role_prompt
from app.runtime import AgentRuntime
from app.schemas import RunRequest
from app.skill_tools import skill_tool_registry
from app.skills import SkillRegistry
from app.tools import get_agent_tools


def _enterprise_policy_tool():
    return next(
        tool
        for tool in skill_tool_registry.tools_for(("enterprise-policy",))
        if tool.__name__ == "search_enterprise_policy"
    )


def test_policy_tools_are_opt_in():
    assert "search_enterprise_policy" not in {t.__name__ for t in get_agent_tools()}
    assert "search_enterprise_policy" in {t.__name__ for t in get_agent_tools(("enterprise-policy",))}
    request = RunRequest(user_id="test", agent_role="enterprise_policy_advisor", content=[{"type": "text", "text": "请假"}])
    assert request.active_skill_ids == []
    assert load_role_prompt(request.agent_role)


def test_selected_skill_discovery_and_file_isolation(monkeypatch):
    from deepagents.backends.protocol import LsResult
    from deepagents.middleware.skills import _list_skills

    runtime = AgentRuntime(Settings())
    monkeypatch.setattr(runtime, "create_model", lambda: None)
    paths = SkillRegistry(runtime.settings).paths_for(["enterprise-policy"])
    kwargs = runtime.deep_agent_kwargs(paths, ("enterprise-policy",))
    backend = kwargs["backend"]
    # Supply the empty graph state normally available during graph execution.
    monkeypatch.setattr(backend.default, "ls", lambda path: LsResult(entries=[]))
    discovered = _list_skills(backend, kwargs["skills"][0])
    assert [s["name"] for s in discovered] == ["enterprise-policy"]
    assert len(backend.routes) == 1
    assert "backend" not in runtime.deep_agent_kwargs([])


def test_policy_bridge_preserves_results_and_arguments():
    expected = {"results": [{"content": "原文", "source_pages": [3]}], "result_count": 1}
    tool = _enterprise_policy_tool()
    module = importlib.import_module(tool.__module__)
    with patch.object(module, "_search_policy", return_value=expected) as search:
        assert tool(" 请假 ", file_id=" policy-1 ") == expected
        search.assert_awaited_once_with({"query": "请假", "top_k": 5, "candidates": 20, "file_id": "policy-1"})
    with pytest.raises(ValueError):
        tool("", top_k=0)


def test_json_invocation_forwards_selected_skills():
    from app.services import _agent_invoke_event

    async def operation(messages, user_id, thread_id, version, skills):
        assert skills == ["enterprise-policy"]
        return {"message": "ok"}

    with patch("app.services.log_agent_event"):
        result = asyncio.run(_agent_invoke_event(operation, [], "u", "t", 1, ["enterprise-policy"], {}))
    assert result["message"] == "ok"
