from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.lmstudio_provider.main import Addon
from addons.lmstudio_provider import main as lmstudio_provider_main
from addons.lmstudio_provider import worker as lmstudio_provider_worker
from core import chat_providers, lmstudio_runtime
from core.runtime_chat import ChatProviderRuntime


class _Settings:
    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model_name: str = "",
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name

    def get_provider_setting(self, provider_id: str, field_id: str) -> str:
        if provider_id == "lmstudio" and field_id == "base_url":
            return self.base_url
        if provider_id == "lmstudio" and field_id == "api_key":
            return self.api_key
        if provider_id == "lmstudio" and field_id == "model_name":
            return self.model_name
        return ""


def _addon_with_base_url(base_url: str) -> Addon:
    addon = Addon()
    addon._chat_service = _Settings(base_url)  # type: ignore[attr-defined]
    return addon


def test_lmstudio_base_url_defaults_to_responses_path() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")

    assert addon._base_url() == "http://127.0.0.1:1234/v1"
    assert addon._responses_url() == "http://127.0.0.1:1234/v1/responses"
    assert addon._native_api_base_url() == "http://127.0.0.1:1234"


def test_lmstudio_worker_uses_responses_for_plain_and_reasoning_models() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    addon._model_catalog_by_id = {
        "plain": {"id": "plain", "supports_reasoning": False, "reasoning_options": []},
        "binary": {"id": "binary", "supports_reasoning": True, "reasoning_options": ["off", "on"]},
    }
    plain = addon._worker_request_config(
        {
            "model": "plain",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.8,
            "top_p": 0.88,
            "max_tokens": 18000,
        },
        {"top_k": 40, "repeat_penalty": 1.11, "min_p": 0.05},
        emit_chunks=True,
        stream=True,
    )
    binary = addon._worker_request_config(
        {
            "model": "binary",
            "messages": [{"role": "user", "content": "hello"}],
        },
        {"reasoning": "off"},
        stream=False,
    )

    payload = plain["payload"]

    assert plain["url"] == "http://127.0.0.1:1234/v1/responses"
    assert binary["url"] == "http://127.0.0.1:1234/v1/responses"
    assert payload["stream"] is True
    assert payload["store"] is False
    assert payload["top_k"] == 40
    assert payload["repeat_penalty"] == 1.11
    assert payload["min_p"] == 0.05
    assert "reasoning" not in payload
    assert binary["payload"]["reasoning"] == {"effort": "none"}
    assert "native" not in plain
    assert "fallback_payload" not in binary


def test_worker_and_direct_use_identical_responses_payloads() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    addon._model_catalog_by_id = {
        "binary": {"id": "binary", "supports_reasoning": True, "reasoning_options": ["off", "on"]}
    }
    params = {
        "model": "binary",
        "messages": [
            {"role": "system", "content": "guard"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
        "response_format": {"type": "json_object"},
    }

    direct = addon._responses_payload(params, {"reasoning": "off"}, stream=False)
    worker = addon._worker_request_config(params, {"reasoning": "off"}, stream=False)["payload"]

    assert worker == direct


def test_worker_config_transport_is_ascii_safe_and_unicode_roundtrips() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")

    class _Stdin:
        def __init__(self) -> None:
            self.text = ""

        def write(self, value: str) -> None:
            self.text += value

        def close(self) -> None:
            pass

    process = type("_Process", (), {"stdin": _Stdin()})()
    config = {"payload": {"input": "A—B It’s fine"}}

    addon._send_worker_config(process, config)

    assert process.stdin.text.isascii()
    assert "\\u2014" in process.stdin.text
    assert "\\u2019" in process.stdin.text
    assert json.loads(process.stdin.text) == config


def test_provider_runtime_source_contains_no_legacy_generation_endpoint() -> None:
    source = Path(lmstudio_provider_main.__file__).read_text(encoding="utf-8")
    worker_source = Path(lmstudio_provider_worker.__file__).read_text(encoding="utf-8")

    assert "chat.completions.create" not in source
    assert '"/api/v1/chat"' not in source
    assert '"/chat/completions"' not in source
    assert "repair_model_history_window" not in source
    assert "build_model_history_window" not in source
    assert "conversation_history" not in source
    assert "/api/v1/chat" not in worker_source
    assert "/chat/completions" not in worker_source


def test_worker_non_stream_extracts_only_responses_output_text() -> None:
    original_post_json = lmstudio_provider_worker._post_json
    try:
        lmstudio_provider_worker._post_json = lambda _url, _payload, _key: {
            "output": [
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "hidden"}]},
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "visible answer"}],
                },
            ]
        }
        text = lmstudio_provider_worker._run_request(
            {
                "url": "http://127.0.0.1:1234/v1/responses",
                "api_key": "lm-studio",
                "payload": {"stream": False},
                "stream": False,
            }
        )
        assert text == "visible answer"
    finally:
        lmstudio_provider_worker._post_json = original_post_json


def test_worker_stream_emits_only_responses_output_text_deltas() -> None:
    original_stream = lmstudio_provider_worker._stream_sse_lines
    original_emit = lmstudio_provider_worker._emit
    emitted = []
    try:
        lmstudio_provider_worker._stream_sse_lines = lambda _url, _payload, _key: iter(
            [
                b'data: {"type":"response.reasoning_summary_text.delta","delta":"hidden"}\n',
                b'data: {"type":"response.output_text.delta","delta":"hello "}\n',
                b'data: {"type":"response.output_text.delta","delta":"world"}\n',
            ]
        )
        lmstudio_provider_worker._emit = lambda payload: emitted.append(dict(payload))
        text = lmstudio_provider_worker._run_request(
            {
                "url": "http://127.0.0.1:1234/v1/responses",
                "api_key": "lm-studio",
                "payload": {"stream": True},
                "emit_chunks": True,
                "stream": True,
            }
        )
        assert text == "hello world"
        assert "".join(str(item.get("chunk") or "") for item in emitted) == "hello world"
    finally:
        lmstudio_provider_worker._stream_sse_lines = original_stream
        lmstudio_provider_worker._emit = original_emit


