from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from addons.buddy_chat.models import (
    BuddyBehaviorProfile,
    BuddyPersona,
    BuddySettings,
)
from addons.buddy_chat.prompting import (
    behavior_instruction,
    build_persona_messages,
    buddy_context_prompt,
    intimacy_instruction,
)
from addons.buddy_chat.response_policy import (
    BUDDY_PASS_TOKEN,
    is_repetitive_secondary,
    normalize_persona_reply,
    recent_speaker_ids,
    select_speakers,
)
from addons.buddy_chat.structured_models import sanitize_structured_buddy_reply


def test_legacy_persona_keeps_behavior_unspecified() -> None:
    persona = BuddyPersona.from_dict({"id": "mira", "display_name": "Mira"})

    assert persona.behavior is None
    assert "behavior" not in persona.to_dict()


def test_behavior_profile_clamps_and_roundtrips() -> None:
    profile = BuddyBehaviorProfile.from_dict(
        {
            "helpfulness": 140,
            "warmth": -10,
            "humor": 61,
            "expressiveness": 77,
            "initiative": 45,
            "directness": 82,
            "disagreement": 55,
            "flirtation": 20,
            "reply_length": "balanced",
            "participation_weight": 125,
        }
    )

    assert profile.helpfulness == 100
    assert profile.warmth == 0
    assert profile.participation_weight == 100
    assert BuddyBehaviorProfile.from_dict(profile.to_dict()) == profile


def test_adult_settings_are_additive_and_off_by_default() -> None:
    settings = BuddySettings.from_dict(
        {"personas": [{"id": "alex", "display_name": "Alex"}]}
    )

    assert settings.adult_nsfw_enabled is False
    assert settings.adult_nsfw_acknowledged is False
    payload = settings.to_dict()
    assert payload["adult_nsfw_enabled"] is False


def test_context_mode_receives_full_character_guidance_without_secrets() -> None:
    persona = BuddyPersona(
        id="mira",
        display_name="Mira",
        role="observant friend",
        description="Notices tension and responds with candid warmth.",
        system_prompt="Challenge avoidance gently instead of agreeing automatically.",
        speaking_style="natural, warm, concise",
        behavior=BuddyBehaviorProfile(
            warmth=88,
            directness=72,
            participation_weight=64,
        ),
    )
    persona.provider.api_key = "secret-key"
    persona.voice.sample_path = "Q:/private/voice.wav"

    context = buddy_context_prompt(BuddySettings(enabled=True, personas=[persona]))

    assert "Notices tension" in context
    assert "Challenge avoidance" in context
    assert "warmth" in context.lower()
    assert "secret-key" not in context
    assert "private/voice.wav" not in context
    assert len(context) <= 7000


def test_legacy_persona_gets_no_structured_behavior_instruction() -> None:
    persona = BuddyPersona(display_name="Alex", behavior=None)

    assert behavior_instruction(persona) == ""


def test_adult_layer_switches_without_rewriting_persona() -> None:
    normal = BuddySettings(adult_nsfw_enabled=False)
    adult = BuddySettings(adult_nsfw_enabled=True)

    assert "non-explicit" in intimacy_instruction(normal)
    assert "adults" in intimacy_instruction(adult).lower()


def test_custom_adult_layer_keeps_generated_adult_only_invariant() -> None:
    settings = BuddySettings.default()
    settings.personas[0].system_prompt = (
        "Keep this exact custom character prompt."
    )
    before = settings.personas[0].system_prompt
    settings.adult_nsfw_enabled = True
    settings.adult_nsfw_prompt = "Use my custom direct adult-mode tone."

    instruction = intimacy_instruction(settings)

    assert "Use my custom direct adult-mode tone." in instruction
    assert "all personas and participants are adults" in instruction.lower()
    assert settings.personas[0].system_prompt == before


def test_long_persona_prompt_cannot_truncate_adult_only_invariant() -> None:
    persona = BuddyPersona(
        id="elara",
        display_name="Elara",
        system_prompt="x" * 20_000,
        behavior=BuddyBehaviorProfile(warmth=91),
    )
    settings = BuddySettings(
        enabled=True,
        adult_nsfw_enabled=True,
        adult_nsfw_prompt="Custom adult tone.",
        personas=[persona],
    )

    messages = build_persona_messages(
        persona=persona,
        settings=settings,
        user_text="Hello",
    )

    assert (
        "all personas and participants are adults"
        in messages[0]["content"].lower()
    )
    assert "warmth 91/100" in messages[0]["content"].lower()


def _buddy(name: str, weight: int) -> BuddyPersona:
    return BuddyPersona(
        id=name.lower(),
        display_name=name,
        behavior=BuddyBehaviorProfile(participation_weight=weight),
    )


def test_explicit_name_beats_weight_and_recency() -> None:
    alex, mira = _buddy("Alex", 90), _buddy("Mira", 20)

    selected = select_speakers(
        personas=[alex, mira],
        user_text="Mira, what do you think?",
        max_speakers=1,
        allow_buddy_to_buddy=True,
        second_speaker_due=False,
        turn_index=0,
        history=[{"role": "assistant", "content": "[Mira] Earlier reply."}],
    )

    assert [item.id for item in selected] == ["mira"]


