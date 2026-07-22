from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.lmstudio_provider.responses import (
    ResponsesProtocolError,
    build_responses_payload,
    decode_http_text,
    extract_response_text,
    iter_response_sse,
    map_reasoning_effort,
    map_response_format,
    responses_url,
)


def test_responses_url_uses_openai_compatible_base() -> None:
    assert responses_url("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1/responses"


def test_payload_preserves_repaired_role_order_and_image_ownership() -> None:
    payload = build_responses_payload(
        {
            "model": "vision-model",
            "messages": [
                {"role": "system", "content": "base"},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "answer"},
                {"role": "system", "content": "guard before image"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "inspect this"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                    ],
                },
            ],
            "temperature": 0.8,
            "top_p": 0.9,
            "max_tokens": 256,
        },
        {"top_k": 40, "repeat_penalty": 1.1, "min_p": 0.05},
        {"supports_reasoning": False, "reasoning_options": []},
        stream=True,
    )

    assert [item["role"] for item in payload["input"]] == ["system", "user", "assistant", "system", "user"]
    assert payload["input"][1]["content"] == "first"
    assert payload["input"][2]["content"] == "answer"
    assert payload["input"][4]["content"] == [
        {"type": "input_text", "text": "inspect this"},
        {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
    ]
    assert payload["store"] is False
    assert payload["stream"] is True
    assert payload["max_output_tokens"] == 256
    assert payload["top_k"] == 40
    assert payload["repeat_penalty"] == 1.1
    assert payload["min_p"] == 0.05
    assert "reasoning" not in payload


def test_reasoning_mapping_uses_catalog_capabilities() -> None:
    binary = {"supports_reasoning": True, "reasoning_options": ["off", "on"]}
    granular = {
        "supports_reasoning": True,
        "reasoning_options": ["none", "minimal", "low", "medium", "high", "xhigh"],
        "reasoning_default": "medium",
    }

    assert map_reasoning_effort("off", binary) == "none"
    assert map_reasoning_effort("on", binary) == "low"
    assert map_reasoning_effort("high", binary) == "low"
    assert map_reasoning_effort("off", granular) == "none"
    assert map_reasoning_effort("high", granular) == "high"
    assert map_reasoning_effort("on", granular) == "medium"
    assert map_reasoning_effort("on", {"supports_reasoning": False}) is None


def test_reasoning_mapping_normalizes_frozen_boolean_values() -> None:
    binary = {"supports_reasoning": True, "reasoning_options": ["off", "on"]}
    granular = {
        "supports_reasoning": True,
        "reasoning_options": ["none", "minimal", "low", "medium", "high", "xhigh"],
        "reasoning_default": "high",
    }

    assert map_reasoning_effort(True, binary) == "low"
    assert map_reasoning_effort(False, binary) == "none"
    assert map_reasoning_effort(True, granular) == "high"
    assert map_reasoning_effort(False, granular) == "none"

    payload = build_responses_payload(
        {"model": "granular"},
        {"reasoning": False},
        granular,
        stream=False,
    )
    assert payload["reasoning"] == {"effort": "none"}


def test_structured_output_maps_to_responses_text_format() -> None:
    assert map_response_format({"type": "json_object"}) == {
        "tools": [
            {
                "type": "function",
                "name": "json_response",
                "description": "Return the requested JSON object.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": True},
                "strict": False,
            }
        ],
        "tool_choice": "required",
    }

    schema = map_response_format(
        {
            "type": "json_schema",
            "json_schema": {
                "name": "route_decision",
                "strict": True,
                "schema": {"type": "object", "properties": {"answer": {"type": "boolean"}}},
            },
        }
    )

    assert schema == {
        "tools": [
            {
                "type": "function",
                "name": "route_decision",
                "description": "Return the requested structured response.",
                "parameters": {"type": "object", "properties": {"answer": {"type": "boolean"}}},
                "strict": True,
            }
        ],
        "tool_choice": "required",
    }


def test_unsupported_structured_output_is_rejected() -> None:
    try:
        map_response_format({"type": "xml"})
    except ValueError as exc:
        assert "Unsupported LM Studio Responses format" in str(exc)
    else:
        raise AssertionError("Unsupported structured output format was accepted")


