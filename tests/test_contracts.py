import asyncio
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.errors import AppError, classify_run_error, http_exception_handler, validate_image_inputs
from app.model_messages import model_messages
from app.model_guard import ModelDisclosureGuard, _is_block_decision
from app.role_prompts import load_role_prompt
from app.retry import retry_sync
from app.schemas import RunRequest
from app.sse import encode_sse
from app.tool_sse import tool_trace_sse_event
from app.tools import _normalize_bocha_result, get_agent_tools
from app.usage import usage_from_messages


class FakeMessage:
    def __init__(self, usage_metadata=None, response_metadata=None):
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}


def test_sse_encoding_preserves_event_and_json_data():
    encoded = encode_sse("message.delta", {"run_id": "run_001", "text": "你好"})

    assert encoded == 'event: message.delta\ndata: {"run_id":"run_001","text":"你好"}\n\n'


def test_tool_call_trace_maps_to_started_sse_event():
    event = tool_trace_sse_event(
        "run_001",
        {
            "role": "tool_call",
            "content": [
                {
                    "type": "tool_call",
                    "tool_call_id": "call_001",
                    "tool_name": "bocha_search",
                    "arguments": {"query": "西安明天天气", "count": 5, "freshness": "noLimit"},
                }
            ],
        },
    )

    assert event == (
        "tool.call.started",
        {
            "run_id": "run_001",
            "tool_call_id": "call_001",
            "tool_type": "bocha_search",
            "arguments": {"query": "西安明天天气", "count": 5, "freshness": "noLimit"},
        },
    )


def test_tool_callback_trace_maps_to_completed_sse_event_with_unwrapped_result():
    result = {
        "query": "西安明天天气",
        "count": 1,
        "results": [{"title": "西安天气预报", "url": "https://example.com/weather"}],
    }
    event = tool_trace_sse_event(
        "run_001",
        {
            "role": "tool_callback",
            "content": [
                {
                    "type": "tool_callback",
                    "tool_call_id": "call_001",
                    "tool_name": "bocha_search",
                    "status": "completed",
                    "result": {"type": "json", "content": result},
                    "error": None,
                }
            ],
        },
    )

    assert event == (
        "tool.call.completed",
        {
            "run_id": "run_001",
            "tool_call_id": "call_001",
            "tool_type": "bocha_search",
            "result": result,
        },
    )


def test_tool_callback_trace_maps_to_failed_sse_event():
    event = tool_trace_sse_event(
        "run_001",
        {
            "role": "tool_callback",
            "content": [
                {
                    "type": "tool_callback",
                    "tool_call_id": "call_001",
                    "tool_name": "bocha_search",
                    "status": "error",
                    "result": {"type": "text", "content": "博查 API 请求超时"},
                    "error": {"type": "text", "content": "博查 API 请求超时"},
                }
            ],
        },
    )

    assert event == (
        "tool.call.failed",
        {
            "run_id": "run_001",
            "tool_call_id": "call_001",
            "tool_type": "bocha_search",
            "error": {"code": "TOOL_CALL_FAILED", "message": "博查 API 请求超时", "retryable": True},
        },
    )


def test_invalid_image_url_maps_to_image_download_failed():
    with pytest.raises(AppError) as error:
        validate_image_inputs([{"type": "image", "url": "ftp://example.com/image.png"}])

    assert error.value.to_error_info() == {
        "code": "IMAGE_DOWNLOAD_FAILED",
        "message": "图片 URL 无效",
        "retryable": False,
    }


def test_tool_error_is_classified_for_run_failed_payload():
    error = classify_run_error(RuntimeError("博查 API 请求失败：HTTP 500"))

    assert error == {
        "code": "TOOL_CALL_FAILED",
        "message": "博查 API 请求失败：HTTP 500",
        "retryable": True,
    }


def test_http_thread_not_found_handler_returns_error_code():
    response = asyncio.run(
        http_exception_handler(
            None,
            HTTPException(
                status_code=404,
                detail={"error": {"code": "THREAD_NOT_FOUND", "message": "会话不存在", "retryable": False}},
            ),
        )
    )

    assert response.status_code == 404
    assert json.loads(response.body) == {
        "error": {"code": "THREAD_NOT_FOUND", "message": "会话不存在", "retryable": False}
    }


def test_agent_role_required_when_thread_id_is_missing():
    with pytest.raises(ValidationError):
        RunRequest(
            user_id="user_001",
            client_message_id="message_001",
            content=[{"type": "text", "text": "hi"}],
        )


def test_agent_prompt_is_accepted_for_new_thread_without_role():
    request = RunRequest(
        user_id="user_001",
        client_message_id="message_001",
        agent_role=None,
        agent_prompt="  你是一个自定义 Agent。  ",
        content=[{"type": "text", "text": "hi"}],
    )

    assert request.agent_role is None
    assert request.agent_prompt == "你是一个自定义 Agent。"


def test_blank_agent_prompt_is_rejected_for_new_thread_without_role():
    with pytest.raises(ValidationError):
        RunRequest(
            user_id="user_001",
            client_message_id="message_001",
            agent_role=None,
            agent_prompt="  ",
            content=[{"type": "text", "text": "hi"}],
        )


