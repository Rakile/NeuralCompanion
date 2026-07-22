from __future__ import annotations

from pathlib import Path
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
import zipfile
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController
from addons.multi_persona_roleplay.long_memory import RoleplayLongMemory
from addons.multi_persona_roleplay.audio_prompts import create_audio_prompt, infer_audio_type
from addons.multi_persona_roleplay import prompting
from addons.multi_persona_roleplay.models import (
    AR_DIALOGUE_DENSITY_MODES,
    AR_MODE,
    SESSION_MODES,
    SESSION_MODE_DESCRIPTIONS,
    VISUAL_MODES,
    PersonaConfig,
    RoleplaySessionState,
)
from addons.multi_persona_roleplay.roleplay_engine import RoleplayEngine
from addons.multi_persona_roleplay.storage import RoleplayStorage
from addons.multi_persona_roleplay.structured_output import STRUCTURED_STORY_SCHEMA_VERSION, build_structured_story_output_schema
from addons.multi_persona_roleplay.voice_routing import PersonaVoiceRouter


def _personas() -> list[PersonaConfig]:
    return [
        PersonaConfig.from_dict({"id": "mentor", "display_name": "Mentor", "role": "mentor"}),
        PersonaConfig.from_dict({"id": "friend", "display_name": "Friend", "role": "friend"}),
        PersonaConfig.from_dict({"id": "story_narrator", "display_name": "Story Narrator", "role": "narrator"}),
    ]


def run_smoke() -> None:
    assert AR_MODE in SESSION_MODES
    assert set(SESSION_MODES).issubset(set(SESSION_MODE_DESCRIPTIONS))
    assert AR_DIALOGUE_DENSITY_MODES == (
        "Cinematic narrator-led",
        "Balanced narrator + character dialogue",
        "Ensemble scene",
        "High-dialogue character drama",
    )
    _smoke_fresh_defaults_are_passive()
    personas = _personas()
    normal = RoleplaySessionState.from_dict({"enabled": True, "mode": "Narrator + characters"})
    normal_prompt = prompting.build_persona_system_prompt(personas[0], normal)
    assert "AlternativeReality mode is active" not in normal_prompt

    ar_session = RoleplaySessionState.from_dict(
        {
            "enabled": True,
            "mode": AR_MODE,
            "scene_title": "Lantern Door",
            "location": "Archive corridor",
            "objective": "Find what moved behind the sealed door.",
            "ar_dialogue_density": "Balanced narrator + character dialogue",
            "ar_state": {
                "current_scene": "A sealed door waits at the end of the archive corridor.",
                "location": "Archive corridor",
                "active_characters": ["mentor", "friend"],
                "tension_level": 4,
                "story_goal": "Find what moved behind the sealed door.",
                "recent_events": ["The user heard a knock from inside the door."],
            },
        }
    )
    assert prompting.is_alternative_reality_mode(ar_session)
    prompt = prompting.build_alternative_reality_prompt(personas, ar_session, latest_user_text="Continue")
    assert "[NARRATOR]" in prompt
    assert "[CHARACTER: Exact Persona Display Name]" in prompt
    assert "[AMBIENCE:" in prompt
    assert "[CHOICES]" in prompt
    assert "Do not make every persona respond every turn" in prompt
    assert "Progression rule" in prompt
    assert "The user asked to continue" in prompt
    assert "Story Narrator" in prompt
    _smoke_story_director_prompt_contract(personas, ar_session)
    _smoke_story_director_ongoing_play_context(personas, ar_session)
    _smoke_voice_routing(personas, ar_session)
    _smoke_story_only_persona_overrides(personas, ar_session)
    _smoke_current_character_view_mode(personas)
    _smoke_visual_reply(personas, ar_session)
    _smoke_manual_visual_requests_are_threaded(personas)
    _smoke_tts_character_image_does_not_auto_show(personas)
    _smoke_structured_output_request_scoping(personas)
    _smoke_structured_output_export_flow(personas)
    _smoke_structured_output_partial_recovery()
    _smoke_chat_choice_mode_finalizer(personas, ar_session)
    _smoke_remote_capabilities()
    _smoke_chromecast_stream_contract()
    _smoke_remote_backend_api()
    _smoke_remote_install_is_opt_in()
    _smoke_ar_scene_state_update(personas)
    _smoke_audio_prompts()
    _smoke_long_memory(personas, ar_session)
    _smoke_long_memory_database_and_databank(personas, ar_session)
    _smoke_remote_memory_snapshot(personas, ar_session)
    _smoke_assistant_reply_recording_scope()
    _smoke_master_story_creator_context_controls()
    _smoke_master_story_load_preserves_saved_memory_and_pauses()
    _smoke_master_story_persona_count_controls()
    _smoke_master_story_apply_is_clean_saved_and_complete()
    _smoke_master_story_cast_isolation_and_snapshot()
    _smoke_master_story_auto_voice_assignment()
    _smoke_master_story_apply_voice_and_avatar_prompt()
    _smoke_master_story_apply_dialog_builds()
    _smoke_master_story_persona_activation()
    _smoke_master_narrator_controls()
    _smoke_master_story_json_validation_and_sfw()
    _smoke_master_story_generation_provider_fallback()
    _smoke_story_library_export_package()
    _smoke_refine_rejects_structured_story_output()
    _smoke_voice_file_browse_uses_non_native_dialog()
    _smoke_persona_editor_identity_commit_is_quiet()
    _smoke_tab_text_inputs_commit_quietly()
    _smoke_chat_play_voice_volume()
    _smoke_chat_play_voice_focus_toolbar_layout()
    _smoke_chat_play_story_engine_cards()
    _smoke_spotify_story_music_integration()
    _smoke_output_playback_volume()
    _smoke_schema_migration()
    _smoke_tutorial_doc()


class _Storage:
    def __init__(self, root: Path):
        self.root = root

    def _read_json(self, relative_path: str, fallback):
        path = self.root / relative_path
        if not path.exists():
            return fallback
        import json

        return json.loads(path.read_text(encoding="utf-8"))

    def read_json(self, relative_path: str):
        return self._read_json(relative_path, {})

    def _write_json(self, relative_path: str, payload):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def write_json(self, relative_path: str, payload):
        self._write_json(relative_path, payload)

    def resolve(self, relative_path: str) -> Path:
        return self.root / relative_path


def _smoke_fresh_defaults_are_passive() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        context = SimpleNamespace(
            logger=None,
            manifest=SimpleNamespace(root_dir=str(Path(__file__).resolve().parent)),
            storage=_Storage(root),
        )
        storage = RoleplayStorage(context)
        storage.ensure_defaults()

        session = storage.load_session()
        settings = storage.load_settings()
        assert session.enabled is False
        assert session.mode != AR_MODE
        assert settings.get("show_current_character_visual") is False


def _smoke_story_director_prompt_contract(personas: list[PersonaConfig], session: RoleplaySessionState) -> None:
    from addons.multi_persona_roleplay import story_director

    rival = PersonaConfig.from_dict(
        {
            "id": "distant_rival",
            "display_name": "Distant Rival",
            "role": "off-screen rival",
            "description": "A rival mentioned in the story bible but not present in this scene.",
        }
    )
    cast = [*personas, rival]

    focused = story_director.build_story_director_prompt(
        cast,
        session,
        latest_user_text="Continue",
        narrator_persona_id="story_narrator",
        cast_mode=story_director.CAST_MODE_FOCUSED_SPEAKER,
    )
    ordered_sections = [
        "Story premise/state:",
        "Active cast:",
        "Speaker discipline:",
        "Story progression rules:",
        "Visual Reply beat rules:",
        "Multi-voice output contract:",
        "Continue/choice nudge:",
    ]
    positions = [focused.index(section) for section in ordered_sections]
    assert positions == sorted(positions)
    assert "Story Director cast mode: focused speaker" in focused
    assert "SillyTavern" not in focused
    assert "Mentor (mentor)" in focused
    assert "Friend (friend)" in focused
    assert "Story Narrator (story_narrator)" in focused
    assert "Distant Rival" not in focused
    assert "AR Cast Energy / Dialogue Density: Balanced narrator + character dialogue" in focused
    assert "Most story turns should include at least one character speaking when active characters are present." in focused
    assert "Do not keep all dialogue in narrator prose." in focused
    assert "Use [CHARACTER: Exact Name] for spoken lines." in focused
    assert "Narrator frames action; characters create tension, opinions, interruptions, emotion." in focused
    assert "Do not make every persona respond every turn" in focused
    assert "Split direct speech into [CHARACTER: Exact Name] blocks" in focused
    assert "Select one visible image beat" in focused
    assert "The player asked to continue" in focused

    joined = story_director.build_story_director_prompt(
        cast,
        session,
        latest_user_text="open the door",
        narrator_persona_id="story_narrator",
        cast_mode=story_director.CAST_MODE_JOINED_CAST,
    )
    assert "Story Director cast mode: joined cast" in joined
    assert "SillyTavern" not in joined
    assert "Distant Rival (distant_rival)" in joined

    high_dialogue_session = RoleplaySessionState.from_dict(
        {
            **session.to_dict(),
            "ar_dialogue_density": "High-dialogue character drama",
        }
    )
    high_dialogue = story_director.build_story_director_prompt(
        cast,
        high_dialogue_session,
        latest_user_text="keep going",
        narrator_persona_id="story_narrator",
        cast_mode=story_director.CAST_MODE_JOINED_CAST,
    )
    assert "AR Cast Energy / Dialogue Density: High-dialogue character drama" in high_dialogue
    assert high_dialogue_session.to_dict()["ar_dialogue_density"] == "High-dialogue character drama"

    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = personas
    probe.session = session
    probe.story_prompt_personas = lambda: personas
    probe._persona_looks_like_narrator = lambda persona: "narrator" in str(getattr(persona, "role", "")).lower()
    probe._mprc_chat_should_offer_choices = lambda: True
    structured_rules = probe._mprc_structured_output_prompt_rules()
    assert "Story Director segment discipline" in structured_rules
    assert "If two characters speak, use two character segments" in structured_rules

    beat = story_director.build_visual_beat_context(
        persona=personas[1],
        session=session,
        reason="assistant_reply",
        source_text=(
            "[NARRATOR]\nRain floods the archive floor as Friend lifts the lantern toward the broken sigil.\n"
            "[CHARACTER: Friend]\nI can see the hinge now.\n"
            "[CHOICES]\n1. Pull the hinge\n2. Step back"
        ),
    )
    assert beat["latest_visible_action"].startswith("Rain floods the archive floor")
    assert "I can see the hinge" not in beat["latest_visible_action"]
    assert "Pull the hinge" not in beat["latest_visible_action"]
    assert beat["visual_subject"] == "Friend"
    assert beat["location"] == "Archive corridor"

    lilith = PersonaConfig.from_dict(
        {
            "id": "lilith",
            "display_name": "Lilith",
            "role": "demon investigator",
        }
    )
    scene_beat = story_director.build_visual_beat_context(
        persona=personas[2],
        personas=[*personas, lilith],
        session=session,
        reason="assistant_reply",
        source_text=(
            "[NARRATOR]\nRain sweeps across the empty alley as Jack reaches the corner.\n"
            "[CHARACTER: Jack]\nShe went this way.\n"
            "[NARRATOR]\nThe streetlight flickers above Lilith as smoky residue curls around her boots. "
            "She does not retreat, but the air thickens with tension.\n"
            "[CHOICES]\n1. Approach Lilith\n2. Search the alley"
        ),
    )
    assert scene_beat["latest_visible_action"].startswith("The streetlight flickers above Lilith")
    assert "smoky residue curls around her boots" in scene_beat["latest_visible_action"]
    assert scene_beat["latest_visible_action"].endswith("air thickens with tension.")
    assert "Rain sweeps across" not in scene_beat["latest_visible_action"]
    assert "She went this way" not in scene_beat["latest_visible_action"]
    assert scene_beat["visual_subject_id"] == "lilith"
    assert scene_beat["visual_subject"] == "Lilith"

    atmosphere_beat = story_director.build_visual_beat_context(
        persona=personas[2],
        personas=personas,
        session=session,
        reason="assistant_reply",
        source_text="[NARRATOR]\nLightning splits the sky above the abandoned station.",
    )
    assert atmosphere_beat["visual_subject_id"] == ""
    assert atmosphere_beat["visual_subject"] == ""


def _smoke_story_director_ongoing_play_context(personas: list[PersonaConfig], session: RoleplaySessionState) -> None:
    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = list(personas)
    probe.session = session
    probe.settings = {"chat_structured_output_enabled": False, "chat_choice_mode": "choices"}
    probe._controls = {}
    probe._mprc_chat_history = [
        {"role": "assistant", "content": "[NARRATOR]\nThe archive door shivers under the lantern light."}
    ]
    probe.story_prompt_personas = lambda: list(personas)
    probe.available_story_audio_files = lambda: []
    probe.selected_narrator_persona_id = lambda: "story_narrator"
    probe.persona_by_id = lambda persona_id: next((persona for persona in personas if persona.id == persona_id), None)
    probe._persona_looks_like_narrator = lambda persona: str(getattr(persona, "id", "") or "") == "story_narrator"
    probe.set_debug_prompt = lambda text: setattr(probe, "_debug_prompt", str(text or ""))

    messages = probe._build_mprc_chat_turn_messages(intent="Act", player_text="lift the lantern")
    system_prompt = messages[0]["content"]
    assert "Story Director cast mode: joined cast" in system_prompt
    assert "AR Cast Energy / Dialogue Density: Balanced narrator + character dialogue" in system_prompt
    assert "SillyTavern" not in system_prompt
    assert "Visual Reply beat rules:" in system_prompt
    assert "Multi-voice output contract:" in system_prompt
    assert "MPRC compact turn state:" in system_prompt

    focused_session = RoleplaySessionState.from_dict(
        {
            **session.to_dict(),
            "ar_state": {
                **session.ar_state.to_dict(),
                "active_characters": ["mentor"],
            },
        }
    )
    focused_probe = object.__new__(MultiPersonaRoleplayController)
    focused_probe.personas = list(personas)
    focused_probe.session = focused_session
    focused_probe.settings = {"chat_structured_output_enabled": False, "chat_choice_mode": "choices"}
    focused_probe._controls = {}
    focused_probe._mprc_chat_history = list(probe._mprc_chat_history)
    focused_probe.story_prompt_personas = lambda: list(personas)
    focused_probe.available_story_audio_files = lambda: []
    focused_probe.selected_narrator_persona_id = lambda: "story_narrator"
    focused_probe.persona_by_id = lambda persona_id: next((persona for persona in personas if persona.id == persona_id), None)
    focused_probe._persona_looks_like_narrator = lambda persona: str(getattr(persona, "id", "") or "") == "story_narrator"
    focused_probe.set_debug_prompt = lambda text: setattr(focused_probe, "_debug_prompt", str(text or ""))
    focused_messages = focused_probe._build_mprc_chat_turn_messages(intent="Act", player_text="lift the lantern")
    assert "Story Director cast mode: focused speaker" in focused_messages[0]["content"]


def _smoke_remote_capabilities() -> None:
    controller = object.__new__(MultiPersonaRoleplayController)
    controller._state_lock = threading.RLock()
    controller._shutting_down = False
    calls = []

    controller.remote_snapshot = lambda: {"schema_version": 1, "session": {"enabled": True}}
    controller.remote_send_user_text = (
        lambda text, intent="Auto", speaker_id="": calls.append(("send", text, intent, speaker_id))
        or {"accepted": True, "text": text, "intent": intent, "speaker_id": speaker_id}
    )
    controller.remote_select_choice = (
        lambda choice: calls.append(("choice", choice)) or {"accepted": True, "choice": choice}
    )
    controller.remote_play = lambda: calls.append(("play",)) or {"accepted": True}
    controller.remote_pause = lambda: calls.append(("pause",)) or {"accepted": True}
    controller.remote_request_visual = lambda: calls.append(("visual",)) or {"accepted": True}
    controller.remote_chromecast_action = (
        lambda payload: calls.append(("cast", dict(payload or {})))
        or {"accepted": True, "cast": {"selected_device": str(dict(payload or {}).get("device_name") or "")}}
    )

    state = controller.invoke_capability_threadsafe("mprc.remote_state")
    assert state["session"]["enabled"] is True
    sent = controller.invoke_capability_threadsafe(
        "mprc.remote_send",
        {"text": "continue the scene", "intent": "Continue", "speaker_id": "mentor"},
    )
    assert sent["accepted"] is True
    assert calls[-1] == ("send", "continue the scene", "Continue", "mentor")
    choice = controller.invoke_capability_threadsafe("mprc.remote_choice", {"choice": "1"})
    assert choice["accepted"] is True
    assert calls[-1] == ("choice", "1")
    assert controller.invoke_capability_threadsafe("mprc.remote_play")["accepted"] is True
    assert calls[-1] == ("play",)
    assert controller.invoke_capability_threadsafe("mprc.remote_pause")["accepted"] is True
    assert calls[-1] == ("pause",)
    assert controller.invoke_capability_threadsafe("mprc.remote_visual")["accepted"] is True
    assert calls[-1] == ("visual",)
    cast = controller.invoke_capability_threadsafe(
        "mprc.remote_cast",
        {"action": "start", "device_name": "Living Room TV"},
    )
    assert cast["accepted"] is True
    assert calls[-1] == ("cast", {"action": "start", "device_name": "Living Room TV"})


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_smoke_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        frames = b"".join(struct.pack("<h", 0) for _index in range(1600))
        handle.writeframes(frames)