def test_worker_http_errors_include_lmstudio_response_body() -> None:
    original_urlopen = lmstudio_provider_worker.urlopen
    error_body = b'{"error":{"message":"Invalid structured output"}}'
    try:
        lmstudio_provider_worker.urlopen = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                "http://127.0.0.1:1234/v1/responses",
                400,
                "Bad Request",
                {},
                io.BytesIO(error_body),
            )
        )
        try:
            lmstudio_provider_worker._post_json(
                "http://127.0.0.1:1234/v1/responses",
                {"model": "test"},
                "lm-studio",
            )
        except RuntimeError as exc:
            assert "Invalid structured output" in str(exc)
        else:
            raise AssertionError("LM Studio HTTP response body was hidden")
    finally:
        lmstudio_provider_worker.urlopen = original_urlopen


def test_direct_http_errors_include_lmstudio_response_body() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    original_urlopen = lmstudio_provider_main.urlopen
    error_body = b'{"error":{"message":"Invalid Responses payload"}}'
    try:
        lmstudio_provider_main.urlopen = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                "http://127.0.0.1:1234/v1/responses",
                400,
                "Bad Request",
                {},
                io.BytesIO(error_body),
            )
        )
        try:
            addon._responses_request({"model": "test"})
        except RuntimeError as exc:
            assert "Invalid Responses payload" in str(exc)
        else:
            raise AssertionError("Direct LM Studio HTTP response body was hidden")
    finally:
        lmstudio_provider_main.urlopen = original_urlopen


def test_worker_stream_http_errors_include_lmstudio_response_body() -> None:
    original_urlopen = lmstudio_provider_worker.urlopen
    error_body = b'{"error":{"message":"Invalid Responses stream"}}'
    try:
        lmstudio_provider_worker.urlopen = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                "http://127.0.0.1:1234/v1/responses",
                400,
                "Bad Request",
                {},
                io.BytesIO(error_body),
            )
        )
        try:
            list(
                lmstudio_provider_worker._stream_sse_lines(
                    "http://127.0.0.1:1234/v1/responses",
                    {"model": "test"},
                    "lm-studio",
                )
            )
        except RuntimeError as exc:
            assert "Invalid Responses stream" in str(exc)
        else:
            raise AssertionError("Streaming LM Studio HTTP response body was hidden")
    finally:
        lmstudio_provider_worker.urlopen = original_urlopen


def test_remote_lmstudio_skips_local_responsiveness_guard() -> None:
    addon = _addon_with_base_url("http://192.168.2.46:1234")
    original_guard = lmstudio_runtime.local_inference_responsiveness_guard
    calls = []

    @contextlib.contextmanager
    def _recording_guard(logger=print):
        calls.append("entered")
        yield

    try:
        lmstudio_runtime.local_inference_responsiveness_guard = _recording_guard
        with addon._responsiveness_guard():
            pass
        assert calls == []
    finally:
        lmstudio_runtime.local_inference_responsiveness_guard = original_guard


def test_non_stream_worker_wait_yields_during_slow_completion() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    original_yield = lmstudio_provider_main._yield_ui
    calls = []
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time; sys.stdin.read(); time.sleep(0.2); print('{\"ok\": true, \"text\": \"done\"}')",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        lmstudio_provider_main._yield_ui = lambda: calls.append("yield")
        stdout, stderr = addon._communicate_worker(process, "{}", timeout=5)
        assert "done" in stdout
        assert stderr == ""
        assert calls
    finally:
        lmstudio_provider_main._yield_ui = original_yield
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def test_stream_worker_line_wait_yields_before_first_chunk() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    original_yield = lmstudio_provider_main._yield_ui
    calls = []
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import time; "
                "time.sleep(0.2); "
                "print('{\"chunk\": \"first\"}', flush=True); "
                "print('{\"ok\": true, \"text\": \"first\"}', flush=True)"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        lmstudio_provider_main._yield_ui = lambda: calls.append("yield")
        lines = list(addon._iter_worker_stdout_lines(process, timeout=5))
        assert any('"chunk"' in line for line in lines)
        assert any('"ok"' in line for line in lines)
        assert calls
    finally:
        lmstudio_provider_main._yield_ui = original_yield
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def test_worker_script_starts_with_repo_imports_available() -> None:
    worker_path = Path(lmstudio_provider_worker.__file__).resolve()
    process = subprocess.run(
        [sys.executable, "-u", str(worker_path)],
        input="{}",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        cwd=str(ROOT),
    )

    assert "ModuleNotFoundError" not in process.stderr
    assert '"ok": false' in process.stdout
    assert "empty request URL" in process.stdout


