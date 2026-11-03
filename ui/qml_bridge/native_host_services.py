"""Finite host-service catalog for the native QML application.

This module is the production addon boundary.  It deliberately excludes the
former focused/complex UI lifecycle catalogs, Designer binders, widget ports,
and manifest-driven Qt host-service imports.
"""

from __future__ import annotations

import math
import re
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from addons.hotkeys import runtime_config as hotkey_config
from addons.visual_reply.providers import (
    normalize_model_for_provider,
    provider_setting_from_config,
    updated_provider_settings,
)
from core.addons.main_chat_remote_host import MainChatRemoteHostService
from ui.qml_bridge.portrait_playback import portrait_message_id
from ui.qml_bridge.runtime_services import (
    AddonCapabilityBridgeService,
    QtAcceptedTurnService,
    QtAudioStoryRuntimeService,
    QtAvatarProviderService,
    QtChatContextService,
    QtChatProviderService,
    QtChatReplayService,
    QtCompanionOrbRuntimeService,
    QtDryRunService,
    QtEngineLifecycleService,
    QtFileTranscriptionService,
    QtHandCalibrationService,
    QtInputActionService,
    QtInputSettingsService,
    QtModelRefreshService,
    QtPerformanceProfileService,
    QtPersonaAvatarService,
    QtPromptRefinementService,
    QtRuntimeControlService,
    QtRuntimeStatusService,
    QtSensoryService,
    QtSpeechPlaybackService,
    QtShellService,
    QtTutorialService,
    QtUserImageTurnService,
)
from core.addons.runtime_config_service import AddonRuntimeOperations, RuntimeConfigService
from core import runtime_hotkeys


class NativeDialogService:
    """Non-widget dialog boundary used by native adapters.

    File selection is initiated by ``QtQuick.Dialogs`` and the chosen path is
    passed into an explicit adapter action.  Synchronous addon dialog calls are
    therefore rejected instead of constructing a hidden ``QFileDialog``.
    """

    @staticmethod
    def open_file(_title: str, _start_dir: str, _file_filter: str):
        return "", ""

    @staticmethod
    def save_file(_title: str, _start_path: str, _file_filter: str):
        return "", ""

    @staticmethod
    def open_directory(_title: str, _start_dir: str):
        return ""

    @staticmethod
    def warning(title: str, message: str) -> None:
        print(f"[Addon warning] {title}: {message}")

    @staticmethod
    def information(title: str, message: str) -> None:
        print(f"[Addon information] {title}: {message}")


class NativeHotkeyService:
    """Finite hotkey catalog and edits without QWidget shortcut discovery."""

    def __init__(self, runtime_config: RuntimeConfigService) -> None:
        self._runtime_config = runtime_config

    def _settings(self) -> dict[str, Any]:
        return hotkey_config.settings(self._runtime_config)

    def list_bindings(self) -> list[dict[str, Any]]:
        labels = hotkey_config.HOTKEY_ACTION_LABELS
        descriptions = hotkey_config.HOTKEY_ACTION_DESCRIPTIONS
        settings = self._settings()
        entries = [
            {
                "action": "push_to_talk",
                "label": str(labels.get("push_to_talk", "Push-to-Talk")),
                "binding": str(settings["push_to_talk"]),
                "default_binding": hotkey_config.DEFAULT_PUSH_TO_TALK_HOTKEY,
                "category": "input",
                "scope": "global",
                "description": str(descriptions["push_to_talk"]),
            }
        ]
        for action, default_binding in hotkey_config.DEFAULT_MANUAL_ACTION_HOTKEYS.items():
            entries.append(
                {
                    "action": action,
                    "label": str(labels.get(action, action)),
                    "binding": str(settings["manual_actions"].get(action, "")),
                    "default_binding": str(default_binding or ""),
                    "category": "manual_controls",
                    "scope": "global_and_window",
                    "description": str(descriptions.get(action, "")),
                }
            )
        for action, default_binding in hotkey_config.DEFAULT_UI_ACTION_HOTKEYS.items():
            entries.append(
                {
                    "action": action,
                    "label": str(labels.get(action, action)),
                    "binding": str(settings["ui_actions"].get(action, "")),
                    "default_binding": str(default_binding or ""),
                    "category": "ui_actions",
                    "scope": "window",
                    "description": str(descriptions.get(action, "")),
                }
            )
        return entries

    def register_actions(self, actions, labels):
        runtime_hotkeys.register_ui_action_hotkeys(dict(actions or {}), dict(labels or {}))
        return self.list_bindings()

    def set_binding(self, action: str, binding: str) -> str:
        action_key = str(action or "").strip()
        binding_text = hotkey_config.normalize_hotkey_text(binding)
        settings = self._settings()
        if action_key == "push_to_talk":
            binding_text = binding_text or hotkey_config.DEFAULT_PUSH_TO_TALK_HOTKEY
            settings["push_to_talk"] = binding_text
        elif action_key in hotkey_config.DEFAULT_MANUAL_ACTION_HOTKEYS:
            settings["manual_actions"][action_key] = binding_text
        elif action_key in hotkey_config.DEFAULT_UI_ACTION_HOTKEYS:
            settings["ui_actions"][action_key] = binding_text
        else:
            raise KeyError(f"Unknown hotkey action: {action_key}")
        self._runtime_config.update("hotkeys", settings)
        return binding_text

    def reset_defaults(self) -> dict[str, Any]:
        settings = {
            "push_to_talk": hotkey_config.DEFAULT_PUSH_TO_TALK_HOTKEY,
            "manual_actions": dict(hotkey_config.DEFAULT_MANUAL_ACTION_HOTKEYS),
            "ui_actions": dict(hotkey_config.DEFAULT_UI_ACTION_HOTKEYS),
        }
        self._runtime_config.update("hotkeys", settings)
        return settings

    @staticmethod
    def build_ui_hotkey_timer():
        return None

    @staticmethod
    def button_titles() -> dict[str, str]:
        return {
            "regenerate_response": "Regenerate",
            "retry_user_input": "Retry Input",
            "pause_speech": "Pause / Resume",
            "skip_speech": "Skip Speech",
            "skip_user_reply": "Skip User Reply",
        }

    @staticmethod
    def supported_actions():
        return OrderedDict()

    @staticmethod
    def dispatch_action(_action):
        return None

    @staticmethod
    def refresh_shortcuts():
        return None

    @staticmethod
    def poll_exact():
        return None

    @staticmethod
    def refresh_labels():
        return None