def _write_smoke_png(path: Path) -> None:
    path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
            "0000000c49444154789c6360f8cf0000020201005dfe2a270000000049454e44ae426082"
        )
    )


def _http_bytes(url: str, *, limit: int = 0) -> tuple[int, str, bytes]:
    with urllib.request.urlopen(url, timeout=5) as response:
        payload = response.read(limit if limit > 0 else -1)
        return int(response.status), str(response.headers.get("Content-Type") or ""), payload


def _smoke_chromecast_stream_contract() -> None:
    from addons.multi_persona_roleplay.chromecast_bridge import MprcCastStreamServer
    from addons.visual_reply import state as visual_reply_state

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image_path = root / "visual.png"
        audio_path = root / "speech.wav"
        _write_smoke_png(image_path)
        _write_smoke_wav(audio_path)

        class FakeController:
            def remote_speech_audio_snapshot(self):
                return {
                    "available": True,
                    "status": "ready",
                    "generation": 7,
                    "items": [
                        {
                            "id": "speech_1",
                            "url_path": "/api/speech-audio/file/speech_1",
                            "speaker": "Mentor",
                            "text": "The lantern hums.",
                            "duration_seconds": 0.1,
                        }
                    ],
                }

            def remote_speech_audio_file_path(self, audio_id: str) -> Path:
                if audio_id != "speech_1":
                    raise FileNotFoundError(audio_id)
                return audio_path

        previous_visual = dict(getattr(visual_reply_state, "current_visual_reply_data", {}) or {})
        server = MprcCastStreamServer(FakeController(), port=_free_local_port())
        try:
            visual_reply_state.current_visual_reply_data = {
                "image_path": str(image_path),
                "caption": "A bright lantern in the archive.",
            }
            base_url = server.start().rstrip("/")
            status, content_type, state_payload = _http_bytes(f"{base_url}/state.json")
            assert status == 200
            assert "application/json" in content_type
            state = json.loads(state_payload.decode("utf-8"))
            assert state["ready"] is True
            assert state["caption"] == "A bright lantern in the archive."
            assert state["audio_generation"] == 7
            assert state["audio_items"][0]["url_path"] == "/audio/file/speech_1"

            status, content_type, image_payload = _http_bytes(f"{base_url}/current.jpg?fit=cast&w=64&h=64", limit=16)
            assert status == 200
            assert content_type.startswith("image/jpeg")
            assert image_payload.startswith(b"\xff\xd8")

            status, content_type, audio_payload = _http_bytes(f"{base_url}/audio/file/speech_1", limit=16)
            assert status == 200
            assert content_type.startswith("audio/")
            assert audio_payload.startswith(b"RIFF")
        finally:
            server.stop()
            visual_reply_state.current_visual_reply_data = previous_visual


class _AddonStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def resolve(self, relative_path: str):
        return self.root / relative_path

    def read_json(self, relative_path: str):
        return json.loads((self.root / relative_path).read_text(encoding="utf-8"))

    def write_json(self, relative_path: str, payload):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class _PeerServices:
    def __init__(self, services: dict[str, object] | None = None):
        self._services = dict(services or {})

    def get(self, service_name: str, default=None):
        return self._services.get(str(service_name or ""), default)


class _AddonContext:
    def __init__(self, root: Path, services: dict[str, object] | None = None):
        self.logger = None
        self.storage = _AddonStorage(root)
        self.services = _PeerServices(services)
        self.manifest = SimpleNamespace(
            root_dir=str(Path(__file__).resolve().parent),
            version="smoke",
        )

    def get_service(self, _name: str):
        return None


def _new_controller(root: Path, *, services: dict[str, object] | None = None) -> MultiPersonaRoleplayController:
    return MultiPersonaRoleplayController(_AddonContext(root, services=services))


def _smoke_long_memory(personas: list[PersonaConfig], session: RoleplaySessionState) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        memory = RoleplayLongMemory(_Storage(Path(tmp)))
        memory.record_turn(
            session=session,
            personas=personas,
            user_text="I open the lantern door slowly.",
            assistant_text="[NARRATOR] The old lantern door opens onto a corridor of blue dust.",
        )
        context = memory.prompt_context(
            session=session,
            personas=personas,
            query="lantern door corridor",
            limit=4,
        )
        assert "Long-term roleplay memory" in context
        assert "lantern door" in context.lower()
        payload = memory.load()
        payload["pinned_facts"] = ["The lantern key belongs to the archive door."]
        memory.save(payload)
        pinned_context = memory.prompt_context(session=session, personas=personas, query="key", limit=2)
        assert "Pinned story facts" in pinned_context
        assert "lantern key" in pinned_context


def _smoke_long_memory_database_and_databank(personas: list[PersonaConfig], session: RoleplaySessionState) -> None:
    from addons.multi_persona_roleplay.databank import StoryDataBank
    from addons.multi_persona_roleplay.memory_database import SQLiteMemoryDatabase, open_memory_database
    from addons.multi_persona_roleplay.memory_embeddings import cosine_similarity, embed_text

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        storage = _Storage(root)
        memory = RoleplayLongMemory(storage)
        event = memory.record_turn(
            session=session,
            personas=personas,
            user_text="I follow the silver lantern toward the Moon Garden.",
            assistant_text="[NARRATOR] The silver lantern opens a hidden Moon Garden behind the archive wall.",
        )
        memory.record_turn(
            session=session,
            personas=personas,
            user_text="I check the brass compass.",
            assistant_text="[NARRATOR] The compass needle trembles beside the archive stairs.",
        )
        for index in range(4):
            memory.record_turn(
                session=session,
                personas=personas,
                user_text=f"I count the stair marker {index}.",
                assistant_text=f"[NARRATOR] Stair marker {index} glows beside the archive stairs.",
            )

        db_path = root / "memory" / "long_memory.sqlite3"
        assert db_path.exists()
        db = SQLiteMemoryDatabase(db_path)
        found_events = db.search_events("silver lantern moon garden", limit=3)
        assert any(item.record_id == event["id"] for item in found_events)

        context = memory.prompt_context(session=session, personas=personas, query="lunar lamp courtyard", limit=4)
        assert "Long-term roleplay memory" in context
        assert "Retrieved story memory" in context
        assert "Moon Garden" in context

        opened = open_memory_database(storage, settings={"long_memory_database_backend": "sqlite"})
        assert isinstance(opened, SQLiteMemoryDatabase)

        databank = StoryDataBank(db)
        chunks = databank.index_document(
            source="lore/moon_garden.md",
            title="Moon Garden Lore",
            text="The Moon Garden opens only when a silver lantern is carried through the archive wall.",
        )
        assert chunks
        databank_context = databank.prompt_context("archive wall silver lamp", max_chunks=2)
        assert "Story data bank" in databank_context
        assert "Moon Garden" in databank_context

        similar = cosine_similarity(embed_text("silver lantern garden"), embed_text("silver lamp garden"))
        unrelated = cosine_similarity(embed_text("silver lantern garden"), embed_text("engine piston"))
        assert similar > unrelated


def _smoke_remote_memory_snapshot(personas: list[PersonaConfig], session: RoleplaySessionState) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        storage = _Storage(root)
        memory = RoleplayLongMemory(storage)
        memory.record_turn(
            session=session,
            personas=personas,
            user_text="Remember the silver lantern.",
            assistant_text="[NARRATOR] The silver lantern is now a key story fact.",
        )
        payload = memory.load()
        payload["pinned_facts"] = ["The silver lantern opens the archive wall."]
        memory.save(payload)

        probe = object.__new__(MultiPersonaRoleplayController)
        probe.long_memory = memory
        probe.settings = {"long_memory_database_backend": "sqlite", "long_memory_databank_sources": ["story_notes.md"]}

        snapshot = probe.remote_memory_snapshot()
        assert snapshot["available"] is True
        assert snapshot["backend"] == "sqlite"
        assert snapshot["database_available"] is True
        assert snapshot["event_count"] >= 1
        assert snapshot["pinned_fact_count"] == 1
        assert snapshot["databank_available"] is True
        assert snapshot["configured_databank_source_count"] == 1
        assert str(root) not in json.dumps(snapshot)


def _smoke_audio_prompts() -> None:
    assert infer_audio_type("Dark forest with something hunting nearby") == "Ambience"
    forest = create_audio_prompt("Dark forest with something hunting nearby", "Auto")
    assert "dark fantasy forest ambience" in forest
    assert "distant creature movement" in forest
    assert "seamless loop" in forest

    battle = create_audio_prompt("Epic dragon battle", "Auto")
    assert "epic fantasy battle music" in battle
    assert "massive orchestral drums" in battle
    assert "no vocals" in battle

    portal = create_audio_prompt("Magic portal opening", "Auto")
    assert "magical portal activation sound effect" in portal
    assert "isolated cinematic sound" in portal

    horror = create_audio_prompt("peaceful fantasy tavern ambience", "Ambience", variant="horror")
    assert "darker horror tone" in horror


class _FakeVisualReply:
    def __init__(self):
        self.calls = []

    def request_generation(self, persona=None, reason: str = "manual", source_text: str = ""):
        self.calls.append((getattr(persona, "id", ""), reason, source_text))
        return {"accepted": True, "message": "ok"}


class _FakeVisualGenerationService:
    def __init__(self, provider: str = "runware"):
        self.provider = provider
        self.requests = []

    def settings_snapshot(self):
        return {"provider_value": self.provider, "model_name": "", "size_value": "1024x1024"}

    def request_generation(self, **kwargs):
        self.requests.append(dict(kwargs))
        return True


class _FakeController:
    def __init__(self, personas: list[PersonaConfig], session: RoleplaySessionState):
        self.personas = personas
        self.session = session
        self.visual_reply = _FakeVisualReply()
        self.visual_reply_service = None
        self.visual_styles = []
        self.context = type("Context", (), {"logger": None, "app_root": Path.cwd()})()
        self.settings = {"narrator_persona_id": "story_narrator"}
        self._story_audio_pending_text = ""
        self._story_audio_block_active = False
        self.auto_visual_requests = []

    def active_persona(self):
        return self.persona_by_id(self.session.active_persona_id) or self.personas[0]

    def current_speaker_persona(self):
        return self.persona_by_id(self.session.current_speaker_id) or self.active_persona()

    def selected_narrator_persona_id(self):
        return str(self.settings.get("narrator_persona_id") or "")

    def selected_narrator_persona(self):
        return self.persona_by_id(self.selected_narrator_persona_id())

    def story_prompt_personas(self):
        return list(self.personas)

    def request_auto_visual_reply(self, persona_id, reason, source_text="", **kwargs):
        self.auto_visual_requests.append(
            {
                "persona_id": str(persona_id or ""),
                "reason": str(reason or ""),
                "source_text": str(source_text or ""),
                **dict(kwargs),
            }
        )

    def _current_linked_persona_ids(self):
        return list(self.settings.get("master_story_linked_persona_ids") or [])

    def persona_by_id(self, persona_id: str):
        for persona in self.personas:
            if persona.id == persona_id:
                return persona
        return None

    def current_tts_backend(self):
        return "chatterbox"

    def strip_story_audio_for_tts(self, text: str, **kwargs):
        if kwargs.get("collect_cues"):
            return text, False, []
        return text, False

    def ensure_personas_from_assistant_text(self, *_args, **_kwargs):
        return None

    def _story_audio_cue_ids(self, *_args, **_kwargs):
        return []

    def save_state(self):
        return None