def test_worker_emit_survives_charmap_stdout() -> None:
    original_stdout = lmstudio_provider_worker.sys.stdout
    raw = io.BytesIO()
    charmap_stdout = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", newline="")
    try:
        lmstudio_provider_worker.sys.stdout = charmap_stdout
        lmstudio_provider_worker._emit({"ok": True, "text": "snowman ☃ and kanji 漢字"})
        charmap_stdout.flush()
    finally:
        lmstudio_provider_worker.sys.stdout = original_stdout
        charmap_stdout.detach()

    payload = json.loads(raw.getvalue().decode("cp1252"))
    assert payload["ok"] is True
    assert payload["text"] == "snowman ☃ and kanji 漢字"


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_native_model_catalog_retains_reasoning_metadata() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    original_urlopen = lmstudio_provider_main.urlopen
    try:
        lmstudio_provider_main.urlopen = lambda *_args, **_kwargs: _JsonResponse(
            {
                "models": [
                    {
                        "key": "binary",
                        "type": "llm",
                        "capabilities": {
                            "vision": True,
                            "reasoning": {"allowed_options": ["off", "on"], "default": "on"},
                        },
                    },
                    {"key": "plain", "type": "llm", "capabilities": {"vision": False}},
                ]
            }
        )
        catalog = addon._list_native_models()
    finally:
        lmstudio_provider_main.urlopen = original_urlopen

    by_id = {item["id"]: item for item in catalog}
    assert by_id["binary"]["supports_reasoning"] is True
    assert by_id["binary"]["reasoning_options"] == ["off", "on"]
    assert by_id["binary"]["reasoning_default"] == "on"
    assert by_id["plain"]["supports_reasoning"] is False
    assert addon._model_catalog_by_id == by_id


def test_incompatible_responses_probe_blocks_without_fallback() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    addon._responses_compatibility_cache = {}

    def fail_probe(_payload):
        raise RuntimeError("invalid reasoning effort none")

    addon._post_responses_probe = fail_probe
    try:
        addon._ensure_responses_compatibility("binary")
    except RuntimeError as exc:
        message = str(exc)
        assert "LM Studio 0.4.7 or newer" in message
        assert "/v1/responses" in message
    else:
        raise AssertionError("Incompatible LM Studio server was not blocked")


def test_compatible_responses_probe_is_cached_per_server_and_model() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    addon._responses_compatibility_cache = {}
    calls = []

    def record_probe(payload):
        calls.append(dict(payload))
        return {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "OK"}]}
            ]
        }

    addon._post_responses_probe = record_probe
    addon._ensure_responses_compatibility("binary")
    addon._ensure_responses_compatibility("binary")

    assert len(calls) == 1
    assert calls[0]["reasoning"] == {"effort": "none"}
    assert calls[0]["store"] is False


def test_simultaneous_first_use_runs_one_compatibility_probe() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    addon._responses_compatibility_cache = {}
    probe_entered = threading.Event()
    release_probe = threading.Event()
    second_started = threading.Event()
    call_lock = threading.Lock()
    calls = []
    errors = []

    def blocking_probe(payload):
        with call_lock:
            calls.append(dict(payload))
        probe_entered.set()
        assert release_probe.wait(2.0)
        return {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "OK"}]}
            ]
        }

    def ensure(*, second=False):
        if second:
            second_started.set()
        try:
            addon._ensure_responses_compatibility("binary")
        except Exception as exc:
            errors.append(exc)

    addon._post_responses_probe = blocking_probe
    first = threading.Thread(target=ensure)
    second = threading.Thread(target=lambda: ensure(second=True))
    first.start()
    assert probe_entered.wait(1.0)
    second.start()
    assert second_started.wait(1.0)
    time.sleep(0.1)
    release_probe.set()
    first.join(2.0)
    second.join(2.0)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert len(calls) == 1
    assert calls[0]["model"] == "binary"


def test_failed_single_flight_unblocks_waiters_and_later_retries() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    addon._responses_compatibility_cache = {}
    probe_entered = threading.Event()
    release_probe = threading.Event()
    second_started = threading.Event()
    call_lock = threading.Lock()
    calls = []
    errors = []
    failing = [True]

    def flaky_probe(payload):
        with call_lock:
            calls.append(dict(payload))
        probe_entered.set()
        assert release_probe.wait(2.0)
        if failing[0]:
            raise RuntimeError("probe unavailable")
        return {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "OK"}]}
            ]
        }

    def ensure(*, second=False):
        if second:
            second_started.set()
        try:
            addon._ensure_responses_compatibility("binary")
        except Exception as exc:
            errors.append(str(exc))

    addon._post_responses_probe = flaky_probe
    first = threading.Thread(target=ensure)
    second = threading.Thread(target=lambda: ensure(second=True))
    first.start()
    assert probe_entered.wait(1.0)
    second.start()
    assert second_started.wait(1.0)
    time.sleep(0.1)
    release_probe.set()
    first.join(2.0)
    second.join(2.0)

    assert not first.is_alive() and not second.is_alive()
    assert len(calls) == 1
    assert len(errors) == 2
    assert errors[0] == errors[1]
    assert "probe unavailable" in errors[0]

    failing[0] = False
    addon._ensure_responses_compatibility("binary")
    assert len(calls) == 2


def test_frozen_execution_reuses_connection_compatibility_cache() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    addon._responses_compatibility_cache = {}
    calls = []

    def record_probe(payload):
        calls.append(dict(payload))
        return {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "OK"}]}
            ]
        }

    addon._post_responses_probe = record_probe
    addon._ensure_responses_compatibility("binary")
    addon._probe_frozen_responses = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("frozen execution repeated a cached compatibility probe")
    )
    addon._ensure_frozen_responses_compatibility(
        url="http://127.0.0.1:1234/v1/responses",
        api_key="captured-secret",
        model="binary",
        timeout=300.0,
    )

    assert len(calls) == 1