class NativeScenicAvatarOperations:
    """Scenic pack operations backed only by runtime configuration and files."""

    def __init__(self, runtime_config: RuntimeConfigService) -> None:
        self._runtime_config = runtime_config

    def runtime_config_snapshot(self) -> dict[str, Any]:
        return dict(self._runtime_config.snapshot() or {})

    def collect_runtime_config(self, runtime_config=None) -> dict[str, Any]:
        runtime = dict(runtime_config or self.runtime_config_snapshot())
        return {"scenic_pack_id": str(runtime.get("scenic_pack_id", "") or "").strip()}

    def update_config_from_widgets(self, runtime_config=None) -> bool:
        for key, value in self.collect_runtime_config(runtime_config).items():
            self._runtime_config.update(key, value)
        self._runtime_config.refresh_avatar_emotions()
        return True

    def refresh_resource_widgets(self, runtime_config=None) -> bool:
        _ = runtime_config
        self._runtime_config.refresh_avatar_emotions()
        return True

    @staticmethod
    def build_runtime_widgets(runtime_config=None) -> bool:
        _ = runtime_config
        return False

    @staticmethod
    def set_provider_controls_enabled(enabled) -> bool:
        _ = enabled
        return True

@dataclass(frozen=True, slots=True)
class _PreparedPhoneVisualRequest:
    prompt: str
    runtime_config: dict[str, Any]
    inputs: tuple[Path, ...]
    reference_strength: float | None
    uses_identity: bool
    edits_source_image: bool = False
    source_edit_error: str = ""


