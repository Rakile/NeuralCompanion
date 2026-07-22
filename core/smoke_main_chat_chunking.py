"""Smoke checks for main-chat chunk timing selection."""

from __future__ import annotations

import ast
from pathlib import Path

from core import speech_text


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


def _test_stream_tts_uses_stream_limits_for_second_pass_split() -> None:
    speak_async = _engine_function("speak_async")
    arg_names = [arg.arg for arg in speak_async.args.args]
    assert "preserve_text_iterable_chunks" in arg_names
    source = Path(ENGINE_PATH).read_text(encoding="utf-8")

    speak_async_source = ast.get_source_segment(source, speak_async) or ""
    assert "get_stream_chunk_limits()" in speak_async_source
    assert "get_text_chunk_limits()" in speak_async_source
    assert any(
        isinstance(node, ast.BoolOp)
        and any(
            isinstance(value, ast.Compare)
            and isinstance(value.left, ast.Name)
            and value.left.id == "text_iterable"
            for value in node.values
        )
        for node in ast.walk(speak_async)
    ), "streamed TTS should choose stream chunk limits when text_iterable is active"

    speak_async_stream = _engine_function("speak_async_stream")
    calls = [
        node
        for node in ast.walk(speak_async_stream)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "speak_async"
    ]
    assert calls, "speak_async_stream must delegate to speak_async"
    assert not any(
        keyword.arg == "preserve_text_iterable_chunks"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for call in calls
        for keyword in call.keywords
    ), "streamed TTS should allow oversized assembler chunks to be split again"


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


def _test_streamed_assistant_history_precedes_transcript_output() -> None:
    flow = _engine_function("run_conversation_flow")
    streamed_completion_blocks = []
    for node in ast.walk(flow):
        if not (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "response_text"
        ):
            continue
        append_assignment = next(
            (
                statement
                for statement in node.body
                if isinstance(statement, ast.Assign)
                and isinstance(statement.value, ast.Call)
                and getattr(statement.value.func, "id", "") == "_append_assistant_history_turn"
            ),
            None,
        )
        if append_assignment is None:
            continue
        positions = {"_append_assistant_history_turn": append_assignment.lineno}
        for part in ast.walk(node):
            if isinstance(part, ast.Call):
                call_name = getattr(part.func, "id", "")
                if call_name == "print" and any(
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and "🤖 Assistant:" in value.value
                    for value in ast.walk(part)
                ):
                    positions["transcript_output"] = part.lineno
                elif call_name in {
                    "_apply_stored_chat_history_limit",
                    "maybe_start_continuity_memory_auto_update",
                    "maybe_start_long_term_memory_auto_archive",
                }:
                    positions[call_name] = part.lineno
            if isinstance(part, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "assistant_history_added"
                for target in part.targets
            ):
                positions["assistant_history_added"] = part.lineno
        streamed_completion_blocks.append(positions)

    assert len(streamed_completion_blocks) == 2, "expected both streamed completion paths"
    for positions in streamed_completion_blocks:
        assert (
            positions["_append_assistant_history_turn"]
            < positions["_apply_stored_chat_history_limit"]
            < positions["assistant_history_added"]
            < positions["transcript_output"]
            < positions["maybe_start_continuity_memory_auto_update"]
            < positions["maybe_start_long_term_memory_auto_archive"]
        ), (
            "streamed assistant history must be finalized before transcript output, "
            "and memory work must start afterward"
        )


def _test_stream_request_envelope_is_frozen_before_worker_and_reused_for_fallback() -> None:
    function = _engine_function("start_streamed_llm_reply")
    arg_names = [arg.arg for arg in function.args.args]
    assert "request_context" in arg_names

    worker = next(
        (node for node in function.body if isinstance(node, ast.FunctionDef) and node.name == "worker"),
        None,
    )
    assert worker is not None
    freeze_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "_freeze_normal_chat_request"
    ]
    assert len(freeze_calls) == 1
    assert freeze_calls[0].lineno < worker.lineno

    worker_calls = [node for node in ast.walk(worker) if isinstance(node, ast.Call)]
    for call_name in ("build_llm_request", "chat_with_llm"):
        calls = [call for call in worker_calls if getattr(call.func, "id", "") == call_name]
        assert calls, f"stream worker must call {call_name}"
        assert any(
            call.args
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "request_context"
            for call in calls
        ), f"{call_name} must reuse the pre-worker request envelope"



def _test_proactive_identity_and_regeneration_target_are_explicit() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    flow = _engine_function("run_conversation_flow")
    flow_source = ast.get_source_segment(source, flow) or ""
    phase2_planner = next(
        node
        for node in flow.body
        if isinstance(node, ast.FunctionDef) and node.name == "_plan_phase2_actions"
    )
    planner_source = ast.get_source_segment(source, phase2_planner) or ""

    assert "*, proactive_request=False" in planner_source
    assert "elif bool(proactive_request):" in planner_source
    assert '== "You continue speaking."' not in planner_source
    assert "proactive_request=proactive_request_pending" in flow_source
    assert "regeneration_target_in_history = True" in flow_source
    assert "regeneration_target_in_history = bool(assistant_history_added)" in flow_source
    assert "target_in_history=regeneration_target_in_history" in flow_source