def _register_frozen_addon(
    addon: Addon,
    *,
    provider_id: str = "lmstudio",
    capture_catalog_reasoning: bool = False,
):
    metadata = None
    if capture_catalog_reasoning:
        metadata = {
            "generation_fields": list(addon._frozen_catalog_reasoning_fields())
        }
    return chat_providers.register_provider(
        provider_id=provider_id,
        label="LM Studio Frozen Smoke",
        api_key_getter=addon._api_key,
        base_url_getter=addon._base_url,
        metadata=metadata,
        **addon._frozen_registration_hooks(),
    )


def test_frozen_public_config_exposes_sanitized_local_and_remote_endpoints() -> None:
    cases = (
        ("http://127.0.0.1:1234", "http://127.0.0.1:1234/v1", False),
        ("http://192.168.2.46:1234", "http://192.168.2.46:1234/v1", True),
    )
    for configured_url, expected_url, expected_remote in cases:
        addon = _addon_with_base_url(configured_url)
        addon._chat_service.api_key = "private-endpoint-secret"  # type: ignore[attr-defined]
        try:
            provider = _register_frozen_addon(addon)
            assert provider.frozen_execution_version == 1
            assert provider.normal_chat_available is True
            context = chat_providers.capture_frozen_provider_context(
                provider,
                model_name="repo/model-key",
            )

            assert dict(context.provider_config) == {
                "base_url": expected_url,
                "provider_is_remote": expected_remote,
            }
            addon._chat_service.base_url = (  # type: ignore[attr-defined]
                "http://127.0.0.1:1234"
                if expected_remote
                else "http://remote.invalid:1234"
            )
            assert context.provider_config["provider_is_remote"] is expected_remote
            assert "api_key" not in context.provider_config
            assert "private-endpoint-secret" not in repr(context.provider_config)
        finally:
            chat_providers.unregister_provider("lmstudio")


def test_frozen_private_config_captures_coherent_final_endpoint_and_locality() -> None:
    addon = _addon_with_base_url("http://unused.invalid:1234")
    captured_urls = iter(
        ("http://127.0.0.1:1234/v1", "http://remote.invalid:1234/v1")
    )
    getter_calls = []

    def changing_base_url() -> str:
        value = next(captured_urls)
        getter_calls.append(value)
        return value

    addon._base_url = changing_base_url
    try:
        provider = _register_frozen_addon(addon)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="repo/model-key",
        )
        binding = context._binding
        assert binding is not None

        assert getter_calls == [
            "http://127.0.0.1:1234/v1",
            "http://remote.invalid:1234/v1",
        ]
        assert dict(context.provider_config) == {
            "base_url": "http://remote.invalid:1234/v1",
            "provider_is_remote": True,
        }
        assert binding._provider_config_copy()["base_url"] == (
            "http://remote.invalid:1234/v1"
        )
        assert binding._provider_config_copy()["provider_is_remote"] is True
    finally:
        chat_providers.unregister_provider("lmstudio")


def test_frozen_public_config_redacts_credential_bearing_endpoint() -> None:
    cases = (
        ("127.0.0.1:1234", False),
        ("remote.invalid:1234", True),
    )
    for host, expected_remote in cases:
        password = "url-password-secret"
        query_secret = "query-token-secret"
        configured_url = (
            f"http://relay-user:{password}@{host}/v1?api_key={query_secret}"
        )
        addon = _addon_with_base_url(configured_url)
        addon._chat_service.api_key = "private-api-secret"  # type: ignore[attr-defined]
        try:
            provider = _register_frozen_addon(addon)
            context = chat_providers.capture_frozen_provider_context(
                provider,
                model_name="repo/model-key",
            )

            assert dict(context.provider_config) == {
                "provider_is_remote": expected_remote,
            }
            visible = " ".join(
                (
                    repr(context),
                    repr(vars(context)),
                    repr(context.provider_config),
                    repr(context.to_summary()),
                )
            )
            for private_text in (
                configured_url,
                "relay-user",
                password,
                query_secret,
                host,
                "private-api-secret",
            ):
                assert private_text not in visible
            assert "base_url" not in context.provider_config
            assert "api_key" not in context.provider_config
        finally:
            chat_providers.unregister_provider("lmstudio")


def test_explicit_frozen_provider_config_does_not_invent_locality() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    explicit_url = "http://remote.invalid:1234/v1"
    try:
        provider = _register_frozen_addon(addon)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="repo/model-key",
            provider_config={"base_url": explicit_url},
        )
        binding = context._binding
        assert binding is not None

        assert dict(context.provider_config) == {"base_url": explicit_url}
        assert binding._provider_config_copy() == {"base_url": explicit_url}
        assert "provider_is_remote" not in context.provider_config
    finally:
        chat_providers.unregister_provider("lmstudio")


