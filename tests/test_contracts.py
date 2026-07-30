import pytest
from pydantic import ValidationError

from app.schemas import RunRequest
from app.sse import encode_sse
from app.usage import usage_from_messages


class FakeMessage:
    def __init__(self, usage_metadata=None, response_metadata=None):
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}


def test_sse_encoding_preserves_event_and_json_data():
    encoded = encode_sse("message.delta", {"run_id": "run_001", "text": "你好"})

    assert encoded == 'event: message.delta\ndata: {"run_id":"run_001","text":"你好"}\n\n'


def test_agent_role_required_when_thread_id_is_missing():
    with pytest.raises(ValidationError):
        RunRequest(
            user_id="user_001",
            client_message_id="message_001",
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