class NativeVisualReplyService:
    """Visual Reply configuration and generation without a QWidget panel."""

    def __init__(self, runtime_config: RuntimeConfigService) -> None:
        self._runtime_config = runtime_config

    def settings_snapshot(self) -> dict[str, Any]:
        runtime = dict(self._runtime_config.snapshot() or {})
        provider = str(runtime.get("visual_reply_provider", "openai") or "openai").strip().lower()
        runtime["provider"] = provider
        runtime["provider_value"] = provider
        runtime["model"] = str(
            provider_setting_from_config(runtime, provider, "model", "")
            or runtime.get("visual_reply_model", "")
            or ""
        )
        runtime["size"] = str(
            provider_setting_from_config(runtime, provider, "size", "")
            or runtime.get("visual_reply_size", "1024x1024")
            or "1024x1024"
        )
        return runtime

    def refresh_hint(self) -> dict[str, Any]:
        return self.settings_snapshot()

    @staticmethod
    def prepare_phone_generation(
        *, prompt: str, runtime_config: dict[str, Any]
    ) -> _PreparedPhoneVisualRequest:
        """Resolve phone identity references on the gateway's existing worker."""
        from addons.visual_reply.runtime_config import extract_visual_reply_prompt
        from core.runtime.visual import plan_persona_visual_request

        runtime = dict(runtime_config or {})
        _visible_text, tagged_prompt = extract_visual_reply_prompt(prompt)
        plan = plan_persona_visual_request(tagged_prompt or prompt, runtime)
        return _PreparedPhoneVisualRequest(
            prompt=plan.prompt,
            runtime_config=runtime,
            inputs=plan.inputs,
            reference_strength=plan.reference_strength,
            uses_identity=plan.uses_persona_identity or plan.uses_user_identity,
            edits_source_image=plan.edits_source_image,
            source_edit_error=plan.source_edit_error,
        )

    def request_generation(
        self,
        *,
        prompt: str,
        caption: str = "",
        provider: str = "inherit",
        model: str = "",
        size: str = "inherit",
        source: str = "",
        metadata: dict | None = None,
        auto_show: bool = True,
        prepared_phone_request: _PreparedPhoneVisualRequest | None = None,
    ):
        prepared = prepared_phone_request if source == "main_chat_remote" else None
        prompt_text = str(prepared.prompt if prepared is not None else prompt or "").strip()
        if not prompt_text:
            return False
        runtime = dict(prepared.runtime_config) if prepared is not None else self.settings_snapshot()
        provider_value = str(provider or "inherit").strip().lower()
        if not provider_value or provider_value == "inherit":
            provider_value = str(runtime.get("provider_value") or "openai")
        runtime["visual_reply_provider"] = provider_value
        model_value = str(model or "").strip()
        if model_value:
            runtime["visual_reply_provider_settings"] = updated_provider_settings(
                runtime, provider_value, "model", model_value
            )
            runtime["visual_reply_model"] = normalize_model_for_provider(
                provider_value, model_value
            )
        size_value = str(size or "inherit").strip()
        if size_value and size_value.lower() != "inherit":
            runtime["visual_reply_provider_settings"] = updated_provider_settings(
                runtime, provider_value, "size", size_value
            )
            runtime["visual_reply_size"] = size_value
        runtime["visual_reply_mode"] = "auto"
        runtime["visual_replies_enabled"] = True
        runtime["visual_reply_auto_show_dock"] = bool(auto_show)
        request_id = f"native_{int(time.time() * 1000)}"
        request_options: dict[str, Any] = {}
        if source == "main_chat_remote":
            phone_metadata = dict(metadata or {})
            phone_request_id = str(phone_metadata.get("request_id") or "")
            if re.fullmatch(r"phone_[0-9]+_[0-9a-f]{6}", phone_request_id):
                request_id = phone_request_id
            request_options["asset_metadata"] = {
                key: phone_metadata[key]
                for key in (
                    "target_turn_id", "normal_chat_transaction_id",
                    "append_visual_variation", "variation_of_request_id",
                )
                if key in phone_metadata
            }
        # Prepared inputs were validated off the UI thread, including UNC paths.
        reference_inputs = prepared.inputs if prepared is not None else _visual_reference_inputs(metadata)
        if (
            provider_value == "xai"
            and reference_inputs
            and (metadata or {}).get("requires_image_to_image") is True
        ):
            runtime["visual_reply_provider_settings"] = updated_provider_settings(
                runtime, "xai", "image_to_image_enabled", True
            )
        if prepared is not None and (prepared.uses_identity or prepared.edits_source_image):
            from core.runtime.visual import persona_visual_request_config

            runtime = persona_visual_request_config(
                runtime,
                reference_strength=prepared.reference_strength,
                reference_count=len(prepared.inputs),
                edits_source_image=prepared.edits_source_image,
                source_edit_error=prepared.source_edit_error,
            )
        accepted = self._runtime_config.request_visual_reply_generation(
            prompt_text,
            inputs=reference_inputs,
            source_text=str(caption or source or metadata or ""),
            request_id=request_id,
            runtime_config=runtime,
            **request_options,
        )
        if not accepted:
            return False
        return {
            "accepted": True,
            "image_path": "",
            "caption": prompt_text,
            "request_id": request_id,
        }


def _visual_reference_inputs(metadata: dict | None) -> tuple[Path, ...]:
    payload = dict(metadata or {})
    raw_values = []
    for key in ("reference_image_path", "referenceImagePath", "image_path"):
        value = payload.get(key)
        if value:
            raw_values.append(value)
    for key in ("reference_image_paths", "referenceImagePaths", "inputs"):
        values = payload.get(key)
        if isinstance(values, (list, tuple, set)):
            raw_values.extend(values)
    result = []
    seen = set()
    for value in raw_values:
        path = Path(str(value or "").strip())
        key = str(path)
        if not key or key in seen:
            continue
        result.append(path)
        seen.add(key)
    return tuple(result)


class _ExactAddonPort:
    def __init__(self, manager_getter, addon_id: str) -> None:
        self._manager_getter = manager_getter
        self._addon_id = str(addon_id)

    def _instance(self):
        manager = self._manager_getter()
        if manager is None:
            return None
        record = manager.get_addon_record(self._addon_id)
        if record is None or record.state != "initialized":
            return None
        return record.instance


class NativeAudioStoryVisualCommands(_ExactAddonPort):
    def __init__(self, manager_getter) -> None:
        super().__init__(manager_getter, "nc.visual_reply")

    def _call(self, name: str, *args):
        addon = self._instance()
        return None if addon is None else getattr(addon, name)(*args)

    def visual_generation(self, runtime_config): return self._call("generation", dict(runtime_config or {}))
    def visual_current_state(self): return self._call("current_state")
    def visual_set_state(self, state): return self._call("set_state", dict(state or {}))
    def visual_story_style_guide(self, runtime_config, text, continuity_strength): return self._call("story_style_guide", dict(runtime_config or {}), str(text or ""), float(continuity_strength))
    def visual_story_prompt(self, runtime_config, text, emotion, story_style_guide): return self._call("story_prompt", dict(runtime_config or {}), str(text or ""), str(emotion or ""), str(story_style_guide or ""))
    def visual_normalize_prompt(self, prompt): return self._call("normalize_prompt", str(prompt or ""))
    def visual_apply_style_anchor(self, runtime_config, prompt): return self._call("apply_style_anchor", dict(runtime_config or {}), str(prompt or ""))
    def visual_output_base(self, prefix, index): return self._call("output_base", str(prefix), int(index))
    def visual_client(self, runtime_config): return self._call("client", dict(runtime_config or {}))
    def visual_write_image(self, runtime_config, response, output_base_path): return self._call("write_image_from_response", dict(runtime_config or {}), response, str(output_base_path))


