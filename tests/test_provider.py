import json
from typing import Any

import httpx
import pytest
from openai import OpenAI

from apg.models import tool_schemas
from apg.provider import LiveProvider, ProviderFailure
from apg.settings import Limits


def response(output: list[dict[str, Any]], status: str = "completed") -> dict[str, Any]:
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-4.1-mini",
        "output": output,
        "parallel_tool_calls": False,
        "usage": {"input_tokens": 30, "output_tokens": 20, "total_tokens": 50},
        "error": None,
        "incomplete_details": None,
    }


def stub(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], status_code: int = 200
) -> list[dict[str, Any]]:
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(status_code, json=payload)

    client = OpenAI(
        api_key="fake",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setattr("apg.provider.OpenAI", lambda **kw: client)
    return seen


def test_official_sdk_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    item = {
        "id": "fc_1",
        "type": "function_call",
        "name": "read_document",
        "arguments": '{"document_id":"launch_brief"}',
        "call_id": "call_1",
        "status": "completed",
    }
    seen = stub(monkeypatch, response([item]))
    turn = LiveProvider().turn(
        [{"role": "user", "content": "Read brief"}], {"permissions": {}}, Limits()
    )
    assert turn.calls[0]["arguments"] == {"document_id": "launch_brief"}
    assert turn.input_tokens == 30
    assert seen[0]["parallel_tool_calls"] is False
    assert len(seen[0]["tools"]) == 3
    for tool in tool_schemas():
        assert tool["strict"] is True
        assert tool["parameters"]["additionalProperties"] is False
        assert set(tool["parameters"]["required"]) == set(tool["parameters"]["properties"])


@pytest.mark.parametrize(
    ("payload", "code", "reason"),
    [
        (
            response(
                [
                    {
                        "id": "m1",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal", "refusal": "No"}],
                    }
                ]
            ),
            200,
            "MODEL_REFUSAL",
        ),
        (response([], "incomplete"), 200, "OUTPUT_LIMIT"),
        ({"error": {"message": "slow down", "type": "rate_limit_error"}}, 429, "RATE_LIMITED"),
        (
            {"error": {"message": "invalid", "type": "invalid_request_error"}},
            400,
            "PROVIDER_REJECTED",
        ),
        (
            response(
                [
                    {
                        "id": "m1",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "x" + chr(0x2014), "annotations": []}
                        ],
                    }
                ]
            ),
            200,
            "UNSUPPORTED_DISPLAY_TEXT",
        ),
    ],
)
def test_provider_failure(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], code: int, reason: str
) -> None:
    stub(monkeypatch, payload, code)
    with pytest.raises(ProviderFailure, match=reason):
        LiveProvider().turn([], {"permissions": {}}, Limits(retries=0))


def test_malformed_arguments_reach_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(
        monkeypatch,
        response(
            [
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "c1",
                    "name": "read_document",
                    "arguments": "{bad",
                }
            ]
        ),
    )
    assert LiveProvider().turn([], {"permissions": {}}, Limits()).calls[0]["arguments"] is None


def test_empty_model_output_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch, response([]))
    with pytest.raises(ProviderFailure, match="MODEL_EMPTY_OUTPUT"):
        LiveProvider().turn([], {"permissions": {}}, Limits(retries=0))


def test_malformed_response_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    malformed = response([])
    malformed["output"] = None
    stub(monkeypatch, malformed)
    with pytest.raises(ProviderFailure, match="MALFORMED_OUTPUT"):
        LiveProvider().turn([], {"permissions": {}}, Limits(retries=0))
