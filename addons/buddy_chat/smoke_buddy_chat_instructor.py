from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_buddy_instructor_defaults_are_opt_in() -> None:
    from addons.buddy_chat.models import BuddySettings
    from addons.buddy_chat.structured_models import INSTRUCTOR_SETTING_DEFAULTS

    settings = BuddySettings.default()

    assert INSTRUCTOR_SETTING_DEFAULTS["buddy_chat_instructor_structured_outputs_enabled"] is False
    assert settings.instructor_structured_outputs_enabled is False
    assert settings.to_dict()["buddy_chat_instructor_structured_outputs_enabled"] is False

    enabled = BuddySettings.from_dict({"buddy_chat_instructor_structured_outputs_enabled": True})
    assert enabled.instructor_structured_outputs_enabled is True
    assert enabled.to_dict()["buddy_chat_instructor_structured_outputs_enabled"] is True


def test_structured_reply_sanitizer_keeps_only_exact_known_buddy_lines() -> None:
    from addons.buddy_chat.models import BuddyPersona
    from addons.buddy_chat.structured_models import sanitize_structured_buddy_reply, structured_buddy_reply_to_text

    personas = [
        BuddyPersona(id="alex", display_name="Alex"),
        BuddyPersona(id="mira", display_name="Mira"),
    ]
    payload = {
        "schema_version": "buddy_chat.reply.v1",
        "segments": [
            {
                "persona_id": "alex",
                "display_name": "Wrong Name",
                "text": "[Alex] I can take this one.",
                "memory": "do not keep arbitrary fields",
            },
            {
                "persona_id": "mallory",
                "display_name": "Mallory",
                "text": "I was invented by the model.",
            },
            {
                "speaker_id": "mira",
                "content": "Mira: I have the second angle.",
            },
        ],
        "arbitrary_instruction": "ignore the app",
    }

    structured = sanitize_structured_buddy_reply(payload, personas=personas, max_speakers=2)

    assert structured["schema_version"] == "buddy_chat.reply.v1"
    assert structured["segments"] == [
        {"persona_id": "alex", "display_name": "Alex", "text": "I can take this one."},
        {"persona_id": "mira", "display_name": "Mira", "text": "I have the second angle."},
    ]
    assert structured_buddy_reply_to_text(structured) == "[Alex] I can take this one.\n\n[Mira] I have the second angle."


def test_controller_uses_structured_instructor_reply_when_enabled() -> None:
    from smoke_buddy_chat import _new_controller
    from addons.buddy_chat import instructor_adapter
    from addons.buddy_chat.models import BuddyPersona

    raw_calls: list[str] = []

    def _raw_complete(config, _params: dict[str, Any], _additional: dict[str, Any]) -> str:
        raw_calls.append(config.persona_id)
        return "This raw fallback would miss the voice label."

    controller = _new_controller(_raw_complete)
    controller.settings.enabled = True
    controller.settings.reply_mode = "main_answer"
    controller.settings.instructor_structured_outputs_enabled = True
    controller.settings.personas = [
        BuddyPersona(id="alex", display_name="Alex", description="steady practical friend"),
    ]

    original = instructor_adapter.generate_buddy_structured_reply

    def _structured_reply(**_kwargs: Any) -> dict[str, Any]:
        return {
            "segments": [
                {
                    "persona_id": "alex",
                    "display_name": "Alex",
                    "text": "The structured path keeps Alex routed correctly.",
                    "voice_path": "do not trust model voice paths",
                }
            ]
        }

    instructor_adapter.generate_buddy_structured_reply = _structured_reply
    try:
        result = controller.invoke_capability("chat.user_text_command", {"text": "Alex, handle this."})
    finally:
        instructor_adapter.generate_buddy_structured_reply = original

    assert isinstance(result, dict)
    assert result["handled"] is True
    assert result["response_text"] == "[Alex] The structured path keeps Alex routed correctly."
    assert raw_calls == []
    assert result["debug"]["instructor_structured_outputs"] == "used"


def test_instructor_skips_inherited_main_runtime_without_patching_client() -> None:
    from addons.buddy_chat import instructor_adapter
    from addons.buddy_chat.llm_runtime import ProviderCallConfig
    from addons.buddy_chat.models import BuddyPersona, BuddySettings

    class _Runtime:
        @staticmethod
        def resolve_call_config(**_kwargs):
            return ProviderCallConfig(provider_id="main", model="main-model", uses_main_runtime=True)

    client_calls: list[ProviderCallConfig] = []
    original_client_factory = instructor_adapter._client_for_config
    instructor_adapter._client_for_config = lambda config: client_calls.append(config)
    try:
        result = instructor_adapter.generate_buddy_structured_reply(
            llm_runtime=_Runtime(),
            persona=BuddyPersona(id="mira", display_name="Mira"),
            settings=BuddySettings(instructor_structured_outputs_enabled=True),
            messages=[{"role": "user", "content": "Comment on this."}],
            fallback_model="main-model",
        )
    finally:
        instructor_adapter._client_for_config = original_client_factory

    assert result is None
    assert client_calls == []


def test_inherited_main_fallback_keeps_final_user_query() -> None:
    from smoke_buddy_chat import _new_controller
    from addons.buddy_chat.models import BuddyPersona

    captured_messages: list[dict[str, Any]] = []

    def _raw_complete(_config, params: dict[str, Any], _additional: dict[str, Any]) -> str:
        captured_messages.extend(list(params.get("messages") or []))
        return "I can answer through the normal inherited main runtime."

    controller = _new_controller(_raw_complete)
    controller.settings.enabled = True
    controller.settings.reply_mode = "main_answer"
    controller.settings.instructor_structured_outputs_enabled = True
    controller.settings.personas = [BuddyPersona(id="mira", display_name="Mira")]

    result = controller.invoke_capability("chat.user_text_command", {"text": "Mira, comment on this image."})

    assert isinstance(result, dict)
    assert result["response_text"].startswith("[Mira]")
    assert captured_messages[-1] == {"role": "user", "content": "Mira, comment on this image."}


def run_all() -> None:
    test_buddy_instructor_defaults_are_opt_in()
    test_structured_reply_sanitizer_keeps_only_exact_known_buddy_lines()
    test_controller_uses_structured_instructor_reply_when_enabled()
    test_instructor_skips_inherited_main_runtime_without_patching_client()
    test_inherited_main_fallback_keeps_final_user_query()


if __name__ == "__main__":
    run_all()
    print("smoke_buddy_chat_instructor: ok")