class NativeMainChatRemoteCommands:
    def __init__(
        self,
        manager_getter,
        *,
        quick_persona_choices: Callable[[], list[dict[str, Any]]] | None = None,
        apply_quick_persona: Callable[[int], dict[str, Any]] | None = None,
        llm_model_choices: Callable[[], dict[str, Any]] | None = None,
        voice_choices: Callable[[], dict[str, Any]] | None = None,
        apply_voice: Callable[[str], dict[str, Any]] | None = None,
        tts_provider_choices: Callable[[], dict[str, Any]] | None = None,
        apply_tts_provider: Callable[[str], dict[str, Any]] | None = None,
        apply_llm_model: Callable[[str, str], dict[str, Any]] | None = None,
        refine_visual_prompt: Callable[..., str] | None = None,
        chat_character_services=None,
        persona_prompt_store=None,
        persona_rule_catalog=None,
        apply_persona_prompts=None,
        quick_persona_identity: Callable[[], str] | None = None,
    ) -> None:
        self._buddy = _ExactAddonPort(manager_getter, "nc.buddy_chat")
        self._chat_character_services = chat_character_services
        self._persona_prompt_store = persona_prompt_store
        self.persona_rule_catalog = persona_rule_catalog
        self.apply_persona_prompts = apply_persona_prompts
        self._quick_persona_identity = quick_persona_identity
        self._mpr = _ExactAddonPort(manager_getter, "nc.multi_persona_roleplay")
        self._quick_persona_choices = quick_persona_choices
        self._apply_quick_persona = apply_quick_persona
        self._llm_model_choices = llm_model_choices
        self._voice_choices = voice_choices
        self._apply_voice = apply_voice
        self._tts_provider_choices = tts_provider_choices
        self._apply_tts_provider = apply_tts_provider
        self._apply_llm_model = apply_llm_model
        self._refine_visual_prompt = refine_visual_prompt

    def refine_visual_prompt(self, text: str) -> str:
        if not callable(self._refine_visual_prompt):
            raise RuntimeError('The desktop image-prompt refiner is unavailable.')
        return str(self._refine_visual_prompt(
            text[:5000], label='Visual Reply image prompt',
            guidance=('Turn this reply into one concise, concrete visual scene for image generation. '
                      'Describe subjects, setting, composition, lighting, and visual style. '
                      'Preserve the source scene\'s subjects, actions, tone, and concrete visual details; '
                      'do not substitute a different scene or add unrelated content. '
                      'Do not quote dialogue or add speech bubbles, captions, lettering, or text. '
                      'Return only the image prompt.')) or '').strip()

    def voice_state(self) -> dict[str, Any]:
        return dict(self._voice_choices() or {}) if callable(self._voice_choices) else {"available": False, "items": []}

    def tts_provider_state(self) -> dict[str, Any]:
        if not callable(self._tts_provider_choices):
            return {"available": False, "providers": []}
        return dict(self._tts_provider_choices() or {})

    def tts_provider_apply(self, provider_id: str) -> dict[str, Any]:
        if not callable(self._apply_tts_provider):
            return {"accepted": False, "message": "TTS provider controls are unavailable."}
        return dict(self._apply_tts_provider(provider_id) or {})

    def chat_characters(self, request):
        if self._chat_character_services is None:
            raise RuntimeError('Chat Character Library is unavailable.')
        return self._chat_character_services.invoke(request)

    def soundscape_client(self):
        if self._chat_character_services is None:
            raise ValueError('Voice Studio provider integration is unavailable.')
        return self._chat_character_services.soundscape_client()

    def chat_character_media(self, identity):
        if self._chat_character_services is None:
            raise FileNotFoundError('Chat character media is unavailable.')
        return self._chat_character_services.media_path(identity)

    def voice_apply(self, voice_path: str) -> dict[str, Any]:
        return dict(self._apply_voice(voice_path) or {}) if callable(self._apply_voice) else {"accepted": False}

    def llm_model_state(self) -> dict[str, Any]:
        if not callable(self._llm_model_choices):
            return {"available": False, "providers": []}
        return dict(self._llm_model_choices() or {})

    def llm_model_apply(self, provider_id: str, model_id: str) -> dict[str, Any]:
        if not callable(self._apply_llm_model):
            return {"accepted": False, "message": "Model controls are unavailable."}
        return dict(self._apply_llm_model(provider_id, model_id) or {})

    def quick_persona_identity(self) -> str:
        """Qt-owned stable identity, without reading persona files on the UI thread."""
        return str(self._quick_persona_identity() or "") if callable(self._quick_persona_identity) else ""

    def quick_persona_state(self) -> list[dict[str, Any]]:
        if not callable(self._quick_persona_choices):
            return []
        return [dict(item or {}) for item in list(self._quick_persona_choices() or [])]

    def quick_persona_prompts(self, request):
        if self._persona_prompt_store is None:
            raise ValueError('Persona prompt editing is unavailable on this desktop.')
        identity = request.get('id')
        if not isinstance(identity, str) or not identity or len(identity) > 256:
            raise ValueError('A persona identity is required.')
        action = request.get('action', 'read')
        if action == 'read':
            return self._persona_prompt_store.prompt_editor(identity)
        if action not in ('save', 'restore'):
            raise ValueError('Unknown persona prompt action.')
        if 'technical_rules' in request and not isinstance(request['technical_rules'], dict):
            raise ValueError('Provider rules must be an object.')
        return self._persona_prompt_store.edit_prompts(identity, request.get('revision'),
            request.get('system_prompt'), request.get('technical_prompt'), restore=action == 'restore',
            technical_rules=request.get('technical_rules'))

    def quick_persona_apply(self, slot: int) -> dict[str, Any]:
        if not callable(self._apply_quick_persona):
            return {
                "accepted": False,
                "message": "Quick Persona controls are unavailable.",
            }
        return dict(self._apply_quick_persona(int(slot)) or {})

    def buddy_status(self):
        addon = self._buddy._instance()
        return None if addon is None else addon.status_snapshot()

    def mprc_state(self):
        addon = self._mpr._instance()
        return None if addon is None else addon.remote_state()

    def mprc_send(self, payload):
        request, addon = dict(payload or {}), self._mpr._instance()
        return None if addon is None else addon.remote_send(request.get("text") or request.get("message"), intent=request.get("intent"), speaker_id=request.get("speaker_id"))

    def mprc_choice(self, payload):
        request, addon = dict(payload or {}), self._mpr._instance()
        return None if addon is None else addon.remote_choice(request.get("choice") or request.get("choice_id") or request.get("text"))

    def mprc_play(self, _payload):
        addon = self._mpr._instance(); return None if addon is None else addon.remote_play()
    def mprc_pause(self, _payload):
        addon = self._mpr._instance(); return None if addon is None else addon.remote_pause()
    def mprc_visual(self, _payload):
        addon = self._mpr._instance(); return None if addon is None else addon.remote_visual()
    def mprc_cast(self, payload):
        addon = self._mpr._instance(); return None if addon is None else addon.remote_cast(dict(payload or {}))


