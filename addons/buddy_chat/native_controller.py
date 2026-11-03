from __future__ import annotations

import copy
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from addons.buddy_chat import instructor_adapter
from addons.buddy_chat import structured_models
from addons.buddy_chat.llm_runtime import BuddyProviderRuntime, CompletionHandler, ProviderCallConfig, list_lmstudio_models_for_base_url
from addons.buddy_chat.models import (
    AVATAR_PROMPT_PRESETS,
    DEFAULT_AVATAR_PROMPT_PRESET,
    DEFAULT_SYSTEM_OVERRIDE_PROMPT,
    AvatarProfile,
    BuddyPersona,
    BuddySettings,
    ProviderOverride,
    PROVIDER_IDS,
    default_avatar_prompt,
)
from addons.buddy_chat.prompting import buddy_context_prompt, build_persona_messages, compact_text
from addons.buddy_chat.refinement import (
    RefinementPatch,
    RefinementRequest,
    apply_refinement_patch,
    build_refinement_messages,
    parse_refinement_result,
    refinement_differences,
)
from addons.buddy_chat.response_policy import (
    BUDDY_PASS_TOKEN,
    extract_selected_persona_reply,
    is_repetitive_secondary,
    normalize_persona_reply,
    select_speakers,
)
from addons.buddy_chat.setup_models import (
    BuddySetupPreview,
    GroupBehavior,
    WizardChoices,
    apply_setup_preview,
)
from addons.buddy_chat.setup_templates import compose_wizard_preview, preview_for_preset
from addons.buddy_chat.voice_segments import split_buddy_voice_segments


SETTINGS_PATH = "settings.json"













