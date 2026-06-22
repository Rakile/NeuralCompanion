from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.audio_story_mode.session_schema import (
    audio_story_mode_session_payload,
    flatten_audio_story_mode_settings,
)


def _require_module(name: str):
    spec = importlib.util.find_spec(name)
    assert spec is not None, f"missing module: {name}"
    return importlib.import_module(name)


def test_session_schema_round_trips_story_state() -> None:
    flat = {
        "audio_story_mode_story_bible": {"summary": "A quiet test story"},
        "audio_story_mode_scene_plan": [{"scene_id": "scene_1", "summary": "Opening scene"}],
        "audio_story_mode_scene_overrides": {"global_scene_anchor": "keep the same room"},
        "audio_story_mode_continuity_memory": {"last_scene_id": "scene_1"},
        "audio_story_mode_character_anchors": {"char_hero": {"label": "Hero"}},
        "audio_story_mode_location_anchors": {"loc_room": {"label": "Room"}},
        "audio_story_mode_transcript_chunks": [{"index": 0, "text": "Once there was a room."}],
        "audio_story_mode_full_transcript_text": "Once there was a room.",
        "audio_story_mode_raw_transcript_segments": [{"start_seconds": 0.0, "end_seconds": 2.0, "text": "Once there was a room."}],
        "audio_story_mode_audio_duration_seconds": 2.0,
    }
    grouped = audio_story_mode_session_payload(flat)["audio_story_mode"]
    story = grouped.get("story", {})
    assert story.get("story_bible") == flat["audio_story_mode_story_bible"]
    assert story.get("scene_plan") == flat["audio_story_mode_scene_plan"]
    assert story.get("transcript_chunks") == flat["audio_story_mode_transcript_chunks"]
    flattened = flatten_audio_story_mode_settings({"audio_story_mode": grouped})
    for key, expected in flat.items():
        assert flattened.get(key) == expected, f"{key} did not round-trip"


def test_story_session_helper_builds_flat_payload() -> None:
    story_session = _require_module("addons.audio_story_mode.story_session")
    flat = story_session.build_story_state_flat_payload(
        story_bible={"summary": "Saved story"},
        scene_plan=[{"scene_id": "scene_saved"}],
        scene_overrides={"global_negative_prompt": "no blur"},
        continuity_memory={"last_scene_id": "scene_saved"},
        character_anchors={"char_saved": {"label": "Saved"}},
        location_anchors={"loc_saved": {"label": "Saved room"}},
        transcript_chunks=[{"index": 0, "text": "Saved text"}],
        full_transcript_text="Saved text",
        raw_transcript_segments=[{"text": "Saved text"}],
        audio_duration_seconds=1.25,
    )
    assert flat["audio_story_mode_story_bible"]["summary"] == "Saved story"
    assert flat["audio_story_mode_audio_duration_seconds"] == 1.25


def test_stream_security_requires_token_when_configured() -> None:
    security = _require_module("addons.audio_story_mode.stream_security")
    token = security.new_stream_access_token()
    assert len(token) >= 20
    secured_url = security.stream_url_with_token("http://127.0.0.1:8765/current.jpg", token)
    assert "token=" in secured_url
    assert security.is_stream_request_authorized(f"/current.jpg?token={token}", {}, token)
    assert security.is_stream_request_authorized("/current.jpg", {"X-Audio-Story-Token": token}, token)
    assert not security.is_stream_request_authorized("/current.jpg", {}, token)
    assert security.is_stream_request_authorized("/current.jpg", {}, "")


def test_scene_review_helper_summarizes_user_facing_scene() -> None:
    review = _require_module("addons.audio_story_mode.story_planner")
    payload = review.build_scene_review(
        {
            "scene_index": 1,
            "scene_id": "scene_lit_room",
            "scene_summary": "A lamp flickers in a quiet room.",
            "location_label": "Quiet room",
            "mood": "tense",
            "generation_mode": "fresh",
            "active_character_ids": ["char_hero"],
            "prompt": "cinematic room prompt",
        },
        {"characters": {"char_hero": {"label": "Hero"}}},
        {},
    )
    assert payload["scene"] == "Scene 2"
    assert payload["location"] == "Quiet room"
    assert payload["characters"] == "Hero"
    assert "lamp flickers" in payload["beat"]


def test_job_control_cancellation_deadline() -> None:
    job_control = _require_module("addons.audio_story_mode.job_control")
    token = job_control.CancellationToken()
    assert not token.cancelled
    token.cancel("timeout")
    assert token.cancelled
    assert token.reason == "timeout"
    deadline = job_control.JobDeadline(timeout_seconds=0.01)
    assert deadline.remaining_seconds(default=1.0) <= 1.0


def test_audio_story_tutorial_uses_professional_release_language() -> None:
    tutorial_path = ROOT / "tutorials" / "audio_story_mode.json"
    data = json.loads(tutorial_path.read_text(encoding="utf-8"))
    text = json.dumps(data, ensure_ascii=False).lower()
    banned = (
        "daddy",
        "offending your eyeballs",
        "questionable imagination",
        "bathroom nightmare",
        "zombie fiasco",
        "confident nonsense",
    )
    for phrase in banned:
        assert phrase not in text, f"release-hostile tutorial phrase remains: {phrase}"


def main() -> int:
    tests = [
        test_session_schema_round_trips_story_state,
        test_story_session_helper_builds_flat_payload,
        test_stream_security_requires_token_when_configured,
        test_scene_review_helper_summarizes_user_facing_scene,
        test_job_control_cancellation_deadline,
        test_audio_story_tutorial_uses_professional_release_language,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