def test_frozen_direct_completion_and_stream_ignore_live_mutation() -> None:
    original_env = os.environ.get("NC_LMSTUDIO_HELPER_PROCESS")
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    addon._chat_service.api_key = "captured-direct-secret"  # type: ignore[attr-defined]
    addon._model_catalog_by_id = {
        "loaded-model": {
            "supports_reasoning": True,
            "reasoning_options": ["off", "on"],
        }
    }
    probes = []
    completions = []
    streams = []
    try:
        os.environ["NC_LMSTUDIO_HELPER_PROCESS"] = "0"
        addon._probe_frozen_responses = lambda **kwargs: probes.append(dict(kwargs)) or True
        addon._complete_prepared_direct = (
            lambda **kwargs: completions.append(dict(kwargs)) or "direct answer"
        )
        addon._stream_prepared_direct = (
            lambda **kwargs: streams.append(dict(kwargs)) or iter(("direct ", "stream"))
        )
        provider = _register_frozen_addon(addon)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="loaded-model",
            generation_fields={
                "temperature": 0.31,
                "top_p": 0.82,
                "top_k": 23,
                "repeat_penalty": 1.07,
                "min_p": 0.04,
                "max_tokens": 321,
                "reasoning": "off",
                "model_supports_reasoning": True,
                "model_supports_reasoning_toggle": True,
            },
        )

        addon._chat_service.base_url = "http://live.invalid:9999/v1"  # type: ignore[attr-defined]
        addon._chat_service.api_key = "live-direct-secret"  # type: ignore[attr-defined]
        addon._model_catalog_by_id = {"loaded-model": {"supports_reasoning": False}}
        os.environ["NC_LMSTUDIO_HELPER_PROCESS"] = "1"
        forbidden = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("frozen execution touched live LM Studio state")
        )
        addon._setting = forbidden
        addon._api_key = forbidden
        addon._base_url = forbidden
        addon._client = forbidden
        addon._model_metadata = forbidden
        addon._list_native_models = forbidden

        request = chat_providers.prepare_frozen_chat_request(
            context,
            {
                "messages": [
                    {"role": "system", "content": "guard"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "hello"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,AA=="},
                            },
                        ],
                    },
                ],
                "temperature": 1.99,
            },
            {"top_k": 999, "reasoning": "on"},
        )
        assert probes == []
        assert chat_providers.complete_frozen_chat(request) == "direct answer"
        assert "".join(chat_providers.stream_frozen_chat(request)) == "direct stream"

        transport = request.additional_params["lmstudio_transport"]
        assert (
            transport["compatibility_protocol"]
            == "lmstudio-responses-reasoning-none-v1"
        )
        assert len(transport["compatibility_fingerprint"]) == 64
        assert len(probes) == 1
        assert probes[0]["url"] == "http://127.0.0.1:1234/v1/responses"
        assert probes[0]["api_key"] == "captured-direct-secret"
        assert len(completions) == len(streams) == 1
        for call in (completions[0], streams[0]):
            assert call["url"] == "http://127.0.0.1:1234/v1/responses"
            assert call["api_key"] == "captured-direct-secret"
            assert call["payload"]["model"] == "loaded-model"
            assert call["payload"]["temperature"] == 0.31
            assert call["payload"]["top_k"] == 23
            assert call["payload"]["reasoning"] == {"effort": "none"}
            assert [item["role"] for item in call["payload"]["input"]] == ["system", "user"]
            assert call["payload"]["input"][1]["content"][1]["type"] == "input_image"

        visible = " ".join(
            (
                repr(context),
                repr(request),
                repr(vars(context)),
                repr(vars(request)),
                repr(context.to_summary()),
                repr(request.to_summary()),
            )
        )
        assert "captured-direct-secret" not in visible
        assert "live-direct-secret" not in visible
        assert "live.invalid" not in visible
    finally:
        chat_providers.unregister_provider("lmstudio")
        if original_env is None:
            os.environ.pop("NC_LMSTUDIO_HELPER_PROCESS", None)
        else:
            os.environ["NC_LMSTUDIO_HELPER_PROCESS"] = original_env


def test_explicit_frozen_output_budget_overrides_captured_default() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    try:
        provider = _register_frozen_addon(addon)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="loaded-model",
            generation_fields={"max_tokens": 321},
        )

        bounded = chat_providers.prepare_frozen_chat_request(
            context,
            {
                "messages": [{"role": "user", "content": "judge this"}],
                "max_tokens": 6272,
            },
            {chat_providers.FROZEN_OUTPUT_TOKEN_BUDGET_OVERRIDE: 6272},
        )
        ordinary = chat_providers.prepare_frozen_chat_request(
            context,
            {"messages": [{"role": "user", "content": "ordinary reply"}]},
        )

        assert bounded.params["lmstudio_responses_payload"]["max_output_tokens"] == 6272
        assert ordinary.params["lmstudio_responses_payload"]["max_output_tokens"] == 321
    finally:
        chat_providers.unregister_provider("lmstudio")


