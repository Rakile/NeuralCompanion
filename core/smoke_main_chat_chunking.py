"""Smoke checks for main-chat chunk timing selection."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = REPO_ROOT / "engine.py"


def _load_get_stream_chunk_limits():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ENGINE_PATH))
    function_node = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "get_stream_chunk_limits":
            function_node = node
            break
    if function_node is None:
        raise AssertionError("engine.get_stream_chunk_limits was not found")
    module = ast.Module(body=[function_node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {}
    exec(compile(module, str(ENGINE_PATH), "exec"), namespace)
    return namespace["get_stream_chunk_limits"], namespace


def _engine_function(name: str) -> ast.FunctionDef:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ENGINE_PATH))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"engine.{name} was not found")


def _test_stream_chunk_limits_ignore_avatar_mode() -> None:
    get_stream_chunk_limits, namespace = _load_get_stream_chunk_limits()
    runtime_config = {}
    namespace["RUNTIME_CONFIG"] = runtime_config

    runtime_config.update({
        "avatar_mode": "vseeface",
        "chunk_target_chars": 40,
        "chunk_max_chars": 60,
        "stream_chunk_target_chars": 220,
        "stream_chunk_max_chars": 320,
    })
    assert get_stream_chunk_limits() == (220, 320)

    runtime_config["avatar_mode"] = "musetalk"
    assert get_stream_chunk_limits() == (220, 320)


def _test_stream_tts_preserves_stream_assembler_chunks() -> None:
    speak_async = _engine_function("speak_async")
    arg_names = [arg.arg for arg in speak_async.args.args]
    assert "preserve_text_iterable_chunks" in arg_names

    speak_async_stream = _engine_function("speak_async_stream")
    calls = [
        node
        for node in ast.walk(speak_async_stream)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "speak_async"
    ]
    assert calls, "speak_async_stream must delegate to speak_async"
    assert any(
        keyword.arg == "preserve_text_iterable_chunks"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for call in calls
        for keyword in call.keywords
    ), "streamed TTS must not re-chunk assembler chunks with normal speech timing"


def _test_main_chat_stream_assembler_uses_buffer_lead_hint() -> None:
    start_streamed_llm_reply = _engine_function("start_streamed_llm_reply")
    constants = {node.value for node in ast.walk(start_streamed_llm_reply) if isinstance(node, ast.Constant)}
    assert "stream_buffer_lead_seconds" in constants
    assert any(
        isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "_stream_buffer_lead_seconds_hint"
        for node in ast.walk(start_streamed_llm_reply)
    ), "streamed main chat should feed buffer lead into StreamingChunkAssembler"

    helper = _engine_function("_stream_buffer_lead_seconds_hint")
    helper_constants = {node.value for node in ast.walk(helper) if isinstance(node, ast.Constant)}
    assert "buffered" in helper_constants
    assert "rendered" in helper_constants


def main() -> None:
    _test_stream_chunk_limits_ignore_avatar_mode()
    _test_stream_tts_preserves_stream_assembler_chunks()
    _test_main_chat_stream_assembler_uses_buffer_lead_hint()
    print("main chat chunking smoke passed")


if __name__ == "__main__":
    main()
