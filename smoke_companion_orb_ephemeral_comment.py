from __future__ import annotations

import copy
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    import engine

    spotify_payload = engine._buddy_contextual_payload_from_hidden_proactive(
        {
            "candidate": "React briefly to the current track.",
            "summary": "Night Drive is playing.",
            "attention": "music",
            "source": "spotify_sense",
        }
    )
    orb_payload = engine._buddy_contextual_payload_from_hidden_proactive(
        {
            "candidate": "Comment on the selected region.",
            "focus_text": "Release checklist",
            "source": "companion_orb_target",
        }
    )
    unrelated_payload = engine._buddy_contextual_payload_from_hidden_proactive(
        {"candidate": "React to camera motion.", "source": "webcam"}
    )
    if spotify_payload.get("source") != "spotify_sense" or "Night Drive" not in spotify_payload.get("context", ""):
        raise AssertionError(f"Spotify proactive context was not mapped for Buddy Chat: {spotify_payload!r}")
    if orb_payload.get("source") != "companion_orb_target" or "Release checklist" not in orb_payload.get("context", ""):
        raise AssertionError(f"Orb proactive context was not mapped for Buddy Chat: {orb_payload!r}")
    if unrelated_payload:
        raise AssertionError(f"Unrelated sensory source should not force Buddy Chat: {unrelated_payload!r}")

    missing_model_name = object()
    selected_text = "ValueError: missing file path"
    original_history = copy.deepcopy(getattr(engine, "conversation_history", []) or [])
    original_selected_text_occurrences = sum(str(item).count(selected_text) for item in original_history)
    original_llm_request_active = engine._llm_request_active.is_set()
    original_llm_request_active_count = int(getattr(engine, "_llm_request_active_count", 0) or 0)
    calls: list[dict] = []

    original_chat_completion = engine._chat_completion_create
    original_apply_fields = engine._apply_plain_text_chat_provider_generation_fields
    original_invoke_addon = engine._invoke_addon_capability
    original_model_name = engine.RUNTIME_CONFIG.get("model_name", missing_model_name)
    case_state = {"name": "", "simulate_overlap": False}
    addon_calls: list[dict] = []
    preexisting_marker_open = False
    overlap_marker_open = False

    def restore_marker_state() -> None:
        lock = getattr(engine, "_llm_request_active_lock", None)
        if lock is None:
            if original_llm_request_active:
                engine._llm_request_active.set()
            else:
                engine._llm_request_active.clear()
            return
        with lock:
            engine._llm_request_active_count = original_llm_request_active_count
            if original_llm_request_active:
                engine._llm_request_active.set()
            else:
                engine._llm_request_active.clear()

    def reset_marker_state() -> None:
        lock = getattr(engine, "_llm_request_active_lock", None)
        if lock is None:
            engine._llm_request_active.clear()
            return
        with lock:
            engine._llm_request_active_count = 0
            engine._llm_request_active.clear()

    def fake_apply(params, additional_params, *, max_tokens=1200):
        params["max_tokens"] = max_tokens

    def fake_completion(params, additional_params=None, *, stream=False):
        nonlocal overlap_marker_open
        active_at_entry = engine._llm_request_active.is_set()
        if case_state["simulate_overlap"]:
            engine._begin_llm_request_marker()
            overlap_marker_open = True
        calls.append({
            "case": case_state["name"],
            "params": copy.deepcopy(params),
            "additional_params": copy.deepcopy(additional_params),
            "stream": stream,
            "llm_request_active": active_at_entry,
            "overlap_started": bool(case_state["simulate_overlap"]),
        })
        return "That error points to a missing file path. Check the configured folder first."

    def fake_invoke_addon(capability, payload=None):
        addon_calls.append({"case": case_state["name"], "capability": capability, "payload": copy.deepcopy(payload or {})})
        if capability == "buddy_chat.contextual_reply" and case_state["name"] == "buddy_due":
            return {
                "handled": True,
                "response_text": "[Mira]\nThat selected error points to the missing path.",
                "debug": {"contextual_source": "companion_orb"},
            }
        return None

    result = None
    result_with_pre_set_active = None
    result_with_overlap = None
    result_with_buddy = None
    active_after_first_call = None
    active_after_pre_set_call = None
    active_after_pre_set_cleanup = None
    active_after_overlap_call = None
    active_after_overlap_cleanup = None
    history_after_call = None

    try:
        reset_marker_state()
        engine.RUNTIME_CONFIG["model_name"] = "unit-test-model"
        engine._apply_plain_text_chat_provider_generation_fields = fake_apply
        engine._chat_completion_create = fake_completion
        engine._invoke_addon_capability = fake_invoke_addon

        case_state.update({"name": "inactive", "simulate_overlap": False})
        result = engine.generate_companion_orb_ephemeral_comment(
            selected_text=selected_text,
            behavior_prompt="Keep comments practical.",
            response_style_label="Very friendly",
            exclude_from_memory=True,
            mode="select_area_comment",
        )
        active_after_first_call = engine._llm_request_active.is_set()

        engine._begin_llm_request_marker()
        preexisting_marker_open = True
        case_state.update({"name": "preexisting_marker", "simulate_overlap": False})
        result_with_pre_set_active = engine.generate_companion_orb_ephemeral_comment(
            selected_text=selected_text,
            behavior_prompt="Keep comments practical.",
            response_style_label="Very friendly",
            exclude_from_memory=True,
            mode="select_area_comment",
        )
        active_after_pre_set_call = engine._llm_request_active.is_set()
        engine._end_llm_request_marker()
        preexisting_marker_open = False
        active_after_pre_set_cleanup = engine._llm_request_active.is_set()

        case_state.update({"name": "overlap", "simulate_overlap": True})
        result_with_overlap = engine.generate_companion_orb_ephemeral_comment(
            selected_text=selected_text,
            behavior_prompt="Keep comments practical.",
            response_style_label="Very friendly",
            exclude_from_memory=True,
            mode="select_area_comment",
        )
        active_after_overlap_call = engine._llm_request_active.is_set()
        engine._end_llm_request_marker()
        overlap_marker_open = False
        active_after_overlap_cleanup = engine._llm_request_active.is_set()

        case_state.update({"name": "buddy_due", "simulate_overlap": False})
        result_with_buddy = engine.generate_companion_orb_ephemeral_comment(
            selected_text=selected_text,
            behavior_prompt="Keep comments practical.",
            response_style_label="Very friendly",
            exclude_from_memory=True,
            mode="select_area_comment",
        )

        history_after_call = copy.deepcopy(getattr(engine, "conversation_history", []) or [])
    finally:
        if preexisting_marker_open and hasattr(engine, "_end_llm_request_marker"):
            engine._end_llm_request_marker()
        if overlap_marker_open and hasattr(engine, "_end_llm_request_marker"):
            engine._end_llm_request_marker()
        engine._chat_completion_create = original_chat_completion
        engine._apply_plain_text_chat_provider_generation_fields = original_apply_fields
        engine._invoke_addon_capability = original_invoke_addon
        if original_model_name is missing_model_name:
            engine.RUNTIME_CONFIG.pop("model_name", None)
        else:
            engine.RUNTIME_CONFIG["model_name"] = original_model_name
        engine.conversation_history = original_history
        restore_marker_state()

    expected = "That error points to a missing file path. Check the configured folder first."
    if result != expected:
        raise AssertionError(f"Unexpected ephemeral comment: {result!r}")
    if result_with_pre_set_active != expected:
        raise AssertionError(f"Unexpected pre-set active ephemeral comment: {result_with_pre_set_active!r}")
    if result_with_overlap != expected:
        raise AssertionError(f"Unexpected overlap ephemeral comment: {result_with_overlap!r}")
    if result_with_buddy != "[Mira]\nThat selected error points to the missing path.":
        raise AssertionError(f"Unexpected Buddy contextual comment: {result_with_buddy!r}")
    if len(calls) != 3:
        raise AssertionError(f"Expected three chat-provider calls, got {len(calls)}")
    if any(call["stream"] is not False for call in calls):
        raise AssertionError(f"Expected non-streaming chat-provider calls, got {[call['stream'] for call in calls]!r}")
    if any(call["params"].get("max_tokens") != 260 for call in calls):
        raise AssertionError(f"Expected max_tokens=260, got {[call['params'].get('max_tokens') for call in calls]!r}")
    if any(not call["llm_request_active"] for call in calls):
        raise AssertionError("Ephemeral comment provider call did not mark LLM request active.")
    if active_after_first_call:
        raise AssertionError("Ephemeral comment left LLM request active after an inactive-start call.")
    if active_after_pre_set_call is not True:
        raise AssertionError("Ephemeral comment cleared a pre-existing LLM request marker.")
    if active_after_pre_set_cleanup:
        raise AssertionError("Pre-existing marker cleanup did not clear LLM request active state.")
    if active_after_overlap_call is not True:
        raise AssertionError("Overlap marker was cleared when the ephemeral helper returned.")
    if active_after_overlap_cleanup:
        raise AssertionError("Overlap marker cleanup did not clear LLM request active state.")
    if engine._llm_request_active.is_set() != original_llm_request_active:
        raise AssertionError("Smoke test did not restore the original LLM request active state.")
    current_model_name = engine.RUNTIME_CONFIG.get("model_name", missing_model_name)
    if original_model_name is missing_model_name:
        if current_model_name is not missing_model_name:
            raise AssertionError("Smoke test did not restore absent model_name.")
    elif current_model_name != original_model_name:
        raise AssertionError("Smoke test did not restore model_name.")
    selected_text_occurrences_after_call = sum(str(item).count(selected_text) for item in history_after_call)
    if selected_text_occurrences_after_call > original_selected_text_occurrences:
        raise AssertionError("Ephemeral comment appended selected text to conversation history.")
    if history_after_call != original_history:
        raise AssertionError("Ephemeral comment mutated conversation history.")
    messages = calls[0]["params"]["messages"]
    if "Do not store" not in messages[0]["content"]:
        raise AssertionError("Ephemeral comment did not include the privacy guard.")
    contextual_calls = [item for item in addon_calls if item["capability"] == "buddy_chat.contextual_reply"]
    completed_calls = [item for item in addon_calls if item["capability"] == "buddy_chat.assistant_reply"]
    if len(contextual_calls) != 4:
        raise AssertionError(f"Expected four Buddy contextual checks, got {len(contextual_calls)}")
    if len(completed_calls) != 4:
        raise AssertionError(f"Expected four Buddy cadence updates, got {len(completed_calls)}")
    if "ValueError: missing file path" not in contextual_calls[-1]["payload"].get("context", ""):
        raise AssertionError("Orb selected text was not passed to Buddy Chat as contextual input.")

    print("Companion Orb ephemeral comment smoke passed.")


if __name__ == "__main__":
    main()