def test_frozen_worker_completion_and_stream_capture_transport_options() -> None:
    env_names = (
        "NC_LMSTUDIO_HELPER_PROCESS",
        "NC_LMSTUDIO_WORKER_TIMEOUT_SECONDS",
        "NC_LMSTUDIO_WORKER_POLL_SECONDS",
        "NC_LMSTUDIO_UI_YIELD_SECONDS",
    )
    original_env = {name: os.environ.get(name) for name in env_names}
    addon = _addon_with_base_url("http://localhost:1234")
    addon._chat_service.api_key = "captured-worker-secret"  # type: ignore[attr-defined]
    probes = []
    completions = []
    streams = []
    try:
        os.environ.update(
            {
                "NC_LMSTUDIO_HELPER_PROCESS": "1",
                "NC_LMSTUDIO_WORKER_TIMEOUT_SECONDS": "77",
                "NC_LMSTUDIO_WORKER_POLL_SECONDS": "0.17",
                "NC_LMSTUDIO_UI_YIELD_SECONDS": "0.011",
            }
        )
        addon._probe_frozen_responses = lambda **kwargs: probes.append(dict(kwargs)) or True
        addon._complete_prepared_worker = (
            lambda **kwargs: completions.append(dict(kwargs)) or "worker answer"
        )
        addon._stream_prepared_worker = (
            lambda **kwargs: streams.append(dict(kwargs)) or iter(("worker ", "stream"))
        )
        provider = _register_frozen_addon(addon)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="loaded-model",
            generation_fields={"temperature": 0.4, "top_k": 18},
        )

        addon._chat_service.base_url = "http://live.invalid:9999/v1"  # type: ignore[attr-defined]
        addon._chat_service.api_key = "live-worker-secret"  # type: ignore[attr-defined]
        addon._model_catalog_by_id = {"loaded-model": {"supports_reasoning": True}}
        os.environ.update(
            {
                "NC_LMSTUDIO_HELPER_PROCESS": "0",
                "NC_LMSTUDIO_WORKER_TIMEOUT_SECONDS": "999",
                "NC_LMSTUDIO_WORKER_POLL_SECONDS": "0.49",
                "NC_LMSTUDIO_UI_YIELD_SECONDS": "0.029",
            }
        )

        request = chat_providers.prepare_frozen_chat_request(
            context,
            {"messages": [{"role": "user", "content": "hello"}]},
        )
        assert chat_providers.complete_frozen_chat(request) == "worker answer"
        assert "".join(chat_providers.stream_frozen_chat(request)) == "worker stream"

        assert len(probes) == 1
        assert len(completions) == len(streams) == 1
        for call in (completions[0], streams[0]):
            config = call["config"]
            assert config["url"] == "http://localhost:1234/v1/responses"
            assert config["api_key"] == "captured-worker-secret"
            assert config["payload"]["model"] == "loaded-model"
            assert call["timeout"] == 77.0
            assert call["poll_interval"] == 0.17
            assert call["ui_yield_seconds"] == 0.011
    finally:
        chat_providers.unregister_provider("lmstudio")
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_frozen_request_is_prepared_once_and_survives_same_id_replacement() -> None:
    original_env = os.environ.get("NC_LMSTUDIO_HELPER_PROCESS")
    first = _addon_with_base_url("http://127.0.0.1:1234")
    first._chat_service.api_key = "first-secret"  # type: ignore[attr-defined]
    second = _addon_with_base_url("http://127.0.0.1:9999")
    prepare_calls = []
    completion_calls = []
    try:
        os.environ["NC_LMSTUDIO_HELPER_PROCESS"] = "0"
        first._probe_frozen_responses = lambda **kwargs: prepare_calls.append(dict(kwargs)) or True
        first._complete_prepared_direct = (
            lambda **kwargs: completion_calls.append(dict(kwargs)) or "first"
        )
        first._stream_prepared_direct = lambda **_kwargs: (_ for _ in ()).throw(
            chat_providers.FrozenChatProviderUnsupportedError("fallback")
        )
        provider = _register_frozen_addon(first)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="loaded-model",
        )
        request = chat_providers.prepare_frozen_chat_request(
            context,
            {"messages": [{"role": "user", "content": "hello"}]},
        )

        second._probe_frozen_responses = lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("replacement prepare must not run")
        )
        second._complete_prepared_direct = lambda **_kwargs: "second"
        _register_frozen_addon(second)

        try:
            list(chat_providers.stream_frozen_chat(request))
        except chat_providers.FrozenChatProviderUnsupportedError:
            pass
        else:
            raise AssertionError("Frozen stream did not preserve its captured fallback result")
        assert chat_providers.complete_frozen_chat(request) == "first"
        assert len(prepare_calls) == 1
        assert len(completion_calls) == 1
        assert completion_calls[0]["api_key"] == "first-secret"
    finally:
        chat_providers.unregister_provider("lmstudio")
        if original_env is None:
            os.environ.pop("NC_LMSTUDIO_HELPER_PROCESS", None)
        else:
            os.environ["NC_LMSTUDIO_HELPER_PROCESS"] = original_env


class _ExactChat:
    histories = []

    @classmethod
    def from_history(cls, history):
        cls.histories.append(history)
        return history


class _ExactLoadedModel:
    def __init__(
        self,
        *,
        model_key: str = "repo/model-key",
        identifier: str = "loaded-instance-alias",
        instance_reference: str = "instance-a",
    ) -> None:
        self.model_key = model_key
        self.identifier = identifier
        self.instance_reference = instance_reference
        self.formatted = []

    def get_info(self):
        return {
            "identifier": self.identifier,
            "instanceReference": self.instance_reference,
            "modelKey": self.model_key,
        }

    def get_context_length(self):
        return 8192

    def apply_prompt_template(self, chat):
        roles = [message["role"] for message in chat["messages"]]
        formatted = "|".join(roles)
        self.formatted.append(formatted)
        return formatted

    def tokenize(self, formatted):
        return list(range(len(formatted)))


class _LlmInstanceInfo:
    def __init__(
        self,
        *,
        model_key: str = "repo/model-key",
        identifier: str = "loaded-instance-alias",
        instance_reference: str = "instance-a",
    ) -> None:
        self.model_key = model_key
        self.identifier = identifier
        self.instance_reference = instance_reference


class _ProductionShapeLoadedModel(_ExactLoadedModel):
    def get_info(self):
        return _LlmInstanceInfo(
            model_key=self.model_key,
            identifier=self.identifier,
            instance_reference=self.instance_reference,
        )


