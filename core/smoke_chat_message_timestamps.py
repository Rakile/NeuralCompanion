from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_chat_message_builder_can_include_or_omit_timestamps():
    from core import conversation_history

    turn = {"role": "user", "content": "Hello there", "created_at": 1783202400.0}
    image_turn = {"role": "user", "content": "", "attachment_image_path": "runtime/example.png", "created_at": 1783202400.0}

    plain = conversation_history.build_chat_message_from_turn(
        turn,
        data_url_for_local_image=lambda _path: "",
        include_timestamp=False,
    )
    stamped = conversation_history.build_chat_message_from_turn(
        turn,
        data_url_for_local_image=lambda _path: "",
        include_timestamp=True,
    )

    assert plain == {"role": "user", "content": "Hello there"}
    assert stamped["role"] == "user"
    assert "Hello there" in stamped["content"]
    assert stamped["content"].startswith("[")
    assert "created_at" not in stamped["content"]

    stamped_image = conversation_history.build_chat_message_from_turn(
        image_turn,
        data_url_for_local_image=lambda _path: "data:image/png;base64,AAAA",
        include_timestamp=True,
    )
    assert isinstance(stamped_image["content"], list)
    assert stamped_image["content"][0]["type"] == "text"
    assert stamped_image["content"][0]["text"].startswith("[")


def test_assistant_history_does_not_teach_models_to_repeat_timestamps():
    from core import conversation_history

    turn = {
        "role": "assistant",
        "content": "[2026-07-13 02:16:01] [2026-07-13 02:16:22] [neutral] Hello there",
        "created_at": 1783202400.0,
    }

    message = conversation_history.build_chat_message_from_turn(
        turn,
        data_url_for_local_image=lambda _path: "",
        include_timestamp=True,
    )

    assert message == {"role": "assistant", "content": "[neutral] Hello there"}


def test_repeated_generated_timestamp_prefixes_can_be_removed():
    from core import conversation_history

    assert conversation_history.strip_leading_turn_timestamps(
        "[2026-07-13 02:16:01] [2026-07-13 02:16:22] [neutral] Hello"
    ) == "[neutral] Hello"
    assert conversation_history.strip_leading_turn_timestamps(
        "The event happened at [2026-07-13 02:16:01]."
    ) == "The event happened at [2026-07-13 02:16:01]."


def test_legacy_conversation_content_migration_preserves_metadata_and_other_roles():
    from core import conversation_history

    history = [
        {
            "role": "user",
            "content": "[2026-07-13 02:15:43] Keep the user's timestamp",
            "created_at": 111.0,
        },
        {
            "role": "assistant",
            "content": "[2026-07-13 02:16:01] [2026-07-13 02:16:22] [neutral] Clean me",
            "created_at": 222.0,
            "visual_reply_prompt": "Preserve this prompt",
        },
        {
            "role": "assistant",
            "content": "The event happened at [2026-07-13 02:16:01].",
            "created_at": 333.0,
        },
    ]

    migration = getattr(conversation_history, "migrate_conversation_history_content", None)
    assert callable(migration), "legacy conversation content migration is missing"
    migrated, report = migration(
        history,
        source_version=0,
    )

    assert migrated[0] == history[0]
    assert migrated[1]["content"] == "[neutral] Clean me"
    assert migrated[1]["created_at"] == 222.0
    assert migrated[1]["visual_reply_prompt"] == "Preserve this prompt"
    assert migrated[2] == history[2]
    assert report == {
        "source_version": 0,
        "target_version": 1,
        "migrated": True,
        "cleaned_assistant_turns": 1,
    }
    assert history[1]["content"].startswith("[2026-07-13 02:16:01]")


def test_current_conversation_content_version_bypasses_cleanup():
    from core import conversation_history

    history = [{"role": "assistant", "content": "[2026-07-13 02:16:01] Keep as supplied"}]
    migration = getattr(conversation_history, "migrate_conversation_history_content", None)
    assert callable(migration), "conversation content version bypass is missing"
    migrated, report = migration(
        history,
        source_version=1,
    )

    assert migrated == history
    assert report["migrated"] is False
    assert report["cleaned_assistant_turns"] == 0


def test_engine_stamps_and_preserves_chat_turn_created_at():
    addons_module = types.ModuleType("addons")
    addons_module.__path__ = [str(ROOT / "addons")]
    sys.modules["addons"] = addons_module
    import addons.vam_avatar.config  # noqa: F401 - prime repo namespace for engine bootstrap imports

    import engine

    original_history = list(engine.conversation_history or [])
    try:
        engine.conversation_history[:] = []
        engine._append_chat_turn({"role": "user", "content": "Stamped"})
        assert isinstance(engine.conversation_history[0].get("created_at"), float)

        saved = engine.export_chat_session_state()
        assert isinstance(saved["conversation_history"][0].get("created_at"), float)
        assert saved["conversation_format_version"] == 1

        engine.replace_chat_conversation_history(
            [{"role": "assistant", "content": "Preserved", "created_at": 1234.5}],
            allow_pending_loaded_user=False,
        )
        assert engine.conversation_history[0]["created_at"] == 1234.5
    finally:
        engine.conversation_history[:] = original_history