def test_non_stream_parser_returns_only_final_output_text() -> None:
    payload = {
        "output": [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "hidden"}]},
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "visible "},
                    {"type": "output_text", "text": "answer"},
                ],
            },
        ]
    }

    assert extract_response_text(payload) == "visible answer"


def test_non_stream_parser_returns_structured_function_arguments() -> None:
    payload = {
        "output": [
            {
                "type": "function_call",
                "name": "route_decision",
                "arguments": '{"answer":true}',
            }
        ]
    }

    assert extract_response_text(payload) == '{"answer":true}'


def test_stream_parser_emits_text_deltas_and_ignores_reasoning() -> None:
    lines = [
        b'data: {"type":"response.reasoning_summary_text.delta","delta":"hidden"}\n',
        b'data: {"type":"response.output_text.delta","delta":"hello "}\n',
        b'data: {"type":"response.output_text.delta","delta":"world"}\n',
        b'data: {"type":"response.completed","response":{}}\n',
        b'data: [DONE]\n',
    ]

    assert list(iter_response_sse(lines)) == ["hello ", "world"]


def test_stream_parser_surfaces_error_events() -> None:
    lines = [b'data: {"type":"error","error":{"message":"model failed"}}\n']

    try:
        list(iter_response_sse(lines))
    except ResponsesProtocolError as exc:
        assert "model failed" in str(exc)
    else:
        raise AssertionError("Responses error event was not raised")


def test_stream_parser_emits_structured_function_arguments_once() -> None:
    done_only = [
        b'data: {"type":"response.function_call_arguments.done","arguments":"{\\"answer\\":true}"}\n'
    ]
    with_deltas = [
        b'data: {"type":"response.function_call_arguments.delta","delta":"{\\"answer\\":"}\n',
        b'data: {"type":"response.function_call_arguments.delta","delta":"true}"}\n',
        b'data: {"type":"response.function_call_arguments.done","arguments":"{\\"answer\\":true}"}\n',
    ]

    assert list(iter_response_sse(done_only)) == ['{"answer":true}']
    assert list(iter_response_sse(with_deltas)) == ['{"answer":', "true}"]


def test_malformed_response_without_output_text_is_rejected() -> None:
    try:
        extract_response_text({"output": [{"type": "reasoning"}]})
    except ResponsesProtocolError as exc:
        assert "no output text" in str(exc)
    else:
        raise AssertionError("Malformed Responses payload was accepted")


def test_provider_preserves_repaired_window_without_repairing_again() -> None:
    repaired = [
        {"role": "system", "content": "base"},
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "retained assistant prefix"},
        {"role": "system", "content": "later guard"},
        {"role": "user", "content": "latest user"},
    ]

    payload = build_responses_payload(
        {"model": "plain", "messages": repaired},
        {},
        {"supports_reasoning": False, "reasoning_options": []},
        stream=False,
    )

    assert payload["input"] == repaired


def test_http_decode_recovers_windows_smart_punctuation() -> None:
    raw_text = "The Kingdom’s last candle."

    assert decode_http_text(raw_text.encode("cp1252"), None) == raw_text


def main() -> int:
    test_responses_url_uses_openai_compatible_base()
    test_payload_preserves_repaired_role_order_and_image_ownership()
    test_reasoning_mapping_uses_catalog_capabilities()
    test_reasoning_mapping_normalizes_frozen_boolean_values()
    test_structured_output_maps_to_responses_text_format()
    test_unsupported_structured_output_is_rejected()
    test_non_stream_parser_returns_only_final_output_text()
    test_non_stream_parser_returns_structured_function_arguments()
    test_stream_parser_emits_text_deltas_and_ignores_reasoning()
    test_stream_parser_surfaces_error_events()
    test_stream_parser_emits_structured_function_arguments_once()
    test_malformed_response_without_output_text_is_rejected()
    test_provider_preserves_repaired_window_without_repairing_again()
    test_http_decode_recovers_windows_smart_punctuation()
    print("smoke_responses: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