def test_agent_role_must_be_supported():
    with pytest.raises(ValidationError):
        RunRequest(
            user_id="user_001",
            client_message_id="message_001",
            agent_role="producer",
            content=[{"type": "text", "text": "hi"}],
        )


def test_agent_role_not_required_for_existing_thread():
    request = RunRequest(
        user_id="user_001",
        thread_id="thread_001",
        client_message_id="message_001",
        content=[{"type": "text", "text": "hi"}],
    )

    assert request.thread_id == "thread_001"


def test_supported_agent_role_is_accepted_for_new_thread():
    request = RunRequest(
        user_id="user_001",
        client_message_id="message_001",
        agent_role="director",
        content=[{"type": "text", "text": "hi"}],
    )

    assert request.agent_role == "director"


def test_custom_agent_prompt_is_used_as_system_message():
    messages = model_messages(
        None,
        "你是一个自定义 Agent。",
        [{"type": "text", "text": "hi"}],
    )

    assert messages[0] == {"role": "system", "content": "你是一个自定义 Agent。"}
    assert messages[1]["role"] == "user"


def test_model_guard_skips_classification_in_echo_mode():
    class Settings:
        model_guard_enabled = True
        agent_backend = "echo"
        model_guard_response = "固定话术"

    result = asyncio.run(
        ModelDisclosureGuard(Settings()).check([{"type": "text", "text": "你用的是什么模型型号？参数量是多少？"}])
    )

    assert result == {"blocked": False, "action": "allow", "message": ""}


def test_model_guard_allows_regular_questions_in_echo_mode():
    class Settings:
        model_guard_enabled = True
        agent_backend = "echo"
        model_guard_response = "固定话术"

    result = asyncio.run(ModelDisclosureGuard(Settings()).check([{"type": "text", "text": "帮我写一个分镜脚本"}]))

    assert result == {"blocked": False, "action": "allow", "message": ""}


def test_model_guard_decision_requires_classifier_json_block_action():
    assert _is_block_decision('{"action":"block"}')
    assert not _is_block_decision('{"action":"allow"}')
    assert not _is_block_decision("block")


def test_role_prompt_loads_from_markdown_file():
    prompt = load_role_prompt("director")

    assert "电影导演" in prompt


def test_usage_sums_multiple_model_messages_in_one_run():
    usage = usage_from_messages(
        [
            FakeMessage({"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}),
            FakeMessage({"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}),
        ]
    )

    assert usage == {"input_tokens": 17, "output_tokens": 7, "total_tokens": 24}


def test_usage_supports_response_metadata_token_usage_shape():
    usage = usage_from_messages(
        [
            FakeMessage(response_metadata={"token_usage": {"prompt_tokens": 11, "completion_tokens": 5}}),
        ]
    )

    assert usage == {"input_tokens": 11, "output_tokens": 5, "total_tokens": 16}


def test_agent_tools_include_bocha_search():
    tool_names = {tool.__name__ for tool in get_agent_tools()}

    assert {"get_current_time", "bocha_search"} <= tool_names


def test_bocha_result_is_normalized_for_agent_output():
    result = _normalize_bocha_result(
        "OpenAI",
        {
            "data": {
                "webPages": {
                    "value": [
                        {
                            "name": "Title",
                            "url": "https://example.com",
                            "siteName": "Example",
                            "datePublished": "2026-08-03",
                            "summary": "Summary",
                        }
                    ]
                }
            }
        },
    )

    assert result == {
        "query": "OpenAI",
        "count": 1,
        "results": [
            {
                "title": "Title",
                "url": "https://example.com",
                "site_name": "Example",
                "date_published": "2026-08-03",
                "snippet": "Summary",
            }
        ],
    }


def test_bocha_ai_search_messages_result_is_normalized_for_agent_output():
    result = _normalize_bocha_result(
        "西安天气",
        {
            "code": 200,
            "messages": [
                {
                    "role": "assistant",
                    "type": "source",
                    "content_type": "webpage",
                    "content": (
                        '{"value":[{"name":"未来三天 陕西降水持续",'
                        '"url":"https://example.com/weather",'
                        '"siteName":"腾讯网",'
                        '"datePublished":"2026-08-03T01:00:07+08:00",'
                        '"summary":"西安三日天气"}]}'
                    ),
                }
            ],
        },
    )

    assert result == {
        "query": "西安天气",
        "count": 1,
        "results": [
            {
                "title": "未来三天 陕西降水持续",
                "url": "https://example.com/weather",
                "site_name": "腾讯网",
                "date_published": "2026-08-03T01:00:07+08:00",
                "snippet": "西安三日天气",
            }
        ],
    }


def test_retry_sync_retries_then_returns_value():
    calls = {"count": 0}

    def flaky_operation():
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("temporary")
        return "ok"

    assert retry_sync(flaky_operation, attempts=3, initial_delay=0, retry_exceptions=(TimeoutError,)) == "ok"
    assert calls["count"] == 3