def _smoke_voice_routing(personas: list[PersonaConfig], session: RoleplaySessionState) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        voice_paths = {
            "story_narrator": root / "narrator.wav",
            "mentor": root / "mentor.wav",
            "friend": root / "friend.wav",
        }
        for path in voice_paths.values():
            path.write_bytes(b"RIFF0000WAVE")
        for persona in personas:
            if persona.id in voice_paths:
                persona.voice.enabled = True
                persona.voice.backend = "chatterbox"
                persona.voice.sample_path = str(voice_paths[persona.id])

        session.enabled = True
        session.mode = AR_MODE
        session.active_persona_id = "mentor"
        session.current_speaker_id = "mentor"
        controller = _FakeController(personas, session)
        controller.settings["mprc_voice_volume"] = 42
        router = PersonaVoiceRouter(controller)

        emoji_prefixed = router.split_text_by_persona(
            {
                "text": "🤖 Assistant: [NARRATOR]\nThe lantern trembles.",
                "tts_backend": "chatterbox",
            }
        )
        assert [item.get("persona_id") for item in emoji_prefixed.get("segments") or []] == ["story_narrator"]

        whole = router.split_text_by_persona(
            {
                "text": "[NARRATOR]\nThe lantern trembles.\n[CHARACTER: Friend]\nWe should move now.",
                "tts_backend": "chatterbox",
            }
        )
        whole_segments = whole.get("segments") or []
        assert [item.get("persona_id") for item in whole_segments] == ["story_narrator", "friend"]
        assert [Path(item.get("voice_path", "")).name for item in whole_segments] == ["narrator.wav", "friend.wav"]
        assert [item.get("voice_volume_percent") for item in whole_segments] == [42, 42]
        assert [item.get("voice_route", {}).get("volume_percent") for item in whole_segments] == [42, 42]
        assert [item.get("voice_route", {}).get("route_reason") for item in whole_segments] == [
            "text_speaker_label",
            "text_speaker_label",
        ]

        unquoted_it_dialogue = router.split_text_by_persona(
            {
                "text": (
                    "[CHARACTER: Friend]\n"
                    "It feels different from what I sensed before. Something old is waking up."
                ),
                "tts_backend": "chatterbox",
            }
        )
        unquoted_it_segments = unquoted_it_dialogue.get("segments") or []
        assert [item.get("persona_id") for item in unquoted_it_segments] == ["friend"]
        assert [Path(item.get("voice_path", "")).name for item in unquoted_it_segments] == ["friend.wav"]
        assert unquoted_it_segments[0].get("voice_route", {}).get("route_reason") == "text_speaker_label"

        mislabeled_action = router.split_text_by_persona(
            {
                "text": (
                    "[CHARACTER: Friend]\n"
                    "A low rumble vibrates through your chest, a sound like distant thunder. "
                    "Friend's massive form looms beside you, scanning the perimeter.\n\n"
                    "[CHARACTER: Friend]\n"
                    "She moves silently beside you, her hair flowing through the rain."
                ),
                "tts_backend": "chatterbox",
            }
        )
        mislabeled_segments = mislabeled_action.get("segments") or []
        assert [item.get("persona_id") for item in mislabeled_segments] == ["story_narrator", "story_narrator"]

        unresolved_after_character = router.split_text_by_persona(
            {
                "text": (
                    "[CHARACTER: Friend]\n"
                    "I know this passage.\n"
                    "[CHARACTER: Missing Character]\n"
                    "This line must not inherit Friend's voice."
                ),
                "tts_backend": "chatterbox",
            }
        )
        unresolved_segments = unresolved_after_character.get("segments") or []
        assert [item.get("persona_id") for item in unresolved_segments] == ["friend", "story_narrator"]

        narrated_dialogue = router.split_text_by_persona(
            {
                "text": (
                    "[NARRATOR]\n"
                    "The lantern trembles. \"We should move now,\" Friend says softly. "
                    "\"Before it wakes.\" She gestures toward the sealed door."
                ),
                "tts_backend": "chatterbox",
            }
        )
        narrated_segments = narrated_dialogue.get("segments") or []
        assert [item.get("persona_id") for item in narrated_segments] == [
            "story_narrator",
            "friend",
            "story_narrator",
            "friend",
            "story_narrator",
        ]
        assert [Path(item.get("voice_path", "")).name for item in narrated_segments] == [
            "narrator.wav",
            "friend.wav",
            "narrator.wav",
            "friend.wav",
            "narrator.wav",
        ]

        repeated_narrator_dialogue = router.split_text_by_persona(
            {
                "text": (
                    "[NARRATOR]\n"
                    "\"Ha! That'll sting the bastard's eyes,\" Mentor laughs, ready to pounce.\n\n"
                    "[NARRATOR]\n"
                    "\"Good one!\" Friend roars approvingly, shifting into position."
                ),
                "tts_backend": "chatterbox",
            }
        )
        repeated_narrator_segments = repeated_narrator_dialogue.get("segments") or []
        assert [item.get("persona_id") for item in repeated_narrator_segments] == [
            "mentor",
            "story_narrator",
            "friend",
            "story_narrator",
        ]
        assert [Path(item.get("voice_path", "")).name for item in repeated_narrator_segments] == [
            "mentor.wav",
            "narrator.wav",
            "friend.wav",
            "narrator.wav",
        ]

        growled_dialogue = router.split_text_by_persona(
            {
                "text": "[NARRATOR]\n\"Stay behind me,\" Friend growls, bracing against the door.",
                "tts_backend": "chatterbox",
            }
        )
        growled_segments = growled_dialogue.get("segments") or []
        assert [item.get("persona_id") for item in growled_segments] == ["friend", "story_narrator"]
        assert [Path(item.get("voice_path", "")).name for item in growled_segments] == ["friend.wav", "narrator.wav"]

        legacy_nix = PersonaConfig.from_dict(
            {"id": "legacy_nix", "display_name": "Nix", "role": "Old story character", "enabled": False}
        )
        linked_nix = PersonaConfig.from_dict(
            {"id": "linked_nix", "display_name": "Nix the Scout", "role": "Current story character", "enabled": True}
        )
        linked_narrator = PersonaConfig.from_dict(
            {"id": "linked_narrator", "display_name": "Story Narrator", "role": "narrator", "enabled": True}
        )
        legacy_voice = root / "legacy_nix.wav"
        linked_voice = root / "linked_nix.wav"
        linked_narrator_voice = root / "linked_narrator.wav"
        for path in (legacy_voice, linked_voice, linked_narrator_voice):
            path.write_bytes(b"RIFF0000WAVE")
        for persona, path in (
            (legacy_nix, legacy_voice),
            (linked_nix, linked_voice),
            (linked_narrator, linked_narrator_voice),
        ):
            persona.voice.enabled = True
            persona.voice.backend = "chatterbox"
            persona.voice.sample_path = str(path)
        cast_session = RoleplaySessionState.from_dict(
            {
                "enabled": True,
                "mode": AR_MODE,
                "active_persona_id": linked_nix.id,
                "current_speaker_id": linked_narrator.id,
            }
        )
        cast_controller = _FakeController([legacy_nix, linked_nix, linked_narrator], cast_session)
        cast_controller.settings.update(
            {
                "narrator_persona_id": linked_narrator.id,
                "master_story_linked_persona_ids": [linked_nix.id, linked_narrator.id],
            }
        )
        cast_router = PersonaVoiceRouter(cast_controller)
        linked_short_label = cast_router.split_text_by_persona(
            {
                "text": "[CHARACTER: Nix]\n\"Now is our chance!\"",
                "tts_backend": "chatterbox",
            }
        )
        linked_short_segments = linked_short_label.get("segments") or []
        assert [item.get("persona_id") for item in linked_short_segments] == [linked_nix.id]
        assert [Path(item.get("voice_path", "")).name for item in linked_short_segments] == [linked_voice.name]

        linked_colon_label = cast_router.split_text_by_persona(
            {
                "text": "Nix: Move now, the gate is closing!",
                "tts_backend": "chatterbox",
            }
        )
        linked_colon_segments = linked_colon_label.get("segments") or []
        assert [item.get("persona_id") for item in linked_colon_segments] == [linked_nix.id]
        assert [Path(item.get("voice_path", "")).name for item in linked_colon_segments] == [linked_voice.name]

        disabled_narrator = PersonaConfig.from_dict(
            {"id": "disabled_narrator", "display_name": "Story Narrator", "role": "narrator", "enabled": False}
        )
        disabled_narrator.voice.enabled = True
        disabled_narrator.voice.backend = "chatterbox"
        disabled_narrator.voice.sample_path = str(root / "disabled_narrator.wav")
        Path(disabled_narrator.voice.sample_path).write_bytes(b"RIFF0000WAVE")
        narrator_controller = _FakeController([disabled_narrator, linked_nix, linked_narrator], cast_session)
        narrator_controller.settings.update(
            {
                "narrator_persona_id": disabled_narrator.id,
                "master_story_linked_persona_ids": [linked_nix.id, linked_narrator.id],
            }
        )
        narrator_router = PersonaVoiceRouter(narrator_controller)
        linked_narration = narrator_router.split_text_by_persona(
            {
                "text": "[NARRATOR]\nThe current story continues.",
                "tts_backend": "chatterbox",
            }
        )
        linked_narration_segments = linked_narration.get("segments") or []
        assert [item.get("persona_id") for item in linked_narration_segments] == [linked_narrator.id]
        assert [Path(item.get("voice_path", "")).name for item in linked_narration_segments] == [linked_narrator_voice.name]

        nix_alpha = PersonaConfig.from_dict(
            {"id": "nix_alpha", "display_name": "Nix Alpha", "role": "Scout", "enabled": True}
        )
        nix_beta = PersonaConfig.from_dict(
            {"id": "nix_beta", "display_name": "Nix Beta", "role": "Guard", "enabled": True}
        )
        ambiguous_controller = _FakeController([nix_alpha, nix_beta, linked_narrator], cast_session)
        ambiguous_controller.settings.update(
            {
                "narrator_persona_id": linked_narrator.id,
                "master_story_linked_persona_ids": [nix_alpha.id, nix_beta.id, linked_narrator.id],
            }
        )
        ambiguous_router = PersonaVoiceRouter(ambiguous_controller)
        ambiguous_short_name = ambiguous_router.split_text_by_persona(
            {
                "text": "[NARRATOR]\n\"Move now,\" Nix says, watching the sealed door.",
                "tts_backend": "chatterbox",
            }
        )
        ambiguous_segments = ambiguous_short_name.get("segments") or []
        assert [item.get("persona_id") for item in ambiguous_segments] == [linked_narrator.id]

        unicode_curly_dialogue = router.split_text_by_persona(
            {
                "text": (
                    "[NARRATOR]\n"
                    "Friend tilts her head toward the broken lock. "
                    "\u201cWait here,\u201d Friend says, and steps into the blue light. "
                    "The corridor goes still."
                ),
                "tts_backend": "chatterbox",
            }
        )
        unicode_curly_segments = unicode_curly_dialogue.get("segments") or []
        assert [item.get("persona_id") for item in unicode_curly_segments] == [
            "story_narrator",
            "friend",
            "story_narrator",
        ]
        assert [Path(item.get("voice_path", "")).name for item in unicode_curly_segments] == [
            "narrator.wav",
            "friend.wav",
            "narrator.wav",
        ]

        unquoted_attributed_dialogue = router.split_text_by_persona(
            {
                "text": (
                    "[NARRATOR]\n"
                    "Friend lifts one hand as the lock starts to glow. "
                    "Friend says, Wait here. "
                    "The corridor goes still."
                ),
                "tts_backend": "chatterbox",
            }
        )
        unquoted_attributed_segments = unquoted_attributed_dialogue.get("segments") or []
        assert [item.get("persona_id") for item in unquoted_attributed_segments] == [
            "story_narrator",
            "friend",
            "story_narrator",
        ]
        assert [Path(item.get("voice_path", "")).name for item in unquoted_attributed_segments] == [
            "narrator.wav",
            "friend.wav",
            "narrator.wav",
        ]

        pronoun_dialogue = router.split_text_by_persona(
            {
                "text": (
                    "[NARRATOR]\n"
                    "Friend's breath hitches as she leans toward the lantern. "
                    "\"Good,\" she murmurs, her voice low. "
                    "\"Now we move.\" The corridor answers with dust.\n"
                    "[CHARACTER: Friend]\n"
                    "\"Feel this,\" she whispers, her hand hovering near the door."
                ),
                "tts_backend": "chatterbox",
            }
        )
        pronoun_segments = pronoun_dialogue.get("segments") or []
        assert [item.get("persona_id") for item in pronoun_segments] == [
            "story_narrator",
            "friend",
            "story_narrator",
            "friend",
            "story_narrator",
            "friend",
            "story_narrator",
        ]

        character_curly_dialogue = router.split_text_by_persona(
            {
                "text": (
                    "[CHARACTER: Friend]\n"
                    "“Right right... can't promise anything,” she echoes back in your own weary cadence. "
                    "A soft chime of amusement colors her tone. "
                    "“That's the spirit. Optimism would just get in the way down here.”"
                ),
                "tts_backend": "chatterbox",
            }
        )
        character_curly_segments = character_curly_dialogue.get("segments") or []
        assert [item.get("persona_id") for item in character_curly_segments] == [
            "friend",
            "story_narrator",
            "friend",
        ]
        assert [Path(item.get("voice_path", "")).name for item in character_curly_segments] == [
            "friend.wav",
            "narrator.wav",
            "friend.wav",
        ]

        assistant_same_line = router.split_text_by_persona(
            {
                "text": (
                    "Assistant: [NARRATOR] Friend studies the old lock with one hand on the key. "
                    "\"Tell me,\" she whispers, her voice low. "
                    "\"Where exactly do I start? Do I turn the key now, or wait for the signal?\" "
                    "Dust moves through the corridor."
                ),
                "tts_backend": "chatterbox",
            }
        )
        assistant_same_line_segments = assistant_same_line.get("segments") or []
        assert [item.get("persona_id") for item in assistant_same_line_segments] == [
            "story_narrator",
            "friend",
            "story_narrator",
            "friend",
            "story_narrator",
        ]

        inline_label_dialogue = router.split_text_by_persona(
            {
                "text": (
                    "[NARRATOR]\n"
                    "The air tightens. \"We should move now.\" "
                    "Friend: \"Before it wakes.\" Dust falls from the seal."
                ),
                "tts_backend": "chatterbox",
            }
        )
        inline_label_segments = inline_label_dialogue.get("segments") or []
        assert [item.get("persona_id") for item in inline_label_segments] == [
            "story_narrator",
            "friend",
            "friend",
            "story_narrator",
        ]
        assert [item.get("text") for item in inline_label_segments] == [
            "The air tightens.",
            "\"We should move now.\"",
            "\"Before it wakes.\"",
            "Dust falls from the seal.",
        ]

        stream_chunks = [
            "[CHARACTER: Friend]\n",
            "We should ",
            "move now.",
            "[NARRATOR]\n",
            "The lantern trembles.",
        ]
        routed = []
        for index, chunk in enumerate(stream_chunks):
            result = router.split_text_by_persona(
                {
                    "text": chunk,
                    "tts_backend": "chatterbox",
                    "streaming": True,
                    "stream_start": index == 0,
                    "stream_source_index": index,
                }
            )
            routed.extend(result.get("segments") or [])
        assert [item.get("persona_id") for item in routed] == ["friend", "friend", "story_narrator"]
        assert [Path(item.get("voice_path", "")).name for item in routed] == ["friend.wav", "friend.wav", "narrator.wav"]

        no_start_chunks = [
            "[CHARACTER: Friend]\n",
            "Hold the lantern steady.",
            "[NARRATOR]\n",
            "The corridor goes quiet.",
        ]
        routed_no_start = []
        for index, chunk in enumerate(no_start_chunks):
            result = router.split_text_by_persona(
                {
                    "text": chunk,
                    "tts_backend": "chatterbox",
                    "streaming": True,
                    "stream_source_index": index,
                    "response_id": "no-start-stream",
                }
            )
            routed_no_start.extend(result.get("segments") or [])
        assert [item.get("persona_id") for item in routed_no_start] == ["friend", "story_narrator"]
        assert [item.get("voice_route", {}).get("route_reason") for item in routed_no_start] == [
            "ar_stream_speaker",
            "ar_stream_speaker",
        ]

        preview_interleave_start = router.split_text_by_persona(
            {
                "text": "[CHARACTER: Friend]\nHold the lantern steady.",
                "tts_backend": "chatterbox",
                "streaming": True,
                "stream_start": True,
                "stream_source_index": 0,
                "response_id": "preview-interleave",
            }
        )
        assert [item.get("persona_id") for item in preview_interleave_start.get("segments") or []] == ["friend"]
        router.split_text_by_persona(
            {
                "text": "[NARRATOR]\nRoute preview only.",
                "tts_backend": "chatterbox",
                "streaming": False,
            }
        )
        preview_interleave_next = router.split_text_by_persona(
            {
                "text": "I still have it.",
                "tts_backend": "chatterbox",
                "streaming": True,
                "stream_source_index": 1,
                "response_id": "preview-interleave",
            }
        )
        assert [item.get("persona_id") for item in preview_interleave_next.get("segments") or []] == ["friend"]

        plain_response = router.split_text_by_persona(
            {
                "text": "The archive settles into silence.",
                "tts_backend": "chatterbox",
            }
        )
        plain_segments = plain_response.get("segments") or []
        assert [item.get("persona_id") for item in plain_segments] == ["story_narrator"]
        assert plain_segments[0].get("voice_route", {}).get("route_reason") == "ar_narrator_default"

        explicit_wins = router.split_text_by_persona(
            {
                "text": "[CHARACTER: Friend]\nThis label should not override the payload speaker.",
                "persona_id": "mentor",
                "tts_backend": "chatterbox",
            }
        )
        explicit_segments = explicit_wins.get("segments") or []
        assert [item.get("persona_id") for item in explicit_segments] == ["mentor"]
        assert "[CHARACTER" not in explicit_segments[0].get("text", "")
        assert explicit_segments[0].get("voice_route", {}).get("route_reason") == "explicit_persona"

        from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

        strict_cast = {
            "friend": {"speaker_name": "Friend"},
        }
        schema = build_structured_story_output_schema(strict_cast)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        segment_schema = schema["properties"]["segments"]["items"]
        assert segment_schema["additionalProperties"] is False
        assert "delivery" not in segment_schema["properties"]
        assert "timing" not in segment_schema["properties"]
        assert schema["properties"]["segments"]["maxItems"] == 6
        assert "speaker_name" not in segment_schema["required"]
        assert "speaker_name" not in segment_schema["properties"]
        assert "segment_id" not in segment_schema["properties"]
        assert "sfx_tags" not in segment_schema["properties"]
        assert segment_schema["properties"]["text"]["maxLength"] == 1600
        assert schema["properties"]["choices"]["items"]["additionalProperties"] is False
        assert "choice_id" not in schema["properties"]["choices"]["items"]["properties"]
        assert "metadata" not in schema["properties"]
        assert segment_schema["properties"]["speaker_id"]["enum"] == [
            "narrator",
            "friend",
            "unknown_speaker",
        ]
        strict_reply = json.dumps(
            {
                "schema_version": STRUCTURED_STORY_SCHEMA_VERSION,
                "response_type": "story_turn",
                "turn_id": "turn_smoke",
                "language": "en",
                "segments": [
                    {
                        "segment_id": 1,
                        "speaker_id": "narrator",
                        "speaker_name": "Narrator",
                        "role": "narrator",
                        "text": "The archive tightens around the lantern light.",
                        "sfx_tags": [],
                    },
                    {
                        "segment_id": 2,
                        "speaker_id": "friend",
                        "speaker_name": "Friend",
                        "role": "character",
                        "text": "Hold the lantern steady before the seal opens.",
                        "sfx_tags": [],
                    },
                    {
                        "segment_id": 3,
                        "speaker_id": "narrator",
                        "speaker_name": "Narrator",
                        "role": "sfx",
                        "text": "A ring of blue sparks opens at their feet.",
                        "sfx_tags": ["magic_spark"],
                    },
                ],
                "choices": [{"choice_id": "hold_lantern", "label": "Hold the lantern steady"}],
                "metadata": {
                    "scene_id": "archive",
                    "scene_state_hash": "archive_smoke_1",
                    "visual_key": "friend_archive_lantern",
                    "notes": None,
                },
            },
            ensure_ascii=False,
        )
        strict_converted = MultiPersonaRoleplayController._normalize_mprc_structured_reply(strict_reply, cast=strict_cast)
        assert "[NARRATOR]" in strict_converted
        assert "[CHARACTER: Friend]" in strict_converted
        assert "[FX: magic_spark]" in strict_converted
        assert "1. Hold the lantern steady" in strict_converted
        strict_routed = router.split_text_by_persona(
            {
                "text": strict_converted,
                "tts_backend": "chatterbox",
            }
        )
        strict_segments = strict_routed.get("segments") or []
        assert [
            item.get("persona_id")
            for item in strict_segments
            if "before the seal opens" in str(item.get("text") or "")
        ] == ["friend"]

        probe = object.__new__(MultiPersonaRoleplayController)
        probe.personas = personas
        probe.session = session
        probe.settings = {"narrator_persona_id": "mentor"}
        session.active_persona_id = "mentor"
        session.current_speaker_id = "mentor"
        assert probe.selected_narrator_persona_id() == "story_narrator"
        probe.settings = {"narrator_persona_id": "mentor", "narrator_persona_mode": "explicit"}
        assert probe.selected_narrator_persona_id() == "mentor"
        probe.settings = {"narrator_persona_id": "", "narrator_persona_mode": "auto"}
        assert probe.selected_narrator_persona_id() == "story_narrator"


