from __future__ import annotations

from pathlib import Path
import json
import os
import sys
import tempfile
import time
import zipfile
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController
from addons.multi_persona_roleplay.long_memory import RoleplayLongMemory
from addons.multi_persona_roleplay.audio_prompts import create_audio_prompt, infer_audio_type
from addons.multi_persona_roleplay import prompting
from addons.multi_persona_roleplay.models import AR_MODE, SESSION_MODES, SESSION_MODE_DESCRIPTIONS, VISUAL_MODES, PersonaConfig, RoleplaySessionState
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
    assert set(SESSION_MODES).issubset(set(SESSION_MODE_DESCRIPTIONS))
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
    _smoke_ar_scene_state_update(personas)
    _smoke_audio_prompts()
    _smoke_long_memory(personas, ar_session)
    _smoke_master_story_persona_count_controls()
    _smoke_master_narrator_controls()
    _smoke_master_story_json_validation_and_sfw()
    _smoke_story_library_export_package()
    _smoke_persona_editor_identity_commit_is_quiet()
    _smoke_tab_text_inputs_commit_quietly()
    _smoke_chat_play_voice_volume()
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

    def _write_json(self, relative_path: str, payload):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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


class _AddonContext:
    def __init__(self, root: Path):
        self.logger = None
        self.storage = _AddonStorage(root)
        self.manifest = SimpleNamespace(
            root_dir=str(Path(__file__).resolve().parent),
            version="smoke",
        )

    def get_service(self, _name: str):
        return None


def _new_controller(root: Path) -> MultiPersonaRoleplayController:
    return MultiPersonaRoleplayController(_AddonContext(root))


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
    assert "Active persona identity" in grok_prompt
    assert "Current story moment" not in runware_prompt
    assert "Hidden LLM" not in runware_prompt
    assert len(runware_prompt) < len(grok_prompt)
    assert len(runware_prompt) <= 520

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
    engine = RoleplayEngine(controller)
    engine._maybe_auto_visual_reply("[NARRATOR] The lantern door opens.\n[CHOICES]\n- Enter\n- Wait")
    deadline = time.time() + 2.0
    while time.time() < deadline and not controller.visual_reply.calls:
        time.sleep(0.02)
    assert controller.visual_reply.calls == [
        ("mentor", "choices_present", "[NARRATOR] The lantern door opens.\n[CHOICES]\n- Enter\n- Wait")
    ]


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
    }


def _master_story_apply_probe(*, max_created: int, allow_exceed: bool):
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    probe = object.__new__(MultiPersonaRoleplayController)
    probe.personas = []
    probe.session = RoleplaySessionState.from_dict({"enabled": True, "mode": "Narrator + characters"})
    probe.settings = {}
    probe._controls = {}
    probe._syncing = False
    probe.context = SimpleNamespace(logger=None)
    probe.storage = SimpleNamespace(
        save_settings=lambda *_args, **_kwargs: None,
        story_id=RoleplayStorage.story_id,
    )
    probe._master_story_draft = {}
    probe._ensure_session_persona = lambda: None
    probe._control_int_value = lambda key, default, minimum, maximum: max_created if key == "master_story_max_created_characters" else default
    probe._control_checked = lambda key, default=False: allow_exceed if key == "master_story_allow_exceed_max_created_characters" else bool(default)
    probe._save_pre_apply_backup = lambda *_args, **_kwargs: None
    probe._clear_master_story_runtime_state = lambda *_args, **_kwargs: None
    probe._story_character_summaries = lambda linked_ids: {persona_id: "" for persona_id in linked_ids}
    probe._generate_story_avatar_images = lambda *_args, **_kwargs: ""
    probe._generate_story_avatar_style_sheets = lambda *_args, **_kwargs: ""
    probe.refresh_ui = lambda: None
    probe.save_state = lambda: None
    probe._set_master_story_status = lambda *_args, **_kwargs: None
    probe._record_story_event = lambda *_args, **_kwargs: None
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
    assert "Status" in body
    assert "Master Story" in body
    assert "Grok/xAI" in body
    assert "Runware" in body
    assert "Voice Routing Inspector" in body


if __name__ == "__main__":
    run_smoke()
    print("[AR_MODE] smoke test passed")
