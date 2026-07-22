from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
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
        "audio_story_mode_selected_range_enabled": True,
        "audio_story_mode_tts_startup_buffer_seconds": 45,
        "audio_story_mode_tts_render_ahead_seconds": 180,
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


def test_session_schema_round_trips_ordered_audio_sources() -> None:
    flat = {
        "audio_story_mode_audio_path": "chapter1.wav",
        "audio_story_mode_audio_paths": ["chapter1.wav", "chapter2.wav"],
        "audio_story_mode_audio_sources": [
            {"path": "chapter1.wav", "duration_seconds": 10.0},
            {"path": "chapter2.wav", "duration_seconds": 12.0},
        ],
        "audio_story_mode_instructor_beats_enabled": True,
    }
    grouped = audio_story_mode_session_payload(flat)
    flattened = flatten_audio_story_mode_settings(grouped)
    assert flattened == flat

    legacy = {"audio_story_mode_audio_path": "legacy.wav"}
    assert flatten_audio_story_mode_settings(audio_story_mode_session_payload(legacy)) == legacy


def test_session_schema_round_trips_project_identity_additively() -> None:
    flat = {
        "audio_story_mode_project_id": "project-session-hint",
        "audio_story_mode_project_revision": 17,
    }
    grouped = audio_story_mode_session_payload(flat)
    assert grouped == {
        "audio_story_mode": {
            "project": {"project_id": "project-session-hint", "revision": 17}
        }
    }
    assert flatten_audio_story_mode_settings(grouped) == flat

    legacy_flat = {
        "audio_story_mode_audio_path": "chapter.wav",
        **flat,
    }
    before = copy.deepcopy(legacy_flat)
    assert flatten_audio_story_mode_settings(legacy_flat) == legacy_flat
    assert legacy_flat == before


def test_story_session_helper_copies_ordered_audio_sources() -> None:
    story_session = _require_module("addons.audio_story_mode.story_session")
    source_payload = [{"path": "chapter.wav", "duration_seconds": 3.5}]
    flat = story_session.build_story_state_flat_payload(
        audio_sources=source_payload,
        audio_duration_seconds=3.5,
    )
    source_payload[0]["path"] = "mutated.wav"
    assert flat["audio_story_mode_audio_sources"] == [
        {"path": "chapter.wav", "duration_seconds": 3.5}
    ]


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


def test_dynamic_controller_loader_registers_module_before_dataclasses_run() -> None:
    from addons.audio_story_mode import main as addon_main

    module_name = "nc_addon_audio_story_mode_controller"
    previous = sys.modules.pop(module_name, None)
    try:
        controller_cls = addon_main._load_controller_class()
        loaded = sys.modules.get(module_name)
        assert loaded is not None
        assert loaded.AudioStoryModeController is controller_cls
    finally:
        sys.modules.pop(module_name, None)
        if previous is not None:
            sys.modules[module_name] = previous


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


def test_audio_story_intro_shows_inline_construction_notice() -> None:
    ui_path = ROOT / "addons" / "audio_story_mode" / "ui" / "audio_story_mode.ui"
    ui_root = ET.parse(ui_path).getroot()
    intro = ui_root.find(".//widget[@name='audio_story_intro_label']")
    assert intro is not None

    text_node = intro.find("./property[@name='text']/string")
    assert text_node is not None
    label_text = text_node.text or ""
    introduction = (
        "Import a story or audiobook, turn it into scenes, generate matching images, "
        "then play or cast the result."
    )
    assert label_text.startswith(f"{introduction} <span")
    assert "color:#ff4d5a" in label_text
    assert "font-weight:700" in label_text
    assert "🚧 Under Construction (but working)</span>" in label_text

    text_format = intro.find("./property[@name='textFormat']/enum")
    assert text_format is not None
    assert text_format.text == "Qt::RichText"


def main() -> int:
    tests = [
        test_session_schema_round_trips_story_state,
        test_story_session_helper_builds_flat_payload,
        test_session_schema_round_trips_ordered_audio_sources,
        test_session_schema_round_trips_project_identity_additively,
        test_story_session_helper_copies_ordered_audio_sources,
        test_stream_security_requires_token_when_configured,
        test_scene_review_helper_summarizes_user_facing_scene,
        test_job_control_cancellation_deadline,
        test_dynamic_controller_loader_registers_module_before_dataclasses_run,
        test_audio_story_tutorial_uses_professional_release_language,
        test_audio_story_intro_shows_inline_construction_notice,
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