def _exact_sdk(*models):
    class _LlmNamespace:
        def list_loaded(self):
            return list(models)

    class _Client:
        calls = []

        def __init__(self, *, api_host):
            self.calls.append(api_host)
            self.llm = _LlmNamespace()

    return type("_ExactSdk", (), {"Client": _Client, "Chat": _ExactChat})


def test_strict_local_capability_attests_exact_loaded_instance_and_prompt_template() -> None:
    original_get_sdk = lmstudio_runtime.get_sdk
    original_sdk_client = lmstudio_runtime.sdk_client
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    addon._chat_service.api_key = "strict-secret"  # type: ignore[attr-defined]
    model = _ExactLoadedModel()
    sdk = _exact_sdk(model)
    client_calls = []
    try:
        lmstudio_runtime.get_sdk = lambda: sdk
        lmstudio_runtime.sdk_client = lambda value, base_url: (
            client_calls.append((value, base_url)) or original_sdk_client(value, base_url)
        )
        provider = _register_frozen_addon(addon)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="repo/model-key",
        )
        addon._chat_service.base_url = "http://live.invalid:9999/v1"  # type: ignore[attr-defined]
        addon._chat_service.api_key = "live-strict-secret"  # type: ignore[attr-defined]
        lmstudio_runtime.get_sdk = lambda: (_ for _ in ()).throw(
            AssertionError("live SDK loader must not run")
        )

        strict_context = chat_providers.upgrade_frozen_context_for_relay(context)
        assert strict_context.strict_relay_available is True
        assert strict_context.capabilities.context_limit == 8192
        count = chat_providers.count_frozen_chat_tokens(
            strict_context,
            [
                {"role": "system", "content": "guard"},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
        )
        assert count == len("system|user|assistant")
        assert model.formatted == ["system|user|assistant"]
        assert client_calls == [(sdk, "http://127.0.0.1:1234/v1")]
        assert sdk.Client.calls == ["127.0.0.1:1234"]
        assert "strict-secret" not in repr(strict_context)
        assert context._binding.execution_identity not in repr(strict_context)
    finally:
        chat_providers.unregister_provider("lmstudio")
        lmstudio_runtime.get_sdk = original_get_sdk
        lmstudio_runtime.sdk_client = original_sdk_client


def test_strict_local_capability_folds_consecutive_system_messages() -> None:
    original_get_sdk = lmstudio_runtime.get_sdk
    original_sdk_client = lmstudio_runtime.sdk_client
    addon = _addon_with_base_url("http://127.0.0.1:1234")

    class _RejectingConsecutiveSystemModel(_ExactLoadedModel):
        def apply_prompt_template(self, chat):
            roles = [message["role"] for message in chat["messages"]]
            if any(
                previous == current == "system"
                for previous, current in zip(roles, roles[1:])
            ):
                raise RuntimeError("Consecutive system prompts are unsupported")
            return super().apply_prompt_template(chat)

    model = _RejectingConsecutiveSystemModel()
    sdk = _exact_sdk(model)
    _ExactChat.histories.clear()
    try:
        lmstudio_runtime.get_sdk = lambda: sdk
        provider = _register_frozen_addon(addon)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="repo/model-key",
        )
        strict_context = chat_providers.upgrade_frozen_context_for_relay(context)

        count = chat_providers.count_frozen_chat_tokens(
            strict_context,
            [
                {"role": "system", "content": "first guard"},
                {"role": "system", "content": "second guard"},
                {"role": "user", "content": "hello"},
            ],
        )

        assert count == len("system|user")
        assert _ExactChat.histories[-1]["messages"] == [
            {"role": "system", "content": "first guard\n\nsecond guard"},
            {"role": "user", "content": "hello"},
        ]
    finally:
        chat_providers.unregister_provider("lmstudio")
        lmstudio_runtime.get_sdk = original_get_sdk
        lmstudio_runtime.sdk_client = original_sdk_client


def test_loaded_model_identity_accepts_production_model_key_and_rejects_ambiguity() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")

    assert addon._loaded_model_identity(_ProductionShapeLoadedModel()) == (
        "repo/model-key",
        "loaded-instance-alias",
        "instance-a",
    )

    class _AmbiguousLoadedModel(_ProductionShapeLoadedModel):
        def get_info(self):
            return {
                "model_key": "repo/model-key",
                "modelKey": "repo/different-key",
                "identifier": self.identifier,
                "instance_reference": self.instance_reference,
            }

    assert addon._loaded_model_identity(_AmbiguousLoadedModel()) is None


def test_strict_local_capability_is_unavailable_without_exact_parity() -> None:
    original_get_sdk = lmstudio_runtime.get_sdk
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    mismatch = _ExactLoadedModel(model_key="repo/different-key")
    try:
        lmstudio_runtime.get_sdk = lambda: _exact_sdk(mismatch)
        provider = _register_frozen_addon(addon)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="repo/model-key",
        )
        strict_context = chat_providers.upgrade_frozen_context_for_relay(context)
        assert strict_context.strict_relay_available is False

        lmstudio_runtime.get_sdk = lambda: _exact_sdk(
            _ExactLoadedModel(instance_reference="instance-a"),
            _ExactLoadedModel(instance_reference="instance-b"),
        )
        chat_providers.unregister_provider("lmstudio")
        provider = _register_frozen_addon(addon)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="repo/model-key",
        )
        strict_context = chat_providers.upgrade_frozen_context_for_relay(context)
        assert strict_context.strict_relay_available is False

        model = _ExactLoadedModel()
        lmstudio_runtime.get_sdk = lambda: _exact_sdk(model)
        chat_providers.unregister_provider("lmstudio")
        provider = _register_frozen_addon(addon)
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="repo/model-key",
        )
        strict_context = chat_providers.upgrade_frozen_context_for_relay(context)
        assert strict_context.strict_relay_available is True
        model.model_key = "repo/mutated-key"
        try:
            chat_providers.count_frozen_chat_tokens(
                strict_context,
                [{"role": "user", "content": "hello"}],
            )
        except chat_providers.FrozenChatProviderCapabilityError:
            pass
        else:
            raise AssertionError("Loaded model identity mutation must fail closed")

        model.model_key = "repo/model-key"
        try:
            chat_providers.count_frozen_chat_tokens(
                strict_context,
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "hello"},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
                        ],
                    }
                ],
            )
        except chat_providers.FrozenChatProviderCapabilityError:
            pass
        else:
            raise AssertionError("Multimodal strict counting must fail closed")
    finally:
        chat_providers.unregister_provider("lmstudio")
        lmstudio_runtime.get_sdk = original_get_sdk