def _test_buddy_voice_stream_preserves_labels_until_routing() -> None:
    sanitized = speech_text.prepare_stream_tts_chunk(
        "[Mira] Buddy sentence.",
        preserve_voice_labels=True,
        sanitizer=lambda value: value.replace("[Mira]", "").strip(),
    )
    assert sanitized == "[Mira] Buddy sentence."
    assert speech_text.prepare_stream_tts_chunk(
        "[Mira] Buddy sentence.",
        preserve_voice_labels=False,
        sanitizer=lambda value: value.replace("[Mira]", "").strip(),
    ) == "Buddy sentence."
    assert speech_text.join_stream_tts_chunks([
        "Assistant sentence.",
        "[Mira] Buddy sentence.",
    ]) == "Assistant sentence.\n[Mira] Buddy sentence."


def _test_voice_stream_policy_decouples_label_preservation_from_buffering() -> None:
    resolver = getattr(speech_text, "resolve_addon_voice_stream_policy", None)
    assert callable(resolver), "streaming voice policy resolver is missing"

    low_latency = resolver(
        [
            {
                "requires_full_text": False,
                "preserve_voice_labels": True,
            }
        ]
    )
    disabled = resolver(
        [
            {
                "requires_full_text": False,
                "preserve_voice_labels": False,
            }
        ]
    )
    legacy_full_text = resolver([{"requires_full_text": True}])

    assert low_latency == {
        "requires_full_text": False,
        "preserve_voice_labels": True,
    }
    assert disabled == {
        "requires_full_text": False,
        "preserve_voice_labels": False,
    }
    assert legacy_full_text == {
        "requires_full_text": True,
        "preserve_voice_labels": True,
    }


def _test_completed_buddy_reply_uses_small_voice_preserving_chunks() -> None:
    chunker = getattr(speech_text, "chunk_voice_segments_for_fast_start", None)
    assert callable(chunker), "completed-reply fast-start chunker is missing"

    source_text = (
        "The sky is turning deep purple, and the cool evening air is settling "
        "around us while distant traffic fades into the background."
    )
    chunks = chunker(
        [
            {
                "text": source_text,
                "persona_id": "mira",
                "display_name": "Mira",
                "voice_path": "Q:/voices/mira.wav",
                "voice_volume": 0.75,
            }
        ],
        first_target_chars=20,
        first_max_chars=30,
        target_chars=80,
        max_chars=120,
    )

    assert len(chunks) >= 2
    assert 10 <= len(chunks[0]["text"]) <= 30
    assert all(len(item["text"]) <= 120 for item in chunks)
    assert all(item["persona_id"] == "mira" for item in chunks)
    assert all(item["voice_path"] == "Q:/voices/mira.wav" for item in chunks)
    assert all(item["voice_volume"] == 0.75 for item in chunks)
    assert " ".join(item["text"] for item in chunks) == source_text


def _test_engine_wires_addon_fast_start_hint_into_tts() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    flow = ast.get_source_segment(source, _engine_function("run_conversation_flow")) or ""
    helper = _engine_function("_prepare_low_latency_completed_tts_segments")

    assert "prefer_low_latency_tts" in flow
    assert "_prepare_low_latency_completed_tts_segments" in flow
    assert "preserve_text_iterable_chunks=True" in flow
    assert "COMPLETED_REPLY_FIRST_TARGET_CHARS" in (ast.get_source_segment(source, helper) or "")
    assert "COMPLETED_REPLY_FIRST_MAX_CHARS" in (ast.get_source_segment(source, helper) or "")
    assert "chunk_voice_segments_for_fast_start" in (ast.get_source_segment(source, helper) or "")


def _test_engine_prepares_addon_voice_conditioning_during_tts_startup() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    init_tts = ast.get_source_segment(source, _engine_function("init_tts")) or ""
    warmup = ast.get_source_segment(source, _engine_function("_warm_up_addon_tts_voice_paths")) or ""

    assert "_warm_up_addon_tts_voice_paths()" in init_tts
    assert "tts.voice_warmup_paths" in warmup
    assert "prepare_voice" in warmup


def _test_engine_buffers_streaming_voice_labels_and_sanitizes_after_routing() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    speak_async_stream = ast.get_source_segment(source, _engine_function("speak_async_stream")) or ""
    speak_async = ast.get_source_segment(source, _engine_function("speak_async")) or ""
    streamed_reply = ast.get_source_segment(source, _engine_function("start_streamed_llm_reply")) or ""
    assert "tts.voice_segments.requires_full_text" in source
    assert "join_stream_tts_chunks" in speak_async_stream
    assert "preserve_voice_labels" in streamed_reply
    assert "_addon_voice_segments_stream_policy" in source
    assert 'buddy_voice_policy.get("preserve_voice_labels"' in source
    assert 'buddy_voice_policy.get("requires_full_text"' in source
    assert "piece_text = sanitize_assistant_text_for_speech" in speak_async


def main() -> None:
    _test_stream_chunk_limits_ignore_avatar_mode()
    _test_stream_tts_uses_stream_limits_for_second_pass_split()
    _test_main_chat_stream_assembler_uses_buffer_lead_hint()
    _test_streamed_assistant_history_precedes_transcript_output()
    _test_stream_request_envelope_is_frozen_before_worker_and_reused_for_fallback()
    _test_proactive_identity_and_regeneration_target_are_explicit()
    _test_buddy_voice_stream_preserves_labels_until_routing()
    _test_voice_stream_policy_decouples_label_preservation_from_buffering()
    _test_completed_buddy_reply_uses_small_voice_preserving_chunks()
    _test_engine_wires_addon_fast_start_hint_into_tts()
    _test_engine_prepares_addon_voice_conditioning_during_tts_startup()
    _test_engine_buffers_streaming_voice_labels_and_sanitizes_after_routing()
    print("main chat chunking smoke passed")


if __name__ == "__main__":
    main()
