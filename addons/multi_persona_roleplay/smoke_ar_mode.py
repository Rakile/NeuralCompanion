from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import time
from types import SimpleNamespace

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
    _smoke_ar_scene_state_update(personas)
    _smoke_audio_prompts()
    _smoke_long_memory(personas, ar_session)
    _smoke_master_story_persona_count_controls()
    _smoke_master_narrator_controls()
    _smoke_master_story_json_validation_and_sfw()
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
