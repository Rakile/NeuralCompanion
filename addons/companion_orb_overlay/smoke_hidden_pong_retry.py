from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import engine


def main() -> None:
    originals = {
        "_sensory_pingpong_enabled": engine._sensory_pingpong_enabled,
        "_hidden_sensory_pingpong_block_reasons": engine._hidden_sensory_pingpong_block_reasons,
        "_build_sensory_pingpong_messages": engine._build_sensory_pingpong_messages,
        "_chat_completion_create": engine._chat_completion_create,
        "_apply_sensory_pong_result": engine._apply_sensory_pong_result,
        "_publish_addon_runtime_event": engine._publish_addon_runtime_event,
        "_remember_hidden_sensory_fallback_request": engine._remember_hidden_sensory_fallback_request,
        "_hidden_sensory_should_use_fallback_request": engine._hidden_sensory_should_use_fallback_request,
    }
    chat_calls: list[dict] = []
    build_allow_images: list[object] = []
    applied_results: list[dict] = []
    remembered_sources: list[str] = []

    def fake_build(_snapshots, *, allow_images=None, priority=False):
        build_allow_images.append(allow_images)
        return [{"role": "system", "content": f"allow_images={allow_images}; priority={priority}"}]

    def fake_chat(params, _additional_params=None, *, stream=False):
        if stream:
            raise AssertionError("hidden PING/PONG should not use streaming")
        chat_calls.append(dict(params))
        if len(chat_calls) == 1:
            return "   "
        return (
            '{"keep": false, "emotion": "", "attention": "screen", "summary": "", '
            '"proactive_candidate": "", "visual_candidate": "", "should_speak": false, '
            '"should_generate_image": false, "focus_bounds": [], "focus_label": "", '
            '"focus_text": "", "tags": []}'
        )

    def fake_apply(result, _snapshots):
        applied_results.append(dict(result))
        return True

    try:
        engine._sensory_pingpong_enabled = lambda: True
        engine._hidden_sensory_pingpong_block_reasons = lambda **_kwargs: []
        engine._build_sensory_pingpong_messages = fake_build
        engine._chat_completion_create = fake_chat
        engine._apply_sensory_pong_result = fake_apply
        engine._publish_addon_runtime_event = lambda *_args, **_kwargs: None
        engine._remember_hidden_sensory_fallback_request = lambda source_text, **_kwargs: remembered_sources.append(str(source_text))

        result = engine.run_hidden_sensory_pingpong_cycle(
            snapshots_override=[{"source": "companion_orb_target", "content": "synthetic sensory payload"}],
            priority=False,
            trace_id="smoke-hidden-pong-retry",
        )
    finally:
        for name, value in originals.items():
            setattr(engine, name, value)

    if result is not True:
        raise AssertionError("Hidden PING/PONG cycle should apply the retry result")
    if len(chat_calls) != 2:
        raise AssertionError(f"Expected one retry after blank hidden PONG, got {len(chat_calls)} provider call(s)")
    if build_allow_images != [None, False]:
        raise AssertionError(f"Expected normal request then text-only retry, got allow_images={build_allow_images!r}")
    if "response_format" not in chat_calls[0]:
        raise AssertionError("Initial hidden PONG request should ask for JSON response_format")
    if "response_format" in chat_calls[1]:
        raise AssertionError("Text-only retry should omit response_format for provider compatibility")
    if not remembered_sources:
        raise AssertionError("Text-only fallback should be remembered for the source after retry")
    if not applied_results or applied_results[0].get("attention") != "screen":
        raise AssertionError(f"Retry result was not parsed/applied: {applied_results!r}")

    fallback_chat_calls: list[dict] = []
    fallback_build_allow_images: list[object] = []
    now = time.time()
    with engine.sensory_pingpong_lock:
        engine.sensory_pingpong_state["invalid_response_source"] = ""
        engine.sensory_pingpong_state["invalid_response_count"] = 0
        engine.sensory_pingpong_state["invalid_response_until"] = 0.0

    def fake_fallback_build(_snapshots, *, allow_images=None, priority=False):
        fallback_build_allow_images.append(allow_images)
        return [{"role": "system", "content": f"fallback allow_images={allow_images}; priority={priority}"}]

    def fake_blank_chat(params, _additional_params=None, *, stream=False):
        if stream:
            raise AssertionError("hidden PING/PONG should not use streaming")
        fallback_chat_calls.append(dict(params))
        return ""

    try:
        engine._sensory_pingpong_enabled = lambda: True
        engine._hidden_sensory_pingpong_block_reasons = lambda **_kwargs: []
        engine._hidden_sensory_should_use_fallback_request = lambda _source_text: True
        engine._build_sensory_pingpong_messages = fake_fallback_build
        engine._chat_completion_create = fake_blank_chat
        engine._apply_sensory_pong_result = fake_apply
        engine._publish_addon_runtime_event = lambda *_args, **_kwargs: None

        fallback_result = engine.run_hidden_sensory_pingpong_cycle(
            snapshots_override=[{"source": "companion_orb_target", "content": "synthetic fallback sensory payload"}],
            priority=False,
            trace_id="smoke-hidden-pong-fallback-blank",
        )
    finally:
        for name, value in originals.items():
            setattr(engine, name, value)

    if fallback_result is not False:
        raise AssertionError("Blank fallback-mode hidden PONG should not be applied")
    if len(fallback_chat_calls) != 1:
        raise AssertionError(f"Fallback mode should not retry again, got {len(fallback_chat_calls)} provider call(s)")
    if fallback_build_allow_images != [False]:
        raise AssertionError(f"Fallback mode should build text-only messages, got allow_images={fallback_build_allow_images!r}")
    if "response_format" in fallback_chat_calls[0]:
        raise AssertionError("Fallback mode should omit response_format")
    with engine.sensory_pingpong_lock:
        cooldown_until = float(engine.sensory_pingpong_state.get("invalid_response_until", 0.0) or 0.0)
        invalid_source = str(engine.sensory_pingpong_state.get("invalid_response_source", "") or "")
        invalid_count = int(engine.sensory_pingpong_state.get("invalid_response_count", 0) or 0)
    if invalid_source != "companion_orb_target" or invalid_count < 1 or cooldown_until <= now:
        raise AssertionError(
            "Blank fallback-mode hidden PONG should set an invalid-response cooldown; "
            f"source={invalid_source!r}, count={invalid_count}, until={cooldown_until}, now={now}"
        )

    print("Hidden PONG invalid-response retry smoke passed.")


if __name__ == "__main__":
    main()