def test_frozen_reasoning_uses_captured_catalog_metadata_after_mutation() -> None:
    original_env = os.environ.get("NC_LMSTUDIO_HELPER_PROCESS")
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    addon._chat_service.model_name = "reasoning-model"  # type: ignore[attr-defined]
    addon._model_catalog_by_id = {
        "reasoning-model": {
            "supports_reasoning": True,
            "supports_reasoning_toggle": True,
            "reasoning_options": [
                "none",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
            ],
            "reasoning_default": "medium",
        }
    }
    try:
        os.environ["NC_LMSTUDIO_HELPER_PROCESS"] = "0"
        addon._probe_frozen_responses = lambda **_kwargs: True
        provider = _register_frozen_addon(
            addon,
            capture_catalog_reasoning=True,
        )
        contexts = {}
        for value in ("on", "high", "off"):
            runtime = ChatProviderRuntime(
                lambda requested=value: {
                    "chat_provider": "lmstudio",
                    "model_name": "reasoning-model",
                    "reasoning": requested,
                    "model_supports_reasoning": True,
                    "model_supports_reasoning_toggle": True,
                }
            )
            contexts[value] = runtime.capture_frozen_context()

        addon._model_catalog_by_id = {
            "reasoning-model": {
                "supports_reasoning": True,
                "supports_reasoning_toggle": True,
                "reasoning_options": ["off", "on"],
                "reasoning_default": "on",
            }
        }
        addon._model_metadata = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("frozen preparation queried live model metadata")
        )
        addon._list_native_models = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("frozen preparation queried the live catalog")
        )

        expected = {"on": "medium", "high": "high", "off": "none"}
        for value, context in contexts.items():
            request = chat_providers.prepare_frozen_chat_request(
                context,
                {"messages": [{"role": "user", "content": "hello"}]},
            )
            payload = request.params["lmstudio_responses_payload"]
            assert payload["reasoning"] == {"effort": expected[value]}
    finally:
        chat_providers.unregister_provider("lmstudio")
        if original_env is None:
            os.environ.pop("NC_LMSTUDIO_HELPER_PROCESS", None)
        else:
            os.environ["NC_LMSTUDIO_HELPER_PROCESS"] = original_env


def main() -> int:
    test_lmstudio_base_url_defaults_to_responses_path()
    test_lmstudio_worker_uses_responses_for_plain_and_reasoning_models()
    test_worker_and_direct_use_identical_responses_payloads()
    test_worker_config_transport_is_ascii_safe_and_unicode_roundtrips()
    test_provider_runtime_source_contains_no_legacy_generation_endpoint()
    test_worker_non_stream_extracts_only_responses_output_text()
    test_worker_stream_emits_only_responses_output_text_deltas()
    test_worker_http_errors_include_lmstudio_response_body()
    test_direct_http_errors_include_lmstudio_response_body()
    test_worker_stream_http_errors_include_lmstudio_response_body()
    test_remote_lmstudio_skips_local_responsiveness_guard()
    test_non_stream_worker_wait_yields_during_slow_completion()
    test_stream_worker_line_wait_yields_before_first_chunk()
    test_worker_script_starts_with_repo_imports_available()
    test_worker_emit_survives_charmap_stdout()
    test_native_model_catalog_retains_reasoning_metadata()
    test_incompatible_responses_probe_blocks_without_fallback()
    test_compatible_responses_probe_is_cached_per_server_and_model()
    test_simultaneous_first_use_runs_one_compatibility_probe()
    test_failed_single_flight_unblocks_waiters_and_later_retries()
    test_frozen_execution_reuses_connection_compatibility_cache()
    test_frozen_public_config_exposes_sanitized_local_and_remote_endpoints()
    test_frozen_private_config_captures_coherent_final_endpoint_and_locality()
    test_frozen_public_config_redacts_credential_bearing_endpoint()
    test_explicit_frozen_provider_config_does_not_invent_locality()
    test_frozen_direct_completion_and_stream_ignore_live_mutation()
    test_explicit_frozen_output_budget_overrides_captured_default()
    test_frozen_worker_completion_and_stream_capture_transport_options()
    test_frozen_request_is_prepared_once_and_survives_same_id_replacement()
    test_strict_local_capability_attests_exact_loaded_instance_and_prompt_template()
    test_strict_local_capability_folds_consecutive_system_messages()
    test_loaded_model_identity_accepts_production_model_key_and_rejects_ambiguity()
    test_strict_local_capability_is_unavailable_without_exact_parity()
    test_frozen_reasoning_uses_captured_catalog_metadata_after_mutation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