def _smoke_visual_reply(personas: list[PersonaConfig], session: RoleplaySessionState) -> None:
    from addons.multi_persona_roleplay.visual_reply import PersonaVisualReply

    assert "auto_choices" in VISUAL_MODES
    personas[0].visual.enabled = True
    personas[0].visual.mode = "auto_choices"
    personas[0].visual.cooldown_seconds = 0
    personas[0].visual.max_auto_images_per_session = 0
    personas[0].visual.character_description = "Mentor with silver spectacles and a dark travel coat"
    personas[0].visual.clothing_props = "brass lantern, field notebook, worn leather gloves"
    personas[0].visual.environment_style = "ancient archive corridor with blue dust and carved stone"
    session.active_persona_id = personas[0].id
    session.current_speaker_id = personas[0].id
    session.turn_index = 1
    session.ar_state.pending_choices = ["Open the lantern door", "Step back"]
    visual_prompt = prompting.build_visual_reply_prompt(personas[0], session, reason="choices_present")
    assert "Story scene image for Visual Reply" in visual_prompt
    assert "Current story moment" in visual_prompt
    comfy_prompt = prompting.build_visual_reply_prompt(personas[0], session, reason="choices_present", provider="comfyui")
    assert "Story scene image for Visual Reply" not in comfy_prompt
    assert "Current story moment" not in comfy_prompt
    assert "dynamic story scene" in comfy_prompt
    grok_prompt = prompting.build_visual_reply_prompt(personas[0], session, reason="choices_present", provider="grok_text_to_image")
    runware_prompt = prompting.build_visual_reply_prompt(personas[0], session, reason="choices_present", provider="runware")
    assert prompting.visual_prompt_style("grok") == "grok"
    assert prompting.normalize_visual_provider_id("grok_text_to_image") == "xai"
    assert "natural-language image prompt" in grok_prompt
    assert "Current story moment" in grok_prompt
    assert "Character appearance to place inside that moment" in grok_prompt
    assert "Current story moment" not in runware_prompt
    assert "Hidden LLM" not in runware_prompt
    assert len(runware_prompt) < len(grok_prompt)
    assert len(runware_prompt) <= 520
    session.location = "The Amber Cup tavern"
    session.scene_summary = "The story opened inside the warm tavern."
    session.ar_state.location = "Rain-slick street outside the tavern"
    session.ar_state.current_scene = "The group has pushed through the tavern door into the rain."
    outside_reply = "[NARRATOR]\nYou step outside the tavern into cold rain, boots splashing on the street stones."
    outside_prompt = prompting.build_visual_reply_prompt(
        personas[0],
        session,
        reason="assistant_reply",
        source_text=outside_reply,
    )
    assert "Latest visible story action" in outside_prompt
    assert "step outside the tavern" in outside_prompt
    assert "Rain-slick street outside the tavern" in outside_prompt
    assert outside_prompt.find("Latest visible story action") < outside_prompt.find("Environment/style reference")
    personas[0].visual.include_active_speaker = False
    personas[0].visual.include_scene_summary = False
    outside_runware_prompt = prompting.build_visual_reply_prompt(
        personas[0],
        session,
        reason="assistant_reply",
        provider="runware",
        source_text=outside_reply,
    )
    assert "current story moment" in outside_runware_prompt
    assert "step outside the tavern" in outside_runware_prompt
    assert "show the character in this scene" in outside_runware_prompt
    assert outside_runware_prompt.find("current story moment") < outside_runware_prompt.find("show the character in this scene")
    assert "Active speaker" not in outside_runware_prompt
    assert "not a portrait" in outside_runware_prompt
    personas[0].visual.include_active_speaker = True
    personas[0].visual.include_scene_summary = True

    visual_service = _FakeVisualGenerationService("runware")
    visual_controller = _FakeController(personas, session)
    visual_controller.visual_reply_service = visual_service
    personas[0].visual.provider = "inherit"
    personas[0].visual.mode = "manual"
    visual_builder = PersonaVisualReply(visual_controller)
    inherited_payload = visual_builder.build_prompt(persona=personas[0], reason="manual")
    assert inherited_payload["effective_provider"] == "runware"
    assert inherited_payload["prompt_style"] == "runware"
    result = visual_builder.request_generation(persona=personas[0], reason="manual")
    assert result["accepted"]
    assert visual_service.requests[-1]["provider"] == "runware"
    personas[0].visual.mode = "auto_choices"
    personas[0].visual.provider = "inherit"

    controller = _FakeController(personas, session)
    personas[2].visual.enabled = True
    personas[2].visual.mode = "auto_choices"
    personas[2].visual.cooldown_seconds = 0
    engine = RoleplayEngine(controller)
    engine._maybe_auto_visual_reply("[NARRATOR] The lantern door opens.\n[CHOICES]\n- Enter\n- Wait")
    assert controller.auto_visual_requests == [
        {
            "persona_id": "story_narrator",
            "policy_persona_id": "story_narrator",
            "reason": "choices_present",
            "scene_focused": True,
            "source_text": "[NARRATOR] The lantern door opens.\n[CHOICES]\n- Enter\n- Wait",
        }
    ]

    jack = PersonaConfig.from_dict(
        {
            "id": "jack",
            "display_name": "Jack",
            "role": "detective",
            "visual": {"enabled": True, "mode": "auto_user_asks"},
        }
    )
    lilith = PersonaConfig.from_dict(
        {
            "id": "lilith",
            "display_name": "Lilith",
            "role": "demon investigator",
            "visual": {"enabled": True, "mode": "off"},
        }
    )
    narrator = PersonaConfig.from_dict(
        {
            "id": "story_narrator",
            "display_name": "Story Narrator",
            "role": "narrator",
            "visual": {
                "enabled": True,
                "mode": "auto_every_n_replies",
                "auto_reply_interval": 1,
                "cooldown_seconds": 0,
            },
        }
    )
    scene_session = RoleplaySessionState.from_dict(
        {
            **session.to_dict(),
            "enabled": True,
            "mode": AR_MODE,
            "turn_index": 2,
            "active_persona_id": "jack",
            "current_speaker_id": "jack",
        }
    )
    scene_controller = _FakeController([jack, lilith, narrator], scene_session)
    scene_engine = RoleplayEngine(scene_controller)
    scene_reply = (
        "[CHARACTER: Jack]\nStay behind me.\n"
        "[NARRATOR]\nLilith steps through the rain as smoke coils around her hands. "
        "The alley falls silent."
    )
    scene_engine._maybe_auto_visual_reply(scene_reply)
    assert scene_controller.auto_visual_requests == [
        {
            "persona_id": "lilith",
            "policy_persona_id": "story_narrator",
            "reason": "reply_interval",
            "scene_focused": False,
            "source_text": scene_reply,
        }
    ]

    scene_service = _FakeVisualGenerationService("runware")
    scene_controller.visual_reply_service = scene_service
    scene_builder = PersonaVisualReply(scene_controller)
    scene_result = scene_builder.request_generation(
        persona=lilith,
        policy_persona=narrator,
        reason="reply_interval",
        source_text=scene_reply,
    )
    assert scene_result["accepted"], "Narrator policy must authorize the inferred subject's scene image"
    assert "Lilith" in str(scene_result["payload"].get("image_prompt") or "")
    assert scene_result["payload"]["visual_policy_persona_id"] == "story_narrator"
    atmosphere_payload = scene_builder.build_prompt(
        persona=narrator,
        policy_persona=narrator,
        reason="assistant_reply",
        source_text="[NARRATOR]\nLightning splits the sky above the abandoned station.",
        use_action_prompt=False,
        scene_focused=True,
    )
    assert "Story Narrator" not in str(atmosphere_payload.get("image_prompt") or "")
    assert atmosphere_payload["scene_focused"] is True


def _smoke_manual_visual_requests_are_threaded(personas: list[PersonaConfig]) -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    persona = personas[0]
    probe = object.__new__(MultiPersonaRoleplayController)
    probe._state_lock = threading.RLock()
    probe._manual_character_image_inflight = set()
    probe._debug_visual_prompt = ""
    probe._selected_persona = lambda: persona
    probe._character_picture_prompt = lambda _persona: "single character portrait prompt"
    probe._run_manual_character_image_request = lambda _persona_id: None
    probe._run_manual_visual_reply_request = lambda _persona_id, *, kind: None
    debug_entries: list[dict] = []
    warnings: list[tuple[str, str]] = []
    queued: list[tuple[str, object]] = []
    probe._record_visual_debug = lambda **kwargs: debug_entries.append(dict(kwargs))
    probe._warn = lambda title, message: warnings.append((str(title), str(message)))
    probe._refresh_debug = lambda: None
    probe._queue_visual_worker = lambda prefix, target: queued.append((str(prefix), target)) or True

    probe._generate_character_image()
    assert warnings == []
    assert queued and queued[-1][0] == "mprc_manual_character_image"
    assert persona.id in probe._manual_character_image_inflight
    assert any("background worker" in str(item.get("message") or "") for item in debug_entries)

    queued.clear()
    probe._generate_visual_reply()
    assert queued and queued[-1][0] == "mprc_manual_visual_reply"
    assert '"queued": true' in probe._debug_visual_prompt.lower()

    queued.clear()
    probe.visual_reply_service = SimpleNamespace(request_generation=lambda **_kwargs: True)
    result = MultiPersonaRoleplayController._queue_story_avatar_generation(
        probe,
        ["mentor"],
        {"id": "story"},
        avatar_enabled=True,
        style_sheet_enabled=True,
    )
    assert queued and queued[-1][0] == "mprc_story_avatar_batch"
    assert "background" in result


def _smoke_tts_character_image_does_not_auto_show(personas: list[PersonaConfig]) -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    persona = personas[0]
    persona.character_image_path = ""
    persona.visual.auto_show_dock = True
    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = [persona]
    probe._state_lock = threading.RLock()
    probe._tts_persona_visual_inflight = {persona.id}
    probe.context = SimpleNamespace(logger=None)
    probe.is_shutdown = lambda: False
    probe.persona_by_id = lambda persona_id: persona if persona_id == persona.id else None
    requests: list[dict] = []

    def request_character_image(received_persona, *, auto_show: bool, source: str):
        requests.append({"persona_id": received_persona.id, "auto_show": auto_show, "source": source})
        return {"ok": True}

    probe._request_character_image_generation = request_character_image
    MultiPersonaRoleplayController._run_tts_character_image_request(probe, persona.id)
    assert requests == [
        {
            "persona_id": persona.id,
            "auto_show": False,
            "source": "nc.multi_persona_roleplay.tts_character_picture",
        }
    ]
    assert persona.id not in probe._tts_persona_visual_inflight


def _smoke_structured_output_request_scoping(personas: list[PersonaConfig]) -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = list(personas)
    probe.story_prompt_personas = lambda: list(personas)
    probe._persona_looks_like_narrator = lambda persona: str(getattr(persona, "id", "") or "") == "story_narrator"
    probe.settings = {}

    params: dict = {}
    assert probe._apply_mprc_chat_structured_response_format(params, full_setup=False) is True
    assert params["response_format"]["type"] == "json_schema"
    schema_payload = params["response_format"]["json_schema"]
    assert schema_payload["name"] == "mprc_story_turn"
    assert schema_payload["strict"] is True
    assert schema_payload["schema"]["properties"]["response_type"]["const"] == "story_turn"
    assert "turn_id" not in schema_payload["schema"]["required"]
    assert "language" not in schema_payload["schema"]["required"]
    assert "metadata" not in schema_payload["schema"]["required"]
    assert "speaker_name" not in schema_payload["schema"]["properties"]["segments"]["items"]["required"]
    assert "speaker_name" not in schema_payload["schema"]["properties"]["segments"]["items"]["properties"]
    assert "metadata" not in schema_payload["schema"]["properties"]
    assert schema_payload["schema"]["properties"]["choices"]["minItems"] == 2
    assert schema_payload["schema"]["properties"]["choices"]["maxItems"] == 4
    assert params["max_tokens"] == 2400

    probe.settings = {"chat_choice_mode": "ask_next_move"}
    params = {}
    assert probe._apply_mprc_chat_structured_response_format(params, full_setup=False) is True
    assert params["response_format"]["json_schema"]["schema"]["properties"]["choices"]["maxItems"] == 0

    probe.settings = {"chat_structured_output_enabled": False}
    params = {}
    assert probe._apply_mprc_chat_structured_response_format(params, full_setup=True) is False
    assert "response_format" not in params

    probe.settings = {"chat_structured_output_enabled": True, "chat_structured_output_scope": "first_turn"}
    params = {}
    assert probe._apply_mprc_chat_structured_response_format(params, full_setup=False) is False
    assert "response_format" not in params
    assert probe._apply_mprc_chat_structured_response_format(params, full_setup=True) is True
    assert params["max_tokens"] == 2400