def test_recent_speaker_penalty_can_select_the_other_buddy() -> None:
    alex, mira = _buddy("Alex", 60), _buddy("Mira", 60)

    selected = select_speakers(
        personas=[alex, mira],
        user_text="Any thoughts?",
        max_speakers=1,
        allow_buddy_to_buddy=True,
        second_speaker_due=False,
        turn_index=0,
        history=[{"role": "assistant", "content": "[Alex] Earlier reply."}],
    )

    assert [item.id for item in selected] == ["mira"]


def test_recent_speaker_order_uses_last_label_in_a_multi_buddy_reply() -> None:
    alex, mira = _buddy("Alex", 60), _buddy("Mira", 60)
    history = [{"role": "assistant", "content": "[Alex] First.\n\n[Mira] Second."}]

    assert recent_speaker_ids(history, [alex, mira]) == ["mira", "alex"]


def test_second_speaker_due_offers_exactly_one_extra_candidate() -> None:
    buddies = [
        _buddy("Alex", 70),
        _buddy("Mira", 60),
        _buddy("Nova", 50),
    ]

    selected = select_speakers(
        personas=buddies,
        user_text="Any ideas?",
        max_speakers=3,
        allow_buddy_to_buddy=True,
        second_speaker_due=True,
        turn_index=0,
        history=[],
    )

    assert len(selected) == 2


def test_explicit_group_request_can_select_up_to_maximum() -> None:
    buddies = [
        _buddy("Alex", 70),
        _buddy("Mira", 60),
        _buddy("Nova", 50),
    ]

    selected = select_speakers(
        personas=buddies,
        user_text="What do all of you think?",
        max_speakers=3,
        allow_buddy_to_buddy=True,
        second_speaker_due=False,
        turn_index=0,
        history=[],
    )

    assert len(selected) == 3


def test_pass_token_never_becomes_visible_reply() -> None:
    alex = BuddyPersona(id="alex", display_name="Alex")

    assert normalize_persona_reply(alex, BUDDY_PASS_TOKEN, [alex]) == ""


def test_wrong_known_label_is_corrected_to_selected_persona() -> None:
    alex = BuddyPersona(id="alex", display_name="Alex")
    mira = BuddyPersona(id="mira", display_name="Mira")

    assert normalize_persona_reply(
        alex,
        "[Mira] Try the smaller model.",
        [alex, mira],
    ) == "[Alex] Try the smaller model."


def test_multi_speaker_result_is_rejected_for_one_persona_call() -> None:
    alex = BuddyPersona(id="alex", display_name="Alex")
    mira = BuddyPersona(id="mira", display_name="Mira")
    text = "[Alex] First thought.\n[Mira] Second thought."

    assert normalize_persona_reply(alex, text, [alex, mira]) == ""


def test_inline_second_speaker_label_is_rejected_for_one_persona_call() -> None:
    alex = BuddyPersona(id="alex", display_name="Alex")
    mira = BuddyPersona(id="mira", display_name="Mira")
    text = "[Alex] First thought. [Mira] Inline second thought."

    assert normalize_persona_reply(alex, text, [alex, mira]) == ""


def test_substantive_duplicate_secondary_is_detected() -> None:
    assert is_repetitive_secondary(
        [
            "Use the smaller local model and reduce the context window "
            "for lower memory use."
        ],
        "Reduce the context window and use a smaller local model "
        "to lower memory use.",
    )


def test_short_reaction_is_not_filtered_as_a_substantive_duplicate() -> None:
    assert not is_repetitive_secondary(
        ["That plan should reduce memory use substantially."],
        "Exactly.",
    )


def test_structured_should_speak_false_produces_no_segment() -> None:
    alex = BuddyPersona(id="alex", display_name="Alex")
    payload = {
        "segments": [
            {
                "persona_id": "alex",
                "display_name": "Alex",
                "text": "Repeated answer",
                "should_speak": False,
            }
        ]
    }

    clean = sanitize_structured_buddy_reply(payload, personas=[alex])

    assert clean["segments"] == []


def run_all() -> None:
    test_legacy_persona_keeps_behavior_unspecified()
    test_behavior_profile_clamps_and_roundtrips()
    test_adult_settings_are_additive_and_off_by_default()
    test_context_mode_receives_full_character_guidance_without_secrets()
    test_legacy_persona_gets_no_structured_behavior_instruction()
    test_adult_layer_switches_without_rewriting_persona()
    test_custom_adult_layer_keeps_generated_adult_only_invariant()
    test_long_persona_prompt_cannot_truncate_adult_only_invariant()
    test_explicit_name_beats_weight_and_recency()
    test_recent_speaker_penalty_can_select_the_other_buddy()
    test_recent_speaker_order_uses_last_label_in_a_multi_buddy_reply()
    test_second_speaker_due_offers_exactly_one_extra_candidate()
    test_explicit_group_request_can_select_up_to_maximum()
    test_pass_token_never_becomes_visible_reply()
    test_wrong_known_label_is_corrected_to_selected_persona()
    test_multi_speaker_result_is_rejected_for_one_persona_call()
    test_inline_second_speaker_label_is_rejected_for_one_persona_call()
    test_substantive_duplicate_secondary_is_detected()
    test_short_reaction_is_not_filtered_as_a_substantive_duplicate()
    test_structured_should_speak_false_produces_no_segment()


if __name__ == "__main__":
    run_all()
    print("smoke_buddy_chat_natural_response: ok")
