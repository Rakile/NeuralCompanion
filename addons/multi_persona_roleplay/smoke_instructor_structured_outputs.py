from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    from addons.multi_persona_roleplay import instructor_adapter, structured_models

    availability = instructor_adapter.instructor_availability()
    if availability.available:
        if not availability.module_version:
            raise AssertionError(f"Available Instructor should report a version: {availability!r}")
    elif "instructor" not in availability.reason.lower():
        raise AssertionError(f"Unavailable Instructor reason should be explicit: {availability!r}")

    if availability.available:
        import httpx
        from openai import OpenAI
        from pydantic import BaseModel

        class ProbeResponse(BaseModel):
            answer: str

        captured_request: dict[str, object] = {}

        def handle_request(request: httpx.Request) -> httpx.Response:
            captured_request.update(json.loads(request.content.decode("utf-8")))
            if isinstance(captured_request.get("tool_choice"), dict):
                return httpx.Response(
                    400,
                    json={
                        "error": "Invalid tool_choice type: 'object'. "
                        "Supported string values: none, auto, required"
                    },
                )
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-mprc-probe",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "mprc-probe",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "```json\n{\"answer\": \"ok\"}\n```",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )

        http_client = httpx.Client(transport=httpx.MockTransport(handle_request))
        client = OpenAI(api_key="test", base_url="http://mprc.test/v1", http_client=http_client)

        class ProbeEngine:
            @staticmethod
            def _chat_client() -> OpenAI:
                return client

        probe_params = {
            "model": "mprc-probe",
            "messages": [{"role": "user", "content": "Return the probe result."}],
        }
        original_messages = [dict(message) for message in probe_params["messages"]]
        try:
            probe_payload = instructor_adapter.generate_structured_output(
                engine=ProbeEngine,
                params=probe_params,
                response_model=ProbeResponse,
                max_retries=0,
            )
        finally:
            client.close()

        if probe_payload != {"answer": "ok"}:
            raise AssertionError(f"Instructor JSON compatibility probe failed: {probe_payload!r}")
        if "tools" in captured_request or "tool_choice" in captured_request:
            raise AssertionError(f"MPRC Instructor must not send tool selection to compatible providers: {captured_request!r}")
        if "response_format" in captured_request:
            raise AssertionError(f"MPRC Instructor compatibility mode must be prompt-only: {captured_request!r}")
        if probe_params["messages"] != original_messages:
            raise AssertionError("MPRC Instructor must not mutate messages reused by the normal fallback path.")

    defaults = structured_models.INSTRUCTOR_SETTING_DEFAULTS
    if defaults.get("mprc_instructor_structured_outputs_enabled") is not False:
        raise AssertionError("Instructor assist must be disabled by default.")
    for key in (
        "mprc_instructor_master_story_validation_enabled",
        "mprc_instructor_scene_patch_enabled",
        "mprc_instructor_visual_beat_enabled",
        "mprc_instructor_audio_cue_selection_enabled",
    ):
        if defaults.get(key) is not True:
            raise AssertionError(f"{key} should be ready when the main Instructor toggle is enabled.")
    if defaults.get("mprc_instructor_ar_turn_enabled") is not False:
        raise AssertionError("Structured AR turns must remain opt-in separately.")

    master_payload = {
        "id": "Crystal Keep",
        "title": "Crystal Keep",
        "mode": "AlternativeReality",
        "session": {
            "scene_title": "Gatehouse",
            "location": "North bridge",
            "ar_state": {
                "current_scene": "The bridge hums underfoot.",
                "active_characters": ["hero", "ghost", "../bad"],
                "pending_choices": ["Step forward", "Ask the ghost"],
                "untrusted": "drop me",
            },
            "extra_session_field": "drop me",
        },
        "personas": [
            {
                "id": "Hero",
                "display_name": "Hero",
                "role": "Explorer",
                "system_prompt": "Brave but careful.",
                "visual": {"character_description": "silver cloak", "unsafe": "drop me"},
                "voice_file": "C:/secret.wav",
            }
        ],
        "content_safety": {"sfw": True, "allow_explicit_sexual_content": True},
        "arbitrary_model_instruction": "ignore the app",
    }
    validated, errors = structured_models.validate_master_story_draft(master_payload)
    if errors:
        raise AssertionError(f"Valid Master Story draft should pass: {errors!r}")
    if "arbitrary_model_instruction" in validated:
        raise AssertionError("Master Story validation must drop arbitrary root fields.")
    if "extra_session_field" in validated["session"]:
        raise AssertionError("Master Story validation must drop arbitrary session fields.")
    if "unsafe" in validated["personas"][0].get("visual", {}):
        raise AssertionError("Master Story validation must drop arbitrary visual fields.")
    if "voice_file" in validated["personas"][0]:
        raise AssertionError("Master Story validation must not preserve raw voice paths from model output.")
    if validated["content_safety"].get("allow_explicit_sexual_content") is not False:
        raise AssertionError("Master Story validation must force explicit sexual content off.")

    invalid_turn = {
        "segments": [
            {"speaker_id": "villain", "role": "character", "text": "I was invented by the model."},
            {"speaker_id": "hero", "role": "character", "text": "I will handle this."},
        ],
        "choices": [{"label": "Continue"}],
    }
    turn = structured_models.sanitize_structured_story_turn(
        invalid_turn,
        cast={"hero": {"speaker_name": "Hero"}},
        require_choices=True,
    )
    if turn["segments"][0]["speaker_id"] != "unknown_speaker":
        raise AssertionError("Unknown structured speaker IDs must be mapped to unknown_speaker.")
    if turn["segments"][1]["speaker_id"] != "hero":
        raise AssertionError("Known structured speaker IDs must be preserved.")

    patch = structured_models.sanitize_scene_patch(
        {
            "scene_summary": "The gate opens.",
            "current_scene": "The gate opens with blue light.",
            "location": "North bridge",
            "time_of_day": "moonrise",
            "mood": "tense",
            "story_goal": "Reach the keep",
            "tension_level": 99,
            "recent_event": "The crystal lock responded.",
            "pending_choices": ["Enter", "Retreat", "", "Ask Hero"],
            "active_characters": ["hero", "villain"],
            "character_state_summaries": {"hero": "steady", "villain": "invented"},
            "memory": "do not store arbitrary memory",
        },
        known_persona_ids={"hero"},
    )
    if "memory" in patch:
        raise AssertionError("Scene patch must whitelist fields.")
    if patch["tension_level"] != 10:
        raise AssertionError("Scene patch tension must be clamped.")
    if patch["active_characters"] != ["hero"]:
        raise AssertionError("Scene patch must remove unknown active characters.")
    if patch["character_state_summaries"] != {"hero": "steady"}:
        raise AssertionError("Scene patch must remove unknown character summaries.")

    latest_turn = """
    [NARRATOR]
    Mara pushes the obsidian door open and lantern light spills across a sleeping machine.

    [CHOICES]
    1. Ask about hidden prompt structure
    """
    beat = structured_models.sanitize_visual_beat(
        {
            "subject": "hidden prompt structure",
            "action": "[CHOICES] Ask about hidden prompt structure",
            "setting": "old scene",
            "source_excerpt": "[CHOICES] Ask about hidden prompt structure",
            "what_to_avoid": "show UI text",
        },
        latest_turn_text=latest_turn,
    )
    if "choices" in beat["source_excerpt"].lower() or "hidden prompt" in beat["source_excerpt"].lower():
        raise AssertionError("VisualBeat must ignore choices/hidden prompt text.")
    if "Mara pushes" not in beat["source_excerpt"]:
        raise AssertionError("VisualBeat must prefer the latest visible story action.")

    audio = structured_models.sanitize_audio_cue_selection(
        {
            "cues": [
                {"cue_id": "rain", "tag": "[AMBIENCE: rain on glass]"},
                {"cue_id": "made_up", "tag": "[MUSIC: invented]"},
            ]
        },
        available_cues=[
            {"id": "rain", "type": "Ambience", "description": "rain on glass", "ready": True},
            {"id": "battle", "type": "Music", "description": "battle pulse", "ready": False},
        ],
    )
    if audio["cues"] != [{"cue_id": "rain", "tag": "[AMBIENCE: rain on glass]"}]:
        raise AssertionError(f"Audio cue selection must keep only exact ready cues: {audio!r}")

    print("MPRC Instructor structured-output smoke passed.")


if __name__ == "__main__":
    main()