class NativeMusicStoryCommands(_ExactAddonPort):
    def __init__(self, manager_getter) -> None:
        super().__init__(manager_getter, "nc.spotify_sense")

    def spotify_story_hook(self, payload):
        addon = self._instance()
        return None if addon is None else addon.story_hook(dict(payload or {}))


def facade_addon_runtime_operations(application_facade) -> AddonRuntimeOperations:
    def update_runtime_config(key, value):
        result = application_facade.config.update(str(key), value)
        if result.accepted:
            return None
        failure = result.failure
        cause = getattr(failure, "cause", None)
        if isinstance(cause, BaseException):
            raise cause
        raise RuntimeError(getattr(failure, "message", "Runtime configuration update failed."))

    return AddonRuntimeOperations(
        provider_config_snapshot=application_facade.addon_chat.provider_config_snapshot,
        provider_capture_selection=application_facade.addon_chat.capture_provider_selection,
        provider_prepare=application_facade.addon_chat.prepare_provider_request,
        provider_complete=application_facade.addon_chat.complete_provider_request,
        provider_stream=application_facade.addon_chat.stream_provider_request,
        provider_apply_generation_fields=application_facade.addon_chat.apply_provider_generation_fields,
        ensure_chat_provider_model_ready=application_facade.addon_chat.ensure_model_ready,
        conversation_history_snapshot=application_facade.addon_chat.history_snapshot,
        collect_addon_chat_contexts=application_facade.addon_chat.collect_contexts,
        submit_accepted_turn=application_facade.addon_chat.submit_accepted_turn,
        speech_snapshot=application_facade.addon_speech.snapshot,
        set_speech_paused=application_facade.addon_speech.set_paused,
        interrupt_speech=application_facade.addon_speech.interrupt,
        ensure_speech_ready=application_facade.addon_speech.ensure_ready,
        speak=application_facade.addon_speech.speak,
        orb_busy_snapshot=application_facade.addon_orb.busy_snapshot,
        orb_extract_selected_text=application_facade.addon_orb.extract_selected_text,
        orb_ground_region=application_facade.addon_orb.ground_region,
        orb_generate_visual_guidance=application_facade.addon_orb.generate_visual_guidance,
        orb_release_vision_model=application_facade.addon_orb.release_vision_model,
        orb_ensure_vision_model=application_facade.addon_orb.ensure_vision_model,
        orb_observe_visual=application_facade.addon_orb.observe_visual,
        orb_conversation_scope=getattr(application_facade.addon_orb, 'conversation_scope', None),
        orb_interpret_watch_intent=getattr(application_facade.addon_orb, 'interpret_watch_intent', None),
        orb_observe_watch=getattr(application_facade.addon_orb, 'observe_watch', None),
        orb_record_communication=getattr(application_facade.addon_orb, 'record_communication', None),
        orb_ephemeral_comment=application_facade.addon_orb.ephemeral_comment,
        orb_submit_proactive=application_facade.addon_orb.submit_proactive,
        orb_run_sensory_cycle=application_facade.addon_orb.run_sensory_cycle,
        orb_generate_drop_guidance=application_facade.addon_orb.generate_drop_guidance,
        orb_format_drop_guidance=application_facade.addon_orb.format_drop_guidance,
        text_chunk_limits=application_facade.addon_audio_story.text_chunk_limits,
        chunk_text=application_facade.addon_audio_story.chunk_text,
        set_seed=application_facade.addon_audio_story.set_seed,
        generate_tts=application_facade.addon_audio_story.generate,
        save_wav=application_facade.addon_audio_story.save_wav,
        safe_delete=application_facade.addon_audio_story.safe_delete,
        tts_sample_rate=application_facade.addon_audio_story.sample_rate,
        push_to_talk_hotkey=application_facade.addon_speech.push_to_talk_hotkey,
        set_push_to_talk_hold=application_facade.addon_speech.set_push_to_talk_hold,
        snapshot_chat_session=application_facade.addon_chat.snapshot_session,
        replayable_chat_entries=application_facade.addon_chat.replayable_chat_entries,
        replayable_chat_messages=application_facade.addon_chat.replayable_chat_messages,
        replayable_assistant_entries=application_facade.addon_chat.replayable_assistant_entries,
        replayable_assistant_messages=application_facade.addon_chat.replayable_assistant_messages,
        build_replay_session_action=application_facade.addon_chat.build_replay_session_action,
        transcribe_file=application_facade.addon_speech.transcribe_file,
        prepare_transcription=application_facade.addon_speech.prepare_transcription,
        runtime_config_snapshot=lambda: dict(application_facade.config.snapshot().values),
        update_runtime_config=update_runtime_config,
        avatar_adapter=application_facade.addon_avatar_resources.adapter,
        refresh_avatar_emotions=application_facade.addon_avatar_resources.refresh_emotions,
        tts_device=application_facade.addon_avatar_resources.tts_device,
        request_visual_reply_generation=application_facade.addon_visual_request.request_generation,
        refine_instruction=application_facade.prompt_refinement.refine,
    )