def test_engine_removes_model_generated_timestamp_prefixes():
    import engine

    original_enabled = engine.RUNTIME_CONFIG.get("chat_message_timestamps_enabled", False)
    original_notify = engine._notify_addon_assistant_reply
    try:
        engine.RUNTIME_CONFIG["chat_message_timestamps_enabled"] = True
        engine._notify_addon_assistant_reply = lambda _text: None
        assert engine.finalize_assistant_reply(
            "[2026-07-13 02:16:01] [2026-07-13 02:16:22] [neutral] Hello"
        ) == "[neutral] Hello"
    finally:
        engine.RUNTIME_CONFIG["chat_message_timestamps_enabled"] = original_enabled
        engine._notify_addon_assistant_reply = original_notify


def test_engine_import_migrates_legacy_conversation_content():
    import engine

    original_history = list(engine.conversation_history or [])
    original_assistant_memory = engine.assistant_memory
    original_sensory_history = list(engine.sensory_hidden_history or [])
    original_generation = engine.chat_session_state_generation
    original_pending = engine.pending_loaded_input_turn
    original_reset = engine.reset_chat_runtime_state
    original_baseline = engine.set_long_term_memory_embedding_session_baseline
    original_set_memory_id = engine.set_continuity_memory_id
    original_prune = engine._prune_sensory_hidden_history
    try:
        engine.reset_chat_runtime_state = lambda: None
        engine.set_long_term_memory_embedding_session_baseline = lambda *_args, **_kwargs: None
        engine.set_continuity_memory_id = lambda memory_id: engine.RUNTIME_CONFIG.__setitem__(
            "continuity_memory_id", memory_id
        )
        engine._prune_sensory_hidden_history = lambda: None
        result = engine.import_chat_session_state(
            {
                "conversation_format_version": 0,
                "continuity_memory_id": "migration_test",
                "conversation_history": [
                    {
                        "role": "assistant",
                        "content": "[2026-07-13 02:16:01] [neutral] Imported",
                        "created_at": 1234.5,
                    }
                ],
            }
        )
        assert engine.conversation_history[0]["content"] == "[neutral] Imported"
        assert engine.conversation_history[0]["created_at"] == 1234.5
        assert result["conversation_content_migration"]["cleaned_assistant_turns"] == 1
    finally:
        engine.conversation_history[:] = original_history
        engine.assistant_memory = original_assistant_memory
        engine.sensory_hidden_history[:] = original_sensory_history
        engine.chat_session_state_generation = original_generation
        engine.pending_loaded_input_turn = original_pending
        engine.reset_chat_runtime_state = original_reset
        engine.set_long_term_memory_embedding_session_baseline = original_baseline
        engine.set_continuity_memory_id = original_set_memory_id
        engine._prune_sensory_hidden_history = original_prune


def test_chat_timestamp_ui_preference_wiring_exists():
    session = _read("ui/runtime/main_window_session.py")
    panel = _read("ui/runtime/backend_operational_panel.py")
    console = _read("ui/runtime/backend_console_chat.py")
    bindings = _read("ui/runtime/real_ui_bindings.py")
    mirrors = _read("ui/runtime/real_ui_sync_mirrors.py")
    real_ui = _read("main.ui")

    assert "chat_message_timestamps_enabled" in session
    assert "chat_timestamp_toggle_button" in panel
    assert "chat_timestamp_toggle_button" in real_ui
    assert "toggle_chat_message_timestamps" in console
    assert "chat_message_timestamps_enabled" in console
    assert "chat_timestamp_toggle_button" in bindings
    assert "chat_timestamp_toggle_button" in mirrors


if __name__ == "__main__":
    test_chat_message_builder_can_include_or_omit_timestamps()
    test_assistant_history_does_not_teach_models_to_repeat_timestamps()
    test_repeated_generated_timestamp_prefixes_can_be_removed()
    test_legacy_conversation_content_migration_preserves_metadata_and_other_roles()
    test_current_conversation_content_version_bypasses_cleanup()
    test_engine_stamps_and_preserves_chat_turn_created_at()
    test_engine_removes_model_generated_timestamp_prefixes()
    test_engine_import_migrates_legacy_conversation_content()
    test_chat_timestamp_ui_preference_wiring_exists()
    print("smoke_chat_message_timestamps: ok")
