import asyncio
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.errors import AppError, classify_run_error, http_exception_handler, validate_image_inputs
from app.role_prompts import load_role_prompt
from app.retry import retry_sync
from app.schemas import RunRequest
from app.sse import encode_sse
from app.tools import _normalize_bocha_result, get_agent_tools
from app.usage import usage_from_messages


class FakeMessage:
    def __init__(self, usage_metadata=None, response_metadata=None):
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}


def test_sse_encoding_preserves_event_and_json_data():
    encoded = encode_sse("message.delta", {"run_id": "run_001", "text": "你好"})

    assert encoded == 'event: message.delta\ndata: {"run_id":"run_001","text":"你好"}\n\n'


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