_MAIN_CHAT_REMOTE_TEXT_FIELDS = {
    "caption": 500,
    "content": 262_144,
    "generated_image_prompt": 240,
    "id": 120,
    "image_caption": 500,
    "turn_id": 120,
    "visual_reply_caption": 500,
    "visual_reply_prompt": 240,
    "visual_reply_request_id": 120,
}
_MAIN_CHAT_REMOTE_PATH_FIELDS = (
    "attachment_image_path",
    "assistant_visual_reply_image_path",
    "generated_image_path",
    "visual_reply_image_path",
)
_MAIN_CHAT_REMOTE_PATH_LIST_FIELDS = (
    "assistant_visual_reply_image_paths",
    "generated_image_paths",
    "visual_reply_image_paths",
)
_MAIN_CHAT_REMOTE_TIME_FIELDS = (
    "created_at",
    "timestamp",
    "visual_reply_created_at",
    "visual_reply_updated_at",
)
_MAIN_CHAT_REMOTE_TRANSACTION_RE = re.compile(r"[0-9a-f]{32}")
_MAIN_CHAT_REMOTE_CAPTURE_RE = re.compile(r"[A-Za-z0-9_-]{1,96}")


def _bounded_history_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value[: max(0, int(limit))]


def _main_chat_remote_history_turn(value: object) -> dict[str, object] | None:
    """Project one live turn to the exact fields consumed by the phone gateway."""

    if not isinstance(value, Mapping):
        return None
    role = _bounded_history_text(value.get("role"), 16).strip().casefold()
    if role not in {"assistant", "system", "user"}:
        return None
    turn: dict[str, object] = {"role": role}
    for field_name, limit in _MAIN_CHAT_REMOTE_TEXT_FIELDS.items():
        text = _bounded_history_text(value.get(field_name), limit)
        if text:
            turn[field_name] = text
    origin = _bounded_history_text(value.get("origin"), 32).strip().casefold()
    if origin in {"assistant_reply", "input"}:
        turn["origin"] = origin
    for field_name in _MAIN_CHAT_REMOTE_TIME_FIELDS:
        item = value.get(field_name)
        if (
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(float(item))
        ):
            turn[field_name] = item
    for field_name in ("hidden_proactive", "interrupted"):
        if bool(value.get(field_name)):
            turn[field_name] = True
    persona = value.get("quick_persona")
    if isinstance(persona, Mapping):
        projected_persona = {
            field_name: text
            for field_name, limit in (
                ("id", 120),
                ("name", 160),
                ("avatar_path", 4096),
            )
            if (text := _bounded_history_text(persona.get(field_name), limit))
        }
        if projected_persona:
            turn["quick_persona"] = projected_persona
    for field_name in _MAIN_CHAT_REMOTE_PATH_FIELDS:
        path = _bounded_history_text(value.get(field_name), 4096).strip()
        if path:
            turn[field_name] = path
    for field_name in _MAIN_CHAT_REMOTE_PATH_LIST_FIELDS:
        items = value.get(field_name)
        if not isinstance(items, (list, tuple)):
            continue
        paths = tuple(
            path
            for item in items[:8]
            if (path := _bounded_history_text(item, 4096).strip())
        )
        if paths:
            turn[field_name] = paths
    raw_transaction_id = value.get("normal_chat_transaction_id")
    if isinstance(raw_transaction_id, str) and _MAIN_CHAT_REMOTE_TRANSACTION_RE.fullmatch(
        raw_transaction_id
    ):
        turn["normal_chat_transaction_id"] = raw_transaction_id
    raw_capture_id = value.get("remote_capture_id")
    if isinstance(raw_capture_id, str) and _MAIN_CHAT_REMOTE_CAPTURE_RE.fullmatch(
        raw_capture_id
    ):
        turn["remote_capture_id"] = raw_capture_id
    return turn


