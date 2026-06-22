from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _assert_contains(path: str, *needles: str) -> None:
    text = _read(path)
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise AssertionError(f"{path} missing expected UI text: {missing}")


def _assert_not_contains(path: str, *needles: str) -> None:
    text = _read(path)
    present = [needle for needle in needles if needle in text]
    if present:
        raise AssertionError(f"{path} still contains technical UI text: {present}")


def main() -> None:
    _assert_contains(
        "addons/multi_persona_roleplay/controller.py",
        '"Story Health"',
        '"Story Memory"',
        '"Story Sounds"',
        '"Story Images"',
        '"Troubleshooting"',
    )
    _assert_not_contains(
        "addons/multi_persona_roleplay/controller.py",
        '"Story Runtime Status"',
        '"Memory Browser / Editor"',
        '"AudioFX Library"',
        '"Prompt / Debug"',
    )

    _assert_contains(
        "addons/audio_story_mode/ui/audio_story_mode.ui",
        "1. Import Audio",
        "2. Transcribe",
        "3. Plan Scenes",
        "4. Generate Images",
        "5. Play / Cast",
        "Transcript detail",
        "Scene detail balance",
        "Maximum prompt length",
        "Planning provider",
        "Advanced xAI image options",
    )

    _assert_contains(
        "addons/companion_orb_overlay/controller.py",
        '"Background Awareness & Response"',
        '"What the orb noticed"',
        '"Orb personality rules"',
        '"Playful nudges"',
    )
    _assert_not_contains(
        "addons/companion_orb_overlay/controller.py",
        'self._checkbox("Harassment"',
        '"Harassment Timer"',
        '"PING payload"',
        '"PONG influence"',
        '"Supervisor Prompt Template"',
    )

    _assert_contains(
        "addons/spotify_sense/controller.py",
        '"Connect Spotify"',
        '"Playback Controls"',
        '"Music Commentary"',
        '"Lower Music While NC Speaks"',
        '"Story Soundtrack"',
        '"Advanced Debug"',
        '"Lower music while NC speaks"',
    )
    _assert_not_contains(
        "addons/spotify_sense/controller.py",
        '"Duck music while NC speaks"',
        '"Duck volume"',
        '"Duck fade down"',
        '"Duck fade up"',
    )

    _assert_contains(
        "addons/main_chat_remote/controller.py",
        '"1. Enable desktop bridge"',
        '"2. Start phone backend"',
        '"3. Pair phone"',
        '"4. Test chat, audio, and visuals"',
    )

    _assert_contains(
        "addons/musetalk_preprocess/ui/musetalk_preprocess.ui",
        "Face crop position",
        "Mouth mask style",
        "Faster avatar startup cache",
        "Advanced mask repair",
    )
    _assert_not_contains(
        "addons/musetalk_preprocess/ui/musetalk_preprocess.ui",
        "BBox Shift",
        "Parsing Mode",
        "Clear .npy Cache",
        "Create .npy startup cache",
    )

    _assert_contains(
        "addons/rag_context/ui/rag_context.ui",
        "Document Memory",
        "Use Document Memory during chat",
        "Search Behavior",
        "How many notes to use",
        "Match strength",
        "Build Search Memory",
    )
    _assert_contains(
        "addons/rag_context/addon.json",
        '"name": "Document Memory"',
        '"title": "Document Memory"',
    )

    _assert_contains(
        "ui/runtime/real_ui_layout.py",
        '"Provider setup"',
        "layout = QtWidgets.QHBoxLayout(card)",
        '"Connected"',
        '"Needs key"',
        '"Needs model"',
        '"Test provider"',
        '"Provider is ready."',
        '"chat_runtime_provider_setup_card"',
        '"visual_reply_runtime_provider_setup_card"',
        "def _runtime_section_group",
        '"visual_reply_runtime_image_settings_group"',
        '"visual_reply_runtime_credentials_group"',
        '"visual_reply_runtime_display_group"',
        '"Image Settings"',
        '"Provider Credentials"',
        '"Display Behavior"',
    )
    _assert_not_contains(
        "ui/runtime/real_ui_layout.py",
        '"stt_runtime_provider_setup_card"',
        '"tts_runtime_provider_setup_card"',
    )

    _assert_contains(
        "main.ui",
        "Natural replies",
        "Conversation memory",
        "Speech Timing",
        "Performance Check",
        "Run Performance Check",
        "Reset Speech Timing Defaults",
    )
    _assert_contains(
        "ui/runtime/real_ui_surfaces.py",
        "Long-term archive",
        "Semantic search",
        "Use semantic search for archive matches",
    )
    _assert_not_contains(
        "main.ui",
        "Conversation Flow",
        "Allow Proactive Replies",
        "Proactive delay (s)",
        "Context window (msgs)",
        "Stored history limit",
        "Overflow policy",
        "Dry Run profiles",
        "Arm Dry Run",
        "Stop Dry Run",
        "Dry Run idle.",
        "Reset Chunking Defaults",
    )

    _assert_contains(
        "addons/chat_session_player/addon.json",
        '"name": "Conversation Replay"',
        '"title": "Conversation Replay"',
    )
    _assert_contains(
        "addons/chat_session_player/ui/chat_session_player.ui",
        "Conversation Replay",
        "Replay Setup",
        "Replay Messages",
    )

    _assert_contains(
        "addons/hotkeys/controller.py",
        "Voice",
        "Chat",
        "Window",
        "Orb",
        "Story",
        "hotkey_category_tabs",
    )

    _assert_contains(
        "addons/ai_presence_mode/controller.py",
        "Presence Preset",
        "Advanced motion and audio",
        "Face Preset",
        "Advanced wireframe",
        "Run visualizer in its own venv",
    )

    _assert_contains(
        "ui/runtime/backend_workspace_addons.py",
        "ADDON_PURPOSE_GROUPS",
        "Core",
        "Voice",
        "Visual",
        "Story",
        "Phone",
        "Experimental",
    )

    print("Easy UI text smoke checks passed.")


if __name__ == "__main__":
    main()
