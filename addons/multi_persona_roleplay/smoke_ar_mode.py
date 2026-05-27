from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from addons.multi_persona_roleplay.long_memory import RoleplayLongMemory
from addons.multi_persona_roleplay.audio_prompts import create_audio_prompt, infer_audio_type
from addons.multi_persona_roleplay import prompting
from addons.multi_persona_roleplay.models import AR_MODE, SESSION_MODES, VISUAL_MODES, PersonaConfig, RoleplaySessionState
from addons.multi_persona_roleplay.roleplay_engine import RoleplayEngine
from addons.multi_persona_roleplay.storage import RoleplayStorage
from addons.multi_persona_roleplay.voice_routing import PersonaVoiceRouter


def _personas() -> list[PersonaConfig]:
    return [
        PersonaConfig.from_dict({"id": "mentor", "display_name": "Mentor", "role": "mentor"}),
        PersonaConfig.from_dict({"id": "friend", "display_name": "Friend", "role": "friend"}),
        PersonaConfig.from_dict({"id": "story_narrator", "display_name": "Story Narrator", "role": "narrator"}),
    ]


def run_smoke() -> None:
    assert AR_MODE in SESSION_MODES
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
    assert "The user asked to continue" in prompt
    assert "Story Narrator" in prompt
    _smoke_voice_routing(personas, ar_session)
    _smoke_story_only_persona_overrides(personas, ar_session)
    _smoke_visual_reply(personas, ar_session)
    _smoke_audio_prompts()
    _smoke_long_memory(personas, ar_session)
    _smoke_schema_migration()


class _Storage:
    def __init__(self, root: Path):
        self.root = root

    def _read_json(self, relative_path: str, fallback):
        path = self.root / relative_path
        if not path.exists():
            return fallback
        import json

        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, relative_path: str, payload):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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

    def request_generation(self, persona=None, reason: str = "manual"):
        self.calls.append((getattr(persona, "id", ""), reason))
        return {"accepted": True, "message": "ok"}


class _FakeController:
    def __init__(self, personas: list[PersonaConfig], session: RoleplaySessionState):
        self.personas = personas
        self.session = session
        self.visual_reply = _FakeVisualReply()
        self.context = type("Context", (), {"logger": None, "app_root": Path.cwd()})()
        self.settings = {"narrator_persona_id": "story_narrator"}
        self._story_audio_pending_text = ""
        self._story_audio_block_active = False

    def active_persona(self):
        return self.persona_by_id(self.session.active_persona_id) or self.personas[0]

    def current_speaker_persona(self):
        return self.persona_by_id(self.session.current_speaker_id) or self.active_persona()

    def selected_narrator_persona_id(self):
        return str(self.settings.get("narrator_persona_id") or "")

    def selected_narrator_persona(self):
        return self.persona_by_id(self.selected_narrator_persona_id())

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

        from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

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
    assert "auto_choices" in VISUAL_MODES
    personas[0].visual.enabled = True
    personas[0].visual.mode = "auto_choices"
    personas[0].visual.cooldown_seconds = 0
    personas[0].visual.max_auto_images_per_session = 0
    session.active_persona_id = personas[0].id
    session.current_speaker_id = personas[0].id
    session.turn_index = 1
    session.ar_state.pending_choices = ["Open the lantern door", "Step back"]
    visual_prompt = prompting.build_visual_reply_prompt(personas[0], session, reason="choices_present")
    assert "Story scene image for Visual Reply" in visual_prompt
    assert "Current story moment" in visual_prompt

    controller = _FakeController(personas, session)
    engine = RoleplayEngine(controller)
    engine._maybe_auto_visual_reply("[NARRATOR] The lantern door opens.\n[CHOICES]\n- Enter\n- Wait")
    deadline = time.time() + 2.0
    while time.time() < deadline and not controller.visual_reply.calls:
        time.sleep(0.02)
    assert controller.visual_reply.calls == [("mentor", "choices_present")]


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


if __name__ == "__main__":
    run_smoke()
    print("[AR_MODE] smoke test passed")