def _smoke_structured_output_export_flow(personas: list[PersonaConfig]) -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    statuses: list[str] = []
    cancelled = object.__new__(MultiPersonaRoleplayController)
    cancelled._controls = {}
    cancelled._set_chat_play_status = lambda text: statuses.append(str(text or ""))
    cancelled._save_file = lambda *args, **kwargs: ""
    cancelled._mprc_structured_output_schema = lambda: (_ for _ in ()).throw(AssertionError("schema built before save path"))
    cancelled._on_export_mprc_structured_output_clicked()
    assert statuses[-1] == "Structured Output export cancelled."

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mprc_schema.json"
        queued: list[tuple[str, dict[str, dict[str, str]], bool]] = []
        probe = object.__new__(MultiPersonaRoleplayController)
        probe._controls = {}
        probe.personas = list(personas)
        probe.story_prompt_personas = lambda: list(personas)
        probe._persona_looks_like_narrator = lambda persona: str(getattr(persona, "id", "") or "") == "story_narrator"
        probe.settings = {"chat_choice_mode": "ask_next_move"}
        probe._save_file = lambda *args, **kwargs: str(path)
        probe._set_chat_play_status = lambda text: statuses.append(str(text or ""))
        probe._queue_mprc_structured_output_export = (
            lambda export_path, cast, require_choices: queued.append((str(export_path), dict(cast), bool(require_choices))) or True
        )
        probe._on_export_mprc_structured_output_clicked()
        assert queued
        assert queued[-1][0] == str(path)
        assert queued[-1][1]["mentor"]["speaker_name"] == "Mentor"
        assert "story_narrator" not in queued[-1][1]
        assert queued[-1][2] is False

        MultiPersonaRoleplayController._write_mprc_structured_output_schema_file(
            path,
            {"friend": {"speaker_name": "Friend"}},
            require_choices=True,
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["properties"]["segments"]["items"]["properties"]["speaker_id"]["enum"] == [
            "narrator",
            "friend",
            "unknown_speaker",
        ]
        assert payload["properties"]["choices"]["minItems"] == 2

        from PySide6 import QtWidgets
        from addons.multi_persona_roleplay.controller import _MprcObjectResultBridge

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        worker_path = Path(tmp) / "mprc_schema_worker.json"
        worker_statuses: list[str] = []
        worker_warnings: list[str] = []
        worker_probe = object.__new__(MultiPersonaRoleplayController)
        worker_probe._state_lock = threading.RLock()
        worker_probe._shutting_down = False
        worker_probe._worker_sequence = 0
        worker_probe._active_worker_tokens = set()
        worker_probe._worker_threads = {}
        worker_probe._structured_output_export_token = ""
        worker_probe._controls = {"chat_export_structured_output": QtWidgets.QPushButton("Export")}
        worker_probe._request_ui_refresh = lambda: None
        worker_probe._set_chat_play_status = lambda text: worker_statuses.append(str(text or ""))
        worker_probe._warn = lambda title, text: worker_warnings.append(f"{title}: {text}")
        worker_probe._structured_export_bridge = _MprcObjectResultBridge(worker_probe._on_mprc_structured_output_export_finished)
        assert worker_probe._queue_mprc_structured_output_export(
            worker_path,
            {"friend": {"speaker_name": "Friend"}},
            True,
        )
        deadline = time.time() + 5
        while time.time() < deadline and not any("Exported Structured Output schema" in item for item in worker_statuses):
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert worker_path.exists()
        assert worker_warnings == []
        assert worker_probe._controls["chat_export_structured_output"].isEnabled() is True
        assert worker_probe._structured_output_export_token == ""


def _smoke_structured_output_partial_recovery() -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    cast = {"friend": {"speaker_name": "Friend"}}
    segment_one = json.dumps(
        {
            "segment_id": 1,
            "speaker_id": "narrator",
            "speaker_name": "Narrator",
            "role": "narrator",
            "text": "The archive door shivers under the lantern light.",
            "sfx_tags": [],
        }
    )
    segment_two = json.dumps(
        {
            "segment_id": 2,
            "speaker_id": "friend",
            "speaker_name": "Friend",
            "role": "character",
            "text": "Hold it steady. The seal is listening.",
            "sfx_tags": [],
        }
    )
    truncated = (
        f'Story: {{"schema_version":"{STRUCTURED_STORY_SCHEMA_VERSION}",'
        f'"response_type":"story_turn","segments":[{segment_one},{segment_two},'
        '{"segment_id":3,"speaker_id":"friend","speaker_name":"Friend","role":"character","text":"'
    )
    recovered = MultiPersonaRoleplayController._normalize_mprc_structured_reply(truncated, cast=cast)
    assert "[NARRATOR]" in recovered
    assert "[CHARACTER: Friend]" in recovered
    assert "The archive door shivers" in recovered
    assert "Hold it steady" in recovered
    assert "schema_version" not in recovered
    assert "response_type" not in recovered
    assert "cut off" in recovered

    unrecoverable = MultiPersonaRoleplayController._normalize_mprc_structured_reply(
        f'Story: {{"schema_version":"{STRUCTURED_STORY_SCHEMA_VERSION}","segments":[{{"segment_id":1,',
        cast=cast,
    )
    assert unrecoverable.startswith("[NARRATOR]")
    assert "schema_version" not in unrecoverable
    attributed_character = MultiPersonaRoleplayController._normalize_mprc_structured_reply(
        json.dumps(
            {
                "schema_version": STRUCTURED_STORY_SCHEMA_VERSION,
                "response_type": "story_turn",
                "segments": [
                    {
                        "speaker_id": "friend",
                        "role": "character",
                        "text": '"Hold it steady," Friend whispered, raising one hand.',
                    }
                ],
                "choices": [{"label": "Keep holding the lantern"}, {"label": "Step back"}],
            }
        ),
        cast=cast,
    )
    assert "[CHARACTER: Friend]\nHold it steady," in attributed_character
    assert "Friend whispered" not in attributed_character


def _smoke_voice_file_browse_uses_non_native_dialog() -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    with tempfile.TemporaryDirectory() as tmp:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        selected_voice = Path(tmp) / "selected_voice.wav"
        selected_voice.write_bytes(b"RIFF0000WAVE")

        controller = _new_controller(Path(tmp) / "storage")
        tab = controller._build_voice_tab()
        assert tab is not None
        persona = controller.active_persona()
        assert persona is not None
        calls: list[dict[str, object]] = []

        def fake_open_file(title: str, start: str, filter_text: str, **kwargs) -> str:
            calls.append({"title": title, "start": start, "filter": filter_text, **kwargs})
            return str(selected_voice)

        controller._open_file = fake_open_file
        controller._browse_voice_sample()
        app.processEvents()
        assert calls[-1].get("non_native") is True
        assert controller._controls["voice_sample"].text() == str(selected_voice)
        assert persona.voice.sample_path == str(selected_voice)

        repair_persona = PersonaConfig.from_dict({"id": "repair", "display_name": "Repair Voice"})
        repair_calls: list[dict[str, object]] = []
        repair_probe = object.__new__(MultiPersonaRoleplayController)
        repair_probe.session = RoleplaySessionState.from_dict({"mode": AR_MODE})
        repair_probe.settings = {}
        repair_probe.selected_narrator_persona = lambda: None
        repair_probe._selected_voice_persona = lambda: repair_persona
        repair_probe.active_persona = lambda: repair_persona
        repair_probe._voice_follows_active = lambda: True
        repair_probe._warn = lambda *_args, **_kwargs: None
        repair_probe.save_state = lambda: None
        repair_probe._record_story_event = lambda *_args, **_kwargs: None
        repair_probe.refresh_ui = lambda: None
        repair_probe._validate_story_setup_to_ui = lambda: None

        def fake_repair_open_file(title: str, start: str, filter_text: str, **kwargs) -> str:
            repair_calls.append({"title": title, "start": start, "filter": filter_text, **kwargs})
            return str(selected_voice)

        repair_probe._open_file = fake_repair_open_file
        repair_probe._repair_browse_voice_file()
        assert repair_calls[-1].get("non_native") is True
        assert repair_persona.voice.enabled is True
        assert repair_persona.voice.sample_path == str(selected_voice)


def _smoke_chat_choice_mode_finalizer(personas: list[PersonaConfig], session: RoleplaySessionState) -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = list(personas)
    probe.session = session
    probe.settings = {}
    session.current_speaker_id = "friend"
    session.active_persona_id = "friend"
    session.objective = "Open the lantern door."
    session.ar_state.story_goal = "Open the lantern door."

    finalized = probe._finalize_mprc_chat_reply_choice_mode("[NARRATOR]\nThe seal starts to glow.")
    assert "[CHOICES]" in finalized
    assert "Pursue objective: Open the lantern door." in finalized
    assert len(probe._extract_ar_choices(finalized)) >= 2

    probe.settings = {"chat_choice_mode": "ask_next_move"}
    freeform = probe._finalize_mprc_chat_reply_choice_mode(
        "[NARRATOR]\nThe seal starts to glow.\n\n[CHOICES]\n1. Open it\n2. Wait"
    )
    assert "[CHOICES]" not in freeform
    assert freeform.endswith("What's your next move?")
    assert probe._extract_ar_choices(freeform) == []


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _remote_json_request(url: str, *, code: str = "", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST" if payload is not None else "GET")
    request.add_header("Accept", "application/json")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    if code:
        request.add_header("X-MPRC-Code", code)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _smoke_remote_backend_api() -> None:
    from addons.multi_persona_roleplay.remote_backend import MPRCRemoteBackend

    class _Probe:
        def __init__(self):
            self.settings = {"remote_enabled": True}
            self.context = SimpleNamespace(logger=None)
            self.sent: list[tuple[str, str, str]] = []
            self.choices: list[str] = []
            self.audio_path = Path(tempfile.gettempdir()) / "mprc_remote_audio_smoke.wav"
            self.audio_path.write_bytes(b"RIFF0000WAVE")

        def remote_status_snapshot(self):
            return {"running": True}

        def remote_snapshot(self):
            return {"session": {"mode": AR_MODE}, "choices": [{"id": "1", "text": "Continue"}]}

        def remote_personas_snapshot(self):
            return [{"id": "mentor", "display_name": "Mentor"}]

        def remote_session_snapshot(self):
            return {"mode": AR_MODE}

        def remote_update_session(self, payload):
            return {"updated": dict(payload or {})}

        def remote_send_user_text(self, text, *, intent="Auto", speaker_id=""):
            self.sent.append((text, intent, speaker_id))
            return self.remote_snapshot()

        def remote_select_choice(self, choice):
            self.choices.append(choice)
            return self.remote_snapshot()

        def remote_play(self):
            return self.remote_snapshot()

        def remote_pause(self):
            return self.remote_snapshot()

        def remote_request_visual(self):
            return self.remote_snapshot()

        def remote_chromecast_action(self, payload):
            return {
                "accepted": True,
                "cast": {
                    "selected_device": str(dict(payload or {}).get("device_name") or ""),
                    "casting": str(dict(payload or {}).get("action") or "") == "start",
                },
            }

        def audio_settings_snapshot(self):
            return {"enabled": True}

        def remote_speech_audio_snapshot(self):
            return {
                "available": True,
                "status": "ready",
                "generation": 1,
                "items": [{"id": "chunk1", "url_path": "/api/speech-audio/file/chunk1"}],
            }

        def remote_speech_audio_file_path(self, audio_id):
            if str(audio_id or "") == "chunk1":
                return self.audio_path
            raise FileNotFoundError("speech audio chunk not found")

    code = "123456"
    port = _free_tcp_port()
    probe = _Probe()
    backend = MPRCRemoteBackend(probe, host="127.0.0.1", port=port, code=code)
    try:
        backend.start()
        base = f"http://127.0.0.1:{port}"
        health = _remote_json_request(base + "/health")
        assert health["ok"] is True
        try:
            _remote_json_request(base + "/api/state")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("remote state without pairing code should fail")
        state = _remote_json_request(base + "/api/state", code=code)
        assert state["ok"] is True
        assert state["state"]["session"]["mode"] == AR_MODE
        bad_send_failed = False
        try:
            _remote_json_request(base + "/api/send", code=code, payload={})
        except urllib.error.HTTPError as exc:
            bad_send_failed = exc.code == 400
        assert bad_send_failed
        sent = _remote_json_request(base + "/api/send", code=code, payload={"text": "Open the door", "intent": "Act"})
        assert sent["ok"] is True
        assert probe.sent[-1] == ("Open the door", "Act", "")
        choice = _remote_json_request(base + "/api/choice", code=code, payload={"choice": "1"})
        assert choice["ok"] is True
        assert probe.choices[-1] == "1"
        cast = _remote_json_request(base + "/api/cast", code=code, payload={"action": "start", "device_name": "Living Room TV"})
        assert cast["ok"] is True
        assert cast["result"]["accepted"] is True
        assert cast["result"]["cast"]["casting"] is True
        audio = _remote_json_request(base + "/api/speech-audio", code=code)
        assert audio["ok"] is True
        assert audio["speech_audio"]["items"][0]["id"] == "chunk1"
        audio_request = urllib.request.Request(base + f"/api/speech-audio/file/chunk1?code={code}")
        with urllib.request.urlopen(audio_request, timeout=5) as response:
            assert response.headers.get_content_type() == "audio/wav"
            assert response.read() == b"RIFF0000WAVE"
    finally:
        backend.stop()
        audio_path = getattr(probe, "audio_path", None)
        if audio_path is not None:
            try:
                Path(audio_path).unlink()
            except Exception:
                pass


def _smoke_remote_install_is_opt_in() -> None:
    probe = object.__new__(MultiPersonaRoleplayController)
    saved: list[dict] = []
    status_lines: list[str] = []
    probe.settings = {"remote_enabled": True, "remote_token": "legacy-token"}
    probe.storage = SimpleNamespace(save_settings=lambda settings: saved.append(dict(settings)))
    probe._remote_backend = None
    probe._controls = {}
    probe._syncing = False
    probe._set_chat_play_status = lambda text: status_lines.append(str(text or ""))

    probe._ensure_remote_settings_defaults()
    assert probe.settings["remote_server_installed"] is False
    assert probe.settings["remote_enabled"] is False
    assert "remote_token" not in probe.settings
    assert "remote_code" not in probe.settings
    assert probe.remote_status_snapshot()["installed"] is False
    probe._sync_remote_backend_from_settings()
    assert probe._remote_backend is None

    probe._on_mprc_remote_install_clicked()
    assert probe.settings["remote_server_installed"] is True
    assert probe.settings["remote_enabled"] is False
    assert probe.settings["remote_host"] == "0.0.0.0"
    assert probe.settings["remote_port"] == 8765
    assert probe._normalized_remote_code(probe.settings.get("remote_code"))
    status = probe.remote_status_snapshot()
    assert status["installed"] is True
    assert status["running"] is False
    assert status["pairing_code"] == probe.settings["remote_code"]
    assert any("Remote controls installed" in line for line in status_lines)


def _smoke_ar_scene_state_update(personas: list[PersonaConfig]) -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    session = RoleplaySessionState.from_dict(
        {
            "enabled": True,
            "mode": AR_MODE,
            "scene_summary": "The story begins at a sealed archive door.",
            "ar_state": {
                "current_scene": "opening beat",
                "location": "Archive corridor",
                "active_characters": ["mentor", "friend"],
                "story_goal": "Open the door.",
                "recent_events": ["A knock came from inside."],
            },
        }
    )
    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = personas
    probe.session = session
    changed = probe._apply_ar_scene_update_payload(
        {
            "scene_summary": "Mentor and Friend have left the archive door and entered a flooded pump room.",
            "current_scene": "Friend kneels beside a valve while Mentor studies a moving reflection.",
            "location": "Flooded pump room",
            "time_of_day": "after midnight",
            "mood": "tense and damp",
            "story_goal": "Stop the water pressure before the hatch bursts.",
            "tension_level": 7,
            "recent_event": "Friend found the valve vibrating under her hand.",
            "pending_choices": ["Turn the valve", "Ask Mentor to listen"],
            "character_state_summaries": {"friend": "Friend is crouched by the unstable valve."},
        }
    )
    assert changed
    assert session.ar_state.current_scene.startswith("Friend kneels")
    assert session.ar_state.location == "Flooded pump room"
    assert session.ar_state.tension_level == 7
    assert session.ar_state.pending_choices == ["Turn the valve", "Ask Mentor to listen"]
    assert session.character_state_summaries["friend"].startswith("Friend is crouched")
    changed = probe._apply_ar_scene_update_payload(
        {
            "scene_summary": "Mentor and Friend move deeper into the pump room.",
            "current_scene": "Friend watches the valve settle while Mentor listens to the pipes.",
            "location": "Flooded pump room",
            "time_of_day": "after midnight",
            "mood": "watchful",
            "story_goal": "Follow the pipe noise.",
            "tension_level": 4,
            "recent_event": "The old choices are no longer current.",
            "pending_choices": [],
            "character_state_summaries": {},
        }
    )
    assert changed
    assert session.ar_state.pending_choices == []
    session.ar_state.current_scene = "The party is still in the tavern."
    session.ar_state.location = "The Amber Cup tavern"
    session.ar_state.player_intent = "Act: Leave the tavern and go outside."
    moved = probe._apply_ar_progression_fallback(
        "[NARRATOR]\n"
        "You push open the tavern door and step outside into the rain. "
        "The street stones shine under the lanternlight as the tavern door swings shut behind you."
    )
    assert moved
    assert "step outside" in session.ar_state.current_scene.lower()
    assert session.ar_state.location in {"Outside the tavern", "Street outside the tavern"}


def _smoke_story_only_persona_overrides(personas: list[PersonaConfig], session: RoleplaySessionState) -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = personas
    probe.session = session
    probe._ensure_session_persona = lambda: None
    probe._master_story_draft = {}
    probe.settings = {
        "master_story_persona_overrides": {
            "mentor": {
                "display_name": "Gate Oracle",
                "draft_id": "gate_oracle",
                "role": "cryptic guide",
                "ar_description": "A story-only version of Mentor for the lantern door scene.",
                "story_profile_notes": "Mentor speaks as the door's patient oracle only in this story.",
            }
        }
    }
    effective = probe.story_prompt_persona("mentor")
    assert effective is not None
    assert effective.id == "mentor"
    assert effective.display_name == "Gate Oracle"
    assert "patient oracle" in effective.system_prompt
    assert personas[0].display_name == "Mentor"
    assert probe.resolve_story_persona_alias("Gate Oracle").id == "mentor"


def _smoke_current_character_view_mode(personas: list[PersonaConfig]) -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    outside = PersonaConfig.from_dict({"id": "outside_cast", "display_name": "Outside Cast"})
    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = list(personas) + [outside]
    probe.session = RoleplaySessionState.from_dict(
        {
            "enabled": True,
            "mode": AR_MODE,
            "active_persona_id": "mentor",
            "current_speaker_id": "mentor",
            "ar_state": {"active_characters": ["mentor", "friend"]},
        }
    )
    probe.settings = {
        "master_story_linked_persona_ids": ["friend"],
        "current_character_view_mode": "active_story",
    }
    assert [persona.id for persona in probe._current_character_roster_personas()] == ["friend"]
    probe.settings["master_story_linked_persona_ids"] = []
    assert [persona.id for persona in probe._current_character_roster_personas()] == ["mentor", "friend"]
    probe.settings["current_character_view_mode"] = "all"
    assert [persona.id for persona in probe._current_character_roster_personas()] == [
        "mentor",
        "friend",
        "story_narrator",
        "outside_cast",
    ]
    _smoke_current_character_preview_layout()


def _smoke_current_character_preview_layout() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore, QtWidgets
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    probe = object.__new__(MultiPersonaRoleplayController)
    probe._controls = {}
    panel = probe._build_character_preview_panel()
    try:
        assert probe._controls["current_character_left_panel"].objectName() == "mprc_current_character_left_panel"
        assert probe._controls["current_character_action_column"].objectName() == "mprc_current_character_action_column"
        assert probe._controls["character_roster_column"].objectName() == "mprc_character_roster_column"
        assert probe._controls["character_roster_frame"].parentWidget() is probe._controls["character_roster_column"]
        assert probe._controls["character_roster_strip"].verticalScrollBarPolicy() == QtCore.Qt.ScrollBarAsNeeded
        assert probe._controls["character_roster_column"].minimumWidth() >= 520
        assert probe._controls["character_roster_column"].maximumWidth() > probe._controls["character_roster_column"].minimumWidth()
        assert probe._controls["character_roster_column"].sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Expanding
        assert probe._controls["quick_change_avatar"].parentWidget() is probe._controls["current_character_action_column"]
        assert probe._controls["current_character_info_scroll"].maximumHeight() >= 160
        assert panel.layout().count() == 2
        assert panel.layout().stretch(0) == panel.layout().stretch(1) == 1
        assert 280 <= panel.minimumHeight() <= 320
        probe.settings = {"show_current_character_visual": True, "current_character_view_mode": "active_story"}
        probe.personas = []
        probe.session = RoleplaySessionState.from_dict({"enabled": True, "mode": AR_MODE})
        probe._sync_mprc_tab_stack_height = lambda: None
        probe._refresh_character_preview()
        assert 280 <= panel.minimumHeight() <= 320
        assert panel.maximumHeight() >= 360

        probe.personas = [
            PersonaConfig.from_dict({"id": "one", "display_name": "One"}),
            PersonaConfig.from_dict({"id": "two", "display_name": "Two"}),
        ]
        probe.session = RoleplaySessionState.from_dict(
            {
                "enabled": True,
                "mode": AR_MODE,
                "active_persona_id": "one",
                "current_speaker_id": "one",
                "ar_state": {"active_characters": ["one", "two"]},
            }
        )
        probe.settings = {"current_character_view_mode": "active_story"}
        probe._current_linked_persona_ids = lambda: []
        probe._refresh_character_roster_strip()
        first_tile = probe._controls["character_roster_layout"].itemAtPosition(0, 0).widget()
        preview = first_tile.findChild(QtWidgets.QLabel)
        assert preview.width() >= 110
        assert preview.height() > preview.width()
    finally:
        panel.deleteLater()
        app.processEvents()


def _smoke_master_story_persona_count_controls() -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    probe = object.__new__(MultiPersonaRoleplayController)
    probe._controls = {}
    probe._control_int_value = lambda key, default, minimum, maximum: 3 if key == "master_story_native_persona_count" else default
    warning = probe._master_story_persona_count_warning({"personas": [{"id": "one"}, {"id": "two"}]})
    assert "Requested 3" in warning
    assert "returned 2" in warning

    text = probe._master_story_generation_constraints_text(
        {
            "native_personas_to_draft": 3,
            "maximum_new_personas_to_create": 2,
            "allow_exceed_max_created_characters": False,
            "use_existing_personas": True,
        }
    )
    assert "Draft exactly 3" in text
    assert "Apply Draft will create no more than 2" in text

    limited = _master_story_apply_probe(max_created=2, allow_exceed=False)
    limited_result = limited._apply_master_story_payload(_story_payload_with_personas(3), apply_plan=_apply_plan())
    assert limited_result["created"] == 2
    assert any("creation limit" in item for item in limited_result["skipped"])

    override = _master_story_apply_probe(max_created=2, allow_exceed=False)
    override_plan = _apply_plan()
    override_plan["allow_exceed_max_created_characters"] = True
    override_result = override._apply_master_story_payload(_story_payload_with_personas(3), apply_plan=override_plan)
    assert override_result["created"] == 3
    assert not override_result["skipped"]

    narrator_plus_cast = _master_story_apply_probe(max_created=3, allow_exceed=False)
    narrator_plus_cast_payload = _story_payload_with_personas(4)
    narrator_plus_cast_payload["personas"][0].update(
        {
            "id": "narrator",
            "display_name": "Narrator",
            "role": "narrator",
            "behavior_mode": "narrator",
        }
    )
    narrator_plus_cast_result = narrator_plus_cast._apply_master_story_payload(
        narrator_plus_cast_payload,
        apply_plan=_apply_plan(),
    )
    assert narrator_plus_cast_result["created"] == 4
    assert not narrator_plus_cast_result["skipped"], (
        "The narrator must not consume the Master Story character-creation limit"
    )


def _smoke_assistant_reply_recording_scope() -> None:
    isolation = {"active": False}
    controller = SimpleNamespace(
        session=RoleplaySessionState.from_dict({"enabled": False, "mode": "Narrator + characters"}),
        settings={},
        context=SimpleNamespace(logger=None),
        ensure_personas_from_assistant_text=lambda *_args, **_kwargs: [],
        record_ar_reply=lambda *_args, **_kwargs: None,
        save_active_story_memory_snapshot=lambda: None,
        save_state=lambda: None,
        mprc_play_isolated_active=lambda: bool(isolation["active"]),
    )
    engine = RoleplayEngine(controller)
    engine._record_long_memory = lambda **_kwargs: None
    engine._maybe_auto_visual_reply = lambda *_args, **_kwargs: None

    assert engine.record_assistant_text("Unrelated desktop reply.", source="main_chat") is False
    assert controller.session.turn_index == 0
    assert engine._recent_assistant_texts == []

    controller.session.enabled = True
    isolation["active"] = True
    assert engine.record_assistant_text("Still unrelated.", source="main_chat") is False
    assert controller.session.turn_index == 0

    assert engine.record_assistant_text(
        "[NARRATOR] The actual story opens.",
        source="mprc_play",
        user_text="Open the lantern door.",
    ) is True
    assert controller.session.turn_index == 1
    assert engine._recent_assistant_texts == ["[NARRATOR] The actual story opens."]
    assert engine._latest_user_input_text == "Open the lantern door."


def _smoke_master_story_creator_context_controls() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        controller = _new_controller(Path(tmp) / "storage")
        controller.settings.update(
            {
                "master_story_mode": "RPG / Game Master mode",
                "master_story_scene_title": "Lantern Threshold",
                "master_story_location": "Sunken archive",
                "master_story_time_of_day": "Storm-lit midnight",
                "master_story_mood": "Watchful and uncanny",
            }
        )
        page = controller._build_master_story_tab()
        try:
            mode = controller._controls["master_story_mode"]
            assert [mode.itemText(index) for index in range(mode.count())] == list(SESSION_MODES)
            assert mode.currentText() == "RPG / Game Master mode"
            assert controller._controls["master_story_scene_title"].text() == "Lantern Threshold"
            assert controller._controls["master_story_location"].text() == "Sunken archive"
            assert controller._controls["master_story_time_of_day"].text() == "Storm-lit midnight"
            assert controller._controls["master_story_mood"].text() == "Watchful and uncanny"

            snapshot = controller._master_story_generation_snapshot("Open a strange archive story.")
            assert snapshot["mode"] == "RPG / Game Master mode"
            assert snapshot["scene_context"] == {
                "scene_title": "Lantern Threshold",
                "location": "Sunken archive",
                "time_of_day": "Storm-lit midnight",
                "mood": "Watchful and uncanny",
            }
            payload = controller._apply_master_story_creator_context(
                _valid_master_story_payload(2),
                snapshot["scene_context"],
                mode=snapshot["mode"],
            )
            assert payload["mode"] == "RPG / Game Master mode"
            assert payload["session"]["scene_title"] == "Lantern Threshold"
            assert payload["session"]["location"] == "Sunken archive"
            assert payload["session"]["time_of_day"] == "Storm-lit midnight"
            assert payload["session"]["mood"] == "Watchful and uncanny"
        finally:
            page.deleteLater()
            app.processEvents()


def _smoke_master_story_apply_is_clean_saved_and_complete() -> None:
    controller = _master_story_apply_probe(max_created=4, allow_exceed=True)
    narrator = PersonaConfig.from_dict(
        {
            "id": "story_narrator",
            "display_name": "Story Narrator",
            "role": "narrator",
            "enabled": False,
        }
    )
    controller.personas = [narrator]
    controller._mprc_play_active = True
    controller._mprc_chat_history = [{"role": "assistant", "content": "Old unrelated reply."}]
    controller._mprc_pending_chat_users = {"old": {"role": "user", "content": "Old input."}}
    controller.roleplay_engine._recent_assistant_texts = ["Old unrelated reply."]
    payload = _story_payload_with_personas(2)
    payload["mode"] = AR_MODE
    payload["session"]["ar_state"] = {"active_characters": ["draft_1"]}

    result = controller._apply_master_story_payload(payload, apply_plan=_apply_plan())

    assert result["created"] == 2
    assert result["linked"] == ["draft_1", "draft_2", "story_narrator"]
    assert controller.settings["narrator_persona_id"] == "story_narrator"
    assert set(controller.session.ar_state.active_characters) == set(result["linked"])
    assert controller.session.enabled is False
    assert controller.mprc_play_isolated_active() is False
    assert controller._mprc_chat_history == []
    assert controller._mprc_pending_chat_users == {}
    assert controller.roleplay_engine._recent_assistant_texts == []
    assert list(controller._saved_story_payloads) == ["limit_story"]
    assert controller._saved_memory_story_ids == ["limit_story"]
    assert controller._saved_story_payloads["limit_story"]["narrator_persona_id"] == "story_narrator"


def _smoke_master_story_load_preserves_saved_memory_and_pauses() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        controller = _new_controller(Path(tmp) / "storage")
        page = controller._build_master_story_tab()
        try:
            story = _valid_master_story_payload(2)
            story["id"] = "remembered_story"
            story["title"] = "Remembered Story"
            story_id = controller.storage.save_story(story)
            controller.settings.update(
                {
                    "last_master_story_id": story_id,
                    "last_master_story_title": story["title"],
                    "master_story_linked_persona_ids": ["draft_1", "draft_2"],
                }
            )
            controller.session = RoleplaySessionState.from_dict(
                {
                    "enabled": True,
                    "mode": AR_MODE,
                    "turn_index": 4,
                    "scene_title": "Remembered opening",
                    "recent_events": ["A story-specific event."],
                }
            )
            controller._save_story_memory_snapshot(story_id)
            assert controller.storage.load_story_memory(story_id)["session"]["turn_index"] == 4

            controller.session.turn_index = 99
            controller.session.recent_events = ["Unrelated current runtime event."]
            controller._populate_master_stories()
            combo = controller._controls["master_story_list"]
            index = combo.findData(story_id)
            assert index >= 0
            combo.setCurrentIndex(index)
            controller._load_selected_master_story()

            assert controller.session.turn_index == 4
            assert controller.session.recent_events == ["A story-specific event."]
            assert controller.session.enabled is False
            assert controller.mprc_play_isolated_active() is False
            assert controller.storage.load_story_memory(story_id)["session"]["turn_index"] == 4
        finally:
            page.deleteLater()
            app.processEvents()


def _smoke_master_story_cast_isolation_and_snapshot() -> None:
    controller = _master_story_apply_probe(max_created=4, allow_exceed=True)
    outside = PersonaConfig.from_dict({"id": "outside_cast", "display_name": "Outside Cast"})
    controller.personas = [outside]
    payload = _story_payload_with_personas(2)
    payload["mode"] = AR_MODE
    payload["narrator_persona_id"] = "draft_1"
    payload["session"]["ar_state"] = {
        "active_characters": ["draft_1", "outside_cast", "draft_2"],
        "current_scene": "A clean new story scene.",
    }
    result = controller._apply_master_story_payload(payload, apply_plan=_apply_plan())
    assert result["linked"] == ["draft_1", "draft_2"]
    assert controller.session.ar_state.active_characters == ["draft_1", "draft_2"]

    controller.settings["master_story_linked_persona_ids"] = list(result["linked"])
    controller.settings["narrator_persona_id"] = "draft_1"
    controller.settings["narrator_persona_mode"] = "explicit"
    controller._normalize_master_story_payload = lambda value: dict(value or {})
    snapshot = controller._current_master_story_snapshot()
    assert [item["id"] for item in snapshot["personas"]] == ["draft_1", "draft_2"]

    legacy_snapshot = _story_payload_with_personas(8)
    legacy_snapshot["generation"] = {
        "source": "master_story_creator",
        "requested_persona_count": 3,
        "max_created_characters": 3,
    }
    for index, persona_payload in enumerate(legacy_snapshot["personas"]):
        persona_payload["enabled"] = index < 3
    compacted, removed = controller._compact_legacy_registry_story_snapshot(legacy_snapshot)
    assert removed == 5
    assert [item["id"] for item in compacted["personas"]] == ["draft_1", "draft_2", "draft_3"]

    controller.settings["master_story_linked_persona_ids"] = ["outside_cast", "draft_1", "draft_2"]
    controller.settings["master_story_created_persona_ids"] = ["outside_cast", "draft_2"]
    controller.settings["master_story_persona_overrides"] = {
        "outside_cast": {"role": "stale"},
        "draft_2": {"role": "current"},
    }
    controller.session.active_persona_id = "outside_cast"
    controller.session.current_speaker_id = "outside_cast"
    controller.session.ar_state.active_characters = ["outside_cast", "draft_1"]
    assert controller._restrict_restored_story_memory_to_cast(["draft_1", "draft_2"])
    assert controller.settings["master_story_linked_persona_ids"] == ["draft_1", "draft_2"]
    assert controller.settings["master_story_created_persona_ids"] == ["draft_2"]
    assert list(controller.settings["master_story_persona_overrides"]) == ["draft_2"]
    assert controller.session.active_persona_id == "draft_1"
    assert controller.session.current_speaker_id == "draft_1"
    assert controller.session.ar_state.active_characters == ["draft_1"]

    controller.settings["narrator_persona_id"] = "outside_cast"
    controller.settings["narrator_persona_mode"] = "explicit"
    assert controller._restrict_restored_story_memory_to_cast(["draft_1", "draft_2"])
    assert controller.settings["narrator_persona_id"] == ""
    assert controller.settings["narrator_persona_mode"] == "auto"


def _smoke_master_story_auto_voice_assignment() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        narrator_voice = root / "female audiobook narrator.wav"
        spy_voice = root / "cunning female spy.wav"
        hero_voice = root / "young male hero.wav"
        for path in (narrator_voice, spy_voice, hero_voice):
            path.write_bytes(b"RIFF0000WAVE")

        controller = _master_story_apply_probe(max_created=4, allow_exceed=True)
        controller.settings["master_story_auto_assign_voices"] = True
        controller._voice_sample_wav_files = lambda: [narrator_voice, spy_voice, hero_voice]
        payload = _story_payload_with_personas(3)
        payload["mode"] = AR_MODE
        payload["narrator_persona_id"] = "draft_1"
        payload["personas"][0].update({"display_name": "Story Narrator", "role": "narrator"})
        payload["personas"][1].update({"display_name": "Mara", "role": "cunning female spy"})
        payload["personas"][2].update({"display_name": "Rowan", "role": "young male hero"})
        payload["session"]["ar_state"] = {"active_characters": ["draft_1", "draft_2", "draft_3"]}
        plan = _apply_plan()
        plan["auto_assign_voices"] = True
        result = controller._apply_master_story_payload(payload, apply_plan=plan)
        assert result["created"] == 3
        assigned = [persona.voice.sample_path for persona in controller.personas]
        assert len(set(assigned)) == 3
        assert Path(controller.persona_by_id("draft_1").voice.sample_path).name == narrator_voice.name
        assert all(persona.voice.enabled for persona in controller.personas)

        controller.settings["narrator_persona_id"] = "draft_1"
        controller.settings["narrator_persona_mode"] = "explicit"
        controller.session.enabled = True
        controller.current_tts_backend = lambda: "chatterbox"
        controller.ensure_personas_from_assistant_text = lambda *_args, **_kwargs: []
        router = PersonaVoiceRouter(controller)
        routed = router.split_text_by_persona(
            {
                "text": "[NARRATOR] The door opens.\n[CHARACTER: Mara] Stay close.\n[CHARACTER: Rowan] I will lead.",
                "tts_backend": "chatterbox",
                "streaming": False,
            }
        )
        voice_paths = [str(item.get("voice_path") or "") for item in routed.get("segments") or []]
        assert len(voice_paths) == 3
        assert len(set(voice_paths)) == 3
        assert all(voice_paths)

        repaired = controller.persona_by_id("draft_3")
        repaired.voice.enabled = False
        repaired.voice.sample_path = ""
        controller.settings["master_story_linked_persona_ids"] = list(result["linked"])
        controller.settings["master_story_created_persona_ids"] = list(result["linked"])
        assert controller._assign_missing_master_story_voices() == 1
        assert repaired.voice.enabled is True
        assert repaired.voice.sample_path
        assert repaired.voice.sample_path not in {
            controller.persona_by_id("draft_1").voice.sample_path,
            controller.persona_by_id("draft_2").voice.sample_path,
        }


def _smoke_master_story_apply_voice_and_avatar_prompt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        voice_path = Path(tmp) / "story_voice.wav"
        voice_path.write_bytes(b"RIFF0000WAVE")
        prompt_override = "single avatar portrait of Draft One, copper coat, lantern light, no text"
        controller = _master_story_apply_probe(max_created=2, allow_exceed=True)
        payload = _story_payload_with_personas(1)
        plan = _apply_plan()
        plan["draft_voice_paths_by_row"] = {"0": str(voice_path)}
        plan["draft_avatar_prompts_by_row"] = {"0": prompt_override}
        result = controller._apply_master_story_payload(payload, apply_plan=plan)
        assert result["created"] == 1
        assert result["linked"] == [controller.personas[0].id]
        persona = controller.personas[0]
        assert persona.voice.enabled is True
        assert persona.voice.sample_path == str(voice_path)
        saved_persona = controller._master_story_draft["personas"][0]
        assert saved_persona["voice"]["sample_path"] == str(voice_path)
        assert saved_persona["avatar_prompt_override"] == prompt_override
        assert controller._story_avatar_prompt(persona, controller._master_story_draft) == prompt_override


def _smoke_master_story_apply_dialog_builds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        controller = _new_controller(Path(tmp) / "storage")
        payload = _valid_master_story_payload(1)
        original_exec = QtWidgets.QDialog.exec
        QtWidgets.QDialog.exec = lambda self: QtWidgets.QDialog.Rejected
        try:
            result = controller._show_master_story_apply_dialog(payload)
            app.processEvents()
        finally:
            QtWidgets.QDialog.exec = original_exec
        assert result is None


def _smoke_master_story_persona_activation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        voice_path = Path(tmp) / "draft_voice.wav"
        voice_path.write_bytes(b"RIFF0000WAVE")
        controller = _master_story_apply_probe(max_created=4, allow_exceed=True)
        extra = PersonaConfig.from_dict({"id": "outside_cast", "display_name": "Outside Cast"})
        extra.enabled = True
        controller.personas = [extra]
        payload = _story_payload_with_personas(1)
        payload["personas"][0]["voice"] = {"enabled": False, "backend": "chatterbox", "sample_path": str(voice_path)}
        result = controller._apply_master_story_payload(payload, apply_plan=_apply_plan())
        assert result["linked"] == ["draft_1"]
        story_persona = controller.persona_by_id("draft_1")
        assert story_persona is not None
        assert story_persona.enabled is True
        assert story_persona.voice.enabled is True
        assert story_persona.voice.sample_path == str(voice_path)
        assert extra.enabled is False
        assert controller.settings.get("current_character_view_mode") == "active_story"
        assert [persona.id for persona in controller._current_character_roster_personas()] == ["draft_1"]
        controller.settings["current_character_view_mode"] = "all"
        assert [persona.id for persona in controller._current_character_roster_personas()] == ["outside_cast", "draft_1"]


def _smoke_master_narrator_controls() -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    plain = PersonaConfig.from_dict({"id": "plain", "display_name": "Plain", "role": "guide"})
    master_one = PersonaConfig.from_dict({"id": "fav_narrator", "display_name": "Favorite Narrator", "master_narrator": True})
    master_two = PersonaConfig.from_dict({"id": "second_narrator", "display_name": "Second Narrator", "master_narrator": True})
    assert master_one.to_dict()["master_narrator"] is True
    assert MultiPersonaRoleplayController._persona_narrator_score(master_one) > MultiPersonaRoleplayController._persona_narrator_score(
        PersonaConfig.from_dict({"id": "story_narrator", "display_name": "Story Narrator"})
    )

    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = [plain, master_one, master_two]
    probe.session = RoleplaySessionState.from_dict({"enabled": True, "mode": AR_MODE})
    probe.settings = {"narrator_persona_mode": "auto"}
    probe._ensure_session_persona = lambda: None
    ordered = probe._ordered_voice_selector_personas()
    assert [persona.id for persona in ordered[:2]] == ["fav_narrator", "second_narrator"]
    assert probe._master_narrator_number(master_two) == 2
    assert "Favorite Narrator #1" in probe._persona_voice_selector_label(master_one)
    assert probe.selected_narrator_persona_id() == "fav_narrator"

    warnings: list[tuple[str, str]] = []
    probe.session.active_persona_id = "fav_narrator"
    probe._selected_persona = lambda: master_one
    probe._warn = lambda title, message: warnings.append((title, message))
    probe.save_state = lambda: (_ for _ in ()).throw(AssertionError("protected delete should not save"))
    probe.refresh_ui = lambda: None
    probe._delete_persona()
    assert [persona.id for persona in probe.personas] == ["plain", "fav_narrator", "second_narrator"]
    assert warnings and "protected" in warnings[0][1].lower()


def _smoke_master_story_json_validation_and_sfw() -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    probe = _master_story_validation_probe(native_count=3, max_created=2, sfw=True)
    duplicate_payload, duplicate_errors = probe._parse_master_story_json_text(
        '{"id":"story_one","title":"Good","mode":"AlternativeReality","session":{},"personas":[],"id":"bad"}'
    )
    assert isinstance(duplicate_payload, dict)
    assert any("Duplicate JSON key 'id'" in item for item in duplicate_errors)
    _overwritten, overwrite_errors = probe._parse_master_story_json_text(
        '{"id":"story_one","title":"Good","mode":"AlternativeReality","session":{},"personas":[{"id":"a"}],"personas":[]}'
    )
    assert any("Duplicate JSON key 'personas'" in item for item in overwrite_errors)

    mixed, mixed_errors = probe._canonical_master_story_payload(
        {
            "task": "Draft a Master Story setup from the user's prompt.",
            "id": "bad_wrapper",
            "draft": _valid_master_story_payload(3),
        }
    )
    assert mixed["id"] == "story_one"
    assert any("mixes wrapper fields" in item for item in mixed_errors)

    normalized = probe._normalize_master_story_payload(_valid_master_story_payload(3, sfw=False))
    assert len(normalized["personas"]) == 3
    assert normalized["content_safety"]["sfw"] is False
    assert normalized["content_safety"]["allow_explicit_sexual_content"] is False
    assert normalized["generation"]["requested_story_native_personas"] == 3
    warning = probe._master_story_generated_persona_limit_warning(normalized)
    assert "This draft contains 3 personas, but only 2 new personas will be created unless override is enabled." in warning

    old_normalized = probe._normalize_master_story_payload(_valid_master_story_payload(3, include_content_safety=False))
    assert old_normalized["content_safety"]["sfw"] is True

    safe_text = probe._master_story_safety_normalized_prompt(
        "Explore inter-racial relationships and sexual activity across enemy lines.",
        sfw=True,
    )
    assert "sexual activity" not in safe_text.lower()
    assert "forbidden relationships" in safe_text.lower()

    invalid_probe = _master_story_validation_probe(native_count=3, max_created=2, sfw=True)
    invalid_probe._controls["master_story_draft"] = _TextControl("{not valid json")
    warnings: list[tuple[str, str]] = []
    applied: list[bool] = []
    invalid_probe._warn = lambda title, message: warnings.append((title, message))
    invalid_probe._show_master_story_apply_dialog = lambda payload: {}
    invalid_probe._apply_master_story_payload = lambda payload, apply_plan=None: applied.append(True)
    invalid_probe._apply_master_story_draft()
    assert warnings
    assert not applied


def _smoke_master_story_generation_provider_fallback() -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController
    from core import engine_access

    class FakeEngine:
        RUNTIME_CONFIG = {"model_name": "fake-model"}

        def __init__(self) -> None:
            self.calls: list[tuple[dict, dict]] = []

        def _apply_chat_provider_generation_fields(self, params: dict, additional_params: dict) -> None:
            params["max_tokens"] = -1
            additional_params["top_k"] = 40

        def _chat_completion_create(self, params: dict, additional_params: dict) -> str:
            self.calls.append((dict(params or {}), dict(additional_params or {})))
            if params.get("response_format") is not None:
                raise RuntimeError("HTTP Error 400: Bad Request")
            if additional_params:
                raise RuntimeError("HTTP Error 400: Bad Request")
            return json.dumps(_valid_master_story_payload(1))

    fake = FakeEngine()
    original_engine_module = engine_access.engine_module
    engine_access.engine_module = lambda: fake
    try:
        probe = object.__new__(MultiPersonaRoleplayController)
        probe.context = SimpleNamespace(logger=None)
        payload_text = probe._generate_master_story_payload(
            {
                "prompt": "Create a small mystery setup.",
                "safe_prompt": "Create a small mystery setup.",
                "visual_direction": "",
                "constraints": {
                    "native_personas_to_draft": 1,
                    "maximum_new_personas_to_create": 2,
                    "use_existing_personas": False,
                    "auto_create_missing_personas": True,
                    "sfw_mode": True,
                },
                "content_safety": {
                    "sfw": True,
                    "allow_romance": True,
                    "allow_mature_themes": False,
                    "allow_explicit_sexual_content": False,
                },
                "safety_instruction": MultiPersonaRoleplayController._master_story_safety_instruction(True),
                "roster": [],
                "use_ar": True,
            }
        )
    finally:
        engine_access.engine_module = original_engine_module

    assert json.loads(payload_text)["id"] == "story_one"
    assert len(fake.calls) == 3
    assert fake.calls[0][0].get("response_format") == {"type": "json_object"}
    assert "response_format" not in fake.calls[1][0]
    assert fake.calls[1][1].get("top_k") == 40
    assert "response_format" not in fake.calls[2][0]
    assert fake.calls[2][1] == {}


def _smoke_story_library_export_package() -> None:
    with tempfile.TemporaryDirectory() as export_tmp, tempfile.TemporaryDirectory() as import_tmp:
        export_root = Path(export_tmp)
        controller = _new_controller(export_root / "storage")
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        card = controller._build_story_export_card()
        assert card is not None
        assert controller._controls.get("story_export_button") is not None
        assert controller._controls.get("story_import_button") is not None
        assert controller._controls.get("story_export_options")
        app.processEvents()
        avatar_path = export_root / "mentor_avatar.png"
        voice_path = export_root / "mentor_voice.wav"
        audio_path = export_root / "rain_loop.wav"
        avatar_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        voice_path.write_bytes(b"RIFF0000WAVE")
        audio_path.write_bytes(b"RIFF1111WAVE")

        persona = controller.personas[0]
        persona.character_image_path = str(avatar_path)
        persona.voice.enabled = True
        persona.voice.backend = "chatterbox"
        persona.voice.sample_path = str(voice_path)
        persona.visual.enabled = True
        persona.visual.mode = "manual"
        persona.visual.style_preset = "cinematic_test"
        controller.visual_styles = [{"id": "cinematic_test", "label": "Cinematic Test", "prompt": "cinematic story image"}]
        controller.session.enabled = True
        controller.session.mode = AR_MODE
        controller.session.active_persona_id = persona.id
        controller.session.current_speaker_id = persona.id
        controller.session.scene_title = "Package Scene"
        controller.session.location = "Archive"
        controller.session.ar_state.active_characters = [persona.id]
        controller.settings["last_master_story_id"] = "package_story"
        controller.settings["last_master_story_title"] = "Package Story"
        controller.settings["master_story_linked_persona_ids"] = [persona.id]
        controller.settings["audio_fx_items"] = [
            {
                "id": "rain_loop",
                "type": "Ambience",
                "description": "rain loop",
                "prompt": "soft rain loop",
                "file_path": str(audio_path),
            }
        ]
        controller._save_audiofx_items(controller.settings["audio_fx_items"])
        story = controller._current_master_story_snapshot()
        story["id"] = "package_story"
        story["title"] = "Package Story"
        controller.storage.save_story(story)
        controller.long_memory.save({"events": [{"summary": "The rain started."}], "pinned_facts": ["The archive key is brass."]})
        controller._save_story_memory_snapshot("package_story")
        controller._record_story_event("package smoke event", kind="smoke", persist=True)

        availability = controller._story_export_availability()
        assert availability["story_setup"]["available"]
        assert availability["personas"]["available"]
        assert availability["avatar_assets"]["available"]
        assert availability["voice_assets"]["available"]
        assert availability["audiofx_assets"]["available"]
        assert availability["visual_styles"]["available"]

        package_path = export_root / "package_story.mprcstory.zip"
        manifest, warnings = controller._write_story_package(package_path)
        assert package_path.exists()
        assert manifest["package_schema_version"] == 1
        assert "avatar_assets" in manifest["included_sections"]
        assert "voice_assets" in manifest["included_sections"]
        assert not warnings
        with zipfile.ZipFile(package_path, "r") as handle:
            names = set(handle.namelist())
            assert "manifest.json" in names
            assert "personas.json" in names
            assert "avatar_images.json" in names
            assert "story_memory.json" in names
            assert any(name.startswith("assets/visuals/") for name in names)
            assert any(name.startswith("assets/voices/") for name in names)
            assert any(name.startswith("assets/audiofx/") for name in names)
            loaded_manifest = json.loads(handle.read("manifest.json").decode("utf-8"))
            assert loaded_manifest["asset_file_map"]

        session_only_path = export_root / "session_only.mprcstory.zip"
        controller._write_story_package(session_only_path, ["story_setup"])
        with zipfile.ZipFile(session_only_path, "r") as handle:
            names = set(handle.namelist())
            assert "session.json" in names
            assert "personas.json" not in names

        original_voice = persona.voice.sample_path
        persona.voice.sample_path = str(export_root / "missing_voice.wav")
        _missing_manifest, missing_warnings = controller._write_story_package(export_root / "missing_voice.mprcstory.zip", ["personas", "persona_voice", "voice_assets"])
        persona.voice.sample_path = original_voice
        assert any("Missing voice sample" in item for item in missing_warnings)

        importer = _new_controller(Path(import_tmp) / "storage")
        result = importer._apply_story_package(package_path)
        assert result["story_id"]
        imported_personas = [item for item in importer.personas if item.display_name.endswith("(Imported)")]
        assert imported_personas
        imported_avatar = next((item.character_image_path for item in imported_personas if item.character_image_path), "")
        assert imported_avatar and Path(imported_avatar).exists()
        imported_voice = next((item.voice.sample_path for item in imported_personas if item.voice.sample_path), "")
        assert imported_voice and Path(imported_voice).exists()
        imported_audio = [item for item in importer._audiofx_items() if item.get("description") == "rain loop"]
        assert imported_audio and Path(str(imported_audio[0].get("file_path") or "")).exists()
        voice_parts = set(Path(imported_voice).parts)
        audio_parts = set(Path(str(imported_audio[0].get("file_path") or "")).parts)
        assert {"assets", "story_packages", "imported", "voices"}.issubset(voice_parts)
        assert {"assets", "story_packages", "imported", "audiofx"}.issubset(audio_parts)
        imported_voice_parent = Path(imported_voice).parent
        imported_audio_parent = Path(str(imported_audio[0].get("file_path") or "")).parent
        importer._apply_story_package(package_path)
        imported_voice_paths = [
            Path(item.voice.sample_path)
            for item in importer.personas
            if item.display_name.endswith("(Imported)") and item.voice.sample_path
        ]
        imported_audio_paths = [
            Path(str(item.get("file_path") or ""))
            for item in importer._audiofx_items()
            if item.get("description") == "rain loop" and item.get("file_path")
        ]
        assert imported_voice_paths
        assert imported_audio_paths
        assert all(path.parent == imported_voice_parent for path in imported_voice_paths)
        assert all(path.parent == imported_audio_parent for path in imported_audio_paths)
        assert importer.storage.load_story(result["story_id"])
        assert importer.storage.load_story_memory(result["story_id"])

        partial_importer = _new_controller(Path(import_tmp) / "partial_storage")
        partial_result = partial_importer._apply_story_package(session_only_path)
        assert partial_result["warnings"] == []


def _smoke_refine_rejects_structured_story_output() -> None:
    from PySide6 import QtWidgets
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = QtWidgets.QPlainTextEdit()
    widget.setPlainText("Original story prompt")
    warnings: list[tuple[str, str]] = []
    original_warning = QtWidgets.QMessageBox.warning
    QtWidgets.QMessageBox.warning = lambda _parent, title, message: warnings.append((str(title), str(message)))
    try:
        probe = object.__new__(MultiPersonaRoleplayController)
        probe._refine_widgets = {"refine_test": lambda: widget}
        probe._finish_worker_token = lambda _token: True
        structured = json.dumps(
            {
                "schema_version": "mprc.story_output.v1",
                "response_type": "story_turn",
                "segments": [{"role": "narrator", "text": "This is not a refined prompt."}],
            }
        )
        probe._on_field_refined("refine_test", "Master Story Prompt", structured, "")
        app.processEvents()
    finally:
        QtWidgets.QMessageBox.warning = original_warning
        widget.deleteLater()

    assert widget.toPlainText() == "Original story prompt"
    assert warnings
    assert "structured MPRC story response" in warnings[0][1]


def _smoke_persona_editor_identity_commit_is_quiet() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        controller = _new_controller(Path(tmp) / "storage")
        tab = controller._build_editor_tab()
        assert tab is not None
        persona = controller.active_persona()
        assert persona is not None
        controller._syncing = True
        try:
            controller._populate_editor(persona)
        finally:
            controller._syncing = False
        original_name = persona.display_name
        display = controller._controls["display_name"]
        role = controller._controls["role"]

        display.setText("Quiet Draft Name")
        app.processEvents()
        assert persona.display_name == original_name

        role.setText("quiet role")
        controller._commit_scheduled_editor()
        assert persona.role == "quiet role"
        assert persona.display_name == original_name

        display.setText("")
        controller._commit_scheduled_editor()
        assert persona.display_name == original_name

        display.setText("Quiet Final Name")
        controller._commit_editor_now(include_identity=True)
        assert persona.display_name == "Quiet Final Name"


def _smoke_tab_text_inputs_commit_quietly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        controller = _new_controller(Path(tmp) / "storage")
        tabs = []
        for builder in (
            controller._build_voice_tab,
            controller._build_session_tab,
            controller._build_ar_tab,
            controller._build_audio_tab,
            controller._build_visual_tab,
        ):
            tab = builder()
            assert tab is not None
            tabs.append(tab)
        persona = controller.active_persona()
        assert persona is not None
        controller._syncing = True
        try:
            controller._refresh_persona_selectors()
            controller._refresh_voice_persona_selector()
            controller._populate_voice(persona)
            controller._populate_session()
            controller._populate_ar()
            controller._populate_audio()
            controller._populate_visual(persona)
        finally:
            controller._syncing = False

        mode_note = controller._controls.get("session_mode_note")
        assert mode_note is not None
        controller._controls["session_mode"].setCurrentText(AR_MODE)
        app.processEvents()
        assert "Narrator-led interactive story mode" in mode_note.text()

        controller._controls["voice_sample"].setText("Q:/quiet/voice.wav")
        app.processEvents()
        assert persona.voice.sample_path != "Q:/quiet/voice.wav"
        controller._commit_voice_now()
        assert persona.voice.sample_path == "Q:/quiet/voice.wav"

        controller._controls["scene_title"].setText("Quiet Scene")
        app.processEvents()
        assert controller.session.scene_title != "Quiet Scene"
        controller._commit_session_now(refresh_ui=False)
        assert controller.session.scene_title == "Quiet Scene"

        controller._controls["ar_current_scene"].setText("Quiet AR Scene")
        app.processEvents()
        assert controller.session.ar_state.current_scene != "Quiet AR Scene"
        controller._commit_ar_state_now()
        assert controller.session.ar_state.current_scene == "Quiet AR Scene"

        controller._controls["audio_sound_description"].setPlainText("quiet ambience")
        app.processEvents()
        assert controller.settings.get("audio_prompt_description") != "quiet ambience"
        controller._commit_audio_settings_now()
        assert controller.settings.get("audio_prompt_description") == "quiet ambience"

        controller._controls["visual_model"].setText("quiet-model")
        app.processEvents()
        assert persona.visual.model != "quiet-model"
        controller._commit_visual_now()
        assert persona.visual.model == "quiet-model"


def _smoke_chat_play_voice_volume() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        controller = _new_controller(Path(tmp) / "storage")
        page = controller._build_chat_play_tab()
        assert page is not None
        slider = controller._controls.get("chat_voice_volume")
        value = controller._controls.get("chat_voice_volume_value")
        assert slider is not None
        assert value is not None
        assert slider.value() == 100
        slider.setValue(37)
        app.processEvents()
        assert controller.settings.get("mprc_voice_volume") == 37
        assert value.text() == "37%"
        assert controller.mprc_voice_volume_percent() == 37
        controller.personas = _personas()
        controller.session.enabled = True
        controller.session.mode = AR_MODE
        controller.settings["narrator_persona_id"] = "story_narrator"
        segments = controller._mprc_chat_reply_voice_segments("[NARRATOR]\nThe lantern speaks.")
        assert segments
        assert segments[0].get("voice_volume_percent") == 37
        assert segments[0].get("voice_volume") == 0.37
        assert segments[0].get("voice_route", {}).get("volume_percent") == 37

        class _FakeEngine:
            tts_model = object()

            def __init__(self):
                self.calls = []

            def speak_async(self, text, text_iterable=None, **_kwargs):
                self.calls.append((text, list(text_iterable or [])))
                return SimpleNamespace(cancel=lambda: None)

        fake_engine = _FakeEngine()
        from core import engine_access

        original_engine_module = engine_access.engine_module

        def run_sync(_token, target, *, name):
            target()
            return True

        try:
            engine_access.engine_module = lambda: fake_engine
            controller._start_daemon_worker = run_sync
            controller._speak_mprc_chat_reply("[NARRATOR]\nThe lantern answers.")
        finally:
            engine_access.engine_module = original_engine_module
        assert fake_engine.calls
        _spoken_text, spoken_segments = fake_engine.calls[-1]
        assert spoken_segments
        assert spoken_segments[0].get("voice_volume_percent") == 37
        assert spoken_segments[0].get("voice_route", {}).get("volume_percent") == 37


def _smoke_chat_play_voice_focus_toolbar_layout() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        controller = _new_controller(Path(tmp) / "storage")
        page = controller._build_chat_play_tab()
        app.processEvents()
        assert page is not None
        visible_row = controller._controls.get("chat_toolbar_voice_focus_row")
        advanced = controller._controls.get("chat_toolbar_advanced")
        assert visible_row is not None
        assert advanced is not None
        assert controller._controls.get("chat_toolbar_voice_card") is None
        for key in (
            "chat_voice_volume",
            "chat_voice_volume_value",
            "chat_voice_volume_popout",
            "chat_intent",
            "chat_speaker",
        ):
            widget = controller._controls.get(key)
            assert widget is not None, key
            assert visible_row.isAncestorOf(widget), key
            assert not advanced.isAncestorOf(widget), key


def _smoke_chat_play_story_engine_cards() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        controller = _new_controller(Path(tmp) / "storage")
        controller.personas = _personas()
        controller.session = RoleplaySessionState.from_dict(
            {
                "enabled": True,
                "mode": AR_MODE,
                "active_persona_id": "mentor",
                "current_speaker_id": "friend",
                "scene_title": "Lantern Door",
                "location": "Archive corridor",
                "objective": "Open the sealed lantern door.",
                "ar_state": {
                    "current_scene": "A sealed door waits at the end of the archive corridor.",
                    "location": "Archive corridor",
                    "time_of_day": "Blue hour",
                    "mood": "tense curiosity",
                    "active_characters": ["mentor", "friend"],
                    "recent_events": ["Friend lifted the lantern toward the sigil."],
                    "pending_choices": ["Touch the sigil", "Ask Mentor to inspect it"],
                    "story_goal": "Open the sealed lantern door.",
                },
            }
        )
        controller.settings["narrator_persona_id"] = "story_narrator"
        controller.settings["long_memory_database_backend"] = "sqlite"
        controller.settings["long_memory_databank_sources"] = ["lore/lantern_notes.md"]
        controller._remote_latest_reply_text = (
            "[NARRATOR]\nFriend lifts the lantern toward the broken sigil.\n"
            "[CHARACTER: Friend]\nI can see the hinge now."
        )
        controller._debug_visual_prompt = json.dumps(
            {
                "prompt": "Friend lifting a brass lantern beside a broken archive sigil",
                "persona_id": "friend",
                "reason": "assistant_reply",
            },
            indent=2,
        )
        controller.long_memory.save(
            {
                "events": [{"summary": "The archive door reacted to the lantern."}],
                "pinned_facts": ["The lantern key belongs to the archive door."],
            }
        )

        page = controller._build_chat_play_tab()
        controller._refresh_chat_play_controls()
        app.processEvents()

        assert page is not None
        tabs = controller._controls.get("chat_story_engine_tabs")
        assert tabs is not None
        assert [tabs.tabText(index) for index in range(tabs.count())] == [
            "Story Director",
            "Memory/Data Bank",
            "Visual Beat",
            "Voice Segments",
            "Spotify Music",
        ]
        expected = {
            "chat_story_director_summary": ("Cast mode", "Focused speaker", "Joined cast"),
            "chat_memory_databank_summary": ("SQLite", "lore/lantern_notes.md", "Pinned facts"),
            "chat_visual_beat_summary": ("Latest visible beat", "Friend lifts the lantern", "Archive corridor"),
            "chat_voice_segments_summary": ("Multi-voice contract", "Narrator", "Friend"),
            "chat_spotify_music_summary": ("Spotify Sense", "Story music", "cinematic ambience"),
        }
        for key, snippets in expected.items():
            widget = controller._controls.get(key)
            assert widget is not None, key
            text = widget.toPlainText() if hasattr(widget, "toPlainText") else widget.text()
            for snippet in snippets:
                assert snippet in text, (key, snippet, text)


def _smoke_spotify_story_music_integration() -> None:
    class _SpotifyService:
        def __init__(self):
            self.calls = []

        def invoke_capability(self, capability, payload=None):
            self.calls.append((str(capability or ""), dict(payload or {})))
            return {"ok": True, "started": True, "query": dict(payload or {}).get("query", "")}

    with tempfile.TemporaryDirectory() as tmp:
        spotify = _SpotifyService()
        controller = _new_controller(Path(tmp) / "storage", services={"spotify.sense": spotify})
        controller.personas = _personas()
        controller.session = RoleplaySessionState.from_dict(
            {
                "enabled": True,
                "mode": AR_MODE,
                "active_persona_id": "mentor",
                "current_speaker_id": "friend",
                "scene_title": "Lantern Door",
                "location": "Archive corridor",
                "objective": "Open the sealed lantern door.",
                "ar_state": {
                    "current_scene": "A sealed door waits at the end of the archive corridor.",
                    "location": "Archive corridor",
                    "time_of_day": "Blue hour",
                    "mood": "tense curiosity",
                    "active_characters": ["mentor", "friend"],
                    "recent_events": ["The sigil answered the lantern."],
                    "story_goal": "Open the sealed lantern door.",
                    "tension_level": 6,
                },
            }
        )
        payload = controller._spotify_story_music_payload_for_reply(
            "[NARRATOR]\nFriend lifts the lantern toward the broken sigil as blue dust turns in the air.",
            user_text="Touch the sigil",
        )
        assert payload["event"] == "story_turn"
        assert payload["source"] == "multi_persona_roleplay"
        assert payload["music_kind"] == "ambient"
        assert payload["mood"] == "mystery"
        assert payload["query"] == "mysterious cinematic ambient story ambience"
        assert payload["prefer_ambient"] is True
        assert "Friend lifts the lantern" in payload["latest_visible_beat"]

        finished_tokens = []

        def run_sync(token, target, *, name):
            target()
            finished_tokens.append((token, name))
            return True

        controller._start_daemon_worker = run_sync
        controller._maybe_request_spotify_story_music(
            "[NARRATOR]\nFriend lifts the lantern toward the broken sigil as blue dust turns in the air.",
            user_text="Touch the sigil",
        )
        assert spotify.calls
        capability, request = spotify.calls[-1]
        assert capability == "spotify.story_hook"
        assert request["query"] == "mysterious cinematic ambient story ambience"
        assert request["music_kind"] == "ambient"
        assert request["event"] == "story_turn"
        assert finished_tokens and finished_tokens[-1][1] == "nc-mprc-spotify-story-music"
        status = controller._chat_play_spotify_music_summary_text()
        assert "mysterious cinematic ambient story ambience" in status
        assert "started" in status.lower()
        controller._last_spotify_story_music_result = {"ok": True, "transitioning": True, "query": request["query"]}
        transitioning_status = controller._chat_play_spotify_music_summary_text()
        assert "transitioning" in transitioning_status.lower()


def _smoke_output_playback_volume() -> None:
    from core import audio_playback

    class _AudioData:
        def __init__(self, value: float):
            self.value = value

        def __mul__(self, other):
            return _AudioData(self.value * float(other))

    class _SoundFile:
        def read(self, _path):
            return _AudioData(1.0), 24000

    class _Stream:
        active = False

    class _SoundDevice:
        def __init__(self):
            self.played = []

        def play(self, data, sample_rate, device=None):
            self.played.append((data.value, sample_rate, device))

        def get_stream(self):
            return _Stream()

        def stop(self):
            return None

    class _Event:
        def set(self):
            return None

        def clear(self):
            return None

    class _Stop:
        def is_set(self):
            return False

    output = _SoundDevice()
    audio_playback.play_audio_file(
        "fake.wav",
        soundfile_module=_SoundFile(),
        sounddevice_module=output,
        stop_event=_Stop(),
        audio_playing_event=_Event(),
        output_device=3,
        volume=0.25,
        logger=lambda *_args: None,
    )
    assert output.played == [(0.25, 24000, 3)]


class _TextControl:
    def __init__(self, text: str = ""):
        self._text = text

    def toPlainText(self) -> str:
        return self._text

    def setPlainText(self, text: str) -> None:
        self._text = str(text or "")


def _valid_master_story_payload(count: int, *, sfw: bool = True, include_content_safety: bool = True) -> dict:
    payload = {
        "id": "story_one",
        "title": "Story One",
        "summary": "A compact adventure premise.",
        "mode": AR_MODE,
        "active_persona_id": "draft_1",
        "current_speaker_id": "draft_1",
        "session": {"scene_title": "Opening", "location": "Archive"},
        "personas": [
            {
                "id": f"draft_{index}",
                "display_name": f"Draft {index}",
                "role": "story character",
                "system_prompt": "Stay in character and preserve user agency.",
            }
            for index in range(1, count + 1)
        ],
    }
    if include_content_safety:
        payload["content_safety"] = {
            "sfw": bool(sfw),
            "allow_romance": True,
            "allow_mature_themes": not bool(sfw),
            "allow_explicit_sexual_content": False,
        }
    return payload


def _master_story_validation_probe(*, native_count: int, max_created: int, sfw: bool):
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = []
    probe.session = RoleplaySessionState.from_dict({"enabled": True, "mode": AR_MODE})
    probe.settings = {"master_story_sfw_mode": sfw}
    probe._controls = {
        "master_story_sfw_mode": SimpleNamespace(isChecked=lambda: sfw, setChecked=lambda *_args: None),
        "master_story_draft": _TextControl(""),
    }
    probe._syncing = False
    probe.storage = SimpleNamespace(story_id=RoleplayStorage.story_id, save_settings=lambda *_args, **_kwargs: None)
    probe._set_master_story_status = lambda *_args, **_kwargs: None
    probe._control_int_value = lambda key, default, minimum, maximum: native_count if key == "master_story_native_persona_count" else (max_created if key == "master_story_max_created_characters" else default)
    probe._control_checked = lambda key, default=False: sfw if key == "master_story_sfw_mode" else bool(default)
    return probe


def _story_payload_with_personas(count: int) -> dict:
    return {
        "id": "limit_story",
        "title": "Limit Story",
        "mode": "Narrator + characters",
        "session": {
            "scene_title": "Limit Scene",
            "location": "Archive",
            "objective": "Test the cast limit.",
        },
        "personas": [
            {
                "id": f"draft_{index}",
                "display_name": f"Draft {index}",
                "role": "story character",
                "description": "A compact draft character.",
            }
            for index in range(1, count + 1)
        ],
    }


def _apply_plan() -> dict:
    return {
        "skip_backup": True,
        "clear_memory": False,
        "auto_create": True,
        "update_existing": False,
        "auto_avatars": False,
        "avatar_style_sheets": False,
        "auto_assign_voices": False,
    }


def _master_story_apply_probe(*, max_created: int, allow_exceed: bool):
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = []
    probe.session = RoleplaySessionState.from_dict({"enabled": True, "mode": "Narrator + characters"})
    probe.settings = {"master_story_auto_assign_voices": False}
    probe._controls = {}
    probe._syncing = False
    probe.context = SimpleNamespace(logger=None)
    probe._saved_story_payloads = {}
    probe._saved_memory_story_ids = []

    def save_story(payload):
        story_id = RoleplayStorage.story_id(payload.get("id") or payload.get("title") or "master_story")
        probe._saved_story_payloads[story_id] = json.loads(json.dumps(payload))
        return story_id

    probe.storage = SimpleNamespace(
        save_settings=lambda *_args, **_kwargs: None,
        save_story=save_story,
        story_id=RoleplayStorage.story_id,
    )
    probe._master_story_draft = {}
    probe._mprc_play_active = False
    probe._mprc_chat_history = []
    probe._mprc_pending_chat_users = {}
    probe.roleplay_engine = RoleplayEngine(probe)
    probe._ensure_session_persona = lambda: None
    probe._control_int_value = lambda key, default, minimum, maximum: max_created if key == "master_story_max_created_characters" else default
    probe._control_checked = lambda key, default=False: allow_exceed if key == "master_story_allow_exceed_max_created_characters" else bool(default)
    probe._save_pre_apply_backup = lambda *_args, **_kwargs: None
    probe._clear_master_story_runtime_state = lambda *_args, **_kwargs: None
    probe._story_character_summaries = lambda linked_ids: {persona_id: "" for persona_id in linked_ids}
    probe._queue_story_avatar_generation = lambda *_args, **_kwargs: ""
    probe._generate_story_avatar_images = lambda *_args, **_kwargs: ""
    probe._generate_story_avatar_style_sheets = lambda *_args, **_kwargs: ""
    probe.refresh_ui = lambda: None
    probe.save_state = lambda: None
    probe._set_master_story_status = lambda *_args, **_kwargs: None
    probe._record_story_event = lambda *_args, **_kwargs: None
    probe._save_story_memory_snapshot = lambda story_id: probe._saved_memory_story_ids.append(str(story_id or ""))
    return probe


def _smoke_schema_migration() -> None:
    storage = object.__new__(RoleplayStorage)
    storage.logger = None
    legacy_story = storage._migrate_story_payload({"id": "legacy", "title": "Legacy Story"}, "legacy")
    assert legacy_story["schema_version"] == 1
    assert isinstance(legacy_story["session"], dict)
    assert isinstance(legacy_story["personas"], list)
    assert legacy_story.get("_migration_log")

    future_story = storage._migrate_story_payload({"id": "future", "schema_version": 999, "personas": []}, "future")
    assert future_story["schema_version"] == RoleplayStorage.STORY_SCHEMA_VERSION
    assert future_story.get("_migration_log")

    legacy_memory = storage._migrate_story_memory({"story_id": "legacy"}, "legacy")
    assert legacy_memory["schema_version"] == 1
    assert isinstance(legacy_memory["long_memory"], dict)
    assert isinstance(legacy_memory["session"], dict)
    assert legacy_memory.get("_migration_log")


def _smoke_tutorial_doc() -> None:
    path = Path(__file__).resolve().parents[2] / "tutorials" / "multi_persona_roleplay.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["id"] == "multi_persona_roleplay"
    body = "\n".join(str(step.get("body", "")) for step in payload.get("steps") or [])
    assert "Story Health" in body
    assert "Master Story" in body
    assert "Grok/xAI" in body
    assert "Runware" in body
    assert "Voice Routing Check" in body


if __name__ == "__main__":
    run_smoke()
    print("[AR_MODE] smoke test passed")
