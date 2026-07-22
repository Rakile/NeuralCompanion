from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeManifest:
    id = "nc.buddy_chat"
    root_dir = ROOT / "addons" / "buddy_chat"


class _FakeStorage:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def addon_dir(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    def resolve(self, relative_path: str = "") -> Path:
        return (self.addon_dir / str(relative_path or "")).resolve()

    def read_json(self, relative_path: str) -> Any:
        return json.loads(self.resolve(relative_path).read_text(encoding="utf-8"))

    def write_json(self, relative_path: str, payload: Any) -> Path:
        target = self.resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target


class _FakeContext:
    def __init__(self, storage_root: Path, app_root: Path | None = None) -> None:
        self.manifest = _FakeManifest()
        self.app_root = app_root or ROOT
        self.storage = _FakeStorage(storage_root)
        self.logger = None
        self._services: dict[str, Any] = {}

    def get_service(self, name: str, default: Any = None) -> Any:
        return self._services.get(name, default)


def _new_controller(completion_handler):
    from addons.buddy_chat.controller import BuddyChatController

    temp_root = Path(tempfile.mkdtemp(prefix="nc-buddy-chat-"))
    controller = BuddyChatController(_FakeContext(temp_root, app_root=temp_root), completion_handler=completion_handler)
    return controller


def test_buddy_chat_side_tab_icon_is_registered() -> None:
    addon_dir = ROOT / "addons" / "buddy_chat"
    expected_icon_path = "../../ui_icons/side_tabs/budy_chat.png"
    manifest = json.loads((addon_dir / "addon.json").read_text(encoding="utf-8"))

    assert manifest["ui"][0].get("icon_path") == expected_icon_path
    assert (addon_dir / expected_icon_path).resolve().is_file()

    main_tree = ast.parse((addon_dir / "main.py").read_text(encoding="utf-8"))
    register_calls = [
        node
        for node in ast.walk(main_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_tab"
    ]
    assert len(register_calls) == 1
    icon_keywords = [keyword for keyword in register_calls[0].keywords if keyword.arg == "icon_path"]
    assert len(icon_keywords) == 1
    assert ast.literal_eval(icon_keywords[0].value) == expected_icon_path


def test_per_persona_lmstudio_lan_provider_does_not_mutate_global_settings() -> None:
    from addons.buddy_chat.llm_runtime import BuddyProviderRuntime, ProviderCallConfig
    from addons.buddy_chat.models import BuddyPersona, BuddySettings, ProviderOverride
    from core import chat_providers

    original_settings = chat_providers.get_provider_settings()
    chat_providers.set_provider_settings({"lmstudio": {"base_url": "http://127.0.0.1:1234/v1"}})
    calls: list[ProviderCallConfig] = []

    def _complete(config: ProviderCallConfig, _params: dict[str, Any], _additional: dict[str, Any]) -> str:
        calls.append(config)
        return "[Mira]\nRemote answer."

    try:
        runtime = BuddyProviderRuntime(completion_handler=_complete)
        settings = BuddySettings(llm_mode="per_persona")
        persona = BuddyPersona(
            id="mira",
            display_name="Mira",
            provider=ProviderOverride(
                provider_id="lmstudio",
                model="remote-model",
                base_url="http://192.168.2.46:1234/v1",
            ),
        )

        text = runtime.complete_for_persona(
            persona=persona,
            settings=settings,
            messages=[{"role": "user", "content": "hello"}],
            fallback_model="local-model",
        )

        assert "Remote answer" in text
        assert calls
        assert calls[0].provider_id == "lmstudio"
        assert calls[0].model == "remote-model"
        assert calls[0].base_url == "http://192.168.2.46:1234/v1"
        assert chat_providers.get_provider_setting("lmstudio", "base_url") == "http://127.0.0.1:1234/v1"
    finally:
        chat_providers.set_provider_settings(original_settings)


def test_buddy_chat_handles_a_turn_with_only_the_selected_persona() -> None:
    from addons.buddy_chat.models import BuddyPersona, ProviderOverride

    calls: list[str] = []

    def _complete(config, _params: dict[str, Any], _additional: dict[str, Any]) -> str:
        calls.append(config.persona_id)
        return f"[{config.persona_name}]\nI can take this one."

    controller = _new_controller(_complete)
    controller.settings.enabled = True
    controller.settings.reply_mode = "main_answer"
    controller.settings.llm_mode = "per_persona"
    controller.settings.max_speakers = 2
    controller.settings.personas = [
        BuddyPersona(id="alex", display_name="Alex", description="steady practical friend"),
        BuddyPersona(
            id="mira",
            display_name="Mira",
            description="warm observant friend",
            provider=ProviderOverride(provider_id="lmstudio", model="remote-model", base_url="http://192.168.2.46:1234/v1"),
        ),
    ]

    result = controller.invoke_capability("chat.user_text_command", {"text": "Mira, what do you think?"})

    assert isinstance(result, dict)
    assert result["handled"] is True
    assert result["response_text"].startswith("[Mira]")
    assert result["prefer_low_latency_tts"] is True
    assert calls == ["mira"]
    assert result["debug"]["memory_store"] == "engine.finalize_assistant_reply"


def test_buddy_settings_roundtrip_forced_buddy_cadence() -> None:
    from addons.buddy_chat.models import BuddySettings

    settings = BuddySettings.from_dict(
        {
            "forced_buddy_every": 3,
            "completed_reply_count": 7,
            "personas": [{"id": "mira", "display_name": "Mira"}],
        }
    )

    payload = settings.to_dict()

    assert payload["forced_buddy_every"] == 3
    assert payload["completed_reply_count"] == 7


def test_context_mode_forces_buddy_on_configured_reply_interval() -> None:
    from addons.buddy_chat.models import BuddyPersona

    calls: list[str] = []

    def _complete(config, _params: dict[str, Any], _additional: dict[str, Any]) -> str:
        calls.append(config.persona_id)
        return "This reply is definitely from the selected buddy."

    controller = _new_controller(_complete)
    controller.settings.enabled = True
    controller.settings.reply_mode = "context_only"
    controller.settings.instructor_structured_outputs_enabled = False
    controller.settings.forced_buddy_every = 3
    controller.settings.completed_reply_count = 2
    controller.settings.personas = [BuddyPersona(id="mira", display_name="Mira")]

    result = controller.invoke_capability("chat.user_text_command", {"text": "What is on the screen?"})

    assert isinstance(result, dict)
    assert result["handled"] is True
    assert result["response_text"].startswith("[Mira]")
    assert result["debug"]["forced_buddy"] is True
    assert calls == ["mira"]


def test_contextual_reply_forces_due_buddy_with_addon_context() -> None:
    from addons.buddy_chat.models import BuddyPersona

    calls: list[dict[str, Any]] = []

    def _complete(config, params: dict[str, Any], _additional: dict[str, Any]) -> str:
        calls.append({"persona_id": config.persona_id, "messages": list(params.get("messages") or [])})
        return "That track fits what you selected on screen."

    controller = _new_controller(_complete)
    controller.settings.enabled = True
    controller.settings.reply_mode = "context_only"
    controller.settings.instructor_structured_outputs_enabled = False
    controller.settings.forced_buddy_every = 3
    controller.settings.completed_reply_count = 2
    controller.settings.personas = [BuddyPersona(id="mira", display_name="Mira")]

    result = controller.invoke_capability(
        "buddy_chat.contextual_reply",
        {
            "text": "Comment naturally on the selected screen area.",
            "source": "companion_orb",
            "context": "Selected text: a release checklist. Spotify: Night Drive by Example Artist.",
        },
    )

    assert isinstance(result, dict)
    assert result["handled"] is True
    assert result["response_text"].startswith("[Mira]")
    assert result["debug"]["forced_buddy"] is True
    assert result["debug"]["contextual_source"] == "companion_orb"
    assert calls[0]["persona_id"] == "mira"
    assert "Night Drive" in calls[0]["messages"][0]["content"]


def test_contextual_reply_keeps_assistant_when_cadence_is_not_due() -> None:
    controller = _new_controller(lambda *_args: "unexpected")
    controller.settings.enabled = True
    controller.settings.reply_mode = "context_only"
    controller.settings.forced_buddy_every = 3
    controller.settings.completed_reply_count = 1

    result = controller.invoke_capability(
        "buddy_chat.contextual_reply",
        {"text": "React to the current song.", "source": "spotify_sense"},
    )

    assert result is None


def test_assistant_reply_notification_advances_forced_buddy_cadence() -> None:
    controller = _new_controller(lambda *_args: "ok")
    controller.settings.enabled = True
    controller.settings.reply_mode = "context_only"
    controller.settings.forced_buddy_every = 3
    controller.settings.completed_reply_count = 0

    result = controller.invoke_capability("buddy_chat.assistant_reply", {"text": "Assistant answer."})

    assert result == {"recorded": True, "completed_reply_count": 1}
    assert controller.settings.completed_reply_count == 1


def test_stale_session_does_not_disable_newer_persisted_buddy_settings() -> None:
    controller = _new_controller(lambda *_args: "ok")
    controller.settings.enabled = True
    controller.settings.forced_buddy_every = 3
    controller.settings.settings_epoch = 1

    controller.import_session_state(
        {
            "buddy_chat": {
                "settings": {
                    "enabled": False,
                    "forced_buddy_every": 0,
                    "personas": [{"id": "mira", "display_name": "Mira"}],
                }
            }
        }
    )

    assert controller.settings.enabled is True
    assert controller.settings.forced_buddy_every == 3
    assert controller.settings.settings_epoch == 1


def test_forced_buddy_provider_error_keeps_buddy_voice_label() -> None:
    from addons.buddy_chat.models import BuddyPersona

    def _complete(*_args) -> str:
        raise RuntimeError("provider offline")

    controller = _new_controller(_complete)
    controller.settings.enabled = True
    controller.settings.reply_mode = "context_only"
    controller.settings.instructor_structured_outputs_enabled = False
    controller.settings.forced_buddy_every = 2
    controller.settings.completed_reply_count = 1
    controller.settings.personas = [BuddyPersona(id="mira", display_name="Mira")]

    result = controller.invoke_capability("chat.user_text_command", {"text": "Can you comment?"})

    assert isinstance(result, dict)
    assert result["handled"] is True
    assert result["response_text"].startswith("[Mira]")
    assert result["debug"]["forced_buddy"] is True
    assert "provider offline" in result["debug"]["errors"][0]
    status = controller.status_snapshot()
    assert "Mira: provider offline" in status["last_provider_error"]
    debug_path = Path(controller.context.app_root) / "runtime" / "addons" / "nc.buddy_chat" / "buddy_chat_debug.log"
    debug_record = json.loads(debug_path.read_text(encoding="utf-8").splitlines()[-1])
    assert debug_record["persona"] == "Mira"
    assert debug_record["message_roles"][-1] == "user"


def test_per_persona_inherit_uses_shared_buddy_provider_when_configured() -> None:
    from addons.buddy_chat.llm_runtime import BuddyProviderRuntime
    from addons.buddy_chat.models import BuddyPersona, BuddySettings, ProviderOverride

    runtime = BuddyProviderRuntime(completion_handler=lambda _config, _params, _additional: "ok")
    settings = BuddySettings(
        llm_mode="per_persona",
        buddy_provider=ProviderOverride(
            provider_id="lmstudio",
            model="shared-buddy-model",
            base_url="http://192.168.2.50:1234/v1",
        ),
    )
    persona = BuddyPersona(id="alex", display_name="Alex", provider=ProviderOverride(provider_id="inherit"))

    config = runtime.resolve_call_config(persona=persona, settings=settings, fallback_model="main-model")

    assert config.provider_id == "lmstudio"
    assert config.model == "shared-buddy-model"
    assert config.base_url == "http://192.168.2.50:1234/v1"


def test_voice_segments_split_buddy_speaker_labels() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile
    from addons.buddy_chat.voice_segments import split_buddy_voice_segments

    personas = [
        BuddyPersona(id="alex", display_name="Alex", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/alex.wav")),
        BuddyPersona(id="mira", display_name="Mira", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
    ]
    result = split_buddy_voice_segments(
        "[Mira]\nThat looks interesting.\n\n[Alex]\nGive it a second.",
        personas=personas,
    )

    assert result["suppress_original"] is True
    assert [segment["persona_id"] for segment in result["segments"]] == ["mira", "alex"]
    assert result["segments"][0]["voice_path"] == "Q:/voices/mira.wav"
    assert result["segments"][1]["voice_path"] == "Q:/voices/alex.wav"


def test_buddy_voice_router_yields_when_no_buddy_label_matches() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile

    controller = _new_controller(lambda *_args: "ok")
    controller.settings.enabled = True
    controller.settings.personas = [
        BuddyPersona(
            id="mira",
            display_name="Mira",
            voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav"),
        )
    ]

    result = controller.invoke_capability(
        "tts.voice_segments",
        {"text": "[NARRATOR] The inherited story voice should handle this."},
    )

    assert result is None


def test_voice_segments_split_inline_bracket_label_text() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile
    from addons.buddy_chat.voice_segments import split_buddy_voice_segments

    personas = [
        BuddyPersona(id="mira", display_name="Mira", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
        BuddyPersona(id="alex", display_name="Alex", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/alex.wav")),
    ]
    result = split_buddy_voice_segments(
        "[Mira] That looks useful.\n[Alex] Keep it simple.",
        personas=personas,
    )

    assert result["suppress_original"] is True
    assert [(segment["persona_id"], segment["text"], segment["voice_path"]) for segment in result["segments"]] == [
        ("mira", "That looks useful.", "Q:/voices/mira.wav"),
        ("alex", "Keep it simple.", "Q:/voices/alex.wav"),
    ]


def test_voice_segments_split_embedded_buddy_label_after_assistant_text() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile
    from addons.buddy_chat.voice_segments import split_buddy_voice_segments

    personas = [
        BuddyPersona(id="mira", display_name="Mira", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
    ]
    result = split_buddy_voice_segments(
        "[neutral] Main assistant observation. [laugh] Still the assistant. [Mira] Buddy response with a different voice.",
        personas=personas,
    )

    assert result["suppress_original"] is True
    assert [(segment["persona_id"], segment["text"], segment["voice_path"]) for segment in result["segments"]] == [
        ("", "[neutral] Main assistant observation. [laugh] Still the assistant.", ""),
        ("mira", "Buddy response with a different voice.", "Q:/voices/mira.wav"),
    ]


def test_buddy_chat_preserves_voice_labels_without_full_text_buffering() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile

    controller = _new_controller(lambda *_args: "ok")
    controller.settings.enabled = True
    controller.settings.personas = [
        BuddyPersona(id="mira", display_name="Mira", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
    ]

    result = controller.invoke_capability("tts.voice_segments.requires_full_text", {"streaming": True})

    assert isinstance(result, dict)
    assert result["requires_full_text"] is False
    assert result["preserve_voice_labels"] is True
    assert result["reason"] == "buddy_chat_streaming_voice_routing"


def test_disabled_buddy_chat_explicitly_declines_stream_voice_routing() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile

    controller = _new_controller(lambda *_args: "ok")
    controller.settings.enabled = False
    controller.settings.personas = [
        BuddyPersona(id="mira", display_name="Mira", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
    ]

    result = controller.invoke_capability_threadsafe(
        "tts.voice_segments.requires_full_text",
        {"streaming": True},
    )

    assert isinstance(result, dict)
    assert result["requires_full_text"] is False
    assert result["preserve_voice_labels"] is False
    assert result["reason"] == "buddy_chat_disabled"


def test_buddy_chat_exposes_enabled_voice_paths_for_tts_warmup() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile

    controller = _new_controller(lambda *_args: "ok")
    controller.settings.enabled = True
    controller.settings.personas = [
        BuddyPersona(id="mira", display_name="Mira", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
        BuddyPersona(id="alex", display_name="Alex", voice=VoiceProfile(enabled=False, sample_path="Q:/voices/alex.wav")),
    ]

    result = controller.invoke_capability_threadsafe("tts.voice_warmup_paths", {"tts_backend": "chatterbox"})

    assert result == {
        "addon": "nc.buddy_chat",
        "paths": ["Q:/voices/mira.wav"],
    }

    controller.settings.enabled = False
    assert controller.invoke_capability_threadsafe("tts.voice_warmup_paths", {"tts_backend": "chatterbox"}) is None


def test_streaming_voice_routing_carries_buddy_across_chunks_and_resets() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile

    controller = _new_controller(lambda *_args: "ok")
    controller.settings.enabled = True
    controller.settings.personas = [
        BuddyPersona(id="mira", display_name="Mira", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
    ]

    first = controller.invoke_capability_threadsafe(
        "tts.voice_segments",
        {
            "text": "[Mira] First streamed sentence.",
            "streaming": True,
            "stream_start": True,
            "stream_source_index": 0,
        },
    )
    second = controller.invoke_capability_threadsafe(
        "tts.voice_segments",
        {
            "text": "Second streamed sentence.",
            "streaming": True,
            "stream_start": False,
            "stream_source_index": 1,
        },
    )
    reset = controller.invoke_capability_threadsafe(
        "tts.voice_segments",
        {
            "text": "A new assistant-only reply.",
            "streaming": True,
            "stream_start": True,
            "stream_source_index": 0,
        },
    )

    assert first["segments"][0]["persona_id"] == "mira"
    assert first["segments"][0]["voice_path"] == "Q:/voices/mira.wav"
    assert second["segments"][0]["persona_id"] == "mira"
    assert second["segments"][0]["voice_path"] == "Q:/voices/mira.wav"
    assert reset is None


def test_buddy_chat_records_voice_routing_debug_queue_item() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile
    try:
        from core import debug_inspector
    except ImportError:
        return

    debug_inspector.clear_queue_history()
    controller = _new_controller(lambda *_args: "ok")
    controller.settings.enabled = True
    controller.settings.personas = [
        BuddyPersona(id="mira", display_name="Mira", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
        BuddyPersona(id="alex", display_name="Alex", voice=VoiceProfile(enabled=False, sample_path="")),
    ]

    result = controller.invoke_capability("tts.voice_segments", {"text": "[Mira] Heard.\n[Alex] No voice sample yet."})
    queues = debug_inspector.get_queue_snapshot(include_done=True, limit=10)
    voice_rows = [item for item in queues if item.get("kind") == "tts_voice_routing" and item.get("owner") == "nc.buddy_chat"]

    assert result["suppress_original"] is True
    assert voice_rows
    row = voice_rows[-1]
    assert row["state"] == "Done"
    assert row["label"] == "Buddy voice routing: 2 segment(s)"
    assert row["metadata"]["matched_personas"] == ["mira", "alex"]
    assert row["metadata"]["voice_paths"] == ["Q:/voices/mira.wav"]
    assert row["metadata"]["missing_voice_personas"] == ["alex"]


def test_voice_segments_split_narrative_buddy_dialogue_and_preserve_narrator() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile
    from addons.buddy_chat.voice_segments import split_buddy_voice_segments

    personas = [
        BuddyPersona(id="mira", display_name="Mira", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
        BuddyPersona(
            id="elara",
            display_name="Elara, The Apprentice Scholar",
            voice=VoiceProfile(enabled=True, sample_path="Q:/voices/elara.wav"),
        ),
    ]
    text = """
[clear throat] We are not in a story now, but the buddies can still answer.

Mira leans in slightly, voice low but clear:
*"So, where do we start?"*

Elara nods eagerly from her corner of the digital room:
*"Yes! What would you like to build today?"*

Your move.
"""

    result = split_buddy_voice_segments(text, personas=personas)

    assert result["suppress_original"] is True
    assert [segment.get("display_name", "") for segment in result["segments"]] == [
        "",
        "",
        "Mira",
        "",
        "Elara, The Apprentice Scholar",
        "",
    ]
    assert result["segments"][0]["text"].startswith("[clear throat]")
    assert "Mira leans in slightly" in result["segments"][1]["text"]
    assert result["segments"][2]["text"] == "So, where do we start?"
    assert result["segments"][2]["voice_path"] == "Q:/voices/mira.wav"
    assert result["segments"][4]["text"] == "Yes! What would you like to build today?"
    assert result["segments"][4]["voice_path"] == "Q:/voices/elara.wav"


def test_voice_segments_split_inline_narrative_quote_for_buddy_voice() -> None:
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile
    from addons.buddy_chat.voice_segments import split_buddy_voice_segments

    personas = [
        BuddyPersona(id="mira", display_name="Mira", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
        BuddyPersona(
            id="elara",
            display_name="Elara, The Apprentice Scholar",
            voice=VoiceProfile(enabled=True, sample_path="Q:/voices/elara.wav"),
        ),
    ]
    text = (
        "[sigh] Absolutely, Mira. We're standing right in the middle of it.\n\n"
        'Elara stirs beside you, her fingers twitching toward her holographic datapad. '
        '"The files suggest we are in Sector 7," she says, her voice carrying a mix of excitement and uncertainty. '
        '"My sensors are picking up residual energy signatures. Do we follow the trail?"\n\n'
        "[laugh] What do you say?"
    )

    result = split_buddy_voice_segments(text, personas=personas)

    assert result["suppress_original"] is True
    spoken = [(segment.get("display_name", ""), segment["text"], segment.get("voice_path", "")) for segment in result["segments"]]
    assert ("Elara, The Apprentice Scholar", "The files suggest we are in Sector 7,", "Q:/voices/elara.wav") in spoken
    assert (
        "Elara, The Apprentice Scholar",
        "My sensors are picking up residual energy signatures. Do we follow the trail?",
        "Q:/voices/elara.wav",
    ) in spoken
    assert spoken[0][0] == ""
    assert spoken[-1][0] == ""


def test_buddy_context_prompt_requests_voice_routable_labels() -> None:
    from addons.buddy_chat.models import BuddyPersona, BuddySettings
    from addons.buddy_chat.prompting import buddy_context_prompt

    settings = BuddySettings(
        enabled=True,
        reply_mode="context_only",
        personas=[BuddyPersona(id="mira", display_name="Mira")],
    )

    prompt = buddy_context_prompt(settings)

    assert "own line with [Name]" in prompt
    assert "Do not write buddy dialogue only as narration" in prompt


def test_buddy_context_prompt_can_override_main_persona_prompt() -> None:
    from addons.buddy_chat.models import BuddyPersona, BuddySettings
    from addons.buddy_chat.prompting import buddy_context_prompt

    settings = BuddySettings(
        enabled=True,
        reply_mode="context_only",
        system_override_enabled=True,
        system_override_prompt="CUSTOM BUDDY OVERRIDE: let buddies speak even if the main persona says solo answers.",
        personas=[BuddyPersona(id="mira", display_name="Mira")],
    )

    prompt = buddy_context_prompt(settings)

    assert "Buddy Chat main-chat override" in prompt
    assert "CUSTOM BUDDY OVERRIDE" in prompt
    assert "single-persona" in prompt
    assert "[Name]" in prompt


def test_buddy_context_prompt_can_disable_system_override() -> None:
    from addons.buddy_chat.models import BuddyPersona, BuddySettings
    from addons.buddy_chat.prompting import buddy_context_prompt

    settings = BuddySettings(
        enabled=True,
        reply_mode="context_only",
        system_override_enabled=False,
        system_override_prompt="SHOULD NOT APPEAR",
        personas=[BuddyPersona(id="mira", display_name="Mira")],
    )

    prompt = buddy_context_prompt(settings)

    assert "SHOULD NOT APPEAR" not in prompt
    assert "Active buddies:" in prompt


def test_buddy_settings_roundtrip_system_override() -> None:
    from addons.buddy_chat.models import BuddySettings

    settings = BuddySettings.from_dict(
        {
            "enabled": True,
            "system_override_enabled": False,
            "system_override_prompt": "Custom prompt text",
            "personas": [{"id": "mira", "display_name": "Mira"}],
        }
    )

    payload = settings.to_dict()

    assert payload["system_override_enabled"] is False
    assert payload["system_override_prompt"] == "Custom prompt text"


def test_buddy_settings_roundtrip_avatar_profile() -> None:
    from addons.buddy_chat.models import BuddySettings

    settings = BuddySettings.from_dict(
        {
            "enabled": True,
            "personas": [
                {
                    "id": "mira",
                    "display_name": "Mira",
                    "avatar": {
                        "prompt": "warm cinematic companion portrait",
                        "image_path": "Q:/avatars/mira.png",
                        "preset": "Cinematic Buddy Portrait",
                    },
                }
            ],
        }
    )

    payload = settings.to_dict()

    assert payload["personas"][0]["avatar"]["prompt"] == "warm cinematic companion portrait"
    assert payload["personas"][0]["avatar"]["image_path"] == "Q:/avatars/mira.png"
    assert payload["personas"][0]["avatar"]["preset"] == "Cinematic Buddy Portrait"


def test_buddy_persona_rows_include_avatar_controls() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    from addons.buddy_chat.controller import BuddyChatController

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = BuddyChatController(
        _FakeContext(Path(tempfile.mkdtemp(prefix="nc-buddy-chat-storage-"))),
        completion_handler=lambda *_args: "ok",
    )
    tab = controller.build_tab()
    try:
        row = controller._controls["persona_0"]
        assert "avatar_preset" in row
        assert "avatar_prompt" in row
        assert "avatar_generate" in row
        assert "avatar_image_path" in row
        assert row["avatar_prompt"].toPlainText().strip()
        assert row["avatar_preview"].width() >= 180
        assert row["avatar_preview"].height() >= 180
    finally:
        tab.deleteLater()
        app.processEvents()


def test_buddy_chat_uses_categorized_mprc_style_tabs() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    from addons.buddy_chat.controller import BuddyChatController

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = BuddyChatController(
        _FakeContext(Path(tempfile.mkdtemp(prefix="nc-buddy-chat-storage-"))),
        completion_handler=lambda *_args: "ok",
    )
    tab = controller.build_tab()
    try:
        stack = controller._controls.get("tab_stack")
        buttons = list(controller._controls.get("tab_buttons") or [])
        assert stack is not None
        assert [str(button.property("buddy_tab_title") or "") for button in buttons] == [
            "Overview",
            "Buddies",
            "Voices",
            "Avatars",
            "Providers",
            "Advanced",
        ]
        assert stack.currentIndex() == 0
        for key in (
            "enabled",
            "reply_mode",
            "llm_mode",
            "max_speakers",
            "instructor_structured_outputs",
            "active_persona_window_open",
            "status_label",
        ):
            assert key in controller._controls, key
    finally:
        tab.deleteLater()
        app.processEvents()


def test_generate_persona_avatar_uses_visual_reply_service() -> None:
    from addons.buddy_chat.controller import BuddyChatController

    class _VisualReply:
        def __init__(self, image_path: Path) -> None:
            self.image_path = image_path
            self.requests: list[dict[str, Any]] = []

        def request_generation(self, **kwargs: Any) -> dict[str, Any]:
            self.requests.append(dict(kwargs))
            return {
                "accepted": True,
                "image_path": str(self.image_path),
                "request_id": "buddy-avatar-test",
            }

    app_root = Path(tempfile.mkdtemp(prefix="nc-buddy-chat-app-"))
    image_path = app_root / "runtime" / "visual_reply" / "mira.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"PNG")
    context = _FakeContext(Path(tempfile.mkdtemp(prefix="nc-buddy-chat-storage-")), app_root=app_root)
    visual_reply = _VisualReply(image_path)
    context._services["qt.visual_reply"] = visual_reply
    controller = BuddyChatController(context, completion_handler=lambda *_args: "ok")
    controller.settings.personas[0].display_name = "Mira"
    controller.settings.personas[0].role = "warm observant buddy"
    controller.settings.personas[0].avatar.prompt = "expressive portrait of Mira"

    result = controller._request_persona_avatar_generation(0, auto_show=False)

    assert result["ok"] is True
    assert controller.settings.personas[0].avatar.image_path == str(image_path)
    assert visual_reply.requests
    request = visual_reply.requests[-1]
    assert request["prompt"] == "expressive portrait of Mira"
    assert request["caption"] == "Buddy avatar: Mira"
    assert request["source"] == "nc.buddy_chat.avatar"
    assert request["metadata"]["persona_id"] == "alex"
    assert request["metadata"]["purpose"] == "buddy_avatar"


def test_buddy_settings_roundtrip_active_persona_window_option() -> None:
    from addons.buddy_chat.models import BuddySettings

    settings = BuddySettings.from_dict(
        {
            "enabled": True,
            "active_persona_window_enabled": True,
            "active_persona_window_on_top": False,
            "personas": [{"id": "mira", "display_name": "Mira"}],
        }
    )

    payload = settings.to_dict()

    assert payload["active_persona_window_enabled"] is True
    assert payload["active_persona_window_on_top"] is False


def test_buddy_chat_session_state_uses_top_dictionary() -> None:
    from addons.buddy_chat.models import BuddySettings

    controller = _new_controller(lambda *_args: "ok")
    controller.settings.enabled = True
    exported = controller.export_session_state()

    assert "settings" not in exported
    assert exported["buddy_chat"]["settings"]["enabled"] is True

    controller.settings.enabled = False
    controller.import_session_state({"buddy_chat": {"settings": {"enabled": True, "personas": [{"id": "mira", "display_name": "Mira"}]}}})
    assert controller.settings.enabled is True
    assert controller.settings.personas[0].display_name == "Mira"

    controller.settings = BuddySettings.default()
    controller.import_session_state({"settings": {"enabled": True, "personas": [{"id": "alex", "display_name": "Alex"}]}})
    assert controller.settings.enabled is True
    assert controller.settings.personas[0].display_name == "Alex"


def test_buddy_session_export_and_real_ui_are_non_blocking_under_state_lock() -> None:
    controller = _new_controller(lambda *_args: "ok")
    controller.settings.enabled = False
    controller._save_settings()

    state_lock = getattr(controller, "_state_lock", None)
    dispatcher = getattr(controller, "invoke_capability_threadsafe", None)
    assert state_lock is not None, "Buddy Chat must own a state lock"
    assert callable(dispatcher), "Buddy Chat must expose a thread-safe capability dispatcher"

    entered = threading.Event()
    release = threading.Event()
    holder_errors: list[BaseException] = []

    def hold_and_mutate() -> None:
        try:
            with state_lock:
                controller.settings.enabled = True
                entered.set()
                if not release.wait(2.0):
                    raise TimeoutError("test did not release Buddy Chat state lock")
        except BaseException as exc:
            holder_errors.append(exc)

    holder = threading.Thread(target=hold_and_mutate, daemon=True)
    holder.start()
    assert entered.wait(1.0)

    try:
        started = time.perf_counter()
        real_ui_result = dispatcher("real_ui.sync_widget_names", {"kind": "combo"})
        real_ui_elapsed = time.perf_counter() - started

        started = time.perf_counter()
        cached_export = controller.export_session_state()
        export_elapsed = time.perf_counter() - started
    finally:
        release.set()
        holder.join(1.0)

    assert not holder.is_alive()
    assert not holder_errors
    assert real_ui_result is None
    assert real_ui_elapsed < 0.2
    assert export_elapsed < 0.2
    assert cached_export["buddy_chat"]["settings"]["enabled"] is False

    refreshed_export = controller.export_session_state()
    assert refreshed_export["buddy_chat"]["settings"]["enabled"] is True


def test_buddy_slow_provider_work_does_not_hold_state_lock() -> None:
    provider_started = threading.Event()
    provider_release = threading.Event()
    worker_errors: list[BaseException] = []
    worker_result: dict[str, Any] = {}

    def complete(_config, _params: dict[str, Any], _additional: dict[str, Any]) -> str:
        provider_started.set()
        if not provider_release.wait(2.0):
            raise TimeoutError("test did not release Buddy Chat provider")
        return "[Alex]\nProvider work completed."

    controller = _new_controller(complete)
    controller.settings.enabled = True
    controller.settings.reply_mode = "main_answer"
    controller.settings.instructor_structured_outputs_enabled = False
    controller.settings.personas = controller.settings.personas[:1]
    controller._current_conversation_history = lambda: []
    controller._external_contexts = lambda _history: []
    controller._current_model_name = lambda: "test-model"

    state_lock = getattr(controller, "_state_lock", None)
    dispatcher = getattr(controller, "invoke_capability_threadsafe", None)
    assert state_lock is not None, "Buddy Chat must own a state lock"
    assert callable(dispatcher), "Buddy Chat must expose a thread-safe capability dispatcher"

    def invoke_buddy() -> None:
        try:
            result = dispatcher("chat.user_text_command", {"text": "Alex, answer this."})
            if isinstance(result, dict):
                worker_result.update(result)
        except BaseException as exc:
            worker_errors.append(exc)

    worker = threading.Thread(target=invoke_buddy, daemon=True)
    worker.start()
    assert provider_started.wait(1.0)

    acquired = state_lock.acquire(blocking=False)
    if acquired:
        state_lock.release()

    provider_release.set()
    worker.join(2.0)

    assert acquired, "Slow Buddy provider work must run outside the state lock"
    assert not worker.is_alive()
    assert not worker_errors
    assert worker_result.get("handled") is True


def test_buddy_addon_routes_capabilities_through_threadsafe_dispatcher() -> None:
    from addons.buddy_chat.main import Addon

    calls: list[tuple[str, dict[str, Any]]] = []

    class _Controller:
        def invoke_capability_threadsafe(self, capability, payload=None):
            calls.append((str(capability or ""), dict(payload or {})))
            return {"path": "threadsafe"}

        def invoke_capability(self, _capability, _payload=None):
            raise AssertionError("Addon bypassed Buddy Chat thread-safe dispatcher")

    addon = Addon()
    addon.controller = _Controller()

    result = addon.invoke_capability("buddy_chat.status", {"source": "test"})

    assert result == {"path": "threadsafe"}
    assert calls == [("buddy_chat.status", {"source": "test"})]


def test_buddy_chat_active_persona_window_controls_exist() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    from addons.buddy_chat.controller import BuddyChatController

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = BuddyChatController(
        _FakeContext(Path(tempfile.mkdtemp(prefix="nc-buddy-chat-storage-"))),
        completion_handler=lambda *_args: "ok",
    )
    tab = controller.build_tab()
    try:
        assert "active_persona_window_enabled" in controller._controls
        assert "active_persona_window_on_top" in controller._controls
        assert "active_persona_window_open" in controller._controls
        assert controller._controls["active_persona_window_open"].text() == "Open Active Persona Window"
    finally:
        tab.deleteLater()
        app.processEvents()


def test_active_persona_window_updates_from_voice_segments() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    from addons.buddy_chat.controller import BuddyChatController
    from addons.buddy_chat.models import BuddyPersona, VoiceProfile

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = BuddyChatController(
        _FakeContext(Path(tempfile.mkdtemp(prefix="nc-buddy-chat-storage-"))),
        completion_handler=lambda *_args: "ok",
    )
    controller.settings.enabled = True
    controller.settings.active_persona_window_enabled = True
    controller.settings.personas = [
        BuddyPersona(id="mira", display_name="Mira", role="warm observer", voice=VoiceProfile(enabled=True, sample_path="Q:/voices/mira.wav")),
    ]
    tab = controller.build_tab()
    try:
        result = controller.invoke_capability("tts.voice_segments", {"text": "[Mira] I can see it now."})
        app.processEvents()

        assert result["suppress_original"] is True
        assert controller._active_persona_id == "mira"
        assert controller._active_persona_window is not None
        assert controller._active_persona_window.name_label.text() == "Mira"
        assert "I can see it now." in controller._active_persona_window.last_line.toPlainText()
    finally:
        if controller._active_persona_window is not None:
            controller._active_persona_window.close()
        tab.deleteLater()
        app.processEvents()


def test_chat_context_does_not_duplicate_when_buddy_owns_main_reply() -> None:
    def _complete(_config, _params: dict[str, Any], _additional: dict[str, Any]) -> str:
        return "[Alex]\nHandled."

    controller = _new_controller(_complete)
    controller.settings.enabled = True
    controller.settings.reply_mode = "main_answer"

    result = controller.invoke_capability("chat_context.collect", {"messages": []})

    assert result is None


def test_buddy_chat_does_not_swallow_music_playback_commands() -> None:
    def _complete(_config, _params: dict[str, Any], _additional: dict[str, Any]) -> str:
        return "[Alex]\nHandled."

    controller = _new_controller(_complete)
    controller.settings.enabled = True
    controller.settings.reply_mode = "main_answer"

    result = controller.invoke_capability("chat.user_text_command", {"text": "play ambient electronic"})

    assert result is None


def test_load_mprc_personas_refreshes_visible_rows() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    from addons.buddy_chat.controller import BuddyChatController

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app_root = Path(tempfile.mkdtemp(prefix="nc-buddy-chat-app-"))
    storage_root = Path(tempfile.mkdtemp(prefix="nc-buddy-chat-storage-"))
    personas_path = app_root / "runtime" / "addons" / "nc.multi_persona_roleplay" / "personas.json"
    personas_path.parent.mkdir(parents=True, exist_ok=True)
    personas_path.write_text(
        json.dumps(
            [
                {
                    "id": "sage",
                    "display_name": "Sage",
                    "role": "quiet lore buddy",
                    "speaking_style": "low, precise",
                }
            ]
        ),
        encoding="utf-8",
    )
    controller = BuddyChatController(_FakeContext(storage_root, app_root=app_root), completion_handler=lambda *_args: "ok")
    tab = controller.build_tab()
    try:
        controller._load_mprc_personas_to_ui()
        assert any(persona.id == "sage" for persona in controller.settings.personas)
        assert "persona_2" in controller._controls
        assert controller._controls["persona_2"]["name"].text() == "Sage"
    finally:
        tab.deleteLater()
        app.processEvents()


def test_voice_browse_button_selects_from_root_voices_folder() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    from addons.buddy_chat.controller import BuddyChatController

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app_root = Path(tempfile.mkdtemp(prefix="nc-buddy-chat-app-"))
    voices_dir = app_root / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    sample_path = voices_dir / "mira.wav"
    sample_path.write_bytes(b"RIFF0000WAVE")

    class _TestController(BuddyChatController):
        def _open_voice_sample_file(self, start_dir: Path) -> str:  # type: ignore[override]
            assert start_dir == voices_dir
            return str(sample_path)

    controller = _TestController(_FakeContext(Path(tempfile.mkdtemp(prefix="nc-buddy-chat-storage-")), app_root=app_root), completion_handler=lambda *_args: "ok")
    tab = controller.build_tab()
    try:
        row = controller._controls["persona_0"]
        assert "voice_browse" in row
        controller._browse_voice_sample_for_persona(0)
        assert row["voice_path"].text() == str(sample_path)
        assert row["voice_enabled"].isChecked() is True
    finally:
        tab.deleteLater()
        app.processEvents()


def test_remove_buddy_deletes_persona_and_refreshes_rows() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    from addons.buddy_chat.controller import BuddyChatController

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = BuddyChatController(
        _FakeContext(Path(tempfile.mkdtemp(prefix="nc-buddy-chat-storage-"))),
        completion_handler=lambda *_args: "ok",
    )
    tab = controller.build_tab()
    try:
        assert [persona.display_name for persona in controller.settings.personas] == ["Alex", "Mira"]
        row = controller._controls["persona_1"]
        assert "remove_buddy" in row

        controller._remove_persona_from_ui(1)

        assert [persona.display_name for persona in controller.settings.personas] == ["Alex"]
        assert "persona_0" in controller._controls
        assert "persona_1" not in controller._controls
        assert controller._controls["persona_0"]["name"].text() == "Alex"
    finally:
        tab.deleteLater()
        app.processEvents()


def test_lmstudio_model_catalog_uses_specific_base_url() -> None:
    from addons.buddy_chat.llm_runtime import list_lmstudio_models_for_base_url

    calls: list[str] = []

    def _fetch_json(url: str, _api_key: str, _timeout: float) -> dict[str, Any]:
        calls.append(url)
        return {
            "models": [
                {"key": "remote-story-model", "type": "llm"},
                {"key": "embedding-model", "type": "embedding"},
            ]
        }

    models = list_lmstudio_models_for_base_url("http://192.168.2.46:1234/v1", fetch_json=_fetch_json)

    assert calls == ["http://192.168.2.46:1234/api/v1/models"]
    assert models == ["remote-story-model"]


def test_persona_prompt_starts_history_with_user_and_repairs_invalid_text() -> None:
    from addons.buddy_chat.models import BuddyPersona, BuddySettings
    from addons.buddy_chat.prompting import build_persona_messages

    messages = build_persona_messages(
        persona=BuddyPersona(id="mira", display_name="Mira"),
        settings=BuddySettings(personas=[BuddyPersona(id="mira", display_name="Mira")]),
        user_text="Comment on this image.",
        history=[
            {"role": "assistant", "content": "An orphaned assistant reply."},
            {"role": "assistant", "content": "Broken replacement: \ufffd"},
            {"role": "user", "content": "Here is the context."},
            {"role": "assistant", "content": "Now the history is valid."},
        ],
    )

    conversational = [message for message in messages if message["role"] != "system"]
    assert conversational[0]["role"] == "user"
    assert conversational[-1] == {"role": "user", "content": "Comment on this image."}
    assert all("\ufffd" not in message["content"] for message in messages)


def run_all() -> None:
    test_buddy_chat_side_tab_icon_is_registered()
    test_per_persona_lmstudio_lan_provider_does_not_mutate_global_settings()
    test_buddy_chat_handles_a_turn_with_only_the_selected_persona()
    test_buddy_settings_roundtrip_forced_buddy_cadence()
    test_context_mode_forces_buddy_on_configured_reply_interval()
    test_contextual_reply_forces_due_buddy_with_addon_context()
    test_contextual_reply_keeps_assistant_when_cadence_is_not_due()
    test_assistant_reply_notification_advances_forced_buddy_cadence()
    test_stale_session_does_not_disable_newer_persisted_buddy_settings()
    test_forced_buddy_provider_error_keeps_buddy_voice_label()
    test_per_persona_inherit_uses_shared_buddy_provider_when_configured()
    test_voice_segments_split_buddy_speaker_labels()
    test_buddy_voice_router_yields_when_no_buddy_label_matches()
    test_voice_segments_split_inline_bracket_label_text()
    test_voice_segments_split_embedded_buddy_label_after_assistant_text()
    test_buddy_chat_preserves_voice_labels_without_full_text_buffering()
    test_disabled_buddy_chat_explicitly_declines_stream_voice_routing()
    test_buddy_chat_exposes_enabled_voice_paths_for_tts_warmup()
    test_streaming_voice_routing_carries_buddy_across_chunks_and_resets()
    test_buddy_chat_records_voice_routing_debug_queue_item()
    test_voice_segments_split_narrative_buddy_dialogue_and_preserve_narrator()
    test_voice_segments_split_inline_narrative_quote_for_buddy_voice()
    test_buddy_context_prompt_requests_voice_routable_labels()
    test_buddy_context_prompt_can_override_main_persona_prompt()
    test_buddy_context_prompt_can_disable_system_override()
    test_buddy_settings_roundtrip_system_override()
    test_buddy_settings_roundtrip_avatar_profile()
    test_buddy_persona_rows_include_avatar_controls()
    test_buddy_chat_uses_categorized_mprc_style_tabs()
    test_generate_persona_avatar_uses_visual_reply_service()
    test_buddy_settings_roundtrip_active_persona_window_option()
    test_buddy_chat_session_state_uses_top_dictionary()
    test_buddy_session_export_and_real_ui_are_non_blocking_under_state_lock()
    test_buddy_slow_provider_work_does_not_hold_state_lock()
    test_buddy_addon_routes_capabilities_through_threadsafe_dispatcher()
    test_buddy_chat_active_persona_window_controls_exist()
    test_active_persona_window_updates_from_voice_segments()
    test_chat_context_does_not_duplicate_when_buddy_owns_main_reply()
    test_buddy_chat_does_not_swallow_music_playback_commands()
    test_load_mprc_personas_refreshes_visible_rows()
    test_voice_browse_button_selects_from_root_voices_folder()
    test_remove_buddy_deletes_persona_and_refreshes_rows()
    test_lmstudio_model_catalog_uses_specific_base_url()
    test_persona_prompt_starts_history_with_user_and_repairs_invalid_text()


if __name__ == "__main__":
    run_all()
    print("smoke_buddy_chat: ok")