class BuddyChatController:
    def __init__(self, context, completion_handler: CompletionHandler | None = None) -> None:
        self.context = context
        self.tasks = context.tasks
        self.settings = self._load_settings()
        self._state_lock = threading.RLock()
        self._shutting_down = False
        self._shutdown_requested = threading.Event()
        self._settings_write_lock = threading.RLock()
        self._pending_settings_payload: dict[str, Any] | None = None
        self._settings_write_active = False
        self._setup_undo_settings: BuddySettings | None = None
        self._last_session_export_state: dict[str, Any] = self._session_export_payload_unlocked()
        self.runtime_config = context.capabilities.runtime_config
        self.providers = context.capabilities.providers
        self.conversation = context.capabilities.conversation
        self.llm_runtime = BuddyProviderRuntime(
            completion_handler=completion_handler,
            provider_execution=self.providers,
            runtime_config=self.runtime_config,
            document_memory=getattr(context.capabilities, "document_memory", None),
        )
        self.visual_reply_service = context.capabilities.visual_reply
        self._refinement_token = 0
        self._refinement_active_token: int | None = None
        self._model_catalog_lock = threading.RLock()
        self._model_catalog_inflight: set[str] = set()
        self._active_persona_id = ""
        self._active_persona_text = ""
        self._active_persona_reason = ""
        self._stream_voice_persona_id = ""
        self._last_provider_error = ""
        self._last_provider_error_at = 0.0
        self._native_status = "Default: buddies use the same provider and model as LLM Runtime."
        self._native_model_catalogs: dict[str, list[str]] = {}
        self._native_setup_choices = {
            "buddy_count": 2,
            "participation": "balanced",
            "traits": {
                "practical": True,
                "warm": True,
                "playful": False,
                "expressive": False,
                "honest": True,
                "creative": False,
                "flirtatious": False,
            },
            "refine_scope": "group",
            "refine_persona": "",
            "refine_field": "display_name",
            "refine_instruction": (
                "Make the selected characters more natural, distinctive, and "
                "internally consistent while preserving their intended roles."
            ),
        }
        self._native_setup_preview = preview_for_preset("reliable_guide")


    def _is_open(self) -> bool:
        with self._state_lock:
            return not self._shutdown_requested.is_set() and not self._shutting_down

    def _commit_avatar_effect(self, effect, cancellation=None):
        admission_scope = getattr(cancellation, "admission_scope", None)
        if callable(admission_scope):
            with admission_scope() as admitted:
                if not admitted:
                    return False, None
                with self._state_lock:
                    if self._shutdown_requested.is_set() or self._shutting_down:
                        return False, None
                    return True, effect()
        with self._state_lock:
            if self._shutdown_requested.is_set() or self._shutting_down:
                return False, None
            return True, effect()

    def collect_chat_context(self, payload):
        return self._chat_context(dict(payload or {})) if self._is_open() else None

    def handle_user_text_command(self, payload):
        return self._handle_user_text_command(dict(payload or {})) if self._is_open() else None

    def contextual_reply(self, payload):
        return self._handle_contextual_reply(dict(payload or {})) if self._is_open() else None

    def record_assistant_reply(self, payload):
        return self._record_completed_reply(dict(payload or {})) if self._is_open() else None

    def voice_segments(self, payload):
        return self._voice_segments(dict(payload or {})) if self._is_open() else None

    def voice_segments_requires_full_text(self, payload):
        return self._requires_full_text_voice_segments(dict(payload or {})) if self._is_open() else None

    def voice_warmup_paths(self):
        return self._voice_warmup_paths() if self._is_open() else None

    def status_snapshot(self) -> dict[str, Any]:
        personas = []
        per_persona_provider_count = 0
        active_persona = self._persona_by_id(self._active_persona_id)
        for persona in list(self.settings.personas or []):
            provider_id = str(persona.provider.provider_id or "inherit").strip().lower() or "inherit"
            if provider_id not in {"inherit", "main"}:
                per_persona_provider_count += 1
            personas.append(
                {
                    "id": str(persona.id or ""),
                    "display_name": str(persona.display_name or ""),
                    "enabled": bool(persona.enabled),
                    "source": str(persona.source or "buddy_chat"),
                    "provider_id": provider_id,
                    "model": str(persona.provider.model or ""),
                    "voice_enabled": bool(persona.voice.enabled),
                    "avatar_prompt_ready": bool(str(persona.avatar.prompt or "").strip()),
                    "avatar_image_path": str(persona.avatar.image_path or ""),
                }
            )
        return {
            "available": True,
            "enabled": bool(self.settings.enabled),
            "reply_mode": str(self.settings.reply_mode or "context_only"),
            "llm_mode": str(self.settings.llm_mode or "main"),
            "buddy_chat_instructor_structured_outputs_enabled": bool(self.settings.instructor_structured_outputs_enabled),
            "buddy_chat_instructor_available": bool(instructor_adapter.instructor_availability().available),
            "persona_count": len(list(self.settings.personas or [])),
            "active_persona_count": len(self.settings.enabled_personas()),
            "max_speakers": int(self.settings.max_speakers or 1),
            "forced_buddy_every": int(self.settings.forced_buddy_every or 0),
            "completed_reply_count": int(self.settings.completed_reply_count or 0),
            "forced_buddy_due_next": bool(self._forced_buddy_due()),
            "per_persona_provider_count": int(per_persona_provider_count),
            "voice_routing_requires_full_text": False,
            "voice_routing_preserves_stream_labels": bool(self._has_active_voice_routes()),
            "active_persona_window_enabled": bool(self.settings.active_persona_window_enabled),
            "active_persona_window_on_top": bool(self.settings.active_persona_window_on_top),
            "active_persona_id": str(self._active_persona_id or ""),
            "active_persona_name": str(active_persona.display_name if active_persona is not None else ""),
            "last_provider_error": str(self._last_provider_error or ""),
            "last_provider_error_at": float(self._last_provider_error_at or 0.0),
            "shared_provider": {
                "provider_id": str(self.settings.buddy_provider.provider_id or "inherit").strip().lower() or "inherit",
                "model": str(self.settings.buddy_provider.model or ""),
            },
            "personas": personas,
        }

    @staticmethod
    def _native_preview_payload(preview: BuddySetupPreview) -> dict[str, Any]:
        return {
            "setup_id": str(preview.setup_id or ""),
            "title": str(preview.title or ""),
            "summary": str(preview.summary or ""),
            "personas": [
                persona.to_dict() for persona in list(preview.personas or [])
            ],
            "group_behavior": {
                "max_speakers": int(preview.group_behavior.max_speakers),
                "allow_buddy_to_buddy": bool(
                    preview.group_behavior.allow_buddy_to_buddy
                ),
                "natural_second_speaker_every": int(
                    preview.group_behavior.natural_second_speaker_every
                ),
                "forced_buddy_every": int(
                    preview.group_behavior.forced_buddy_every
                ),
            },
            "adult_ready": bool(preview.adult_ready),
            "system_override_prompt": str(preview.system_override_prompt or ""),
            "normal_intimacy_prompt": str(preview.normal_intimacy_prompt or ""),
            "adult_nsfw_prompt": str(preview.adult_nsfw_prompt or ""),
        }

    @staticmethod
    def _native_preview_from_payload(payload: dict[str, Any]) -> BuddySetupPreview:
        data = dict(payload or {})
        group = dict(data.get("group_behavior") or {})
        return BuddySetupPreview(
            setup_id=str(data.get("setup_id") or "native_setup"),
            title=str(data.get("title") or "Buddy group"),
            summary=str(data.get("summary") or ""),
            personas=[
                BuddyPersona.from_dict(item)
                for item in list(data.get("personas") or [])
                if isinstance(item, dict)
            ],
            group_behavior=GroupBehavior(
                max_speakers=max(
                    1, min(4, int(group.get("max_speakers", 1) or 1))
                ),
                allow_buddy_to_buddy=bool(
                    group.get("allow_buddy_to_buddy", False)
                ),
                natural_second_speaker_every=max(
                    0,
                    min(
                        100,
                        int(group.get("natural_second_speaker_every", 0) or 0),
                    ),
                ),
                forced_buddy_every=max(
                    0, min(100, int(group.get("forced_buddy_every", 0) or 0))
                ),
            ),
            adult_ready=bool(data.get("adult_ready", False)),
            system_override_prompt=(
                str(data.get("system_override_prompt") or "") or None
            ),
            normal_intimacy_prompt=(
                str(data.get("normal_intimacy_prompt") or "") or None
            ),
            adult_nsfw_prompt=(str(data.get("adult_nsfw_prompt") or "") or None),
        )

    def native_snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "settings": copy.deepcopy(self.settings.to_dict()),
                "status": str(self._native_status or ""),
                "model_catalogs": copy.deepcopy(self._native_model_catalogs),
                "setup_choices": copy.deepcopy(self._native_setup_choices),
                "setup_preview": self._native_preview_payload(
                    self._native_setup_preview
                ),
                "refinement_busy": self._refinement_active_token is not None,
                "undo_available": self._setup_undo_settings is not None,
            }

    @staticmethod
    def _set_nested_value(
        payload: dict[str, Any], path: str, value: Any
    ) -> None:
        parts = [part for part in str(path or "").split(".") if part]
        if not parts:
            raise KeyError("Buddy Chat setting path is empty.")
        target: Any = payload
        for part in parts[:-1]:
            if isinstance(target, list):
                target = target[int(part)]
            elif isinstance(target, dict):
                if part not in target or target[part] is None:
                    target[part] = {}
                target = target[part]
            else:
                raise KeyError(f"Invalid Buddy Chat setting path '{path}'.")
        if isinstance(target, list):
            target[int(parts[-1])] = value
        elif isinstance(target, dict):
            target[parts[-1]] = value
        else:
            raise KeyError(f"Invalid Buddy Chat setting path '{path}'.")

    def native_update_setting(self, key: str, value: Any) -> None:
        path = str(key or "").strip()
        if path.startswith("setup_choices."):
            choice_key = path.split(".", 1)[1]
            with self._state_lock:
                if choice_key.startswith("traits."):
                    trait = choice_key.split(".", 1)[1]
                    if trait not in self._native_setup_choices["traits"]:
                        raise KeyError(f"Unknown Buddy setup trait '{trait}'.")
                    self._native_setup_choices["traits"][trait] = bool(value)
                elif choice_key in {
                    "buddy_count",
                    "participation",
                    "refine_scope",
                    "refine_persona",
                    "refine_field",
                    "refine_instruction",
                }:
                    self._native_setup_choices[choice_key] = value
                else:
                    raise KeyError(f"Unknown Buddy setup choice '{choice_key}'.")
            return
        if path.startswith("setup_preview."):
            preview_payload = self._native_preview_payload(
                self._native_setup_preview
            )
            self._set_nested_value(
                preview_payload, path.removeprefix("setup_preview."), value
            )
            with self._state_lock:
                self._native_setup_preview = self._native_preview_from_payload(
                    preview_payload
                )
            return
        allowed_top_level = {
            "enabled",
            "reply_mode",
            "llm_mode",
            "instructor_structured_outputs_enabled",
            "system_override_enabled",
            "system_override_prompt",
            "adult_nsfw_enabled",
            "normal_intimacy_prompt",
            "adult_nsfw_prompt",
            "active_persona_window_enabled",
            "active_persona_window_on_top",
            "allow_buddy_to_buddy",
            "max_speakers",
            "natural_second_speaker_every",
            "forced_buddy_every",
        }
        if path not in allowed_top_level and not path.startswith(
            ("buddy_provider.", "personas.")
        ):
            raise KeyError(f"Unknown Buddy Chat setting '{path}'.")
        payload_path = (
            "buddy_chat_instructor_structured_outputs_enabled"
            if path == "instructor_structured_outputs_enabled"
            else path
        )
        with self._state_lock:
            payload = self.settings.to_dict()
            self._set_nested_value(payload, payload_path, value)
            if path == "adult_nsfw_enabled" and bool(value):
                payload["adult_nsfw_acknowledged"] = True
            payload["settings_epoch"] = int(
                self.settings.settings_epoch or 0
            ) + 1
            self.settings = BuddySettings.from_dict(payload)
        self._save_settings(defer_write=True)

    def _native_stage_setup(self, request: dict[str, Any]) -> None:
        preset_id = str(request.get("preset_id") or "").strip()
        if preset_id:
            preview = preview_for_preset(preset_id)
        else:
            choices = copy.deepcopy(self._native_setup_choices)
            traits = tuple(
                key
                for key, enabled in dict(choices.get("traits") or {}).items()
                if bool(enabled)
            )
            preview = compose_wizard_preview(
                WizardChoices(
                    buddy_count=int(choices.get("buddy_count", 2) or 2),
                    participation=str(
                        choices.get("participation") or "balanced"
                    ),
                    traits=traits,
                )
            )
        preview.system_override_prompt = self.settings.system_override_prompt
        preview.normal_intimacy_prompt = self.settings.normal_intimacy_prompt
        preview.adult_nsfw_prompt = self.settings.adult_nsfw_prompt
        with self._state_lock:
            self._native_setup_preview = preview
        self._set_status(f"Previewing Buddy setup: {preview.title}.")

    def _native_generate_avatar(self, index: int) -> None:
        row_index = int(index)
        self._set_status("Generating buddy avatar through Visual Reply...")

        def worker(cancellation) -> None:
            try:
                result = self._request_persona_avatar_generation(
                    row_index,
                    auto_show=True,
                    commit_effect=lambda effect: self._commit_avatar_effect(
                        effect, cancellation
                    ),
                )
            except Exception as exc:
                result = {
                    "ok": False,
                    "message": f"Buddy avatar generation failed: {exc}",
                }
            if cancellation.cancelled or not self._is_open():
                return
            self._set_status(
                str(result.get("message") or "Buddy avatar request finished.")
            )

        self.tasks.spawn(f"native-avatar-generation-{row_index}", worker)

    def _native_test_provider(self) -> None:
        provider = BuddyPersona(
            id="test_buddy",
            display_name="Test Buddy",
            provider=ProviderOverride.from_dict(
                self.settings.buddy_provider.to_dict()
            ),
        )

        def worker(cancellation) -> None:
            try:
                text = self.llm_runtime.complete_for_persona(
                    persona=provider,
                    settings=BuddySettings(
                        enabled=True,
                        llm_mode="buddy",
                        buddy_provider=provider.provider,
                        personas=[provider],
                    ),
                    messages=[
                        {"role": "system", "content": "Reply with one short sentence."},
                        {"role": "user", "content": "Say Buddy Chat provider test ok."},
                    ],
                    fallback_model=self._current_model_name(),
                )
                message = "Provider test ok: " + (
                    text[:160] if text else "empty response"
                )
            except Exception as exc:
                message = f"Provider test failed: {exc}"
            if not cancellation.cancelled and self._is_open():
                self._set_status(message)

        self.tasks.spawn("native-provider-test", worker)
        self._set_status("Testing provider...")

    def _native_refresh_models(self, target_key: str) -> None:
        target = str(target_key or "shared").strip()
        if target == "shared":
            provider = self.settings.buddy_provider
        elif target.startswith("persona:"):
            index = int(target.split(":", 1)[1])
            provider = self.settings.personas[index].provider
        else:
            raise KeyError(f"Unknown Buddy model target '{target}'.")
        if str(provider.provider_id or "").strip().lower() != "lmstudio":
            self._set_status("Model refresh is available for LM Studio providers.")
            return
        base_url = str(provider.base_url or "").strip()
        api_key = str(provider.api_key or "").strip()
        lock_key = f"native|{target}|{base_url}|{api_key}"
        with self._model_catalog_lock:
            if lock_key in self._model_catalog_inflight:
                return
            self._model_catalog_inflight.add(lock_key)

        def worker(cancellation) -> None:
            error = ""
            models: list[str] = []
            try:
                models = list_lmstudio_models_for_base_url(
                    base_url, api_key=api_key
                )
            except Exception as exc:
                error = str(exc)
            finally:
                with self._model_catalog_lock:
                    self._model_catalog_inflight.discard(lock_key)
            if cancellation.cancelled or not self._is_open():
                return
            with self._state_lock:
                self._native_model_catalogs[target] = [
                    str(item or "").strip()
                    for item in models
                    if str(item or "").strip()
                ]
            self._set_status(
                f"Could not load LM Studio models: {error}"
                if error
                else f"Loaded {len(models)} LM Studio model(s) for Buddy Chat."
            )

        self.tasks.spawn(f"native-model-catalog-{target}", worker)
        self._set_status("Fetching LM Studio models for Buddy Chat...")

    def _native_refine_setup(self) -> None:
        with self._state_lock:
            if self._refinement_active_token is not None:
                return
            preview = copy.deepcopy(self._native_setup_preview)
            choices = copy.deepcopy(self._native_setup_choices)
            self._refinement_token += 1
            token = self._refinement_token
            self._refinement_active_token = token
        if not preview.personas:
            self._refinement_active_token = None
            self._set_status("Choose or build a Buddy setup first.")
            return
        persona_id = str(choices.get("refine_persona") or "")
        target = next((item for item in preview.personas if item.id == persona_id), preview.personas[0])
        persona_id = str(target.id or "")
        request = RefinementRequest(
            scope=str(choices.get("refine_scope") or "group"),
            instruction=str(choices.get("refine_instruction") or ""),
            preview=preview,
            persona_id=persona_id,
            field_name=str(choices.get("refine_field") or "display_name"),
        )
        settings_snapshot = BuddySettings.from_dict(self.settings.to_dict())

        def worker(cancellation) -> None:
            patch = None
            error = ""
            changes = []
            try:
                text = self.llm_runtime.complete_for_persona(
                    persona=target,
                    settings=settings_snapshot,
                    messages=build_refinement_messages(request),
                    fallback_model=self._current_model_name(),
                )
                patch = parse_refinement_result(text, request)
                if patch is None:
                    error = "The LLM returned no valid editable Buddy changes."
            except Exception as exc:
                error = f"Buddy setup refinement failed: {exc}"
            if cancellation.cancelled or not self._is_open():
                return
            with self._state_lock:
                if self._refinement_active_token != token:
                    return
                self._refinement_active_token = None
                if patch is not None:
                    updated = apply_refinement_patch(request.preview, patch)
                    changes = refinement_differences(request.preview, updated)
                    if not changes:
                        error = "The LLM proposed no changes. Try a more specific instruction; the staged setup was kept."
                    else:
                        self._native_setup_preview = updated
            self._set_status(
                error
                or f"Refined {len(changes)} field(s) in the staged Buddy setup. Review the preview, then use Apply Group."
            )

        self._set_status("Refining the staged Buddy setup with the selected LLM...")
        self.tasks.spawn("native-setup-refinement", worker)

    def native_action(self, action: str, payload=None) -> None:
        name = str(action or "").strip()
        request = dict(payload or {})
        if name == "save":
            self._save_settings()
            self._set_status("Buddy Chat settings saved.")
        elif name == "reset_system_prompt":
            self.native_update_setting(
                "system_override_prompt", DEFAULT_SYSTEM_OVERRIDE_PROMPT
            )
            self.native_update_setting("system_override_enabled", True)
            self._set_status("Buddy Chat override prompt reset to the recommended default.")
        elif name == "add_persona":
            index = len(self.settings.personas) + 1
            display_name = f"Buddy {index}"
            self.settings.personas.append(
                BuddyPersona(
                    id=f"buddy_{index}",
                    display_name=display_name,
                    avatar=AvatarProfile(
                        prompt=default_avatar_prompt(display_name),
                        preset=DEFAULT_AVATAR_PROMPT_PRESET,
                    ),
                )
            )
            self.settings.settings_epoch += 1
            self._save_settings()
            self._set_status(f"Added Buddy {index}.")
        elif name == "remove_persona":
            index = int(request.get("index", -1))
            if len(self.settings.personas) <= 1:
                raise RuntimeError("Keep at least one buddy. Disable Buddy Chat instead.")
            removed = self.settings.personas.pop(index)
            self.settings.settings_epoch += 1
            self._save_settings()
            self._set_status(f"Removed buddy: {removed.display_name or removed.id}")
        elif name == "use_avatar_preset":
            index = int(request.get("index", -1))
            persona = self.settings.personas[index]
            persona.avatar.prompt = default_avatar_prompt(
                persona.display_name,
                persona.role,
                persona.speaking_style,
                persona.avatar.preset,
            )
            self.settings.settings_epoch += 1
            self._save_settings()
            self._set_status(f"Avatar prompt preset applied for {persona.display_name}.")
        elif name == "generate_avatar":
            self._native_generate_avatar(int(request.get("index", -1)))
        elif name == "import_mprc":
            self._import_mprc_personas()
        elif name == "test_provider":
            self._native_test_provider()
        elif name == "refresh_models":
            self._native_refresh_models(str(request.get("target") or "shared"))
        elif name == "stage_setup":
            self._native_stage_setup(request)
        elif name == "apply_setup":
            with self._state_lock:
                preview = copy.deepcopy(self._native_setup_preview)
            self._setup_undo_settings = BuddySettings.from_dict(
                self.settings.to_dict()
            )
            self.settings = apply_setup_preview(self.settings, preview)
            self.settings.settings_epoch += 1
            self._save_settings()
            self._set_status(f"Applied Buddy setup: {preview.title}.")
        elif name == "cancel_setup":
            self._native_stage_setup({"preset_id": "reliable_guide"})
            self._set_status("Cancelled the staged Buddy setup.")
        elif name == "undo_setup":
            if self._setup_undo_settings is None:
                raise RuntimeError("There is no Buddy setup to undo in this session.")
            self.settings = BuddySettings.from_dict(
                self._setup_undo_settings.to_dict()
            )
            self.settings.settings_epoch += 1
            self._setup_undo_settings = None
            self._save_settings()
            self._set_status("Restored the previous Buddy Chat setup.")
        elif name == "refine_setup":
            self._native_refine_setup()
        elif name == "cancel_refinement":
            with self._state_lock:
                self._refinement_active_token = None
            self._set_status("Buddy setup refinement cancelled.")
        else:
            raise KeyError(f"Unknown Buddy Chat native action '{name}'.")

    def _has_active_voice_routes(self) -> bool:
        if not self.settings.enabled:
            return False
        for persona in self.settings.enabled_personas():
            voice = getattr(persona, "voice", None)
            if bool(getattr(voice, "enabled", False)) and str(getattr(voice, "sample_path", "") or "").strip():
                return True
        return False

    def _voice_warmup_paths(self) -> dict[str, Any] | None:
        if not self.settings.enabled:
            return None
        paths: list[str] = []
        for persona in self.settings.enabled_personas():
            voice = getattr(persona, "voice", None)
            path = str(getattr(voice, "sample_path", "") or "").strip()
            if not bool(getattr(voice, "enabled", False)) or not path or path in paths:
                continue
            paths.append(path)
        if not paths:
            return None
        return {"addon": "nc.buddy_chat", "paths": paths}

    def _voice_segments(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        streaming = bool(payload.get("streaming", False))
        stream_start = bool(payload.get("stream_start", False))
        if not self.settings.enabled:
            if streaming:
                with self._state_lock:
                    self._stream_voice_persona_id = ""
            return None

        personas = self.settings.enabled_personas()
        with self._state_lock:
            if streaming and stream_start:
                self._stream_voice_persona_id = ""
            current_persona_id = str(self._stream_voice_persona_id or "")

        text = str(payload.get("text") or "")
        result = split_buddy_voice_segments(text, personas=personas)
        explicit_segments = [
            dict(item)
            for item in list(result.get("segments") or [])
            if isinstance(item, dict)
        ]
        if streaming and not explicit_segments and current_persona_id:
            current_persona = next(
                (
                    persona
                    for persona in personas
                    if str(persona.id or "").strip().lower() == current_persona_id.lower()
                ),
                None,
            )
            if current_persona is not None and text.strip():
                result = split_buddy_voice_segments(
                    f"[{current_persona.display_name}]\n{text}",
                    personas=personas,
                )

        result = self._publish_addon_audio_events(result)

        segments = [
            dict(item)
            for item in list(result.get("segments") or [])
            if isinstance(item, dict)
        ]
        if streaming and segments:
            with self._state_lock:
                self._stream_voice_persona_id = str(segments[-1].get("persona_id") or "")

        if explicit_segments:
            self._record_voice_routing_debug(result, payload)
            self._update_active_persona_from_voice_segments(result)
        return result if segments else None

    @staticmethod
    def _publish_addon_audio_events(result: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(result or {})
        normalized["segments"] = [
            {**dict(item), "publish_tts_addon_events": True}
            for item in list(normalized.get("segments") or [])
            if isinstance(item, dict)
        ]
        return normalized

    def _persona_by_id(self, persona_id: str) -> BuddyPersona | None:
        target = str(persona_id or "").strip().lower()
        if not target:
            return None
        for persona in list(self.settings.personas or []):
            if str(persona.id or "").strip().lower() == target:
                return persona
        return None


    def _set_active_persona(self, persona_id: str, *, reason: str = "", text: str = "") -> None:
        persona = self._persona_by_id(persona_id)
        if persona is None:
            return
        with self._state_lock:
            self._active_persona_id = str(persona.id or "")
            self._active_persona_text = str(text or "").strip()
            self._active_persona_reason = str(reason or "").strip()


    def _update_active_persona_from_voice_segments(self, result: dict[str, Any] | None) -> None:
        if not isinstance(result, dict):
            return
        for segment in list(result.get("segments") or []):
            if not isinstance(segment, dict):
                continue
            persona_id = str(segment.get("persona_id") or "").strip()
            if persona_id:
                self._set_active_persona(
                    persona_id,
                    reason="TTS voice segment",
                    text=str(segment.get("text") or "").strip(),
                )
                return






    def _requires_full_text_voice_segments(self, payload: dict[str, Any]) -> dict[str, Any]:
        streaming = bool(payload.get("streaming", False))
        active_voice_routes = bool(self._has_active_voice_routes())
        preserve_voice_labels = bool(streaming and active_voice_routes)
        if not self.settings.enabled:
            reason = "buddy_chat_disabled"
        elif not streaming:
            reason = "buddy_chat_not_streaming"
        elif not active_voice_routes:
            reason = "buddy_chat_no_active_voice_routes"
        else:
            reason = "buddy_chat_streaming_voice_routing"
        return {
            "requires_full_text": False,
            "preserve_voice_labels": preserve_voice_labels,
            "reason": reason,
            "addon": "nc.buddy_chat",
            "active_voice_personas": [
                persona.id
                for persona in self.settings.enabled_personas()
                if bool(persona.voice.enabled) and str(persona.voice.sample_path or "").strip()
            ],
        }

    def _record_voice_routing_debug(self, result: dict[str, Any] | None, payload: dict[str, Any]) -> None:
        if not isinstance(result, dict):
            return
        segments = [dict(item) for item in list(result.get("segments") or []) if isinstance(item, dict)]
        if not segments and not bool(result.get("suppress_original", False)):
            return
        matched_personas = []
        missing_voice_personas = []
        voice_paths = []
        for segment in segments:
            persona_id = str(segment.get("persona_id") or "").strip()
            if not persona_id:
                continue
            if persona_id not in matched_personas:
                matched_personas.append(persona_id)
            voice_path = str(segment.get("voice_path") or "").strip()
            if voice_path:
                if voice_path not in voice_paths:
                    voice_paths.append(voice_path)
            elif persona_id not in missing_voice_personas:
                missing_voice_personas.append(persona_id)
        state = "Done" if segments else "Skipped"
        label = f"Buddy voice routing: {len(segments)} segment(s)" if segments else "Buddy voice routing: no matched segments"
        try:
            from core import debug_inspector

            queue_id = "buddy_chat.voice_routing." + str(abs(hash(str(payload.get("text", "")))))[:12]
            debug_inspector.begin_queue_item(
                queue_id,
                owner="nc.buddy_chat",
                label=label,
                kind="tts_voice_routing",
                state=state,
                waiting_on="TTS voice sample routing",
                source="addons/buddy_chat/controller.py",
                metadata={
                    "streaming": bool(payload.get("streaming", False)),
                    "suppress_original": bool(result.get("suppress_original", False)),
                    "segment_count": len(segments),
                    "matched_personas": matched_personas,
                    "voice_paths": voice_paths,
                    "missing_voice_personas": missing_voice_personas,
                    "text_preview": str(payload.get("text") or "")[:500],
                },
            )
            debug_inspector.finish_queue_item(queue_id, state=state)
        except Exception:
            return

















    def _chat_context(self, _payload: dict[str, Any]):
        if not self.settings.enabled:
            return None
        context = buddy_context_prompt(self.settings)
        if not context:
            return None
        return {
            "context": context,
            "debug": {
                "sources": ["buddy_chat"],
                "reply_mode": self.settings.reply_mode,
                "llm_mode": self.settings.llm_mode,
            },
        }

    def _handle_user_text_command(self, payload: dict[str, Any]):
        port = getattr(getattr(self.context, "capabilities", None), "document_memory", None)
        lease = port.begin_activity("buddy_chat", str(time.monotonic_ns())) if port is not None else None
        try:
            return self._handle_user_text_command_with_activity(payload)
        finally:
            if lease is not None:
                lease.close()

    def _handle_user_text_command_with_activity(self, payload: dict[str, Any]):
        if not self.settings.enabled:
            return None
        turn_context = payload.get("turn_context")
        if isinstance(turn_context, dict) and bool(
            turn_context.get("requires_shared_awareness_pipeline", False)
        ):
            # The shared Main Chat request owns image payloads and sensory
            # context. Buddy Chat contributes its roster through _chat_context
            # instead of replacing that request with a text-only persona call.
            return None
        forced_buddy = self.settings.reply_mode == "context_only" and self._forced_buddy_due()
        if self.settings.reply_mode != "main_answer" and not forced_buddy:
            return None
        user_text = str(payload.get("text") or "").strip()
        if not user_text or self._looks_like_other_addon_command(user_text):
            return None
        history = self._current_conversation_history()
        selected = self._select_speakers(user_text, history=history)
        if not selected:
            return None
        external_contexts = self._external_contexts(history)
        contextual_text = str(payload.get("context") or "").strip()
        if contextual_text:
            external_contexts.insert(0, contextual_text)
        contextual_source = str(payload.get("source") or "").strip().lower()
        fallback_model = self._current_model_name()
        replies: list[tuple[BuddyPersona, str]] = []
        provider_debug: list[dict[str, str]] = []
        errors: list[str] = []
        instructor_enabled = structured_models.structured_feature_enabled(self.settings)
        instructor_attempted = False
        instructor_used = False
        instructor_fallback = False
        for selection_index, persona in enumerate(selected):
            is_secondary = selection_index > 0
            allow_pass = not (forced_buddy and selection_index == 0)
            messages = build_persona_messages(
                persona=persona,
                settings=self.settings,
                user_text=user_text,
                history=history,
                external_contexts=external_contexts,
                previous_replies=replies,
                allow_pass=allow_pass,
                is_secondary=is_secondary,
            )
            try:
                config = self.llm_runtime.resolve_call_config(persona=persona, settings=self.settings, fallback_model=fallback_model)
                provider_debug.append(
                    {
                        "persona_id": persona.id,
                        "provider_id": config.provider_id,
                        "model": config.model,
                        "base_url": config.base_url,
                        "uses_main_runtime": str(bool(config.uses_main_runtime)),
                    }
                )
                reply = ""
                if instructor_enabled:
                    instructor_attempted = True
                    reply = self._complete_structured_persona_reply(persona=persona, messages=messages, fallback_model=fallback_model)
                    if reply:
                        instructor_used = True
                    else:
                        instructor_fallback = True
                if not reply:
                    reply = self.llm_runtime.complete_for_persona(
                        persona=persona,
                        settings=self.settings,
                        messages=messages,
                        fallback_model=fallback_model,
                    )
            except Exception as exc:
                if not self._is_open():
                    return None
                self._record_provider_error(persona, exc, messages)
                errors.append(f"{persona.display_name}: {exc}")
                continue
            if not self._is_open():
                return None
            normalized = normalize_persona_reply(
                persona,
                reply,
                self.settings.enabled_personas(),
            )
            if not normalized and forced_buddy:
                normalized = extract_selected_persona_reply(
                    persona,
                    reply,
                    self.settings.enabled_personas(),
                )
            if not normalized:
                continue
            if is_secondary and is_repetitive_secondary(
                [
                    self._strip_visible_persona_label(previous_persona, previous_reply)
                    for previous_persona, previous_reply in replies
                ],
                self._strip_visible_persona_label(persona, normalized),
            ):
                continue
            replies.append((persona, normalized))
        if not self._is_open():
            return None
        if not replies:
            if errors:
                if forced_buddy and selected:
                    persona = selected[0]
                    replies.append(
                        (
                            persona,
                            f"[{persona.display_name}]\nI couldn't form a full reply because my language model provider is unavailable.",
                        )
                    )
                else:
                    return {
                        "handled": True,
                        "response_text": "Buddy Chat could not reach the selected persona provider: " + "; ".join(errors[:2]),
                        "debug": {"sources": ["buddy_chat"], "errors": errors},
                    }
            else:
                return None
        if not self._is_open():
            return None
        self.settings.turn_index += 1
        first_persona, first_reply = replies[0]
        self._set_active_persona(
            first_persona.id,
            reason="Buddy reply",
            text=self._strip_visible_persona_label(first_persona, first_reply),
        )
        self._save_settings(defer_write=True)
        return {
            "handled": True,
            "response_text": "\n\n".join(reply for _persona, reply in replies),
            "use_llm_response": False,
            "prefer_low_latency_tts": True,
            "debug": {
                "sources": ["buddy_chat"],
                "forced_buddy": bool(forced_buddy),
                "contextual_source": contextual_source,
                "selected_personas": [persona.id for persona, _reply in replies],
                "providers": provider_debug,
                "errors": errors,
                "instructor_structured_outputs": self._instructor_debug_status(
                    enabled=instructor_enabled,
                    attempted=instructor_attempted,
                    used=instructor_used,
                    fallback=instructor_fallback,
                ),
                "memory_store": "engine.finalize_assistant_reply",
                "memory_note": "NC finalization records handled replies through the existing assistant-reply and continuity-memory hooks.",
            },
        }

    def _record_provider_error(self, persona: BuddyPersona, exc: Exception, messages: list[dict[str, str]]) -> None:
        error = compact_text(exc, 2000) or exc.__class__.__name__
        self._last_provider_error = f"{persona.display_name}: {error}"
        self._last_provider_error_at = time.time()
        try:
            path = Path(self.context.app_root) / "runtime" / "addons" / "nc.buddy_chat" / "buddy_chat_debug.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": self._last_provider_error_at,
                "persona": persona.display_name,
                "provider_mode": self.settings.llm_mode,
                "error": error,
                "message_roles": [str(item.get("role") or "") for item in messages],
            }
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def _handle_contextual_reply(self, payload: dict[str, Any]):
        if not self.settings.enabled:
            return None
        if self.settings.reply_mode == "context_only" and not self._forced_buddy_due():
            return None
        return self._handle_user_text_command(payload)

    def _complete_structured_persona_reply(self, *, persona: BuddyPersona, messages: list[dict[str, Any]], fallback_model: str) -> str:
        from core.runtime.document_context import filter_document_messages
        messages = filter_document_messages(messages)
        logger = getattr(self.context, "logger", None)
        payload = instructor_adapter.generate_buddy_structured_reply(
            llm_runtime=self.llm_runtime,
            persona=persona,
            settings=self.settings,
            messages=messages,
            fallback_model=fallback_model,
            logger=logger,
        )
        clean = structured_models.sanitize_structured_buddy_reply(
            payload,
            personas=self.settings.enabled_personas(),
            max_speakers=1,
            allowed_persona_ids={persona.id},
        )
        if (
            not list(clean.get("segments") or [])
            and structured_models.structured_buddy_reply_is_pass(payload)
        ):
            return BUDDY_PASS_TOKEN
        return structured_models.structured_buddy_reply_to_text(clean)

    @staticmethod
    def _instructor_debug_status(*, enabled: bool, attempted: bool, used: bool, fallback: bool) -> str:
        if not bool(enabled):
            return "disabled"
        if bool(used) and bool(fallback):
            return "partial"
        if bool(used):
            return "used"
        if bool(attempted) or bool(fallback):
            return "fallback"
        return "disabled"

    def _select_speakers(
        self,
        user_text: str,
        *,
        history: list[dict[str, Any]] | None = None,
    ) -> list[BuddyPersona]:
        return select_speakers(
            personas=self.settings.enabled_personas(),
            user_text=user_text,
            max_speakers=int(self.settings.max_speakers or 1),
            allow_buddy_to_buddy=bool(self.settings.allow_buddy_to_buddy),
            second_speaker_due=self._natural_second_speaker_due(),
            turn_index=int(self.settings.turn_index or 0),
            history=list(history or []),
        )

    def _natural_second_speaker_due(self) -> bool:
        interval = int(self.settings.natural_second_speaker_every or 0)
        return bool(interval > 0 and (int(self.settings.turn_index or 0) + 1) % interval == 0)

    def _forced_buddy_due(self) -> bool:
        interval = int(self.settings.forced_buddy_every or 0)
        return bool(interval > 0 and (int(self.settings.completed_reply_count or 0) + 1) % interval == 0)

    def _record_completed_reply(self, payload: dict[str, Any]):
        if not self.settings.enabled or not str(payload.get("text") or "").strip():
            return None
        self.settings.completed_reply_count = int(self.settings.completed_reply_count or 0) + 1
        self._save_settings(defer_write=True)
        return {
            "recorded": True,
            "completed_reply_count": int(self.settings.completed_reply_count),
        }

    @staticmethod
    def _looks_like_other_addon_command(text: str) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        return bool(
            re.search(r"^(play|pause|stop|next|previous|prev|resume)\b.*\b(music|spotify|track|song|playlist|album)\b", lowered)
            or re.search(r"^(play|pause|stop|next|previous|prev|resume)\b", lowered)
            or lowered.startswith("spotify ")
        )

    @staticmethod
    def _strip_visible_persona_label(persona: BuddyPersona, reply: str) -> str:
        text = str(reply or "").strip()
        if not text:
            return ""
        name = re.escape(str(persona.display_name or "").strip())
        if name:
            text = re.sub(rf"^\s*\[{name}\]\s*", "", text, flags=re.IGNORECASE).strip()
        return text

    def _current_conversation_history(self) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in self.conversation.history_snapshot()
            if isinstance(item, dict)
        ]

    def _current_model_name(self) -> str:
        return str(self.runtime_config.get("model_name", "") or "").strip()

    def _external_contexts(self, history: list[dict[str, Any]]) -> list[str]:
        contexts = []
        options = {"request_kind": "buddy_chat"} if getattr(self.conversation, "document_context_version", 0) >= 1 else {}
        for item in self.conversation.addon_contexts(history, **options):
            if not isinstance(item, dict):
                continue
            debug = item.get("debug")
            sources = (
                list(debug.get("sources") or ())
                if isinstance(debug, dict)
                else []
            )
            if "buddy_chat" in {str(source or "").strip() for source in sources}:
                continue
            context = str(item.get("context") or "").strip()
            if context:
                from core.runtime.document_context import DocumentContextTicket
                ticket = item.get("_nc_document_ticket")
                contexts.append({"role": "system", "content": context, "_nc_document_ticket": ticket} if isinstance(ticket, DocumentContextTicket) else context)
        return contexts

    def _load_settings(self) -> BuddySettings:
        try:
            payload = self.context.storage.read_json(SETTINGS_PATH)
            return BuddySettings.from_dict(payload if isinstance(payload, dict) else {})
        except Exception:
            return BuddySettings.default()

    def _write_settings_payload(self, payload: dict[str, Any]) -> None:
        try:
            self.context.storage.write_json(SETTINGS_PATH, dict(payload or {}))
        except Exception:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[BuddyChat] Could not save settings.", exc_info=True)

    def _save_settings(self, *, defer_write: bool = False) -> None:
        with self._state_lock:
            if self._shutting_down:
                return
            self._last_session_export_state = self._session_export_payload_unlocked()
            payload = copy.deepcopy(self._last_session_export_state["buddy_chat"]["settings"])
        if defer_write:
            self._queue_settings_payload(payload)
            return
        self._write_settings_payload(payload)

    def _queue_settings_payload(self, payload: dict[str, Any]) -> None:
        with self._settings_write_lock:
            self._pending_settings_payload = copy.deepcopy(dict(payload or {}))
            if self._settings_write_active:
                return
            self._settings_write_active = True
        try:
            self.tasks.spawn(
                "settings-writer",
                self._settings_write_worker,
            )
        except Exception:
            with self._settings_write_lock:
                self._settings_write_active = False
            raise

    def _settings_write_worker(self, cancellation) -> None:
        while True:
            with self._settings_write_lock:
                payload = self._pending_settings_payload
                self._pending_settings_payload = None
                if payload is None:
                    self._settings_write_active = False
                    return
            if cancellation.cancelled or not self._is_open():
                with self._settings_write_lock:
                    self._settings_write_active = False
                return
            self._write_settings_payload(payload)





    def _visual_reply_generation_service(self):
        service = self.visual_reply_service
        if service is None and self.context is not None:
            try:
                service = self.context.capabilities.visual_reply
                self.visual_reply_service = service
            except Exception:
                service = None
        return service

    def _request_persona_avatar_generation(
        self,
        index: int,
        *,
        auto_show: bool = True,
        commit_effect=None,
    ) -> dict[str, Any]:
        commit = commit_effect if callable(commit_effect) else self._commit_avatar_effect
        if not self._is_open():
            return {"ok": False, "message": "Buddy avatar generation was cancelled."}
        personas = list(self.settings.personas or [])
        row_index = int(index)
        if row_index < 0 or row_index >= len(personas):
            return {"ok": False, "message": "No buddy persona matched that avatar request."}
        persona = personas[row_index]
        prompt = str(persona.avatar.prompt or "").strip()
        if not prompt:
            prompt = default_avatar_prompt(persona.display_name, persona.role, persona.speaking_style, persona.avatar.preset)
        if not prompt:
            return {"ok": False, "message": "Add an avatar prompt before generating a buddy avatar."}
        service = self._visual_reply_generation_service()
        generator = getattr(service, "request_generation", None)
        if not callable(generator):
            return {"ok": False, "message": "Visual Reply generation service is unavailable."}
        if not self._is_open():
            return {"ok": False, "message": "Buddy avatar generation was cancelled.", "prompt": prompt}
        try:
            result = generator(
                prompt=prompt,
                caption=f"Buddy avatar: {persona.display_name}",
                provider="inherit",
                model="",
                size="1024x1024",
                source="nc.buddy_chat.avatar",
                metadata={
                    "persona_id": persona.id,
                    "display_name": persona.display_name,
                    "purpose": "buddy_avatar",
                    "preset": persona.avatar.preset,
                },
                auto_show=bool(auto_show),
            )
        except Exception as exc:
            return {"ok": False, "message": f"Buddy avatar generation failed:\n\n{exc}", "prompt": prompt}
        if not self._is_open():
            return {"ok": False, "message": "Buddy avatar generation was cancelled.", "prompt": prompt}
        image_path = str(result.get("image_path") or "").strip() if isinstance(result, dict) else ""
        if image_path and Path(image_path).exists():
            def apply_image():
                persona.avatar.prompt = prompt
                persona.avatar.image_path = image_path
                self._save_settings()
                return {
                    "ok": True,
                    "image_path": image_path,
                    "message": f"Buddy avatar generated: {Path(image_path).name}",
                    "prompt": prompt,
                }

            committed, response = commit(apply_image)
            return response if committed else {
                "ok": False,
                "message": "Buddy avatar generation was cancelled.",
                "prompt": prompt,
            }
        if result:
            def apply_prompt():
                persona.avatar.prompt = prompt
                self._save_settings()
                return {
                    "ok": True,
                    "image_path": "",
                    "message": "Visual Reply accepted the buddy avatar request, but no image path was returned yet.",
                    "prompt": prompt,
                }

            committed, response = commit(apply_prompt)
            return response if committed else {
                "ok": False,
                "message": "Buddy avatar generation was cancelled.",
                "prompt": prompt,
            }
        return {"ok": False, "message": "Visual Reply did not accept the buddy avatar request.", "prompt": prompt}














    def _import_mprc_personas(self) -> None:
        path = Path(self.context.app_root) / "runtime" / "addons" / "nc.multi_persona_roleplay" / "personas.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._set_status(f"Could not load MPRC personas: {exc}")
            return
        imported = [
            BuddyPersona.from_dict({**item, "source": "multi_persona_roleplay"})
            for item in list(payload or [])
            if isinstance(item, dict)
        ]
        if not imported:
            self._set_status("No MPRC personas found.")
            return
        with self._state_lock:
            existing_by_id = {persona.id: persona for persona in self.settings.personas}
            for persona in imported:
                existing_by_id[persona.id] = persona
            self.settings.personas = list(existing_by_id.values())
            self.settings.settings_epoch += 1
        self._save_settings()
        self._set_status(f"Loaded {len(imported)} MPRC persona(s).")









    def _voice_sample_folder(self) -> Path:
        root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
        return root / "voices"





    def _set_status(self, message: str) -> None:
        with self._state_lock:
            self._native_status = str(message or "")



    def _session_export_payload_unlocked(self) -> dict[str, Any]:
        return {"buddy_chat": {"settings": self.settings.to_dict()}}

    def export_session_state(self) -> dict[str, Any]:
        acquired = self._state_lock.acquire(blocking=False)
        if not acquired:
            return copy.deepcopy(self._last_session_export_state)
        try:
            if self._shutting_down:
                return copy.deepcopy(self._last_session_export_state)
            self._last_session_export_state = self._session_export_payload_unlocked()
            return copy.deepcopy(self._last_session_export_state)
        finally:
            self._state_lock.release()

    def import_session_state(self, session: dict[str, Any] | None) -> None:
        root = dict(session or {})
        grouped = root.get("buddy_chat")
        payload = dict(grouped or {}).get("settings") if isinstance(grouped, dict) else None
        if not isinstance(payload, dict):
            payload = root.get("settings")
        if isinstance(payload, dict):
            incoming_epoch = int(payload.get("settings_epoch", 0) or 0)
            incoming_settings = BuddySettings.from_dict(payload)
            with self._state_lock:
                if self._shutting_down:
                    return
                if incoming_epoch < int(self.settings.settings_epoch or 0):
                    return
                self.settings = incoming_settings
                self._last_session_export_state = self._session_export_payload_unlocked()
                settings_payload = copy.deepcopy(self._last_session_export_state["buddy_chat"]["settings"])
            self._write_settings_payload(settings_payload)

    def begin_shutdown(self) -> None:
        self._shutdown_requested.set()

    def shutdown(self) -> None:
        self.begin_shutdown()
        with self._state_lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            self._refinement_active_token = None
        self.tasks.cancel_and_join("buddy_chat_shutdown")
        with self._settings_write_lock:
            self._pending_settings_payload = None
            self._settings_write_active = False