def _main_chat_remote_history_snapshot(application_facade) -> dict[str, object]:
    snapshot_callback = getattr(getattr(application_facade, "chat", None), "snapshot", None)
    snapshot = snapshot_callback() if callable(snapshot_callback) else None
    messages = getattr(snapshot, "messages", None)
    if messages is None:
        history = application_facade.addon_chat.history_snapshot()
    else:
        history = tuple(
            {
                **dict(message.metadata),
                "role": message.role,
                "content": message.content,
                "turn_id": message.message_id,
            }
            for message in messages
        )
    return {
        "conversation_history": tuple(
            turn
            for item in tuple(history or ())
            if (turn := _main_chat_remote_history_turn(item)) is not None
        )
    }


def _main_chat_remote_portrait_playback_snapshot(application_facade) -> dict[str, str]:
    """Expose only the desktop's currently admitted portrait mood and row identity."""

    conversation = application_facade.chat.snapshot()
    state = application_facade.avatar.snapshot().portrait_playback
    message_id = portrait_message_id(state, conversation)
    if not message_id or state is None:
        return {}
    return {
        "message_id": message_id,
        "transaction_id": str(state.transaction_id or ""),
        "mood": str(state.expression or ""),
    }


def build_native_host_services(
    host,
    application_facade,
    *,
    chat_persona_store=None,
    persona_prompt_store=None,
    persona_rule_catalog: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    apply_persona_prompts: Callable[[dict[str, Any]], None] | None = None,
    quick_persona_identity: Callable[[], str] | None = None,
    quick_persona_choices: Callable[[], list[dict[str, Any]]] | None = None,
    apply_quick_persona: Callable[[int], dict[str, Any]] | None = None,
    llm_model_choices: Callable[[], dict[str, Any]] | None = None,
    voice_choices: Callable[[], dict[str, Any]] | None = None,
    apply_voice: Callable[[str], dict[str, Any]] | None = None,
    tts_provider_choices: Callable[[], dict[str, Any]] | None = None,
    apply_tts_provider: Callable[[str], dict[str, Any]] | None = None,
    web_search_status: Callable[[], dict[str, Any] | None] | None = None,
    set_web_search_enabled: Callable[[bool], dict[str, Any]] | None = None,
    apply_llm_model: Callable[[str, str], dict[str, Any]] | None = None,
    toggle_main_window: Callable[[], object] | None = None,
    initialize_system: Callable[[], object] | None = None,
    terminate_system: Callable[[], object] | None = None,
    runtime_state: Callable[[], dict[str, bool]] | None = None,
    activate_floating_workspace: Callable[[str, bool], object] | None = None,
    app_root: Path | None = None,
    on_phone_chat_load: Callable[[bool], None] | None = None,
    chat_persistence_enabled: bool = True,
) -> dict[str, Any]:
    runtime_config = RuntimeConfigService(host)
    runtime_status = QtRuntimeStatusService(host)
    hotkeys = NativeHotkeyService(runtime_config)
    host._native_hotkey_service = hotkeys
    scenic = NativeScenicAvatarOperations(runtime_config)
    visual_reply = NativeVisualReplyService(runtime_config)
    host._scenic_avatar_host_operations = scenic
    main_chat_remote_host = MainChatRemoteHostService(
        status_snapshot=runtime_status.snapshot,
        conditional_input=application_facade.addon_chat.submit_if_current_and_idle,
        stage_continuous_next=application_facade.addon_chat.stage_continuous_next,
        user_speech_runtime=QtAudioStoryRuntimeService(host),
        phone_reply_controls=application_facade.addon_chat.phone_reply_controls,
        history_snapshot=lambda: _main_chat_remote_history_snapshot(
            application_facade
        ),
        portrait_playback_snapshot=lambda: _main_chat_remote_portrait_playback_snapshot(
            application_facade
        ),
    )
    host._main_chat_remote_host_service = main_chat_remote_host
    manager_getter = lambda: host._addon_manager
    from .chat_character_services import ChatCharacterServices
    character_services = ChatCharacterServices(
        _ExactAddonPort(manager_getter, 'nc.multi_persona_roleplay')._instance,
        _ExactAddonPort(manager_getter, 'nc.voice_studio')._instance,
        lambda: dict(application_facade.config.snapshot().values), chat_persona_store,
        refine_prompt=application_facade.prompt_refinement.refine)
    from core.runtime.resource_sources import release_idle_speech_models
    def release_room_speech_models():
        manager = manager_getter()
        resources = getattr(application_facade, 'resources', None)
        if manager is None or resources is None:
            return {'ok': False, 'message': 'Speech resource cleanup is unavailable.'}
        return release_idle_speech_models(resources, manager.service_registry.list_entries())
    speech_playback = QtSpeechPlaybackService(host, release_idle_models=release_room_speech_models)
    from .chess_persona_service import ChessPersonaService
    def chess_mcp(operation, fields):
        response = application_facade.addons.invoke_addon_capability(
            'nc.chat_mcp_tools', 'chat_mcp.conversation', dict(fields, operation=operation))
        return response.value if response.accepted else None
    def chess_online_request(facade, message):
        response=facade.addons.invoke_addon_capability(
            'nc.main_chat_remote','runtime.main_chat_remote.chess_mcp',message)
        if not response.accepted or not isinstance(response.value,dict):
            raise RuntimeError('Connect NC Relay in Main Chat Remote Internet settings first.')
        return response.value
    chess_personas = ChessPersonaService(
        persona_store=chat_persona_store,
        config_snapshot=lambda: dict(application_facade.config.snapshot().values),
        providers=QtChatProviderService(host), invoke_chat_mcp=chess_mcp,
        speech=application_facade.addon_speech.speak_chess,
        online_mcp=lambda message: chess_online_request(application_facade,message))
    return {
        "runtime.chess_persona_turns.v1": chess_personas,
        "qt.chat_context": QtChatContextService(
            host, app_root=app_root if chat_persistence_enabled else None,
            on_phone_load=on_phone_chat_load),
        "qt.dialogs": NativeDialogService(),
        "qt.dry_run": QtDryRunService(host),
        "qt.engine_lifecycle": QtEngineLifecycleService(host),
        "qt.hand_calibration": QtHandCalibrationService(host),
        "qt.hotkeys": hotkeys,
        "qt.input_actions": QtInputActionService(host),
        "qt.input_settings": QtInputSettingsService(host),
        "qt.persona_avatar": QtPersonaAvatarService(host),
        "qt.performance_profiles": QtPerformanceProfileService(host),
        "qt.runtime_config": runtime_config,
        "qt.scenic_avatar_host": scenic,
        "qt.model_refresh": QtModelRefreshService(host),
        "qt.runtime_controls": QtRuntimeControlService(
            host, web_search_status=web_search_status, set_web_search_enabled=set_web_search_enabled,
        ),
        "qt.runtime_status": runtime_status,
        "qt.shell": QtShellService(
            host,
            toggle_main_window=toggle_main_window,
            initialize_system=initialize_system,
            terminate_system=terminate_system,
            runtime_state=runtime_state,
            activate_floating_workspace=activate_floating_workspace,
        ),
        "qt.tutorials": QtTutorialService(host),
        "qt.user_image_turns": QtUserImageTurnService(host, application_facade.chat),
        "qt.avatar_providers": QtAvatarProviderService(host),
        "qt.sensory": QtSensoryService(host),
        "qt.chat_providers": QtChatProviderService(host),
        "qt.chat_replay": QtChatReplayService(host),
        "qt.visual_reply": visual_reply,
        "runtime.file_transcription": QtFileTranscriptionService(host),
        "runtime.accepted_turns": QtAcceptedTurnService(host),
        "runtime.speech": speech_playback,
        "runtime.playback": speech_playback,
        "runtime.document_memory": getattr(application_facade, "document_memory", None),
        "runtime.companion_orb": QtCompanionOrbRuntimeService(host),
        "runtime.audio_story": QtAudioStoryRuntimeService(host),
        "runtime.audio_story_visual": NativeAudioStoryVisualCommands(manager_getter),
        "runtime.remote_commands": NativeMainChatRemoteCommands(
            manager_getter,
            chat_character_services=character_services,
            persona_prompt_store=persona_prompt_store,
            persona_rule_catalog=persona_rule_catalog,
            apply_persona_prompts=apply_persona_prompts,
            quick_persona_identity=quick_persona_identity,
            quick_persona_choices=quick_persona_choices,
            apply_quick_persona=apply_quick_persona,
            llm_model_choices=llm_model_choices,
            voice_choices=voice_choices,
            apply_voice=apply_voice,
            tts_provider_choices=tts_provider_choices,
            apply_tts_provider=apply_tts_provider,
            apply_llm_model=apply_llm_model,
            refine_visual_prompt=application_facade.prompt_refinement.refine,
        ),
        "runtime.main_chat_remote_host": main_chat_remote_host,
        "runtime.avatar_creation": application_facade.avatar_creation,
        "runtime.music_commands": NativeMusicStoryCommands(manager_getter),
        "runtime.prompt_refinement": QtPromptRefinementService(host),
        "addons.capabilities": AddonCapabilityBridgeService(manager_getter),
    }


__all__ = ["build_native_host_services", "facade_addon_runtime_operations"]
