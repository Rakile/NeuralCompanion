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
from core import sensory


def main() -> None:
    contributor_id = "nc.screen_supervisor.behavior"
    controller_source = (ROOT_DIR / "addons" / "companion_orb_overlay" / "controller.py").read_text(encoding="utf-8")
    if controller_source.count("def refresh_from_runtime(self):") != 1:
        raise AssertionError("Companion Orb Overlay should have exactly one refresh_from_runtime method.")
    refresh_block = controller_source.split("def refresh_from_runtime(self):", 1)[1].split("def import_session_state", 1)[0]
    if "_refresh_companion_orb_supervisor_designer_if_available()" not in refresh_block:
        raise AssertionError("Runtime refresh should update the Companion Orb supervisor designer state.")
    if "_register_companion_orb_supervisor_contributor()" not in refresh_block:
        raise AssertionError("Runtime refresh should register the Companion Orb supervisor contributor when enabled.")
    orb_controller_source = (
        ROOT_DIR / "addons" / "companion_orb_overlay" / "companion_orb" / "companion_orb_controller.py"
    ).read_text(encoding="utf-8")
    drop_inspection_block = orb_controller_source.split("def _inspect_drop_target", 1)[1].split(
        "bounds = target_bounds(target)", 1
    )[0]
    if 'mode="region"' in drop_inspection_block:
        raise AssertionError("Drop target inspection should honor companion_orb_target_mode instead of forcing region mode.")
    if "self._resolve_target_at(point" not in drop_inspection_block:
        raise AssertionError("Drop target inspection should use the configured target resolver.")
    if "_capture_target_for_current_mode(" not in orb_controller_source:
        raise AssertionError("Companion Orb capture should refresh or re-resolve targets for the current target mode.")
    if "_refresh_target_for_mode_change(" not in orb_controller_source:
        raise AssertionError("Changing Companion Orb target mode should immediately reselect from the orb position.")
    resolver_source = (
        ROOT_DIR / "addons" / "companion_orb_overlay" / "companion_orb" / "window_target_resolver.py"
    ).read_text(encoding="utf-8")
    if "def refresh_window_target(" not in resolver_source:
        raise AssertionError("Window targets should expose a live refresh helper so resized/moved windows update bounds.")
    for required_key in (
        "companion_orb_supervisor_enabled",
        "companion_orb_supervisor_prompt_template",
        "companion_orb_supervisor_personas",
        "companion_orb_supervisor_selected_persona_id",
    ):
        if required_key not in engine.RUNTIME_CONFIG:
            raise AssertionError(f"Engine runtime config is missing {required_key}.")

    original_tts_model = engine.tts_model
    original_hidden_speech = engine.RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech")
    with engine.sensory_pingpong_lock:
        original_action_state = dict(engine.sensory_hidden_action_state)

    try:
        sensory.register_prompt_contributor(
            contributor_id=contributor_id,
            source_id="screen",
            label="Screen Supervisor Smoke",
            prompt="When the screen shows YouTube, comment on the visible video.",
            metadata={
                "type": "behavior_rule",
                "active_behaviors": [
                    {
                        "trigger": "The user is watching YouTube.",
                        "action": "Comment on the YouTube content visible.",
                        "repeat_mode": "Every Nth match",
                        "repeat_interval": 1,
                    }
                ],
            },
        )
        if not engine._sensory_behavior_prompt_active(["screen_capture"]):
            raise AssertionError("Screen behavior contributor should be active for screen-like source aliases.")

        prompt_text = engine._sensory_pingpong_source_prompt_text(["screen_capture"])
        if "Screen Supervisor Smoke" not in prompt_text:
            raise AssertionError("Screen behavior prompt should be included for screen-like source aliases.")

        engine.tts_model = object()
        engine.RUNTIME_CONFIG["sensory_allow_hidden_proactive_speech"] = True
        with engine.sensory_pingpong_lock:
            engine.sensory_hidden_action_state.update(
                {
                    "pending_proactive": None,
                    "active_proactive": None,
                    "last_proactive_key": "",
                    "last_proactive_at": 0.0,
                    "last_proactive_candidate_key": "",
                    "last_proactive_candidate_at": 0.0,
                    "last_screen_subject_comment_key": "",
                    "last_screen_supervisor_meaningful_key": "",
                    "last_screen_supervisor_meaningful_subject": "",
                    "last_screen_supervisor_meaningful_trigger": "",
                }
            )

        applied = engine._apply_sensory_pong_result(
            {
                "keep": True,
                "emotion": "neutral",
                "attention": "screen",
                "summary": f"The user is watching a YouTube video in a code tutorial at {time.time()}.",
                "proactive_candidate": "That YouTube tutorial looks relevant to the code you have open.",
                "visual_candidate": "",
                "should_speak": True,
                "should_generate_image": False,
                "focus_bounds": [],
                "focus_label": "YouTube tutorial",
                "focus_text": "YouTube tutorial",
                "tags": ["[screen_supervisor_match]", "[screen_subject:youtube code tutorial]"],
            },
            [{"source": "screen_capture", "content": "synthetic screen payload"}],
        )
        if not applied:
            raise AssertionError("Supervisor PONG should be applied.")
        with engine.sensory_pingpong_lock:
            pending = dict(engine.sensory_hidden_action_state.get("pending_proactive") or {})
        if pending.get("candidate") != "That YouTube tutorial looks relevant to the code you have open.":
            raise AssertionError(f"Supervisor proactive candidate was not queued: {pending!r}")
        if pending.get("focus_text") != "YouTube tutorial":
            raise AssertionError(f"Companion Orb focus text was not preserved: {pending!r}")
    finally:
        sensory.unregister_prompt_contributor(contributor_id)
        engine.tts_model = original_tts_model
        if original_hidden_speech is None:
            engine.RUNTIME_CONFIG.pop("sensory_allow_hidden_proactive_speech", None)
        else:
            engine.RUNTIME_CONFIG["sensory_allow_hidden_proactive_speech"] = original_hidden_speech
        with engine.sensory_pingpong_lock:
            engine.sensory_hidden_action_state.clear()
            engine.sensory_hidden_action_state.update(original_action_state)

    print("Screen Supervisor to Companion Orb bridge smoke passed.")


if __name__ == "__main__":
    main()
