"""Contract-preserving bridge between the NC runtime and native QML."""

from __future__ import annotations
from core.persona_prompt_builder import normalize_builder, normalize_type
from ui.qml_bridge.persona_prompt_builder import PersonaPromptBuilderController

from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, is_dataclass
import json
import logging
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
import time
import uuid
from types import SimpleNamespace
from typing import Any

import dry_run
from PySide6 import QtCore, QtGui
from ui.qml_bridge.window_geometry import WindowGeometry

from core.image_attachments import image_paths
from core import conversation_history as conversation_history_runtime
from core import tutorial_catalog
from core import tutorial_scope
from core.tutorial_course import prepare_tutorial
from core.tutorial_narration import TutorialNarrationController
from addons.visual_reply.providers import PROVIDER_SPECS as VISUAL_REPLY_PROVIDER_SPECS
from addons.visual_reply.providers import provider_settings_from_config
from addons.visual_reply.comfyui_prompting import (
    RULE_LABELS as COMFYUI_RULE_LABELS,
    cached_detection as cached_comfyui_detection,
    detect_workflow_model,
    effective_rules as effective_comfyui_rules,
    normalize_rules as normalize_comfyui_rules,
    remember_detection as remember_comfyui_detection,
    ModelDetection as ComfyUIModelDetection,
)
from addons.visual_reply.runtime_config import (
    RUNWARE_DEFAULT_IMAGE_TO_IMAGE_MODEL,
    RUNWARE_IMAGE_TO_IMAGE_MODEL_OPTIONS,
    XAI_DEFAULT_IMAGE_TO_IMAGE_MODEL,
    XAI_IMAGE_TO_IMAGE_MODEL_OPTIONS,
    VisualReplyRuntime,
    size_labels_for_provider,
)
from addons.ai_presence_mode.mood_color_resolver import normalize_mood_name, resolve_mood_colors
from ui.qml_bridge.portrait_playback import portrait_message_id, portrait_generation_moods
from addons.ai_presence_mode.native_controller import AI_PRESENCE_CORE_SESSION_KEYS
from core import chat_providers, lmstudio_runtime, visual_reply_history
from core.persona_overrides import normalize_persona_overrides
from core.chat_runtime_session_schema import GENERATION_DEFAULT_KEYS
from core.sensory import (
    capture_snapshot as capture_sensory_snapshot,
    get_provider as get_sensory_provider,
    list_providers as list_sensory_providers,
)
from core.sensory_source_selection import (
    normalize_source_tokens,
    source_runtime_updates,
    source_tokens_value,
)
from core.runtime.providers import infer_model_supports_images
from core.session_persistence_contract import RestorePhase
from core.runtime.visual import (
    normalize_persona_self_image_mode,
    normalize_persona_appearance_freedom,
    normalize_persona_visual_reply_policy,
    persona_visual_request_config,
    resolve_persona_visual_reply_policy,
)
from core.stt_runtime import (
    WHISPER_LANGUAGE_OPTIONS,
    WHISPER_MODEL_SIZE_OPTIONS,
    normalize_whisper_language,
    stt_backend_runtime_config,
)
from ui.qml_bridge.conversation_window import ConversationVisualWindow, normalize_visual_batch_size
from ui.qml_bridge.conversation_list_model import ConversationListModel
from ui.qml_bridge import composer_spellcheck
from ui.qml_bridge.conversation_commands import ConversationCommands
from ui.qml_bridge.voice_references import local_voice_reference_files
from ui.qml_bridge.musetalk_preview import MuseTalkPreview
from ui.qml_bridge.musetalk_creator import MuseTalkCreatorModel
from ui.qml_bridge.system_prompt_library import (
    add_prompt_to_quick,
    all_prompt_records,
    delete_custom_prompts,
    find_prompt,
    is_prompt_quick,
    remove_prompt_from_quick,
    save_prompt_as,
)
from ui.shell_specs import (
    UI_SHELL_CHUNKING_SPECS,
    UI_SHELL_DEFAULT_CHUNKING_VALUES,
)
from ui.qml_bridge.quick_persona_store import (
    QUICK_PERSONA_PAGE_SIZE,
    QuickPersonaStore,
    clean_persona_portrait_prompt,
)
from ui.qml_bridge.workspace_layout import MAIN_DOCK_ZONES, QmlWorkspaceLayoutStore
from ui.qml_bridge.addon_rail_layout import AddonRailLayoutStore
from ui.qml_bridge.appearance import AppearanceController
from ui.qml_bridge.audio_controls import AudioControlsBridge
from ui.qml_bridge.adapters import (
    HotkeysNativeAdapter,
    build_ai_presence_adapter,
    build_audio_story_mode_adapter,
    build_buddy_chat_adapter,
    build_chatterbox_adapter,
    build_chatterbox_multilingual_adapter,
    build_chat_replay_adapter,
    build_clipboard_source_adapter,
    build_companion_orb_adapter,
    build_corsair_visual_instrument_adapter,
    build_discord_voice_bridge_adapter,
    build_elevenlabs_tts_adapter,
    build_gemini_tts_adapter,
    build_identity_artifacts_adapter,
    build_main_chat_remote_adapter,
    build_mock_heart_rate_adapter,
    build_multi_persona_roleplay_adapter,
    build_musetalk_avatar_adapter,
    build_musetalk_preprocess_adapter,
    build_pockettts_adapter,
    build_pockettts_multilingual_adapter,
    build_rag_context_adapter,
    build_screen_source_adapter,
    build_scenic_avatar_adapter,
    build_spotify_sense_adapter,
    build_supervisor_adapters,
    build_user_identity_adapter,
    build_vseeface_avatar_adapter,
    build_visual_reply_core_adapter,
    build_visual_story_adapter,
    build_web_intelligence_adapter,
    build_webcam_source_adapter,
)
from ui.qml_bridge.resources import ResourceMonitor
from ui.qml_bridge.native_registry import NativeSurfaceRegistry
from addons.voice_studio.native_adapter import build_voice_studio_adapter
from addons.scenic_pack_creator.native_adapter import build_scenic_pack_creator_adapter
from ui.qml_bridge.native_console import NativeConsoleCapture
from ui.qml_bridge.native_addons import NativeAddonRuntime
from ui.qml_bridge.native_dry_run import NativeDryRunController
from ui.qml_bridge.native_runtime import NativeRuntimeController
from ui.qml_bridge.native_presets import NativePresetStore
from ui.qml_bridge.native_session import NativeSessionStore
from ui.qml_bridge.native_telemetry import normalize_pipeline_progress
from ui.qml_bridge.ui_review_notes import UiReviewNotesController
from ui.qml_bridge.visual_reply_toolbar import VisualReplyToolbarController
from ui.conversation_action_layout import (
    normalize_conversation_response_action_layout,
    normalize_conversation_user_action_layout,
)
from visual_presence import runtime as visual_presence_runtime


_APP_ROOT = Path(__file__).resolve().parents[2]
_VOICE_INDICATOR_STYLES = frozenset({"ribbon", "spectrum", "kinetic"})
_CONVERSATION_CANVAS_STYLES = frozenset(
    {"original", "glass", "recessed", "vignette"}
)
_SPEECH_HIGHLIGHT_MODES = frozenset({"off", "word", "reading"})
_SPEECH_HIGHLIGHT_STYLES = frozenset({"classic", "rounded", "glow", "flow"})


def _bounded_strength(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _identity_relay_state_for_qml(
    payload: Mapping[str, Any] | None,
    *,
    persona_ref: str,
    persona_has_explicit_ref: bool,
) -> dict[str, Any]:
    """Normalize addon-owned Identity Relay state for the two QML surfaces."""

    options = [{"label": "None", "value": ""}]
    if not isinstance(payload, Mapping):
        return {
            "available": False,
            "options": options,
            "personaRef": str(persona_ref or "") if persona_has_explicit_ref else "",
            "personaHasExplicitRef": bool(persona_has_explicit_ref),
            "connectedRef": "",
            "connectedLabel": "",
            "relayAvailable": False,
            "enabled": False,
            "pending": False,
            "pendingRef": "",
            "warning": "",
            "status": "Identity Relay is unavailable.",
            "phase": "idle",
            "reviewReady": False,
            "review": {},
        }

    labels: dict[str, str] = {}
    for item in list(payload.get("artifacts") or []):
        if not isinstance(item, Mapping):
            continue
        artifact_ref = str(
            item.get("artifact_ref") or item.get("artifact_id") or ""
        ).strip()
        if not artifact_ref or artifact_ref in labels:
            continue
        artifact_id = str(item.get("artifact_id") or artifact_ref).strip()
        provider = str(item.get("provider_label") or "").strip()
        label = f"{provider} - {artifact_id}" if provider else artifact_id
        labels[artifact_ref] = label
        options.append({"label": label, "value": artifact_ref})

    connected_ref = str(payload.get("connected_ref") or "").strip()
    selected_ref = (
        str(persona_ref or "").strip()
        if persona_has_explicit_ref
        else connected_ref
    )
    for artifact_ref in (connected_ref, selected_ref):
        if artifact_ref and artifact_ref not in labels:
            labels[artifact_ref] = "Unavailable imported identity"
            options.append(
                {"label": labels[artifact_ref], "value": artifact_ref}
            )
    warning = str(payload.get("relay_warning") or "").strip()
    pending = bool(payload.get("connection_pending", False))
    review_value = payload.get("connection_review")
    review = dict(review_value) if isinstance(review_value, Mapping) else {}
    status = str(payload.get("connection_status") or "").strip()
    if not status:
        if pending:
            status = "Waiting for Identity Relay review."
        elif connected_ref and bool(payload.get("relay_available", False)):
            status = "Connected and approved. Enable it per conversation when needed."
        elif connected_ref:
            status = warning or "The connected identity is unavailable."
        elif len(options) > 1:
            status = "Choose an imported identity for this persona."
        else:
            status = "No imported identities are available."
    return {
        "available": True,
        "options": options,
        "personaRef": selected_ref,
        "personaHasExplicitRef": bool(persona_has_explicit_ref),
        "connectedRef": connected_ref,
        "connectedLabel": labels.get(connected_ref, ""),
        "relayAvailable": bool(payload.get("relay_available", False)),
        "enabled": bool(payload.get("relay_enabled", False)),
        "pending": pending,
        "pendingRef": str(payload.get("pending_ref") or ""),
        "warning": warning,
        "status": status,
        "phase": str(payload.get("connection_phase") or "idle"),
        "reviewReady": bool(payload.get("review_ready", False)),
        "review": review,
    }


def _invoke_identity_relay_capability(
    addons: Any,
    capability: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Invoke the addon through the finite facade boundary."""

    invoker = getattr(addons, "invoke_addon_capability", None)
    if not callable(invoker):
        return None
    result = invoker(
        "nc.identity_artifacts",
        str(capability or ""),
        dict(payload or {}),
    )
    if not bool(getattr(result, "accepted", False)):
        return None
    value = getattr(result, "value", None)
    return dict(value) if isinstance(value, Mapping) else None


_VISUAL_REPLY_DISPLAY_MODES = frozenset({"fit", "fill", "original", "compact"})
_PERSONA_MOOD_PORTRAITS = ("neutral", "happy", "sad", "angry", "curious")
_SPEECH_TIMING_KEYS = tuple(UI_SHELL_CHUNKING_SPECS)
_CHAT_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"})
_CHAT_FONT_SIZES = (8, 10, 12, 14, 16, 18, 20)
_STARTUP_SESSION_CONFIG_KEYS = frozenset(
    {
        "chat_provider",
        "chat_provider_settings",
        "chat_provider_generation_settings",
        "model_name",
        "model_requires_vision",
        "model_supports_images",
        "model_supports_reasoning",
        "model_supports_reasoning_toggle",
        "stt_backend_settings",
        "gemini_tts_preview_settings",
        "elevenlabs_tts_settings",
        "visual_reply_provider",
        "visual_reply_provider_settings",
        "visual_reply_mode",
        "visual_replies_enabled",
        "visual_reply_model",
        "visual_reply_size",
        "visual_reply_auto_show_dock",
        "conversation_speech_highlight_mode",
        "conversation_speech_highlight_style",
        "conversation_visual_reply_display_mode",
        "conversation_visual_reply_auto_follow",
        "conversation_visual_replies_visible",
        "conversation_live_session_visible",
        "conversation_console_visible",
        "conversation_console_auto_scroll",
        "conversation_console_font_size",
        "conversation_reset_button_visible",
        "conversation_save_button_visible",
        "conversation_save_as_button_visible",
        "conversation_load_button_visible",
        "conversation_memory_button_visible",
        "conversation_web_search_visible",
        "conversation_canvas_style",
        "conversation_background_path",
        "conversation_transparent_message_cards_enabled",
        "conversation_message_text_color",
        "conversation_message_font_family",
        "conversation_bionic_reading_enabled",
        "conversation_message_borders_enabled",
        "conversation_response_width_ratio",
        "conversation_response_min_height",
        "conversation_response_action_layout",
        "conversation_user_width_ratio",
        "conversation_user_min_height",
        "conversation_user_action_layout",
        "conversation_action_labels_enabled",
        "conversation_response_placement_guides_enabled",
        "active_quick_persona_name",
        "active_quick_persona_id",
        "persona_visual_identity_prompt",
        "persona_portrait_prompt",
        "persona_visual_reference_path",
        "persona_self_image_mode",
        "persona_appearance_freedom",
        "persona_visual_reference_strength",
        "persona_mood_reference_enabled",
        "voice_path",
        "tts_use_cloned_voice",
        "audio_input_device",
        # Output routing intentionally follows the operating-system default on
        # every launch. A user may still choose another device for this run.
        "audio_output_volume",
        "ai_presence_microphone_reactivity_enabled",
        *AI_PRESENCE_CORE_SESSION_KEYS,
    }
)


def _extract_quick_persona_fallbacks(
    values: Mapping[str, Any] | None,
) -> dict[str, Any]:
    config = dict(values or {})
    visual_policy = resolve_persona_visual_reply_policy(config)
    return {
        "active_quick_persona_id": "",
        "system_prompt": str(config.get("system_prompt") or ""),
        "persona_prompt_type": normalize_type(config.get("persona_prompt_type")),
        "emotional_instructions": str(config.get("emotional_instructions") or ""),
        "voice_path": str(config.get("voice_path") or ""),
        "tts_use_cloned_voice": bool(config.get("tts_use_cloned_voice", True)),
        "persona_visual_reply_policy": visual_policy,
        "visual_reply_mode": "off" if visual_policy == "off" else "auto",
        "visual_replies_enabled": visual_policy != "off",
        "visual_reply_auto_show_dock": bool(
            config.get("visual_reply_auto_show_dock", True)
        ),
    }


def restore_startup_session_state(
    session_store: Any,
    addon_runtime: Any,
    *,
    restore_user_identity=None,
    capture_persona_fallbacks=None,
    restore_active_quick_persona=None,
    sync_ui=None,
) -> None:
    payload = dict(session_store.addon_import_payload() or {})
    session_store.restore_config_phase(RestorePhase.PRE_ADDON)
    addon_runtime.start()
    addon_runtime.import_session_state(payload)
    session_store.restore_config_phase(RestorePhase.POST_ADDON)
    session_store.restore_config_phase(RestorePhase.OWNER_PROJECTION)
    if callable(restore_user_identity):
        restore_user_identity()
    if callable(capture_persona_fallbacks):
        capture_persona_fallbacks()
    if callable(restore_active_quick_persona):
        restore_active_quick_persona()
    session_store.restore_config_phase(RestorePhase.UI_SYNC)
    if callable(sync_ui):
        sync_ui()


def _voice_reference_options(
    app_root: Path,
    configured_voice_path: Any,
) -> list[dict[str, str]]:
    """List app-local voices while keeping a saved missing reference visible."""

    root = Path(app_root).resolve()
    options = [
        {
            "label": path.name,
            "value": str(Path("voices") / path.name),
        }
        for path in local_voice_reference_files(root)
    ]
    configured = str(configured_voice_path or "").strip()
    normalized_values = {
        str(option["value"]).replace("\\", "/").lower() for option in options
    }
    normalized_configured = configured.replace("\\", "/").lower()
    if configured and normalized_configured not in normalized_values:
        configured_path = Path(configured)
        candidate = configured_path if configured_path.is_absolute() else root / configured_path
        label = configured_path.name or configured
        if not candidate.is_file():
            label = f"{label} (missing)"
        options.append({"label": label, "value": configured})
    return [{"label": "Built-in / default voice", "value": ""}, *options]


def _normalize_chat_font_size(value: Any) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        return 12
    return min(_CHAT_FONT_SIZES, key=lambda candidate: abs(candidate - requested))


def _normalize_console_font_size(value: Any) -> int:
    try:
        return max(8, min(32, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 12


def _normalize_conversation_response_width_ratio(value: Any) -> float:
    try:
        requested = float(value)
    except (TypeError, ValueError):
        return 0.68
    return min(0.96, max(0.35, requested))


def _normalize_conversation_response_min_height(value: Any) -> int:
    try:
        requested = int(round(float(value)))
    except (TypeError, ValueError):
        return 140
    return min(420, max(96, requested))


def _normalize_conversation_user_width_ratio(value: Any) -> float:
    try:
        requested = float(value)
    except (TypeError, ValueError):
        return 0.0
    if requested <= 0.0:
        return 0.0
    return min(0.92, max(0.28, requested))


def _normalize_conversation_user_min_height(value: Any) -> int:
    try:
        requested = int(round(float(value)))
    except (TypeError, ValueError):
        return 96
    return min(420, max(96, requested))


def _quick_chat_context_path() -> Path:
    return _APP_ROOT / "runtime" / "chat_context_quick_save.json"


def _write_quick_chat_context(application: Any, target: Path, *, on_saved=None) -> str:
    from ui.qml_bridge.chat_context_io import write_chat_context
    return write_chat_context(application, target, on_saved=on_saved)


def _load_quick_chat_context(application: Any, target: Path, *, on_loaded=None) -> str:
    from ui.qml_bridge.chat_context_io import load_chat_context
    return load_chat_context(application, target, on_loaded=on_loaded)


def _model_catalog_entry_supports_images(item: Mapping[str, Any]) -> bool:
    """Resolve catalog image support while preserving explicit provider metadata."""
    from ui.qml_bridge.model_catalog import model_catalog_entry_supports_images
    return model_catalog_entry_supports_images(item)


def _filter_model_catalog(
    catalog: list[dict[str, Any]],
    *,
    require_vision: bool,
    require_tools: bool = False,
) -> list[dict[str, Any]]:
    from ui.qml_bridge.model_catalog import model_catalog_entry_tool_support
    return [dict(item) for item in catalog
            if (not require_vision or _model_catalog_entry_supports_images(item))
            and (not require_tools or model_catalog_entry_tool_support(item) is not False)]


def _normalize_model_catalog(
    catalog: Any,
) -> tuple[list[dict[str, Any]], str]:
    """Normalize provider catalogs while keeping error placeholders out of the UI."""

    normalized: list[dict[str, Any]] = []
    catalog_error = ""
    for raw_item in list(catalog or []):
        if isinstance(raw_item, Mapping):
            item = dict(_plain(raw_item) or {})
            model_id = str(
                item.get("id") or item.get("model") or item.get("name") or ""
            ).strip()
        else:
            model_id = str(raw_item or "").strip()
            item = {"id": model_id}
        if not model_id:
            continue
        if model_id.lower().startswith("error: check "):
            catalog_error = model_id
            continue
        normalized.append(item)
    return normalized, catalog_error


def _single_loaded_lmstudio_model(
    provider_id: str,
    selected_model: str,
    catalog: Any,
) -> str:
    """Return an unambiguous loaded LM Studio model for empty legacy sessions."""

    if str(provider_id or "").strip().lower() != "lmstudio":
        return ""
    if str(selected_model or "").strip():
        return ""
    loaded_names = {
        str(item.get("id") or item.get("model") or item.get("name") or "").strip()
        for item in list(catalog or [])
        if isinstance(item, Mapping) and bool(item.get("loaded"))
    }
    loaded_names.discard("")
    return next(iter(loaded_names)) if len(loaded_names) == 1 else ""


def _vision_provider_activation_controls(
    provider_id: str,
    enabled: bool,
) -> tuple[tuple[str, str, bool], ...]:
    """Return addon-owned activation controls coupled to a sensory source."""

    source = str(provider_id or "").strip().lower()
    state = bool(enabled)
    if source == "companion_orb_target":
        controls = [
            (
                "companion_orb_overlay_tab",
                "companion_orb_sensory_target_enabled_checkbox",
                state,
            )
        ]
        return tuple(controls)
    if source == "spotify_sense":
        return (("spotify_sense_tab", "spotify_sense_enabled", state),)
    return ()


def _empty_sensory_probe_message(provider_id: str) -> str:
    source = str(provider_id or "").strip().lower()
    return {
        "clipboard": (
            "No clipboard snapshot is ready. Copy an image, then test again. "
            "Configure background clipboard capture in the Clipboard Source addon."
        ),
        "companion_orb_target": (
            "No Companion Orb snapshot is ready. Select an Orb target or enable its "
            "full-screen context map, then test again."
        ),
        "spotify_sense": (
            "No Spotify snapshot is pending. Spotify must be connected, song-change "
            "monitoring/commentary must be enabled, and a fresh track change must occur."
        ),
    }.get(source, "The provider returned no snapshot. Check device access and provider settings.")


class _NativeAddonCatalogView:
    """Read-only manager-shaped view over the facade's serialized catalog."""

    def __init__(self, categories: list[dict[str, Any]]) -> None:
        self._categories = []
        for item in categories:
            category = dict(item or {})
            # Required Runtime services are managed on their Runtime pages,
            # outside the optional-addon toggles and generated workspaces.
            addons = list(category.get("addons") or [])
            category["addons"] = [
                dict(addon or {}) for addon in addons
                if not dict(addon or {}).get("core_runtime", False)
            ]
            if category["addons"] or not addons:
                self._categories.append(category)
        self._records: dict[str, SimpleNamespace] = {}
        self._contributions: list[SimpleNamespace] = []
        for category in self._categories:
            for addon in list(category.get("addons") or []):
                payload = dict(addon or {})
                addon_id = str(payload.get("id") or "").strip()
                if not addon_id:
                    continue
                manifest = SimpleNamespace(
                    id=addon_id,
                    name=str(payload.get("name") or addon_id),
                    description=str(payload.get("description") or ""),
                    category=str(payload.get("category") or "").strip().lower(),
                    version=str(payload.get("version") or ""),
                    enabled=bool(payload.get("manifest_enabled", True)),
                    root_dir=Path(str(payload.get("root_dir") or _APP_ROOT)),
                    manifest_path=None,
                    runtime_defaults=dict(payload.get("runtime_defaults") or {}),
                )
                record = SimpleNamespace(
                    manifest=manifest,
                    state=str(payload.get("state") or "initialized"),
                    addon_enabled=bool(payload.get("enabled", True)),
                    effective_enabled=bool(payload.get("effective_enabled", True)),
                )
                manifest._catalog_record = record
                self._records[addon_id] = record
                for raw_ui in list(payload.get("ui") or []):
                    entry = dict(raw_ui or {})
                    metadata = dict(entry.get("metadata") or {})
                    icon_path = str(
                        entry.get("icon_path") or metadata.get("icon_path") or ""
                    ).strip()
                    self._contributions.append(
                        SimpleNamespace(
                            addon_id=addon_id,
                            id=str(entry.get("id") or addon_id).strip(),
                            title=str(entry.get("title") or manifest.name).strip(),
                            area=str(entry.get("area") or "top_level").strip().lower(),
                            order=int(entry.get("order", 1000) or 1000),
                            tooltip=str(entry.get("tooltip") or "").strip(),
                            parent_tab_id=str(entry.get("parent_tab_id") or "").strip(),
                            icon_path=icon_path,
                            metadata=metadata,
                        )
                    )

    def get_addon_registry_snapshot(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._categories]

    def get_tab_contributions(self, area: str = "top_level") -> list[SimpleNamespace]:
        target = str(area or "top_level").strip().lower()
        return sorted(
            [item for item in self._contributions if item.area == target],
            key=lambda item: (item.order, item.title.lower()),
        )

    def get_addon_record(self, addon_id: str):
        return self._records.get(str(addon_id or "").strip())

    def _addon_enabled_override(self, addon_id: str) -> bool | None:
        record = self.get_addon_record(addon_id)
        if record is None:
            return None
        if record.addon_enabled == bool(record.manifest.enabled):
            return None
        return bool(record.addon_enabled)

    @staticmethod
    def _manifest_effectively_enabled(manifest: Any) -> bool:
        return bool(
            getattr(
                getattr(manifest, "_catalog_record", None),
                "effective_enabled",
                getattr(manifest, "enabled", True),
            )
        )


def _normalize_voice_indicator_style(value: Any) -> str:
    normalized = str(value or "ribbon").strip().lower()
    return normalized if normalized in _VOICE_INDICATOR_STYLES else "ribbon"


def _normalize_conversation_canvas_style(value: Any) -> str:
    normalized = str(value or "original").strip().lower()
    return normalized if normalized in _CONVERSATION_CANVAS_STYLES else "original"


def _normalize_conversation_message_text_color(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    return normalized if re.fullmatch(r"#[0-9a-f]{6}", normalized) else ""


def _normalize_conversation_message_font_family(value: Any) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized or len(normalized) > 128:
        return ""
    if any(ord(character) < 32 for character in normalized):
        return ""
    return normalized


def _normalize_speech_highlight_mode(value: Any) -> str:
    normalized = str(value or "off").strip().lower()
    return normalized if normalized in _SPEECH_HIGHLIGHT_MODES else "off"


def _normalize_speech_highlight_style(value: Any) -> str:
    normalized = str(value or "classic").strip().lower()
    return normalized if normalized in _SPEECH_HIGHLIGHT_STYLES else "classic"


def _normalize_visual_reply_display_mode(value: Any) -> str:
    normalized = str(value or "fit").strip().lower()
    return normalized if normalized in _VISUAL_REPLY_DISPLAY_MODES else "fit"


def _provider_failure_message(text: Any) -> str:
    """Return a concise provider failure line, or an empty string."""

    value = str(text or "")
    lowered = value.lower()
    patterns = (
        "provider request failed",
        "frozen completion failed",
        "selected chat provider did not pass",
    )
    if not any(pattern in lowered for pattern in patterns):
        return ""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    for line in reversed(lines):
        if any(pattern in line.lower() for pattern in patterns):
            return line[:240]
    return "Language provider failure"


def _local_asset_url(relative_path: str) -> str:
    """Return a QML-safe URL for an existing repository asset."""

    normalized = str(relative_path or "").strip()
    if not normalized:
        return ""
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = _APP_ROOT / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return ""
    if not resolved.is_file():
        return ""
    return QtCore.QUrl.fromLocalFile(str(resolved)).toString()


def _plain(value: Any) -> Any:
    """Convert frozen runtime snapshots to QML-safe values."""

    # JavaScript arrays and objects passed through a QVariant slot arrive as
    # QJSValue instances. Convert them before the normal recursive handling;
    # stringifying a QJSValue loses file URLs carried by picker actions.
    if hasattr(value, "toVariant"):
        try:
            value = value.toVariant()
        except (AttributeError, RuntimeError, TypeError):
            return None
    if is_dataclass(value):
        return {
            field.name: _plain(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _conversation_history_with_edited_assistant(
    history: Iterable[Mapping[str, object]],
    history_index: int,
    content: str,
    *,
    edited_at: float,
    allow_user: bool = False,
) -> tuple[dict[str, object], ...]:
    """Edit one response (or input when opted in), preserving all other records."""

    replacement = [dict(_plain(item) or {}) for item in history]
    position = int(history_index)
    if position < 0 or position >= len(replacement):
        raise IndexError("The selected response is no longer in the conversation.")
    text = str(content or "")
    if not text.strip():
        raise ValueError("A message cannot be saved as empty text.")
    item = replacement[position]
    metadata = dict(item.get("metadata") or {})
    role = str(item.get("role") or "").strip().lower()
    origin = str(item.get("origin") or metadata.get("origin") or "").strip().lower()
    is_user = role == "user" or origin == "input"
    if not ((role == "assistant" and origin != "input") or (allow_user and is_user)):
        raise ValueError("Only assistant responses can be edited from this control.")
    item["content"] = text
    item["nc_user_edited"] = True
    item["nc_user_edited_at"] = float(edited_at)
    return tuple(replacement)


def _conversation_inline_edit_identity(message: Mapping[str, Any]) -> tuple[str, ...]:
    item = dict(message or {})
    metadata = dict(item.get("metadata") or {})
    return (
        str(item.get("role") or ""),
        str(item.get("origin") or metadata.get("origin") or ""),
        str(item.get("normal_chat_transaction_id") or ""),
        str(item.get("created_at") or ""),
        str(item.get("content") or ""),
    )


def _message_mood(content: Any, metadata: Mapping[str, Any] | None = None,
                  portrait_names: object = ()) -> str:
    """Resolve a stable portrait mood from existing message metadata or tags."""

    values = dict(metadata or {})
    names = {str(name).strip().lower() for name in portrait_names}
    for key in ("mood", "emotion", "expression", "mood_name", "emotion_tag"):
        candidate = str(values.get(key) or "").strip()
        if candidate:
            if candidate.lower().strip("[]") in names:
                return candidate.lower().strip("[]")
            normalized = normalize_mood_name(candidate.strip("[]"))
            if normalized != "neutral" or candidate.lower().strip("[]") == "neutral":
                return normalized
    known = names | {"neutral", "happy", "sad", "angry", "shy", "surprised", "calm",
                     "curious", "excited", "fear", "tension", "focus", "dark", "epic", "energetic"}
    for tag in re.findall(r"\[([A-Za-z0-9_-]+)\]", str(content or "")):
        if tag.lower() in known:
            return tag.lower()
    return "neutral"


def _quick_persona_attribution(value: Any) -> dict[str, str]:
    raw = dict(value) if isinstance(value, Mapping) else {}
    return {
        key: item
        for key, item in {
            "name": str(raw.get("name") or "").strip(),
            "avatar_path": str(raw.get("avatar_path") or "").strip(),
        }.items()
        if item
    }


def _conversation_message_persona_key(message: Mapping[str, Any]) -> str:
    transaction_id = str(message.get("normal_chat_transaction_id") or "").strip()
    if transaction_id:
        return f"transaction:{transaction_id}"
    return "legacy:{created}:{content}".format(
        created=str(message.get("created_at") or "").strip(),
        content=str(message.get("content") or ""),
    )


def _conversation_persona_attribution_for_message(
    message: Mapping[str, Any],
    metadata: Mapping[str, Any],
    active_persona: Mapping[str, Any],
    fallbacks: dict[str, dict[str, str]],
) -> dict[str, str]:
    attribution = _quick_persona_attribution(
        message.get("quick_persona") or metadata.get("quick_persona")
    )
    if attribution:
        return attribution
    key = _conversation_message_persona_key(message)
    attribution = dict(fallbacks.get(key) or {})
    if attribution:
        return attribution
    attribution = _quick_persona_attribution(active_persona)
    if attribution:
        fallbacks[key] = dict(attribution)
    return attribution


def _normalized_persona_asset_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = _APP_ROOT / candidate
    try:
        return os.path.normcase(str(candidate.resolve()))
    except OSError:
        return os.path.normcase(str(candidate))


def _quick_persona_for_attribution(
    attribution: Mapping[str, Any],
    personas: list[Mapping[str, Any]],
) -> dict[str, Any]:
    avatar_path = _normalized_persona_asset_path(attribution.get("avatar_path"))
    if avatar_path:
        for record in personas:
            if _normalized_persona_asset_path(record.get("avatar_path")) == avatar_path:
                return dict(record)
    name = str(attribution.get("name") or "").strip().casefold()
    if name:
        for record in personas:
            if str(record.get("name") or "").strip().casefold() == name:
                return dict(record)
    return dict(attribution)


def _conversation_visual_reply_assets(
    message: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    *,
    history_index: int = -1,
) -> list[dict[str, Any]]:
    """Resolve the generated images attached to one assistant history turn."""

    sources = (dict(message or {}), dict(metadata or {}))
    raw_paths: list[str] = []
    for source in sources:
        for field_name in visual_reply_history.VISUAL_REPLY_IMAGE_FIELDS:
            value = source.get(field_name)
            if isinstance(value, (list, tuple, set, frozenset)):
                raw_paths.extend(
                    str(item or "").strip()
                    for item in value
                    if str(item or "").strip()
                )
            elif str(value or "").strip():
                raw_paths.append(str(value or "").strip())

    prompt = str(
        message.get("visual_reply_prompt")
        or dict(metadata or {}).get("visual_reply_prompt")
        or ""
    ).strip()
    request_id = str(
        message.get("visual_reply_request_id")
        or dict(metadata or {}).get("visual_reply_request_id")
        or ""
    ).strip()
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path_text in raw_paths:
        url = _local_asset_url(path_text)
        if not url or url in seen:
            continue
        seen.add(url)
        assets.append(
            {
                "url": url,
                "name": Path(path_text).name,
                "prompt": prompt,
                "historyIndex": int(history_index),
                "requestId": request_id,
            }
        )
    return assets


class QmlApplicationBridge(QtCore.QObject):
    personaPortraitEditorChanged = QtCore.Signal()
    conversationPortraitsChanged = QtCore.Signal()
    _personaPortraitSetSaved = QtCore.Signal(int, str, str)
    _quickPersonaMoved = QtCore.Signal(str)
    _quickPersonaRowsSaved = QtCore.Signal(int, str)
    _quickPersonaBioSaved = QtCore.Signal(str)
    """Small typed presentation facade consumed by the QML application shell."""

    workspaceChanged = QtCore.Signal()
    workspaceLayoutChanged = QtCore.Signal()
    mainNavigationChanged = QtCore.Signal()
    mainDockLayoutChanged = QtCore.Signal()
    applicationClosingChanged = QtCore.Signal()
    applicationShutdownReady = QtCore.Signal()
    desktopRestartConfirmationRequested = QtCore.Signal()
    desktopRestartConfirmed = QtCore.Signal()
    configurationChanged = QtCore.Signal()
    providersChanged = QtCore.Signal()
    providerViewChanged = QtCore.Signal()
    addonsChanged = QtCore.Signal()
    addonViewChanged = QtCore.Signal()
    addonSectionRequested = QtCore.Signal(str, str)
    runtimeSectionRequested = QtCore.Signal(str)
    technicalRulesProviderRequested = QtCore.Signal(str)
    orbProviderSettingsRequested = QtCore.Signal()
    addonSettingsChanged = QtCore.Signal()
    liveAddonControlsChanged = QtCore.Signal()
    localRoomControlsRequested = QtCore.Signal()
    runtimeProviderSettingsChanged = QtCore.Signal()
    modelCatalogChanged = QtCore.Signal()
    modelRefreshChanged = QtCore.Signal()
    providerTestChanged = QtCore.Signal()
    runtimeChanged = QtCore.Signal()
    conversationChanged = QtCore.Signal()
    conversationViewportChanged = QtCore.Signal()
    conversationAboutToChange = QtCore.Signal()
    conversationEditChanged = QtCore.Signal()
    conversationAttachmentChanged = QtCore.Signal()
    conversationDraftStateChanged = QtCore.Signal()
    conversationContextChanged = QtCore.Signal()
    liveSessionChanged = QtCore.Signal()
    conversationMessageDeletionAvailabilityChanged = QtCore.Signal()
    conversationActionsChanged = QtCore.Signal()
    _conversationActionReceived = QtCore.Signal(object)
    consoleChanged = QtCore.Signal()
    visualStateChanged = QtCore.Signal()
    musetalkStateChanged = QtCore.Signal()
    spotifySenseStateChanged = QtCore.Signal()
    sessionSetupChanged = QtCore.Signal()
    communicationLoggingChanged = QtCore.Signal()
    speechBackendsChanged = QtCore.Signal()
    runtimeOperationChanged = QtCore.Signal()
    visualReplySetupChanged = QtCore.Signal()
    visualReplyStorageReady = QtCore.Signal(QtCore.QUrl)
    coreSettingsChanged = QtCore.Signal()
    documentMemoryChanged = QtCore.Signal()
    visionProviderTestChanged = QtCore.Signal()
    themeChanged = QtCore.Signal()
    personaChanged = QtCore.Signal()
    identityRelayChanged = QtCore.Signal()
    voiceOptionsChanged = QtCore.Signal()
    quickPersonaChanged = QtCore.Signal()
    quickPersonaRowsBusyChanged = QtCore.Signal()
    quickPersonaReorderChanged = QtCore.Signal()
    personaAvatarGenerationChanged = QtCore.Signal()
    personaAvatarPromptChanged = QtCore.Signal()
    tutorialStateChanged = QtCore.Signal()
    tutorialNarrationFinished = QtCore.Signal(int, int, str)
    operationsChanged = QtCore.Signal()
    speechTimingSettingsChanged = QtCore.Signal()
    onboardingChanged = QtCore.Signal()
    welcomeHubRequested = QtCore.Signal()
    toggleMainWindowRequested = QtCore.Signal()
    orbWorkspaceActionRequested = QtCore.Signal(str, bool)
    orbWatchDraftChanged = QtCore.Signal()
    notificationRaised = QtCore.Signal(str, str, str)
    externalAvatarFocusRequested = QtCore.Signal(str)
    _configurationReceived = QtCore.Signal(object)
    _mcpModelNoticeReceived = QtCore.Signal(object)
    _modelsReceived = QtCore.Signal(str, object, str)
    _providerTestReceived = QtCore.Signal(str, object, str)
    _visionProviderTestReceived = QtCore.Signal(object)
    _runtimeOperationReceived = QtCore.Signal(str, str, bool, str)
    _webSearchActionReceived = QtCore.Signal(str, object, str)
    _personaAvatarPrepared = QtCore.Signal(int, str, bool, str)
    _personaPromptRefined = QtCore.Signal(bool, str)
    _conversationContextReceived = QtCore.Signal(str, bool, str)
    _phoneChatContextLoaded = QtCore.Signal(bool)
    _memoryReportReceived = QtCore.Signal(bool, str)
    _visualAssetSaved = QtCore.Signal(bool, str)
    _visualAssetCopied = QtCore.Signal(object, str)
    _comfyuiDetectionReady = QtCore.Signal(str, str, object)

    _WORKSPACES = (
        {"key": "runtime", "label": "Runtime", "glyph": "⌘"},
        {"key": "addons", "label": "Addons", "glyph": "◆"},
        {"key": "conversation", "label": "Conversation", "glyph": "◌"},
        {"key": "visuals", "label": "Visual Reply", "glyph": "▣"},
        {"key": "musetalk", "label": "Avatar Preview", "glyph": "◉"},
    )
    _CORE_ADDON_WORKSPACES = (
        {
            "id": "core.persona",
            "label": "Persona",
            "iconAsset": "ui_icons/side_tabs/persona.png",
            "description": "Companion identity and prompt library",
        },
        {
            "id": "core.addons",
            "label": "Addons",
            "iconAsset": "ui_icons/side_tabs/addons.png",
            "description": "Installed addons and integrations",
        },
        {
            "id": "core.speech_timing",
            "label": "Speech Timing",
            "iconAsset": "ui_icons/side_tabs/chunking.png",
            "description": "Pipeline and speech timing",
        },
        {
            "id": "core.performance",
            "label": "Performance Check",
            "iconAsset": "ui_icons/side_tabs/dry_run.png",
            "description": "Dry-run and hardware guidance",
        },
        {
            "id": "core.tutorials",
            "label": "Tutorials",
            "iconAsset": "ui_icons/side_tabs/tutorials.png",
            "description": "Interactive application guides",
        },
    )
    _ADDON_ICON_ASSETS = {
        "nc.mcp_core": "ui_icons/side_tabs/mcp_core.png",
        "nc.companion_chess": "ui_icons/side_tabs/companion_chess.png",
        "nc.ai_presence_mode": "ui_icons/side_tabs/ai_presence.png",
        "nc.audio_story_mode": "ui_icons/side_tabs/story_visuals.png",
        "nc.buddy_chat": "ui_icons/side_tabs/budy_chat.png",
        "nc.chat_session_player": "ui_icons/side_tabs/chat_player.png",
        "nc.companion_orb_overlay": "ui_icons/side_tabs/companion_orb.png",
        "nc.corsair_visual_instrument": "ui_icons/side_tabs/key_led.png",
        "nc.discord_voice_bridge": "ui_icons/side_tabs/discord_chatt.png",
        "nc.ditto_preprocess": "ui_icons/side_tabs/ditto_creator.png",
        "nc.hotkeys": "ui_icons/side_tabs/hotkeys.png",
        "nc.identity_artifacts": "ui_icons/side_tabs/artifacts.png",
        "nc.main_chat_remote": "ui_icons/side_tabs/desktop_bridge.png",
        "nc.multi_persona_roleplay": "ui_icons/side_tabs/mp_story_mode.png",
        "nc.musetalk_avatar": "ui_icons/side_tabs/musetalk.png",
        "nc.musetalk_preprocess": "ui_icons/side_tabs/musetalk.png",
        "nc.rag_context": "addons/rag_context/ui/icons/RAG.png",
        "nc.user_identity": "ui_icons/side_tabs/user_identity.svg",
        "nc.voice_studio": "ui_icons/side_tabs/voice_studio.svg",
        "nc.scenic_avatar": "ui_icons/side_tabs/scenic.png",
        "nc.spotify_sense": "ui_icons/side_tabs/spotisense.png",
        "nc.ua_companion_orb_overlay": "ui_icons/side_tabs/companion_orb.png",
        "nc.visual_reply": "ui_icons/side_tabs/visuals.png",
        "nc.visual_story_settings": "ui_icons/side_tabs/story_visuals.png",
        "nc.vseeface_avatar": "ui_icons/side_tabs/vseeface.png",
    }
    _CONTRIBUTION_AREA_ICON_ASSETS = {
        "top_level": "ui_icons/side_tabs/brain.png",
        "host_settings": "ui_icons/side_tabs/host.png",
        "tts_runtime": "ui_icons/side_tabs/chat.png",
        "vision_source": "ui_icons/side_tabs/vision.png",
        "avatar_tools": "ui_icons/side_tabs/vseeface.png",
        "visual_reply_runtime": "ui_icons/side_tabs/visuals.png",
    }
    _ADDON_SECTIONS = {
        # Keep these page names aligned with the established widget UI.  Addons
        # without an internal page selector intentionally expose one Overview
        # page instead of distributing controls across redesign-only tabs.
        "nc.ai_presence_mode": ("Overview",),
        "nc.audio_story_mode": ("Project", "Audio", "Novel", "Story", "Images", "Review", "Play / Cast"),
        "nc.buddy_chat": ("Setup", "Overview", "Buddies", "Voices", "Avatars", "Providers", "Advanced"),
        "nc.chat_session_player": ("Overview",),
        "nc.companion_orb_overlay": ("Overview", "Look", "Behavior", "Eye Tracking", "Reading", "Awareness", "Hotkeys", "Vision & Actions", "Advanced"),
        "nc.corsair_visual_instrument": ("Overview",),
        "nc.discord_voice_bridge": ("General", "Discord", "Capture", "Playback", "Filter", "Persona", "Bots", "Runtime", "Status", "Moderator"),
        "nc.hotkeys": ("Bindings",),
        "nc.identity_artifacts": ("Overview",),
        "nc.main_chat_remote": ("LAN", "Internet"),
        # Status owns the controls that sit above the legacy MPRC page stack
        # and therefore remain visible regardless of the selected legacy page.
        "nc.multi_persona_roleplay": ("Status", "Play", "Guide", "Story Health", "Registry", "Editor", "Voice", "Session", "AR", "Master", "Story Sounds", "Story Images", "Troubleshooting"),
        "nc.musetalk_avatar": ("Overview",),
        "nc.user_identity": ("Profile", "Portrait", "Visual Replies", "Privacy"),
        "nc.scenic_avatar": ("Overview",),
        "nc.spotify_sense": ("Overview", "Connect", "Playback", "Awareness", "Ducking", "Story", "Hidden Sense", "Advanced"),
        "nc.vseeface_avatar": ("Overview", "Body", "Dynamics"),
    }
    _CORE_EDITABLE_KEYS = frozenset(
        {
            "sensory_feedback_source",
            "sensory_feedback_interval_seconds",
            "sensory_pingpong_enabled",
            "sensory_pingpong_history_depth",
            "sensory_allow_hidden_proactive_speech",
            "sensory_allow_hidden_visual_generation",
            "screen_source_capture_screen_index",
            "screen_source_auto_attach_next_user_turn",
            "system_prompt",
            "emotional_instructions",
            "chat_context_window_messages",
            "chat_context_overflow_policy",
            "stored_chat_history_limit",
            "chat_visual_batch_size",
            "chat_message_timestamps_enabled",
            "conversation_speech_highlight_mode",
            "conversation_speech_highlight_style",
            "conversation_visual_reply_display_mode",
            "conversation_visual_reply_auto_follow",
            "conversation_visual_replies_visible",
            "conversation_message_borders_enabled",
            "conversation_response_action_layout",
            "conversation_action_labels_enabled",
            "conversation_response_placement_guides_enabled",
            "spellcheck_enabled",
            "spellcheck_language",
            "limit_response_length",
            "max_response_tokens",
            "allow_proactive_replies",
            "require_first_user_before_proactive",
            "listen_idle_window_seconds",
            "proactive_delay_seconds",
            "visual_reply_story_mode",
            "visual_reply_story_max_images",
            "visual_reply_story_continuity_strength",
            "visual_reply_master_style_prompt",
            "visual_reply_master_prompt_safe",
            "visual_reply_master_prompt_no_speech_bubbles",
            "continuity_memory_enabled",
            "continuity_memory_update_on_save",
            "continuity_memory_auto_summarize",
            "continuity_memory_auto_turns",
            "continuity_memory_inject",
            "continuity_memory_max_chars",
            "long_term_memory_retrieval_enabled",
            "long_term_memory_retrieval_max_items",
            "long_term_memory_recall_text_budget",
            "long_term_memory_recall_image_limit",
            "long_term_memory_image_review_enabled",
            "long_term_memory_image_context_max_output_tokens",
            "long_term_memory_auto_archive_enabled",
            "long_term_memory_archive_batch_turns",
            "long_term_memory_embedding_enabled",
            "long_term_memory_embedding_provider",
            "long_term_memory_embedding_base_url",
            "long_term_memory_embedding_model",
            "long_term_memory_embedding_context_length",
            "long_term_memory_embedding_min_score",
        }
    )

    def __init__(
        self,
        application_facade: Any,
        *,
        session_read_only: bool = False,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._ui_review_notes = UiReviewNotesController(_APP_ROOT, parent=self)
        self._appearance = AppearanceController(
            _APP_ROOT / "runtime" / "qml_appearance.json",
            read_only=session_read_only,
            parent=self,
        )
        self._application = application_facade
        self._resource_monitor = ResourceMonitor(
            getattr(application_facade, 'resources', None), self,
            settings=QtCore.QSettings(str(_APP_ROOT / 'runtime' / 'resource_monitor.ini'),
                                      QtCore.QSettings.Format.IniFormat),
            read_only=session_read_only,
        )
        self._prompt_builder_read_only = bool(session_read_only)
        self._visual_reply_toolbar = VisualReplyToolbarController(
            application_facade.addons,
            self.notificationRaised.emit,
            self.refreshVisualState,
            parent=self,
        )
        self._visual_reply_toolbar.storageReady.connect(self.visualReplyStorageReady.emit)
        self._visual_reply_toolbar.stateReady.connect(self._apply_visual_state)
        self._session_store = NativeSessionStore(
            _APP_ROOT,
            application_facade,
            read_only=session_read_only,
        )
        self._quick_personas = QuickPersonaStore(_APP_ROOT)
        self._quick_personas.ensure_builtin_guide()
        self._quick_persona_fallbacks: dict[str, Any] = {}
        self._identity_relay_state = _identity_relay_state_for_qml(
            None,
            persona_ref="",
            persona_has_explicit_ref=False,
        )
        self._identity_relay_pending_selection: dict[str, Any] = {}
        self._identity_relay_pending_deadline = 0.0
        self._addon_runtime = NativeAddonRuntime(
            application_facade,
            app_root=_APP_ROOT,
            chat_persona_store=self._quick_personas,
            quick_persona_choices=self._remote_quick_persona_choices,
            persona_prompt_store=self._quick_personas,
            persona_rule_catalog=self._remote_persona_rule_catalog,
            apply_persona_prompts=self._remote_apply_persona_prompts,
            quick_persona_identity=lambda: getattr(self, "_remote_prompt_active_id", ""),
            apply_quick_persona=self._remote_apply_quick_persona,
            llm_model_choices=self._remote_llm_model_state,
            voice_choices=self._remote_voice_state,
            apply_voice=self._remote_apply_voice,
            tts_provider_choices=self._remote_tts_provider_state,
            apply_tts_provider=self._remote_apply_tts_provider,
            web_search_status=self._conversation_web_search_status,
            set_web_search_enabled=self.setConversationWebSearchEnabled,
            apply_llm_model=self._remote_apply_llm_model,
            toggle_main_window=self.toggleMainWindowRequested.emit,
            initialize_system=self.initializeSystem,
            terminate_system=self.terminateSystem,
            runtime_state=lambda: {
                "running": self.systemRunning,
                "starting": self.runtimeStarting,
                "cleanup_pending": self.runtimeCleanupPending,
                "theme_preset": self.currentTheme,
            },
            activate_floating_workspace=(
                self.orbWorkspaceActionRequested.emit
            ),
            on_phone_chat_load=self._phoneChatContextLoaded.emit,
            chat_persistence_enabled=not session_read_only,
        )
        restore_startup_session_state(
            self._session_store,
            self._addon_runtime,
            restore_user_identity=lambda: None,
            capture_persona_fallbacks=self._capture_quick_persona_fallbacks,
            restore_active_quick_persona=self._restore_active_quick_persona,
            sync_ui=lambda: None,
        )
        self._audio_controls = AudioControlsBridge(
            application_facade,
            persist=self._session_store.save,
            parent=self,
        )
        self._preset_store = NativePresetStore(_APP_ROOT, application_facade)
        self._dry_run = NativeDryRunController(
            application_facade,
            persist=self._session_store.save,
        )
        self._native_surfaces = NativeSurfaceRegistry(self)
        # Optional addon-local MCP settings controller and native registration.
        self._mcp_core_controller = None
        self._chat_mcp_controller = None
        try:
            from addons.chat_mcp_tools.native_adapter import ChatMcpNativeAdapter
        except ImportError:
            pass
        else:
            self._chat_mcp_controller = ChatMcpNativeAdapter(application_facade, self)
        try:
            from addons.mcp_core.native_adapter import McpCoreNativeAdapter
        except ImportError:
            pass
        else:
            self._mcp_core_controller = McpCoreNativeAdapter(application_facade)
            self._native_surfaces.register(self._mcp_core_controller)
        self._chess_controller = None
        try:
            from addons.companion_chess.native_adapter import ChessNativeAdapter
        except ImportError:
            pass
        else:
            self._chess_controller = ChessNativeAdapter(application_facade)
            self._native_surfaces.register(self._chess_controller)
        # BEGIN optional Ditto addon native surfaces
        try:
            from addons.ditto_avatar.native_adapter import build_ditto_avatar_adapter
            from addons.ditto_preprocess.native_adapter import build_ditto_preprocess_adapter
        except ImportError:
            pass  # The pair can be uninstalled without preventing host startup.
        else:
            self._native_surfaces.register_many((
                build_ditto_avatar_adapter(application_facade, persist=self._session_store.save),
                build_ditto_preprocess_adapter(application_facade, persist=self._session_store.save),
            ))
        # END optional Ditto addon native surfaces
        # Optional LiquidAI addon; importing the UI must not require its install.
        try:
            from addons.liquidai_tts.native_adapter import build_liquidai_adapter
        except ImportError:
            pass
        else:
            self._native_surfaces.register(
                build_liquidai_adapter(application_facade, persist=self._session_store.save)
            )
        self._native_surfaces.register_many(
            (
                HotkeysNativeAdapter(application_facade),
                build_voice_studio_adapter(application_facade),
                build_scenic_pack_creator_adapter(application_facade, persist=self._session_store.save,
                    can_edit=lambda: self.avatarProviderChangeAllowed),
                build_ai_presence_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_audio_story_mode_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_buddy_chat_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_chatterbox_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_chatterbox_multilingual_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_chat_replay_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_elevenlabs_tts_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_gemini_tts_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_identity_artifacts_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_main_chat_remote_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_musetalk_avatar_adapter(
                    application_facade,
                    persist=self._session_store.save,
                    focus_request=self.externalAvatarFocusRequested.emit,
                ),
                build_musetalk_preprocess_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_pockettts_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_pockettts_multilingual_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_rag_context_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_user_identity_adapter(application_facade),
                build_clipboard_source_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_companion_orb_adapter(
                    application_facade, persist=self._session_store.save,
                    configure_provider=self._configure_orb_vision_provider,
                ),
                build_corsair_visual_instrument_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_discord_voice_bridge_adapter(application_facade),
                build_mock_heart_rate_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_multi_persona_roleplay_adapter(application_facade),
                build_screen_source_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_scenic_avatar_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_spotify_sense_adapter(
                    application_facade, persist=self._session_store.save
                ),
                *build_supervisor_adapters(
                    application_facade, persist=self._session_store.save
                ),
                build_vseeface_avatar_adapter(
                    application_facade,
                    persist=self._session_store.save,
                    focus_request=self.externalAvatarFocusRequested.emit,
                ),
                build_visual_reply_core_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_visual_story_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_web_intelligence_adapter(
                    application_facade, persist=self._session_store.save
                ),
                build_webcam_source_adapter(
                    application_facade, persist=self._session_store.save
                ),
            )
        )
        self._native_surfaces.surfaceChanged.connect(
            self._on_native_surface_changed
        )
        self._native_surfaces.actionCompleted.connect(
            self._on_native_action_completed
        )
        creator_adapter = self._native_surfaces.adapter("musetalk_preprocess_tab")
        if creator_adapter is None:
            raise RuntimeError("MuseTalk Avatar Creator native adapter is unavailable.")
        self._musetalk_creator = MuseTalkCreatorModel(creator_adapter, parent=self)
        self._workspace = "runtime"
        self._workspace_layout = QmlWorkspaceLayoutStore(_APP_ROOT)
        self._workspace_layout_state = self._workspace_layout.load()
        self.workspaceLayoutChanged.connect(self.mainNavigationChanged.emit)
        self._addon_rail_layout = AddonRailLayoutStore(_APP_ROOT)
        restored_workspace = str(
            self._workspace_layout_state.get("main_window", {}).get("active")
            or "runtime"
        )
        if self._workspace_host(restored_workspace) == "main":
            self._workspace = restored_workspace
        else:
            self._workspace = next(
                (
                    str(item["key"])
                    for item in self._WORKSPACES
                    if self._workspace_host(str(item["key"])) == "main"
                ),
                "",
            )
        self._application_closing = False
        self._desktop_restart_confirmation_pending = False
        self._desktop_restart_save_choice: bool | None = None
        self._viewed_provider = ""
        # Logical tabs survive restarts; scroll offsets remain session-local.
        self._navigation_read_only = bool(session_read_only)
        self._navigation_selections: dict[str, str] = dict(
            self._workspace_layout_state.get("navigation") or {}
        )
        self._settings_scroll_positions: dict[str, float] = {}
        self._providers: list[dict[str, Any]] = []
        self._addon_workspaces: list[dict[str, Any]] = []
        self._addon_navigation_workspaces: list[dict[str, Any]] = []
        self._hidden_addon_navigation_workspaces: list[dict[str, Any]] = []
        self._addon_registry: list[dict[str, Any]] = []
        self._addon_settings_by_workspace: dict[str, dict[str, Any]] = {}
        self._live_addon_controls: list[dict[str, Any]] = []
        self._runtime_provider_settings: dict[str, Any] = {}
        self._viewed_speech_backends = {"stt": "", "tts": ""}
        self._viewed_avatar_provider = ""
        self._viewed_vision_provider = ""
        self._viewed_visual_reply_provider = ""
        self._selected_addon = self.navigationSelection("addons:selected", "core.persona")
        self._models: list[dict[str, Any]] = []
        self._remote_model_catalogs: dict[str, dict[str, Any]] = {}
        self._model_refresh_in_flight = False
        self._model_refresh_provider = ""
        self._model_refresh_message = ""
        self._provider_test_in_flight = False
        self._provider_test_provider = ""
        self._vision_provider_test: dict[str, Any] = {
            "providerId": "",
            "inFlight": False,
            "status": "idle",
            "message": "",
            "details": {},
        }
        self._speech_input_backends: list[dict[str, Any]] = []
        self._speech_output_backends: list[dict[str, Any]] = []
        self._runtime_operation = ""
        self._runtime_operation_backend = ""
        self._runtime_operation_previous: dict[str, Any] | None = None
        self._conversation_revision = -1
        self._conversation_message_deletion_available: bool | None = None
        self._conversation_actions_state = {}
        self._conversation_action_future = None
        self._conversation_messages: list[dict[str, Any]] = []
        self._conversation_window = ConversationVisualWindow()
        self._conversation_selection_active = False
        self._conversation_persona_fallbacks: dict[str, dict[str, str]] = {}
        self._conversation_context_operation = ""
        self._conversation_edit_mode = False
        self._conversation_edit_revision = -1
        self._conversation_edit_source: list[dict[str, Any]] = []
        self._conversation_edit_messages: list[dict[str, Any]] = []
        self._conversation_edit_deleted: set[int] = set()
        self._conversation_edit_anchor = -1
        self._conversation_display_model = ConversationListModel(self)
        self.conversationChanged.connect(self._sync_conversation_display_model)
        self.conversationEditChanged.connect(self._sync_conversation_display_model)
        self._conversation_view_state: dict[str, Any] = {}
        self._conversation_view_generation = None
        self._conversation_attachment: dict[str, Any] = {}
        self._conversation_draft_state: dict[str, Any] = {
            "composerText": "",
            "copiedPromptText": "",
            "inlineResponseHistoryIndex": -1,
            "inlineResponseText": "",
        }
        self._conversation_deferred_turn: dict[str, Any] | None = None
        self._conversation_inline_response_identity: tuple[str, ...] | None = None
        self._live_session_state: dict[str, Any] = {
            "state": "stopped",
            "stateLabel": "Runtime stopped",
            "ready": False,
            "recording": False,
            "paused": False,
            "playbackActive": False,
            "replayActive": False,
            "audioLevel": 0.0,
            "mood": "neutral",
            **resolve_mood_colors("neutral"),
            "buffer": normalize_pipeline_progress(None),
            "faultMessage": "",
        }
        self._voice_error_until = 0.0
        self._voice_error_message = ""
        self._console_text = ""
        self._console_max_characters = 180_000
        self._visual_state: dict[str, Any] = {}
        self._visual_reply_views: set[str] = set()
        self._conversation_views: set[str] = set()
        self._musetalk_state: dict[str, Any] = {}
        self._musetalk_preview = MuseTalkPreview()
        self._musetalk_preview_views: set[str] = set()
        self._spotify_sense_state: dict[str, Any] = {"available": False}
        self.tutorialNarrationFinished.connect(self._tutorial_narration_finished, QtCore.Qt.QueuedConnection)
        self._tutorial_payload: dict[str, Any] = {}
        self._tutorial_step_index = 0
        self._tutorial_temporary_widget_states: dict[str, bool] = {}
        self._tutorial_speech_enabled = bool(
            self._application.config.get("tutorial_read_aloud_enabled", False)
        )
        self._tutorial_narration = TutorialNarrationController(
            primary_speak=lambda text, config: self._application.addon_speech.speak(
                text,
                runtime_config_override=config,
            )
        )
        self._should_prompt_first_run = self._session_store.first_run() or bool(
            self._application.config.get("welcome_hub_show_on_startup", False)
        )
        self._quick_persona_page = 0
        self._quick_persona_rows = self._quick_personas.visible_rows()
        self._quick_persona_rows_busy = False
        self._quick_persona_reorder_busy = False
        self._persona_avatar_generation: dict[str, Any] = {
            "inFlight": False,
            "requestId": "",
            "slot": -1,
            "mood": "",
            "remaining": [],
            "message": "",
            "preparing": False,
            "transparentBackground": True,
        }
        self._persona_avatar_prompt_state: dict[str, Any] = {
            "inFlight": False,
            "text": "",
            "error": "",
        }
        self._persona_avatar_started_at = 0.0
        self._portrait_editor_state = {"inFlight": False, "error": "", "saved": False}
        self._conversation_portrait_moods: dict[str, str] = {}
        self._portrait_session_generation = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nc-qml-model-catalog")
        self._comfyui_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nc-comfyui-detection")
        self._comfyui_detection_pending: set[tuple[str, str]] = set()
        self._comfyui_generation_cache: dict[tuple[str, str], dict] = {}
        self._runtime_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nc-qml-runtime-command")
        self._persona_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nc-qml-persona-avatar")
        self._config_subscription = None
        self._closing = False
        self._conversation_commands = ConversationCommands(self)
        self._runtime_controller = NativeRuntimeController(
            application_facade, self, creator_startup_handoff=creator_adapter.chat_startup_handoff,
            start_guard=lambda: not self._room_blocks_main_chat(),
        )
        self._runtime_controller.startupRequested.connect(self._musetalk_creator.invalidateDeparture)
        self.runtimeChanged.connect(
            lambda: self._musetalk_creator.setStartupPending(self._runtime_controller.starting)
        )
        self._runtime_controller.runningChanged.connect(self.runtimeChanged)
        self._runtime_controller.finished.connect(self._on_native_runtime_finished)
        self.runtimeChanged.connect(self._musetalk_creator.refresh)
        self.runtimeChanged.connect(
            self._addon_runtime.publish_main_chat_remote_status
        )
        self.liveSessionChanged.connect(
            self._addon_runtime.publish_main_chat_remote_status
        )
        self.conversationChanged.connect(
            self._addon_runtime.publish_main_chat_remote_history
        )
        self._addon_runtime.bind_runtime_controller(self._runtime_controller)

        self._configurationReceived.connect(
            self._on_configuration_received,
            QtCore.Qt.QueuedConnection,
        )
        self._comfyuiDetectionReady.connect(
            self._on_comfyui_detection_ready,
            QtCore.Qt.QueuedConnection,
        )
        self._modelsReceived.connect(
            self._on_models_received,
            QtCore.Qt.QueuedConnection,
        )
        self._providerTestReceived.connect(
            self._on_provider_test_received,
            QtCore.Qt.QueuedConnection,
        )
        self._visionProviderTestReceived.connect(
            self._on_vision_provider_test_received,
            QtCore.Qt.QueuedConnection,
        )
        self._runtimeOperationReceived.connect(
            self._on_runtime_operation_received,
            QtCore.Qt.QueuedConnection,
        )
        self._webSearchActionReceived.connect(
            self._on_conversation_web_search_action_received,
            QtCore.Qt.QueuedConnection,
        )
        self._conversationActionReceived.connect(self._on_conversation_action_received, QtCore.Qt.QueuedConnection)
        self._personaAvatarPrepared.connect(
            self._on_persona_avatar_prepared,
            QtCore.Qt.QueuedConnection,
        )
        self._personaPortraitSetSaved.connect(self._on_portrait_set_saved, QtCore.Qt.QueuedConnection)
        self._quickPersonaMoved.connect(self._on_quick_persona_moved, QtCore.Qt.QueuedConnection)
        self._quickPersonaRowsSaved.connect(self._on_quick_persona_rows_saved, QtCore.Qt.QueuedConnection)
        self._quickPersonaBioSaved.connect(self._on_quick_persona_bio_saved, QtCore.Qt.QueuedConnection)
        self._personaPromptRefined.connect(
            self._on_persona_prompt_refined,
            QtCore.Qt.QueuedConnection,
        )
        self._conversationContextReceived.connect(
            self._on_conversation_context_received,
            QtCore.Qt.QueuedConnection,
        )
        self._phoneChatContextLoaded.connect(
            self._on_phone_chat_context_loaded,
            QtCore.Qt.QueuedConnection,
        )
        self._memoryReportReceived.connect(
            self._on_memory_report_received,
            QtCore.Qt.QueuedConnection,
        )
        self._visualAssetSaved.connect(
            self._on_visual_asset_saved,
            QtCore.Qt.QueuedConnection,
        )
        self._visualAssetCopied.connect(
            self._on_visual_asset_copied,
            QtCore.Qt.QueuedConnection,
        )
        self._config_subscription = self._application.subscriptions.config(
            lambda event: self._configurationReceived.emit(event)
        )
        self._mcpModelNoticeReceived.connect(self._on_mcp_model_notice, QtCore.Qt.QueuedConnection)
        subscribe_notice = getattr(self._application.subscriptions, 'event', None)
        self._mcp_model_notice_subscription = (subscribe_notice('chat.mcp_model_unsupported',
            lambda event: self._mcpModelNoticeReceived.emit(event)) if callable(subscribe_notice) else None)
        self._console_capture = NativeConsoleCapture(self)
        self._console_capture.textReady.connect(
            self._append_console_text,
            QtCore.Qt.QueuedConnection,
        )
        self._console_capture.install()
        self._conversation_timer = QtCore.QTimer(self)
        self._conversation_timer.setInterval(250)
        self._conversation_timer.timeout.connect(self._refresh_conversation_if_visible)
        self._conversation_timer.start()
        self._conversation_refresh_timer = QtCore.QTimer(self)
        self._conversation_refresh_timer.setSingleShot(True)
        self._conversation_refresh_timer.setInterval(0)
        self._conversation_refresh_timer.timeout.connect(self._refresh_conversation_if_visible)
        self._live_session_timer = QtCore.QTimer(self)
        self._live_session_timer.setInterval(100)
        self._live_session_timer.timeout.connect(self._refresh_live_session_if_visible)
        self._live_session_timer.timeout.connect(self._runtime_controller.refresh_readiness)
        self._live_session_timer.start()
        self._document_memory_timer = QtCore.QTimer(self)
        self._document_memory_timer.setInterval(100)
        self._document_memory_timer.timeout.connect(self._refresh_document_memory_status)
        self._document_memory_timer.start()
        self._visual_timer = QtCore.QTimer(self)
        self._visual_timer.setInterval(350)
        self._visual_timer.timeout.connect(self._refresh_visuals_if_visible)
        self._visual_timer.start()
        self._musetalk_preview_timer = QtCore.QTimer(self)
        self._musetalk_preview_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._musetalk_preview_timer.setInterval(42)
        self._musetalk_preview_timer.timeout.connect(self.refreshMusetalkPreview)
        self._musetalk_creator.renderPreviewChanged.connect(self.refreshMusetalkPreview)
        self._spotify_sense_timer = QtCore.QTimer(self)
        self._spotify_sense_timer.setInterval(1000)
        self._spotify_sense_timer.timeout.connect(
            self._refresh_spotify_sense_if_visible
        )
        self._spotify_sense_timer.start()
        self._operations_timer = QtCore.QTimer(self)
        self._operations_timer.setInterval(750)
        self._operations_timer.timeout.connect(self._refresh_operations_if_visible)
        self._operations_timer.start()
        self._persona_avatar_timer = QtCore.QTimer(self)
        self._persona_avatar_timer.setInterval(450)
        self._persona_avatar_timer.timeout.connect(self._poll_persona_avatar_generation)
        self._identity_relay_timer = QtCore.QTimer(self)
        self._identity_relay_timer.setInterval(350)
        self._identity_relay_timer.timeout.connect(
            self._poll_identity_relay_persona_selection
        )
        self._user_identity_avatar_timer = QtCore.QTimer(self)
        self._user_identity_avatar_timer.setInterval(450)
        self._user_identity_avatar_timer.timeout.connect(
            self._poll_user_identity_avatar_generation
        )
        from ui.qml_bridge.memory_workspace import MemoryWorkspaceController

        self._memory_workspace = MemoryWorkspaceController(application_facade, parent=self)
        from ui.qml_bridge.embedding_setup import EmbeddingSetupController
        self._embedding_setup = EmbeddingSetupController(application_facade,
            save_settings=self._save_native_session_or_raise, parent=self)
        self._embedding_setup.settingsSaved.connect(self.coreSettingsChanged.emit)
        self._embedding_setup.settingsSaved.connect(self.configurationChanged.emit)
        self.coreSettingsChanged.connect(self._embedding_setup.refreshSelection)
        self._memory_workspace.notificationRaised.connect(self.notificationRaised.emit)
        from ui.qml_bridge.chat_context_guard import ChatContextGuard
        self._chat_context_guard = ChatContextGuard(application_facade, parent=self)
        self._chat_context_guard.saved.connect(lambda: self._on_named_context_changed('save_context'))
        self._memory_workspace.departure_guard = self._chat_context_guard
        self._memory_workspace.contextSaved.connect(self._chat_context_guard.markSavedReceipt)
        self._chat_guard_binding = application_facade.memory.bind_updates(self._chat_context_guard.memoryUpdated)
        from ui.qml_bridge.room_conversation import RoomConversationSession
        self._room_conversation = RoomConversationSession(
            self._runtime_controller, self._chat_context_guard, self._room_conversation_snapshot,
            self._dispatch_room_conversation_action, self._reset_main_for_room,
            self._show_room_conversation_workspace, self._show_local_room_controls, parent=self)
        self._room_conversation.errorRaised.connect(
            lambda message: self.notificationRaised.emit('error', 'Room request failed', message))
        from ui.qml_bridge.sensory_image_status import SensoryImageStatusController

        self._sensory_image_status = SensoryImageStatusController(application_facade, parent=self)
        self._sensory_image_status.notificationRaised.connect(self.notificationRaised.emit)
        self.coreSettingsChanged.connect(self._sensory_image_status.refresh)
        from ui.qml_bridge.sensory_prompt_settings import SensoryPromptSettingsController

        self._sensory_prompt_settings = SensoryPromptSettingsController(
            application_facade, persist=self._session_store.save, parent=self
        )
        self._sensory_prompt_settings.notificationRaised.connect(self.notificationRaised.emit)
        self._sensory_prompt_settings.saved.connect(self.coreSettingsChanged.emit)
        self.coreSettingsChanged.connect(self._sensory_prompt_settings.refresh)
        self.configurationChanged.connect(self._sensory_prompt_settings.refresh)
        self._memory_workspace.contextChanged.connect(self._on_named_context_changed)
        self.coreSettingsChanged.connect(self._memory_workspace.requestRefresh)
        self.refreshProviderState()
        self.refreshSpeechBackendState()
        self.refreshAddonState()
        self.refreshSpotifySenseState()
        self.refreshConversationState()
        self.refreshLiveSessionState()
        self.refreshVisualState()
        self.refreshIdentityRelayState()
        active_persona = self._quick_personas.active_persona()
        if active_persona is not None:
            present_fields = self._saved_quick_persona_field_names(
                int(active_persona.get("slot", -1))
            )
            self._sync_persona_identity_relay(active_persona, present_fields)

        self._prompt_builder = PersonaPromptBuilderController(
            context=self._prompt_builder_context, providers=self._prompt_builder_providers,
            models=self._prompt_builder_models,
            refine=self._application.prompt_refinement.refine_persona,
            save=self._save_prompt_builder, applied=self._apply_prompt_builder, parent=self,
        )
        self.personaChanged.connect(self._prompt_builder.synchronize)
        self.providersChanged.connect(self._prompt_builder.refreshProviders)
        from ui.qml_bridge.persona_voice import PersonaVoiceController

        self._persona_voice = PersonaVoiceController(
            self._native_surfaces, backend_getter=lambda: self.selectedSpeechOutputBackend,
            parent=self,
        )
        self.configurationChanged.connect(self._persona_voice.refreshState)
        self.coreSettingsChanged.connect(self._persona_voice.refreshState)
        from ui.qml_bridge.avatar_rule_catalog import AvatarRuleCatalog
        self._avatar_rule_catalog = AvatarRuleCatalog(self, _APP_ROOT)
        QtCore.QTimer.singleShot(0, self.refreshComfyUIDetection)
        if not session_read_only:
            # Diagnostic/visual smoke sessions must not activate a user's chat
            # or its memory stores while exercising an isolated UI fixture.
            QtCore.QTimer.singleShot(0, self._restore_saved_conversation)

    @QtCore.Property(QtCore.QObject, constant=True)
    def personaVoice(self) -> QtCore.QObject:
        return self._persona_voice

    @QtCore.Property(QtCore.QObject, constant=True)
    def mcpCoreController(self) -> QtCore.QObject:
        return self._mcp_core_controller

    @QtCore.Property(QtCore.QObject, constant=True)
    def chatMcpController(self) -> QtCore.QObject:
        return self._chat_mcp_controller

    @QtCore.Property(QtCore.QObject, constant=True)
    def chessController(self) -> QtCore.QObject:
        return self._chess_controller

    @QtCore.Slot(str, bool, result=bool)
    def assignPersonaVoice(self, voice_path: str, use_cloned: bool) -> bool:
        """Explicit assignment saves only voice fields to the currently active persona."""
        config = self._application.config
        previous = {key: config.get(key, default) for key, default in
                    (('voice_path', ''), ('tts_use_cloned_voice', True))}
        applied = False
        try:
            active = self._quick_personas.active_persona(strict=True)
            result = config.update_many({
                'voice_path': str(voice_path), 'tts_use_cloned_voice': bool(use_cloned),
            })
            if not result.accepted:
                raise ValueError(str(getattr(result.failure, 'message', 'Could not apply the voice.')))
            applied = True
            if active is not None:
                self._quick_personas.save_persona(int(active['slot']), {
                    'voice_path': str(voice_path), 'use_cloned_voice': bool(use_cloned),
                }, strict=True)
        except (OSError, ValueError) as error:
            if applied:
                config.update_many(previous)
            self.notificationRaised.emit('error', 'Persona voice was not saved', str(error))
            return False
        if active is None:
            self._remember_quick_persona_fallbacks(('voice_path', 'tts_use_cloned_voice'))
            self._save_native_session()
        self.quickPersonaChanged.emit()
        self.personaChanged.emit()
        self.coreSettingsChanged.emit()
        self.configurationChanged.emit()
        return True

    @QtCore.Slot(str, str, str, result=bool)
    def assignPersonaLiquidVoice(self, persona_id: str, voice: str, language: str) -> bool:
        """Save a captured Persona identity's provider selections, never global defaults."""
        config = self._application.config
        keys = ('liquidai_tts_voice', 'liquidai_tts_language')
        previous = {key: config.get(key, '') for key in keys}
        applied = False
        try:
            if self.quickPersonaReorderBusy:
                raise ValueError("Wait for the persona order to finish saving.")
            if self.selectedSpeechOutputBackend != 'liquidai':
                raise ValueError("Select LiquidAI as the speech provider before applying this voice.")
            active = self._quick_personas.active_persona(strict=True)
            captured_id = str(persona_id or '')
            if (active is not None and captured_id != str(active.get('id') or '')) or (
                active is None and captured_id not in ('', '__session__')
            ):
                raise ValueError("The active Persona changed. Select its voice again.")
            selections = self._persona_voice.validate_liquid_selection(voice, language)
            if active is not None:
                overrides = dict(active.get('overrides') or {})
                for key in keys:
                    if selections.get(key):
                        overrides[key] = selections[key]
                    else:
                        overrides.pop(key, None)
                self._quick_personas.save_overrides(captured_id, overrides)
            else:
                # Inherit in the session picker retains the current provider value.
                updates = {key: selections[key] for key in keys if selections.get(key)}
                result = config.update_many(updates)
                if not result.accepted:
                    raise ValueError(str(getattr(result.failure, 'message', 'Could not apply the voice.')))
                applied = True
                if not self._session_store.save():
                    raise OSError("Could not save the session voice.")
        except (OSError, ValueError) as error:
            if applied:
                config.update_many(previous)
            self.notificationRaised.emit('error', 'Persona voice was not saved', str(error))
            return False
        if active is None:
            self._remember_quick_persona_fallbacks(keys)
        self.quickPersonaChanged.emit()
        self.personaChanged.emit()
        self.coreSettingsChanged.emit()
        self.configurationChanged.emit()
        return True

    @QtCore.Property(QtCore.QObject, constant=True)
    def promptBuilder(self) -> QtCore.QObject:
        return self._prompt_builder

    def _prompt_builder_context(self) -> dict[str, Any]:
        record = self._quick_personas.active_persona() or {}
        return {
            "id": str(record.get("id") or "__session__"),
            "builder": record.get("prompt_builder") if record else self._application.config.get("persona_prompt_builder", {}),
            "appliedPrompt": self._application.config.get("system_prompt", ""),
            "appliedType": self._application.config.get("persona_prompt_type", ""),
        }

    def _prompt_builder_providers(self) -> list[dict[str, Any]]:
        config = self._application.config.snapshot().values
        settings_map = _plain(config.get("chat_provider_settings", {})) or {}
        result = []
        for row in self._providers:
            provider_id = str(row.get("id") or "")
            settings = dict(settings_map.get(provider_id) or {})
            active = provider_id == self.activeProviderId
            model = str(config.get("model_name") or "") if active else str(settings.get("model_name") or "")
            if not model:
                model = next((str(field.get("value") or "") for field in row.get("fields", [])
                              if field.get("id") == "model_name"), "")
            if row.get("available") and (settings or active or model):
                result.append({"id": provider_id, "label": row.get("label", provider_id),
                               "model": model, "active": active})
        return result

    def _prompt_builder_models(self, provider_id: str) -> list[dict[str, str]]:
        rows, error = _normalize_model_catalog(self._application.providers.list_models(provider_id, quiet=True))
        if error:
            raise RuntimeError(error)
        return [{"id": str(row.get("id") or row.get("model") or row.get("name") or ""),
                 "label": str(row.get("label") or row.get("id") or row.get("model") or row.get("name") or "")}
                for row in rows]

    def _save_prompt_builder(self, key: str, draft: Mapping[str, Any], apply: bool) -> None:
        """Called by the builder's serial persistence worker, never by QML directly."""
        if self._prompt_builder_read_only:
            raise ValueError("This session is read-only.")
        if key != "__session__":
            self._quick_personas.save_prompt_builder(key, draft, apply=apply)
            return
        updates: dict[str, Any] = {"persona_prompt_builder": normalize_builder(draft)}
        if apply:
            updates.update(system_prompt=str(draft.get("_apply_text") or draft["candidate"]),
                           persona_prompt_type=normalize_type(draft.get("_apply_type", draft["prompt_type"])))
        previous = self._application.config.get("persona_prompt_builder", {})
        result = self._application.config.update("persona_prompt_builder", updates["persona_prompt_builder"])
        if not result.accepted:
            raise ValueError(str(getattr(result.failure, "message", "Could not save prompt settings.")))
        try:
            if not self._session_store.save(config_overrides=updates):
                raise OSError("Could not save the session prompt.")
        except Exception:
            self._application.config.update("persona_prompt_builder", previous)
            raise

    def _apply_prompt_builder(self, key: str, draft: Mapping[str, Any]) -> None:
        if self._prompt_builder_context()["id"] != key:
            return
        result = self._application.config.update_many({
            "system_prompt": str(draft.get("_apply_text") or draft["candidate"]),
            "persona_prompt_type": normalize_type(draft.get("_apply_type", draft["prompt_type"])),
        })
        if not result.accepted:
            raise ValueError(str(getattr(result.failure, "message", "Could not activate the prompt.")))
        if key == "__session__":
            self._remember_quick_persona_fallbacks(("system_prompt", "persona_prompt_type"))
        self.personaChanged.emit()
        self.quickPersonaChanged.emit()
        self.coreSettingsChanged.emit()

    @QtCore.Property(str, constant=True)
    def applicationTitle(self) -> str:
        return "NeuralCompanion"

    @QtCore.Property(str, constant=True)
    def applicationSubtitle(self) -> str:
        return "Runtime Workspace"

    @QtCore.Property(bool, notify=onboardingChanged)
    def shouldPromptFirstRun(self) -> bool:
        return self._should_prompt_first_run

    def _workspace_host(self, workspace_key: str) -> str:
        key = str(workspace_key or "").strip().lower()
        for group_id, group in self._workspace_layout_state.get("groups", {}).items():
            if key in group.get("workspaces", []):
                return str(group_id)
        return "main"

    def _main_workspace_zone(self, workspace_key: str) -> str:
        key = str(workspace_key or "").strip().lower()
        panes = self._workspace_layout_state.get("main_window", {}).get("panes", {})
        for zone in MAIN_DOCK_ZONES:
            if key in panes.get(zone, {}).get("workspaces", []):
                return zone
        return ""

    def _workspace_record(self, workspace: Mapping[str, Any]) -> dict[str, Any]:
        item = dict(workspace)
        host_id = self._workspace_host(str(item.get("key") or ""))
        item["hostId"] = host_id
        item["detached"] = host_id != "main"
        item["dockZone"] = self._main_workspace_zone(str(item.get("key") or ""))
        return item

    def _persist_main_workspace(self, workspace_key: str) -> None:
        if not workspace_key or self._workspace_host(workspace_key) != "main":
            return
        try:
            self._workspace_layout_state = self._workspace_layout.set_main_active(
                workspace_key
            )
        except (OSError, ValueError):
            return

    @QtCore.Property("QVariantList", notify=workspaceLayoutChanged)
    def workspaces(self) -> list[dict[str, Any]]:
        return [self._workspace_record(item) for item in self._WORKSPACES]

    @QtCore.Property("QVariantList", notify=mainNavigationChanged)
    def mainTabControls(self) -> list[dict[str, Any]]:
        hidden = self._workspace_layout_state.get("hidden_main_tabs", [])
        return [dict(self._workspace_record(item), visible=item["key"] not in hidden,
                     shortcutNumber=index + 1) for index, item in enumerate(self._WORKSPACES)]

    @QtCore.Property("QVariantList", notify=mainNavigationChanged)
    def mainNavigationWorkspaces(self) -> list[dict[str, Any]]:
        hidden = self._hidden_workspace_tabs()
        return [dict(item, visible=True) for item in self.mainTabControls if item["key"] not in hidden]

    def _tutorial_workspace(self) -> str:
        """The current guide's destination, without changing saved tab visibility."""
        steps = list((getattr(self, "_tutorial_payload", {}) or {}).get("steps") or [])
        index = getattr(self, "_tutorial_step_index", 0)
        if not 0 <= index < len(steps):
            return ""
        step = steps[index] or {}
        payload = getattr(self, "_tutorial_payload", {}) or {}
        if tutorial_scope.is_scoped(payload):
            step = tutorial_scope.step_route(payload, step)
        return "addons" if step.get("addon") else str(step.get("workspace") or "").strip().lower()

    def _hidden_workspace_tabs(self) -> list[str]:
        destination = self._tutorial_workspace()
        return [key for key in self._workspace_layout_state.get("hidden_main_tabs", [])
                if key != destination]

    def _refresh_tutorial_layout(self) -> None:
        # A hidden destination is borrowed for this step only. No visibility,
        # docking, splitter, lock, or window geometry setting is rewritten.
        self.mainNavigationChanged.emit()
        self.mainDockLayoutChanged.emit()
        self.workspaceLayoutChanged.emit()
        self.workspaceChanged.emit()

    @QtCore.Property(bool, notify=mainNavigationChanged)
    def panelPositionsLocked(self) -> bool:
        return bool(self._workspace_layout_state.get("panel_positions_locked", False))

    @QtCore.Slot(str, bool)
    def setMainTabVisible(self, key: str, visible: bool) -> None:
        try:
            state = self._workspace_layout.set_main_tab_visible(str(key), visible)
        except (OSError, ValueError) as error:
            self.notificationRaised.emit("error", "Tab visibility was not saved", str(error))
            self.mainNavigationChanged.emit()
            return
        self._workspace_layout_state = state
        self.mainNavigationChanged.emit()
        self.mainDockLayoutChanged.emit()
        self.workspaceLayoutChanged.emit()
        self.workspaceChanged.emit()

    @QtCore.Slot(bool)
    def setAllMainTabsVisible(self, visible: bool) -> None:
        try:
            state = self._workspace_layout.set_all_main_tabs_visible(visible)
        except OSError as error:
            self.notificationRaised.emit("error", "Tab visibility was not saved", str(error))
            self.mainNavigationChanged.emit()
            return
        self._workspace_layout_state = state
        self.mainNavigationChanged.emit()
        self.mainDockLayoutChanged.emit()
        self.workspaceLayoutChanged.emit()
        self.workspaceChanged.emit()

    @QtCore.Slot(bool)
    def setPanelPositionsLocked(self, locked: bool) -> None:
        try:
            state = self._workspace_layout.set_panel_positions_locked(locked)
        except OSError as error:
            self.notificationRaised.emit("error", "Panel lock was not saved", str(error))
            self.mainNavigationChanged.emit()
            return
        self._workspace_layout_state = state
        self.mainNavigationChanged.emit()

    @QtCore.Property("QVariantMap", notify=workspaceLayoutChanged)
    def mainWindowLayout(self) -> dict[str, Any]:
        return dict(self._workspace_layout_state.get("main_window") or {})

    @QtCore.Property(QtCore.QObject, constant=True)
    def windowGeometry(self) -> QtCore.QObject:
        if not hasattr(self, '_window_geometry'):
            self._window_geometry = WindowGeometry(self)
        return self._window_geometry

    @QtCore.Property("QVariantMap", notify=mainDockLayoutChanged)
    def mainDockLayout(self) -> dict[str, Any]:
        hidden = self._hidden_workspace_tabs()
        workspace_by_key = {
            str(item["key"]): dict(item)
            for item in self._WORKSPACES
        }
        raw_main = dict(self._workspace_layout_state.get("main_window") or {})
        raw_panes = dict(raw_main.get("panes") or {})
        panes: dict[str, dict[str, Any]] = {}
        pane_count = 0
        for zone in MAIN_DOCK_ZONES:
            raw_pane = dict(raw_panes.get(zone) or {})
            workspace_items = [
                self._workspace_record(workspace_by_key[key])
                for key in raw_pane.get("workspaces", [])
                if key in workspace_by_key and key not in hidden
            ]
            if workspace_items:
                pane_count += 1
            active = str(raw_pane.get("active") or "")
            panes[zone] = {
                "zone": zone,
                # Keep an empty hidden pane's last view mounted for restoration.
                "retainedActive": str(raw_pane.get("active") or ""),
                "active": (
                    active
                    if any(str(item["key"]) == active for item in workspace_items)
                    else (str(workspace_items[0]["key"]) if workspace_items else "")
                ),
                "workspaces": workspace_items,
            }
        return {
            "panes": panes,
            "splits": dict(raw_main.get("splits") or {}),
            "paneCount": pane_count,
        }

    @QtCore.Property("QVariantList", notify=workspaceLayoutChanged)
    def floatingWorkspaceGroups(self) -> list[dict[str, Any]]:
        hidden = self._hidden_workspace_tabs()
        workspace_by_key = {
            str(item["key"]): dict(item)
            for item in self._WORKSPACES
        }
        groups: list[dict[str, Any]] = []
        for group in self._workspace_layout_state.get("groups", {}).values():
            workspace_items = [
                self._workspace_record(workspace_by_key[key])
                for key in group.get("workspaces", [])
                if key in workspace_by_key and key not in hidden
            ]
            active = str(group.get("active") or "")
            groups.append(
                {
                    "id": str(group.get("id") or ""),
                    "active": (active if any(item["key"] == active for item in workspace_items)
                               else (str(workspace_items[0]["key"]) if workspace_items else "")),
                    "geometry": dict(group.get("geometry") or {}),
                    "avatarOnly": bool(group.get("avatar_only", False)),
                    "alwaysOnTop": bool(group.get("always_on_top", False)),
                    "workspaces": workspace_items,
                    "title": " + ".join(str(item["label"]) for item in workspace_items),
                }
            )
        return groups

    @QtCore.Property(bool, notify=applicationClosingChanged)
    def applicationClosing(self) -> bool:
        return self._application_closing

    @QtCore.Property(QtCore.QObject, constant=True)
    def uiReviewNotes(self) -> QtCore.QObject:
        """Presentation-only UI review notes exposed to the native QML shell."""

        return self._ui_review_notes

    @QtCore.Property(QtCore.QObject, constant=True)
    def audioControls(self) -> QtCore.QObject:
        return self._audio_controls

    @QtCore.Property(QtCore.QObject, constant=True)
    def memoryWorkspace(self) -> QtCore.QObject:
        return self._memory_workspace

    @QtCore.Property(QtCore.QObject, constant=True)
    def embeddingSetup(self) -> QtCore.QObject:
        return self._embedding_setup

    @QtCore.Slot()
    def openMemorySearchSetup(self) -> None:
        provider = str(self._application.config.snapshot().values.get('long_term_memory_embedding_provider') or 'lmstudio')
        if provider == 'lmstudio':
            available = {str(row.get('id')) for row in self.providers}
            candidates = (self.activeProviderId, self.viewedProviderId, 'lmstudio_sdk', 'lmstudio')
            provider = next((item for item in candidates
                             if item in {'lmstudio', 'lmstudio_sdk'} and item in available), provider)
        self.viewProvider(provider)
        self.rememberNavigationSelection('runtime:responsibility', 'language')
        self.rememberNavigationSelection('runtime:section', 'runtime')
        self.currentWorkspace = 'runtime'
        # This existing signal opens the language-provider settings surface.
        self.orbProviderSettingsRequested.emit()

    @QtCore.Slot()
    def openConversationMemory(self) -> None:
        self.rememberNavigationSelection('runtime:chat-tab', 'memory')
        self.rememberNavigationSelection('runtime:section', 'chat')
        self.currentWorkspace = 'runtime'
        self.runtimeSectionRequested.emit('chat')

    @QtCore.Property(QtCore.QObject, constant=True)
    def sensoryImageStatus(self) -> QtCore.QObject:
        return self._sensory_image_status

    @QtCore.Property(QtCore.QObject, constant=True)
    def sensoryPromptSettings(self) -> QtCore.QObject:
        return self._sensory_prompt_settings

    @QtCore.Property(QtCore.QObject, constant=True)
    def museTalkCreator(self) -> QtCore.QObject:
        return self._musetalk_creator

    @QtCore.Property("QVariantMap", notify=documentMemoryChanged)
    def documentMemoryWorkspace(self) -> dict[str, Any]:
        """Mount the existing RAG surface independently of Addons selection."""
        adapter = self._native_surfaces.adapter("rag_context_tab")
        surface = adapter.snapshot() if adapter is not None else None
        controls = [] if surface is None else [
            {**control, "id": f"rag_context_tab::{control['id']}"}
            for control in surface.to_qml_controls()
        ]
        return {
            **(adapter.document_snapshot() if adapter is not None else {}),
            "id": "rag_context_tab",
            "label": "Document Memory",
            "description": "Choose local text or PDF files, build a searchable memory, and use matching notes during chat.",
            "sections": list(getattr(surface, "sections", ("Sources", "Retrieval", "Index", "Test search"))),
            "controls": controls,
        }

    @QtCore.Slot()
    def refreshDocumentMemory(self) -> None:
        self._refresh_document_memory_status()
        self.documentMemoryChanged.emit()

    def _refresh_document_memory_status(self):
        if self._closing:
            return
        adapter = self._native_surfaces.adapter("rag_context_tab")
        if adapter is not None:
            try:
                if adapter.refresh_document_status():
                    self.documentMemoryChanged.emit()
            except (RuntimeError, ValueError, TypeError):
                pass  # Addon can be disabled or closing.

    def _document_memory_retrieving(self, now):
        adapter = self._native_surfaces.adapter("rag_context_tab")
        retrieval = adapter.document_snapshot().get("retrieval", {}) if adapter is not None else {}
        return bool(retrieval.get("active") and now - float(retrieval.get("started", now)) >= .15)

    def _document_memory_retrieval_label(self):
        adapter = self._native_surfaces.adapter("rag_context_tab")
        retrieval = adapter.document_snapshot().get("retrieval", {}) if adapter is not None else {}
        consumer = {"normal_chat": "Main Chat", "discord_voice": "Discord Voice", "buddy_chat": "Buddy Chat", "test_search": "Test search"}.get(retrieval.get("consumer"), "Addon")
        package = str(retrieval.get("package_name") or "")
        return "Retrieving document memories…" + (f" {package} ({consumer})" if package else "")

    @QtCore.Slot(str, "QVariantMap")
    def documentMemoryCommand(self, capability, payload):
        adapter = self._native_surfaces.adapter("rag_context_tab")
        snapshot = adapter.document_snapshot() if adapter is not None else {}
        self._trigger_runtime_provider_action("rag_context_tab::rag_context_command", {
            "_expected_package_id": snapshot.get("activePackageId"),
            "_expected_activation_revision": snapshot.get("revision"),
            "capability": capability, **dict(payload or {})})

    @QtCore.Slot(str)
    def createDocumentMemoryPackage(self, name):
        self.documentMemoryCommand("runtime.rag.packages.create", {"name": name})

    @QtCore.Slot(str)
    def selectDocumentMemoryPackage(self, package_id):
        self.documentMemoryCommand("runtime.rag.packages.select", {"package_id": package_id})

    @QtCore.Slot(str, bool)
    def setDocumentMemorySourceEnabled(self, source_id, enabled):
        self.documentMemoryCommand("runtime.rag.sources.enable", {"source_id": source_id, "enabled": enabled})

    @QtCore.Slot("QVariantList")
    def refreshDocumentMemorySources(self, source_ids):
        self.documentMemoryCommand("runtime.rag.sources.refresh", {"source_ids": list(source_ids)})

    @QtCore.Slot()
    def _restore_saved_conversation(self) -> None:
        """Reopen the last named chat through normal async Load, without the engine."""
        if self._closing or self._application.chat.history():
            return
        path = str(self._application.config.snapshot().values.get('active_chat_context_path', '') or '')
        if path:
            workspace = self._memory_workspace
            future = workspace._future
            if workspace.state['busy'] or (future is not None and not future.done()):
                # A restored Memory view can start its initial status refresh
                # before this callback. Recheck chat/path after it finishes.
                QtCore.QTimer.singleShot(100, self._restore_saved_conversation)
                return
            workspace.runAction('load_context', {'path': path})

    @QtCore.Slot(str)
    def _on_named_context_changed(self, action: str) -> None:
        if self._closing:
            return
        if action == "load_context":
            self._conversation_persona_fallbacks.clear()
            self._conversation_window.reset()
            self._conversation_revision = -1
            self.refreshConversationState()
        self.coreSettingsChanged.emit()
        self.configurationChanged.emit()
        self.conversationContextChanged.emit()
        if not self._session_store.save():
            self.notificationRaised.emit("error", "Memory settings were not saved", "The chat context operation completed, but the session settings could not be saved.")

    @QtCore.Property(str, notify=workspaceChanged)
    def currentWorkspace(self) -> str:
        if self._workspace in self._hidden_workspace_tabs():
            panes = self.mainDockLayout["panes"]
            zone = self._main_workspace_zone(self._workspace)
            active = str(panes.get(zone, {}).get("active") or "")
            return active or next((str(pane["active"]) for pane in panes.values()
                                   if pane["active"]), "")
        return self._workspace

    @currentWorkspace.setter
    def currentWorkspace(self, value: str) -> None:
        key = str(value or "").strip().lower()
        if key in self._hidden_workspace_tabs():
            return
        if key not in {item["key"] for item in self._WORKSPACES} or key == self._workspace:
            return
        if self._workspace == "addons" and self._selected_addon == "musetalk_preprocess_tab":
            self._musetalk_creator.requestDeparture()
        self._workspace = key
        self._persist_main_workspace(key)
        if self._workspace_host(key) == "main":
            self.mainDockLayoutChanged.emit()
        self.workspaceChanged.emit()
        if key == "conversation":
            self.refreshConversationState()
            self.refreshLiveSessionState()
            self.refreshSpotifySenseState()
        elif key in {"visuals", "musetalk"}:
            self.refreshVisualState()
        elif key == "addons":
            self.refreshSpotifySenseState()

    @QtCore.Property("QVariantList", notify=providersChanged)
    def providers(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._providers]

    @QtCore.Property(QtCore.QObject, constant=True)
    def conversationCommands(self) -> ConversationCommands:
        return self._conversation_commands

    @QtCore.Property(str, notify=configurationChanged)
    def activeProviderId(self) -> str:
        return chat_providers.normalize_provider_id(
            self._application.config.get("chat_provider", chat_providers.DEFAULT_PROVIDER_ID),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )

    @QtCore.Property(str, notify=providerViewChanged)
    def viewedProviderId(self) -> str:
        return self._viewed_provider or self.activeProviderId

    @QtCore.Property("QVariantMap", notify=providerViewChanged)
    def viewedProvider(self) -> dict[str, Any]:
        provider_id = self.viewedProviderId
        for item in self._providers:
            if item.get("id") == provider_id:
                return dict(item)
        return {
            "id": provider_id,
            "label": chat_providers.provider_label(provider_id),
            "description": "Provider settings are not available yet.",
            "fields": [],
            "generationFields": [],
            "modelName": "",
        }

    @QtCore.Property("QVariantList", notify=modelCatalogChanged)
    def unfilteredModelCatalog(self) -> list[dict[str, Any]]:
        """Capabilities remain available when a filter hides the selected model."""
        return [dict(item) for item in self._models]

    @QtCore.Property("QVariantList", notify=modelCatalogChanged)
    def modelCatalog(self) -> list[dict[str, Any]]:
        return _filter_model_catalog(
            self._models,
            require_vision=self.modelRequiresVision,
            require_tools=self.modelRequiresTools,
        )

    @QtCore.Property("QVariantList", notify=modelCatalogChanged)
    def modelNames(self) -> list[str]:
        return [
            str(item.get("id") or item.get("model") or item.get("name") or "")
            for item in self.modelCatalog
            if str(item.get("id") or item.get("model") or item.get("name") or "")
        ]

    @QtCore.Property(bool, notify=modelCatalogChanged)
    def modelRequiresVision(self) -> bool:
        config = dict(self._application.config.snapshot().values)
        settings_map = _plain(config.get("chat_provider_settings", {})) or {}
        provider_settings = dict(settings_map.get(self.viewedProviderId) or {})
        if "model_requires_vision" in provider_settings:
            return bool(provider_settings.get("model_requires_vision"))
        if self.viewedProviderId == self.activeProviderId:
            return bool(config.get("model_requires_vision", False))
        return False

    @QtCore.Property(bool, notify=modelCatalogChanged)
    def modelToolFilterAvailable(self) -> bool:
        from ui.qml_bridge.model_catalog import model_catalog_entry_tool_support
        return any(model_catalog_entry_tool_support(item) is not None for item in self._models)

    @QtCore.Property(bool, notify=modelCatalogChanged)
    def modelRequiresTools(self) -> bool:
        settings_map = _plain(self._application.config.get("chat_provider_settings", {})) or {}
        return self.modelToolFilterAvailable and bool(
            (settings_map.get(self.viewedProviderId) or {}).get("model_requires_tools", False))

    @QtCore.Property(str, notify=modelCatalogChanged)
    def modelToolFilterMessage(self) -> str:
        if self.modelRequiresTools and self._models and not self.modelNames:
            return ("No models match the active filters. Models reported without tool support are excluded; "
                    "models with unknown support remain visible. Turn off a filter to see more models.")
        return ""

    @QtCore.Property(bool, notify=modelRefreshChanged)
    def modelRefreshInFlight(self) -> bool:
        return self._model_refresh_in_flight

    @QtCore.Property(str, notify=modelRefreshChanged)
    def modelRefreshMessage(self) -> str:
        return self._model_refresh_message

    @QtCore.Property(bool, notify=providerTestChanged)
    def providerTestInFlight(self) -> bool:
        return self._provider_test_in_flight

    @QtCore.Property("QVariantList", notify=speechBackendsChanged)
    def speechInputBackends(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._speech_input_backends]

    @QtCore.Property("QVariantList", notify=speechBackendsChanged)
    def speechOutputBackends(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._speech_output_backends]

    @QtCore.Property(str, notify=configurationChanged)
    def selectedSpeechInputBackend(self) -> str:
        return str(self._application.config.get("stt_backend", "none") or "none").strip().lower()

    @QtCore.Property(str, notify=configurationChanged)
    def selectedSpeechOutputBackend(self) -> str:
        return str(self._application.config.get("tts_backend", "none") or "none").strip().lower()

    @QtCore.Property(str, notify=speechBackendsChanged)
    def viewedSpeechInputBackend(self) -> str:
        return str(
            self._viewed_speech_backends.get("stt")
            or self.selectedSpeechInputBackend
        )

    @QtCore.Property(str, notify=speechBackendsChanged)
    def viewedSpeechOutputBackend(self) -> str:
        return str(
            self._viewed_speech_backends.get("tts")
            or self.selectedSpeechOutputBackend
        )

    @QtCore.Property(str, notify=runtimeOperationChanged)
    def runtimeOperation(self) -> str:
        return self._runtime_operation

    @QtCore.Property(QtCore.QObject, constant=True)
    def resourceMonitor(self):
        return self._resource_monitor

    @QtCore.Property(bool, notify=runtimeChanged)
    def systemRunning(self) -> bool:
        return self._runtime_controller.running

    @QtCore.Property(bool, notify=runtimeChanged)
    def avatarProviderChangeAllowed(self) -> bool:
        return not any(bool(getattr(self, name, False)) for name in (
            "systemRunning", "runtimeStarting", "runtimeInitializing",
            "runtimeStopping", "runtimeCancelling", "runtimeCleanupPending",
        ))

    @QtCore.Property(bool, notify=runtimeChanged)
    def runtimeStarting(self) -> bool:
        return bool(getattr(self._runtime_controller, "starting", False))

    @QtCore.Property(bool, notify=runtimeChanged)
    def runtimeInitializing(self) -> bool:
        return bool(getattr(self._runtime_controller, "initializing", self.runtimeStarting))

    @QtCore.Property(bool, notify=runtimeChanged)
    def runtimeStopping(self) -> bool:
        return bool(getattr(self._runtime_controller, "stopping", False))

    @QtCore.Property(bool, notify=runtimeChanged)
    def runtimeCancelling(self) -> bool:
        return bool(getattr(self._runtime_controller, "cancelling", False))

    @QtCore.Property(bool, notify=runtimeChanged)
    def runtimeCleanupPending(self) -> bool:
        return self._runtime_controller.cleanup_pending

    @QtCore.Property(QtCore.QObject, constant=True)
    def conversationDisplayModel(self) -> QtCore.QObject:
        return self._conversation_display_model

    @QtCore.Slot()
    def _sync_conversation_display_model(self) -> None:
        rows = self.conversationEditMessages if self._conversation_edit_mode else self.conversationMessages
        self._conversation_display_model.update_rows(rows)

    @QtCore.Property("QVariantList", notify=conversationChanged)
    def conversationMessages(self) -> list[dict[str, Any]]:
        return [_plain(item) for item in self._conversation_messages]

    @QtCore.Property(bool, notify=conversationChanged)
    def conversationHasOlderMessages(self) -> bool:
        return self._conversation_window.has_older

    @QtCore.Property(bool, notify=conversationChanged)
    def conversationHasNewerMessages(self) -> bool:
        return self._conversation_window.has_newer

    @QtCore.Property(bool, notify=conversationViewportChanged)
    def conversationFollowingLatest(self) -> bool:
        return self._conversation_window.following_latest

    def _conversation_window_protected(self) -> bool:
        return (self._conversation_edit_mode or self._conversation_selection_active
                or int(self._conversation_draft_state.get("inlineResponseHistoryIndex", -1)) >= 0)

    @QtCore.Slot(bool)
    def setConversationSelectionActive(self, active: bool) -> None:
        was_active = self._conversation_selection_active
        self._conversation_selection_active = bool(active)
        if was_active and not active:
            QmlApplicationBridge._queue_conversation_refresh(self)

    @staticmethod
    def _queue_conversation_refresh(owner: Any) -> None:
        # Release protected rows after the current QML selection/edit signal has
        # unwound. The owned timer is cancelled on close and coalesces releases.
        timer = getattr(owner, "_conversation_refresh_timer", None)
        if timer is not None and not getattr(owner, "_closing", False):
            timer.start()

    @QtCore.Slot(str, str, bool)
    def setConversationViewport(self, first_id: str, last_id: str, following_latest: bool) -> None:
        if self._conversation_window_protected():
            return
        visible_ids = {row["messageId"] for row in self._conversation_messages}
        if first_id not in visible_ids or last_id not in visible_ids:
            return
        self._conversation_window.set_viewport(first_id, last_id, following_latest)
        if self._conversation_window.batch_size == -1:
            # Scrolling show-all mode only changes follow intent, not the rows.
            self.conversationViewportChanged.emit()
            return
        self._conversation_revision = -1
        self.refreshConversationState()

    @QtCore.Slot()
    def jumpToLatestConversationMessages(self) -> None:
        if self._conversation_window_protected():
            return
        self._conversation_window.jump_to_latest()
        self._conversation_revision = -1
        self.refreshConversationState()

    @QtCore.Property(int, notify=conversationChanged)
    def conversationTotalDisplayMessages(self) -> int:
        return self._conversation_window.total

    @QtCore.Slot(result=int)
    def loadPreviousConversationBatch(self) -> int:
        if self._conversation_window_protected() or not self._conversation_window.has_older:
            return 0
        snapshot = self._application.chat.snapshot()
        if snapshot.revision != self._conversation_revision:
            self.refreshConversationState()
            return 0
        old_count = len(self._conversation_messages)
        self._conversation_window.expand()
        self._conversation_revision = -1
        self.refreshConversationState()
        return max(0, len(self._conversation_messages) - old_count)

    @QtCore.Property(int, notify=configurationChanged)
    def conversationFontSize(self) -> int:
        return _normalize_chat_font_size(
            self._application.config.get("chat_font_size", 12)
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationTimestampsEnabled(self) -> bool:
        return bool(
            self._application.config.get("chat_message_timestamps_enabled", False)
        )

    @QtCore.Property(str, notify=configurationChanged)
    def conversationSpeechHighlightMode(self) -> str:
        return _normalize_speech_highlight_mode(
            self._application.config.get("conversation_speech_highlight_mode", "off")
        )

    @QtCore.Property(str, notify=configurationChanged)
    def conversationSpeechHighlightStyle(self) -> str:
        return _normalize_speech_highlight_style(
            self._application.config.get(
                "conversation_speech_highlight_style", "classic"
            )
        )

    @QtCore.Property(str, notify=configurationChanged)
    def conversationVisualReplyDisplayMode(self) -> str:
        return _normalize_visual_reply_display_mode(
            self._application.config.get(
                "conversation_visual_reply_display_mode", "fit"
            )
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationVisualRepliesVisible(self) -> bool:
        return bool(self._application.config.get("conversation_visual_replies_visible", True))

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationVisualReplyAutoFollow(self) -> bool:
        return bool(
            self._application.config.get(
                "conversation_visual_reply_auto_follow", True
            )
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationLiveSessionVisible(self) -> bool:
        return bool(
            self._application.config.get("conversation_live_session_visible", True)
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationConsoleVisible(self) -> bool:
        return bool(
            self._application.config.get("conversation_console_visible", True)
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationConsoleAutoScroll(self) -> bool:
        return bool(
            self._application.config.get("conversation_console_auto_scroll", True)
        )

    @QtCore.Property(int, notify=configurationChanged)
    def conversationConsoleFontSize(self) -> int:
        return _normalize_console_font_size(
            self._application.config.get("conversation_console_font_size", 12)
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationResetButtonVisible(self) -> bool:
        return bool(
            self._application.config.get("conversation_reset_button_visible", True)
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationSaveButtonVisible(self) -> bool:
        return bool(
            self._application.config.get("conversation_save_button_visible", True)
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationSaveAsButtonVisible(self) -> bool:
        return bool(
            self._application.config.get("conversation_save_as_button_visible", True)
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationLoadButtonVisible(self) -> bool:
        return bool(
            self._application.config.get("conversation_load_button_visible", True)
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationMemoryButtonVisible(self) -> bool:
        return bool(
            self._application.config.get("conversation_memory_button_visible", True)
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationWebSearchVisible(self) -> bool:
        return bool(
            self._application.config.get("conversation_web_search_visible", True)
        )

    def _conversation_web_search_status(self) -> dict[str, Any] | None:
        result = self._application.addons.invoke_addon_capability(
            "nc.web_intelligence",
            "runtime.web_intelligence.status",
            {},
        )
        if not result.accepted or not isinstance(result.value, Mapping):
            return None
        return dict(result.value)

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationWebSearchEnabled(self) -> bool:
        status = QmlApplicationBridge._conversation_web_search_status(self)
        if (status is None or not status.get("enabled", True)
                or str(status.get("mode") or "auto") == "off"):
            return False
        backend = dict(status.get("backend") or {})
        return int(backend.get("online_count") or 0) > 0

    @QtCore.Property("QVariantMap", notify=conversationDraftStateChanged)
    def conversationDraftState(self) -> dict[str, Any]:
        return dict(self._conversation_draft_state)

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationMessageBordersEnabled(self) -> bool:
        return bool(
            self._application.config.get("conversation_message_borders_enabled", True)
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationTransparentMessageCardsEnabled(self) -> bool:
        return bool(
            self._application.config.get(
                "conversation_transparent_message_cards_enabled", False
            )
        )

    @QtCore.Property(str, notify=configurationChanged)
    def conversationMessageTextColor(self) -> str:
        return _normalize_conversation_message_text_color(
            self._application.config.get("conversation_message_text_color", "")
        )

    @QtCore.Property(str, notify=configurationChanged)
    def conversationMessageFontFamily(self) -> str:
        selected = _normalize_conversation_message_font_family(
            self._application.config.get("conversation_message_font_family", "")
        )
        if not selected or QtGui.QGuiApplication.instance() is None:
            return selected
        families = {
            family.casefold(): family for family in QtGui.QFontDatabase.families()
        }
        return families.get(selected.casefold(), "")

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationBionicReadingEnabled(self) -> bool:
        return bool(
            self._application.config.get("conversation_bionic_reading_enabled", False)
        )

    @QtCore.Property(float, notify=configurationChanged)
    def conversationResponseWidthRatio(self) -> float:
        return _normalize_conversation_response_width_ratio(
            self._application.config.get("conversation_response_width_ratio", 0.68)
        )

    @QtCore.Property(int, notify=configurationChanged)
    def conversationResponseMinHeight(self) -> int:
        return _normalize_conversation_response_min_height(
            self._application.config.get("conversation_response_min_height", 140)
        )

    @QtCore.Property(float, notify=configurationChanged)
    def conversationUserWidthRatio(self) -> float:
        return _normalize_conversation_user_width_ratio(
            self._application.config.get("conversation_user_width_ratio", 0.0)
        )

    @QtCore.Property(int, notify=configurationChanged)
    def conversationUserMinHeight(self) -> int:
        return _normalize_conversation_user_min_height(
            self._application.config.get("conversation_user_min_height", 96)
        )

    @QtCore.Property("QVariantMap", notify=configurationChanged)
    def conversationResponseActionLayout(self) -> dict[str, list[str]]:
        return normalize_conversation_response_action_layout(
            self._application.config.get("conversation_response_action_layout", {})
        )

    @QtCore.Property("QVariantMap", notify=configurationChanged)
    def conversationUserActionLayout(self) -> dict[str, list[str]]:
        return normalize_conversation_user_action_layout(
            self._application.config.get("conversation_user_action_layout", {})
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationActionLabelsEnabled(self) -> bool:
        return bool(
            self._application.config.get(
                "conversation_action_labels_enabled",
                False,
            )
        )

    @QtCore.Property(bool, notify=configurationChanged)
    def conversationResponsePlacementGuidesEnabled(self) -> bool:
        return bool(
            self._application.config.get(
                "conversation_response_placement_guides_enabled", False
            )
        )

    @QtCore.Property(bool, notify=conversationContextChanged)
    def conversationContextBusy(self) -> bool:
        return bool(self._conversation_context_operation)

    @QtCore.Property(bool, notify=conversationEditChanged)
    def conversationEditMode(self) -> bool:
        return self._conversation_edit_mode

    @QtCore.Property("QVariantList", notify=conversationEditChanged)
    def conversationEditMessages(self) -> list[dict[str, Any]]:
        return [_plain(item) for item in self._conversation_edit_messages]

    @QtCore.Property(int, notify=conversationEditChanged)
    def conversationEditSelectionCount(self) -> int:
        return sum(bool(item.get("selected")) for item in self._conversation_edit_messages)

    @QtCore.Property("QVariantMap", notify=conversationAttachmentChanged)
    def conversationAttachment(self) -> dict[str, Any]:
        return dict(_plain(self._conversation_attachment) or {})

    @QtCore.Property(int, notify=conversationChanged)
    def conversationRevision(self) -> int:
        return self._conversation_revision

    @QtCore.Property("QVariantMap", notify=liveSessionChanged)
    def liveSessionState(self) -> dict[str, Any]:
        return _plain(self._live_session_state)

    @QtCore.Property(str, notify=configurationChanged)
    def conversationVoiceIndicatorStyle(self) -> str:
        return _normalize_voice_indicator_style(
            self._application.config.get(
                "conversation_voice_indicator_style",
                "ribbon",
            )
        )

    @QtCore.Property(str, notify=configurationChanged)
    def conversationCanvasStyle(self) -> str:
        return _normalize_conversation_canvas_style(
            self._application.config.get("conversation_canvas_style", "original")
        )

    @QtCore.Property(str, notify=configurationChanged)
    def conversationBackgroundUrl(self) -> str:
        configured = str(
            self._application.config.get("conversation_background_path", "") or ""
        ).strip()
        if not configured:
            return ""
        try:
            resolved = Path(configured).expanduser().resolve()
        except OSError:
            return ""
        if (
            not resolved.is_file()
            or resolved.suffix.lower() not in _CHAT_IMAGE_EXTENSIONS
        ):
            return ""
        return QtCore.QUrl.fromLocalFile(str(resolved)).toString()

    @QtCore.Property(str, notify=configurationChanged)
    def conversationBackgroundName(self) -> str:
        configured = str(
            self._application.config.get("conversation_background_path", "") or ""
        ).strip()
        return Path(configured).name if configured else ""

    @QtCore.Property(str, notify=consoleChanged)
    def consoleText(self) -> str:
        return self._console_text

    @QtCore.Property("QVariantMap", notify=visualStateChanged)
    def visualReplyState(self) -> dict[str, Any]:
        return dict(self._visual_state)

    @QtCore.Property(bool, notify=configurationChanged)
    def visualReplyToolbarExpanded(self) -> bool:
        return bool(
            self._application.config.get("visual_reply_toolbar_expanded", False)
        )

    @QtCore.Property("QVariantMap", notify=musetalkStateChanged)
    def musetalkState(self) -> dict[str, Any]:
        return dict(self._musetalk_state)

    @QtCore.Property("QVariantMap", notify=spotifySenseStateChanged)
    def spotifySenseState(self) -> dict[str, Any]:
        return dict(self._spotify_sense_state)

    @QtCore.Property("QVariantList", notify=configurationChanged)
    def activeRuntimeStack(self) -> list[dict[str, Any]]:
        config = dict(self._application.config.snapshot().values)
        visual_provider_id = str(
            config.get("visual_reply_provider") or "openai"
        ).strip().lower()
        visual_provider_spec = next(
            (
                item
                for item in VISUAL_REPLY_PROVIDER_SPECS
                if item.provider_id == visual_provider_id
            ),
            VISUAL_REPLY_PROVIDER_SPECS[0],
        )
        return [
            {
                "key": "llm",
                "label": "LLM",
                "value": chat_providers.provider_label(self.activeProviderId),
                "status": "active",
            },
            {
                "key": "stt",
                "label": "Speech-to-text",
                "value": str(config.get("stt_backend") or config.get("stt_mode") or "Disabled"),
                "status": "active" if str(config.get("stt_backend") or "").lower() not in {"", "none", "disabled"} else "disconnected",
            },
            {
                "key": "tts",
                "label": "Text-to-speech",
                "value": str(config.get("tts_backend") or config.get("tts_mode") or "Disabled"),
                "status": "active" if str(config.get("tts_backend") or "").lower() not in {"", "none", "disabled"} else "disconnected",
            },
            {
                "key": "visual",
                "label": "Visual reply",
                "value": visual_provider_spec.label,
                "status": "active",
            },
            {
                "key": "avatar",
                "label": "Avatar",
                "value": str(config.get("avatar_mode") or config.get("avatar_engine") or "None"),
                "status": "active" if str(config.get("avatar_mode") or config.get("avatar_engine") or "none").lower() not in {"", "none", "disabled"} else "disconnected",
            },
        ]

    @QtCore.Property('QVariantMap',notify=communicationLoggingChanged)
    def communicationLogging(self):
        owner=getattr(self._application,'communication_logging',None)
        return owner.snapshot() if owner else dict(state='unavailable',path='',incomplete_reason='Recorder unavailable.')

    @QtCore.Slot(bool)
    def setCommunicationLogging(self,enabled):
        try:
            owner=getattr(self._application,'communication_logging',None)
            if owner is None:
                raise RuntimeError('Communication recorder unavailable.')
            owner.set_enabled(bool(enabled))
        except (RuntimeError,OSError,ValueError) as exc:
            self.notificationRaised.emit('error','Communication logging',str(exc))
        self.communicationLoggingChanged.emit()

    @QtCore.Slot()
    def refreshCommunicationLogging(self):
        self.communicationLoggingChanged.emit()

    @QtCore.Slot(str)
    def openCommunicationLog(self,action):
        try:
            owner=getattr(self._application,'communication_logging',None)
            state=owner.snapshot() if owner else {}
            path=str(state.get('path') or '')
            if not path:
                raise RuntimeError('No communication recording exists yet.')
            if action=='copy':
                QtGui.QGuiApplication.clipboard().setText(path)
                return
            if action=='transcript':
                path=owner.export()
            if action not in {'folder','transcript'}:
                raise ValueError('Unknown communication log action.')
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path)):
                raise RuntimeError('Could not open the communication log.')
        except (RuntimeError,OSError,ValueError) as exc:
            self.notificationRaised.emit('error','Communication logging',str(exc))

    @QtCore.Property("QVariantMap", notify=sessionSetupChanged)
    def sessionSetup(self) -> dict[str, Any]:
        config = dict(self._application.config.snapshot().values)
        return {
            "avatarMode": str(config.get("avatar_mode") or config.get("avatar_engine") or "none"),
            "inputMode": str(config.get("input_mode") or "text_only"),
            "inputRole": str(config.get("input_message_role") or "user"),
            "streamMode": bool(config.get("stream_mode", False)),
            "activePreset": str(config.get("active_preset_name") or ""),
            "performanceGuidance": bool(config.get("performance_guidance_visible", False)),
        }

    @QtCore.Property("QVariantList", notify=sessionSetupChanged)
    def avatarOptions(self) -> list[dict[str, str]]:
        options = []
        for provider in self._application.avatar.provider_catalog():
            options.append(
                {
                    "id": str(provider.id),
                    "label": str(provider.label),
                    "description": str(provider.description),
                }
            )
        return options or [{"id": "none", "label": "None", "description": "No avatar"}]

    @QtCore.Property(str, notify=sessionSetupChanged)
    def viewedAvatarProvider(self) -> str:
        return str(self._viewed_avatar_provider or self.sessionSetup.get("avatarMode") or "none")

    @QtCore.Property("QVariantList", notify=coreSettingsChanged)
    def visionProviderOptions(self) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = [
            {
                "id": "shared_awareness",
                "label": "Shared Awareness Policy",
                "description": "Shared rules and prompt used by all enabled sensory providers.",
            }
        ]
        seen = {"shared_awareness"}
        try:
            providers = list_sensory_providers()
        except Exception:
            providers = []
        for provider in providers:
            provider_id = str(getattr(provider, "id", "") or "").strip().lower()
            if not provider_id or provider_id in seen:
                continue
            options.append(
                {
                    "id": provider_id,
                    "label": str(getattr(provider, "label", "") or provider_id),
                    "description": str(
                        getattr(provider, "description", "")
                        or "Ambient sensory input provider."
                    ),
                }
            )
            seen.add(provider_id)
        return options

    @QtCore.Property(str, notify=coreSettingsChanged)
    def activeVisionProvider(self) -> str:
        return source_tokens_value(
            self._application.config.get("sensory_feedback_source", "off")
        )

    @QtCore.Property("QVariantList", notify=coreSettingsChanged)
    def activeVisionProviders(self) -> list[str]:
        return normalize_source_tokens(
            self._application.config.get("sensory_feedback_source", "off")
        )

    @QtCore.Property("QVariantMap", notify=visionProviderTestChanged)
    def visionProviderTest(self) -> dict[str, Any]:
        return dict(_plain(self._vision_provider_test) or {})

    @QtCore.Property(str, notify=coreSettingsChanged)
    def viewedVisionProvider(self) -> str:
        if self._viewed_vision_provider:
            return str(self._viewed_vision_provider)
        if not bool(self._application.config.get("sensory_pingpong_enabled", False)):
            return "shared_awareness"
        active = self.activeVisionProviders
        return str(active[0] if active else "shared_awareness")

    @QtCore.Property("QVariantList", notify=sessionSetupChanged)
    def presetNames(self) -> list[str]:
        return self._preset_store.names()

    @QtCore.Property("QVariantList", notify=visualReplySetupChanged)
    def visualReplyProviders(self) -> list[dict[str, Any]]:
        return [
            {
                "id": spec.provider_id,
                "label": spec.label,
                "description": (
                    "Local or LAN workflow server"
                    if spec.provider_id == "comfyui"
                    else "Hosted image generation provider"
                ),
                "requiresApiKey": bool(spec.requires_api_key),
            }
            for spec in VISUAL_REPLY_PROVIDER_SPECS
        ]

    @QtCore.Property("QVariantMap", notify=visualReplySetupChanged)
    def visualReplySetup(self) -> dict[str, Any]:
        config = dict(self._application.config.snapshot().values)
        active_provider_id = str(
            config.get("visual_reply_provider") or "openai"
        ).strip().lower()
        active_spec = next(
            (
                item
                for item in VISUAL_REPLY_PROVIDER_SPECS
                if item.provider_id == active_provider_id
            ),
            VISUAL_REPLY_PROVIDER_SPECS[0],
        )
        active_provider_id = active_spec.provider_id
        viewed_provider_id = str(
            self._viewed_visual_reply_provider or active_provider_id
        ).strip().lower()
        spec = next(
            (
                item
                for item in VISUAL_REPLY_PROVIDER_SPECS
                if item.provider_id == viewed_provider_id
            ),
            active_spec,
        )
        provider_id = spec.provider_id
        settings = provider_settings_from_config(config)
        provider_settings = dict(settings.get(provider_id) or {})
        api_key = str(provider_settings.get(spec.api_key_setting_key) or "")
        model = str(
            provider_settings.get(spec.model_setting_key)
            or (config.get("visual_reply_model") if provider_id == active_provider_id else "")
            or spec.default_model
        )
        workflow_folder = ""
        if provider_id == "comfyui":
            workflow_folder = str(provider_settings.get("workflow_folder") or "")
            if not workflow_folder and Path(model).is_absolute():
                workflow_folder = str(Path(model).parent)
        size = str(
            provider_settings.get(spec.size_setting_key)
            or config.get("visual_reply_size")
            or "1024x1024"
        )
        base_url = str(provider_settings.get(spec.base_url_setting_key) or spec.default_base_url)
        if provider_id == "comfyui" and not provider_settings.get(spec.base_url_setting_key):
            base_url = VisualReplyRuntime(
                lambda: {**config, "visual_reply_provider": "comfyui"}
            ).base_url()
        prompting_rules = normalize_comfyui_rules(provider_settings.get("prompting_rules", "auto"))
        detected = cached_comfyui_detection(model, base_url) if provider_id == "comfyui" else None
        active_rules = effective_comfyui_rules(prompting_rules, detected) if detected else "generic"
        image_to_image_default = (
            XAI_DEFAULT_IMAGE_TO_IMAGE_MODEL
            if provider_id == "xai"
            else RUNWARE_DEFAULT_IMAGE_TO_IMAGE_MODEL
        )
        image_to_image_model = str(
            provider_settings.get("image_to_image_model")
            or image_to_image_default
        ).strip() or image_to_image_default
        image_to_image_model_options = list(
            XAI_IMAGE_TO_IMAGE_MODEL_OPTIONS
            if provider_id == "xai"
            else RUNWARE_IMAGE_TO_IMAGE_MODEL_OPTIONS
        )
        if image_to_image_model not in image_to_image_model_options:
            image_to_image_model_options.insert(0, image_to_image_model)
        image_to_image_enabled = provider_settings.get("image_to_image_enabled", False)
        if isinstance(image_to_image_enabled, str):
            image_to_image_enabled = image_to_image_enabled.strip().lower() in {
                "1", "true", "yes", "on", "enabled"
            }
        try:
            image_to_image_strength = max(
                0.0,
                min(1.0, float(provider_settings.get("image_to_image_strength", 0.8))),
            )
        except (TypeError, ValueError):
            image_to_image_strength = 0.8
        return {
            "enabled": bool(config.get("visual_replies_enabled", False)),
            "mode": str(config.get("visual_reply_mode") or "off"),
            "provider": provider_id,
            "providerLabel": spec.label,
            "activeProvider": active_provider_id,
            "activeProviderLabel": active_spec.label,
            "model": model,
            "workflowFolderUrl": QtCore.QUrl.fromLocalFile(workflow_folder).toString() if workflow_folder else "",
            "size": size,
            "sizeOptions": list(size_labels_for_provider(provider_id)),
            "apiKey": "••••••••" if api_key and spec.api_key_setting_key == "api_key" else api_key,
            "baseUrl": base_url,
            "requiresApiKey": bool(spec.requires_api_key),
            "autoShow": bool(config.get("visual_reply_auto_show_dock", True)),
            "storyMode": bool(config.get("visual_reply_story_mode", False)),
            "imageToImageEnabled": bool(image_to_image_enabled),
            "imageToImageModel": image_to_image_model,
            "imageToImageModelOptions": image_to_image_model_options,
            "imageToImageStrength": image_to_image_strength,
            "promptingRules": prompting_rules,
            "promptingRuleIds": list(COMFYUI_RULE_LABELS),
            "promptingRuleLabels": list(COMFYUI_RULE_LABELS.values()),
            "detectedModel": detected.model_name if detected else "",
            "activePromptingRules": COMFYUI_RULE_LABELS.get(active_rules, COMFYUI_RULE_LABELS["generic"]) if detected else "",
            "promptingDetectionStatus": detected.status if detected else "",
        }

    @QtCore.Property("QVariantMap", notify=visualReplySetupChanged)
    def comfyuiGenerationSetup(self) -> dict[str, Any]:
        from addons.visual_reply.comfyui_settings import profile_for

        setup = self.visualReplySetup
        if setup.get("provider") != "comfyui":
            return {}
        path, base_url = str(setup["model"]), str(setup["baseUrl"])
        config = dict(self._application.config.snapshot().values)
        runtime = VisualReplyRuntime(lambda: {**config, "visual_reply_provider": "comfyui"})
        cached = getattr(self, "_comfyui_generation_cache", {}).get((path, base_url), {})
        status = cached.get("status", "Inspecting workflow…")
        try:
            timeout = runtime.comfyui_timeout_seconds()
        except (ValueError, TypeError):
            timeout = 180.0
            status = "Saved timeout is invalid. Enter a valid timeout before generating."
        return {**cached, "profile": profile_for(config, base_url, path),
                "legacySize": "1024x1024" if setup["size"].lower() == "auto" else setup["size"],
                "negativePrompt": runtime.comfyui_negative_prompt(),
                "timeoutSeconds": timeout,
                "cleanupMode": runtime.comfyui_cleanup_mode(),
                "status": status}

    @QtCore.Slot(str, "QVariant")
    def setComfyUIGenerationField(self, field: str, value: Any) -> None:
        from addons.visual_reply.comfyui_settings import update_profile

        setup = self.visualReplySetup
        if setup.get("provider") != "comfyui":
            return
        config = dict(self._application.config.snapshot().values)
        try:
            settings = update_profile(config, str(setup["baseUrl"]), str(setup["model"]), field, value)
            from addons.visual_reply.comfyui_settings import profile_for

            profile = profile_for({**config, "visual_reply_provider_settings": settings}, str(setup["baseUrl"]), str(setup["model"]))
            initial: dict[str, Any] = {}
            if field == "seed_mode" and value == "fixed" and "seed" not in profile:
                initial["seed"] = "0"
            if field == "dimension_mode" and value == "custom":
                metadata = getattr(self, "_comfyui_generation_cache", {}).get((str(setup["model"]), str(setup["baseUrl"])), {})
                if not metadata.get("dimensions_supported"):
                    raise ValueError("Custom dimensions require supported, unlinked width and height inputs.")
                initial = {name: profile.get(name, metadata.get(name)) for name in ("width", "height")}
            for name, initial_value in initial.items():
                settings = update_profile({**config, "visual_reply_provider_settings": settings},
                                          str(setup["baseUrl"]), str(setup["model"]), name, initial_value)
            if field == "sampler_id":
                # A different stage must not inherit another stage's overrides.
                changed = {**config, "visual_reply_provider_settings": settings}
                settings = update_profile(changed, str(setup["baseUrl"]), str(setup["model"]), "reset_sampler", None)
                settings = update_profile({**config, "visual_reply_provider_settings": settings},
                                          str(setup["baseUrl"]), str(setup["model"]), "seed_mode", "legacy")
            result = self._application.config.update("visual_reply_provider_settings", settings)
            if not result.accepted:
                raise ValueError(str(getattr(result.failure, "message", "Could not save generation settings.")))
        except (ValueError, TypeError) as exc:
            self.notificationRaised.emit("error", "Generation setting was not saved", str(exc))
            self.visualReplySetupChanged.emit()
            return
        self._save_visual_reply_session()
        self.visualReplySetupChanged.emit()
        self.configurationChanged.emit()

    @QtCore.Slot()
    def refreshComfyUIDetection(self) -> None:
        """Load the viewed ComfyUI workflow off the UI thread for status and chat rules."""
        if self._application_closing:
            return
        setup = self.visualReplySetup
        if setup.get("provider") != "comfyui":
            return
        path, base_url = str(setup["model"]), str(setup["baseUrl"])
        key = (path, base_url)
        if key in self._comfyui_detection_pending:
            return
        self._comfyui_detection_pending.add(key)

        def worker() -> None:
            from addons.visual_reply.generation import (
                _load_comfyui_workflow_json, _as_comfyui_api_workflow,
                _comfyui_object_info, _find_comfyui_prompt_nodes,
            )
            from addons.visual_reply.comfyui_settings import describe_workflow

            metadata: dict[str, Any] = {}
            try:
                payload = _load_comfyui_workflow_json(path, base_url)
                detected = detect_workflow_model(payload)
                info = _comfyui_object_info(base_url, refresh=True)
                workflow = _as_comfyui_api_workflow(payload, info)
                sampler_id, _, _, latent_id = _find_comfyui_prompt_nodes(workflow)
                metadata = describe_workflow(workflow, info, sampler_id, latent_id)
            except Exception as exc:
                metadata = {"status": "Workflow inspection unavailable. Check server address, workflow path and connection.",
                            "samplers": [], "dimensions_supported": False, "metadata_available": False}
                detected = ComfyUIModelDetection(status="Workflow unavailable; using Generic rules")
                if cached_comfyui_detection(path, base_url).status != detected.status:
                    logging.getLogger(__name__).warning(
                        "ComfyUI model detection fell back to Generic (%s)", type(exc).__name__
                    )
            remember_comfyui_detection(path, base_url, detected)
            if not self._application_closing:
                try:
                    self._comfyuiDetectionReady.emit(path, base_url, metadata)
                except RuntimeError:
                    pass  # The bridge was disposed while the background check finished.

        try:
            self._comfyui_executor.submit(worker)
        except RuntimeError:
            self._comfyui_detection_pending.discard(key)

    @QtCore.Slot(str, str, object)
    def _on_comfyui_detection_ready(self, path: str, base_url: str, metadata: dict) -> None:
        self._comfyui_detection_pending.discard((path, base_url))
        self._comfyui_generation_cache[(path, base_url)] = metadata
        setup = self.visualReplySetup
        if setup.get("provider") == "comfyui" and setup.get("model") == path and setup.get("baseUrl") == base_url:
            self.visualReplySetupChanged.emit()

    @QtCore.Property("QVariantMap", notify=coreSettingsChanged)
    def coreSettings(self) -> dict[str, Any]:
        config = dict(self._application.config.snapshot().values)
        return {
            key: _plain(config.get(key))
            for key in self._CORE_EDITABLE_KEYS
        }

    @QtCore.Property("QVariantMap", notify=coreSettingsChanged)
    def sensoryState(self) -> dict[str, Any]:
        try:
            return dict(_plain(self._application.sensory.snapshot()) or {})
        except Exception:
            return {}

    @QtCore.Property("QVariantList", notify=coreSettingsChanged)
    def screenOptions(self) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = [
            {"label": "Active / default monitor", "value": -1}
        ]
        for index, screen in enumerate(QtGui.QGuiApplication.screens()):
            geometry = screen.geometry()
            name = str(screen.name() or f"Monitor {index + 1}")
            options.append(
                {
                    "label": f"{index}: {name} ({geometry.width()}×{geometry.height()})",
                    "value": index,
                }
            )
        return options

    @QtCore.Property(QtCore.QObject, constant=True)
    def appearance(self) -> AppearanceController:
        return self._appearance

    @QtCore.Property(str, notify=themeChanged)
    def currentTheme(self) -> str:
        return str(self._application.config.get("ui_theme_preset", "midnight") or "midnight").strip().lower()

    @QtCore.Property("QVariantList", constant=True)
    def themeOptions(self) -> list[dict[str, str]]:
        return [
            {
                "id": "dark_gray",
                "label": "Dark Gray",
                "description": "Neutral graphite workspace with restrained contrast.",
                "swatch": "#43474f",
            },
            {
                "id": "forest",
                "label": "Forest",
                "description": "Deep green studio palette with cool mint status accents.",
                "swatch": "#456957",
            },
            {
                "id": "midnight",
                "label": "Midnight",
                "description": "Blue-black high-contrast workspace with cyan focus cues.",
                "swatch": "#31d5f4",
            },
        ]

    @staticmethod
    def _persona_reference_path(record: Mapping[str, Any]) -> Path | None:
        raw_path = str(record.get("avatar_path") or "").strip()
        if not raw_path:
            return None
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = _APP_ROOT / candidate
        try:
            candidate = candidate.resolve()
        except OSError:
            return None
        return candidate if candidate.is_file() else None

    @staticmethod
    def _persona_visual_identity_seed(record: Mapping[str, Any]) -> str:
        if not record:
            return ""
        saved = str(record.get("visual_identity_prompt") or "").strip()
        if saved:
            return saved
        portrait = str(record.get("portrait_prompt") or "").strip()
        if portrait:
            return portrait
        name = str(record.get("name") or "NeuralCompanion persona").strip()
        if normalize_persona_appearance_freedom(record.get("appearance_freedom")) == "flexible":
            return f"A recurring adult character named {name}."
        return (
            f"A consistent recurring character named {name}. Match the saved "
            "reference portrait: preserve the same face, hair, eyes, age, body "
            "traits, signature clothing motifs, color palette, and art style."
        )

    def _persona_fallback_updates(
        self,
        values: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = values
        if config is None:
            config = self._application.config.snapshot().values
        return _extract_quick_persona_fallbacks(config)

    def _capture_quick_persona_fallbacks(self) -> None:
        self._quick_persona_fallbacks = self._persona_fallback_updates()

    def _remember_quick_persona_fallbacks(self, keys: tuple[str, ...]) -> None:
        if not keys:
            return
        current = self._persona_fallback_updates()
        for key in keys:
            if key in current:
                self._quick_persona_fallbacks[key] = current[key]

    def _saved_quick_persona_field_names(
        self,
        slot: int,
    ) -> set[str]:
        try:
            payload = json.loads(
                self._quick_personas.path.read_text(encoding="utf-8")
            )
        except (OSError, TypeError, ValueError):
            return set()
        if not isinstance(payload, Mapping):
            return set()
        personas = payload.get("personas")
        if not isinstance(personas, Mapping):
            return set()
        record = personas.get(str(int(slot)))
        if not isinstance(record, Mapping):
            return set()
        return {str(key) for key in record}

    def _persona_runtime_updates(self, record: Mapping[str, Any]) -> dict[str, Any]:
        self._remote_prompt_active_id = str(record.get('id') or '')
        reference = self._persona_reference_path(record)
        strength = _bounded_strength(record.get("visual_reference_strength"), 0.75)
        return {
            "active_quick_persona_name": str(record.get("name") or ""),
            "active_quick_persona_id": str(record.get("id") or ""),
            "persona_mood_tags": {
                str(tag): str(dict(record.get("mood_descriptions") or {}).get(tag) or "")
                for tag in dict(record.get("mood_images") or {})
            },
            "persona_visual_identity_prompt": self._persona_visual_identity_seed(record),
            "persona_portrait_prompt": str(record.get("portrait_prompt") or ""),
            "persona_visual_reference_path": str(reference or ""),
            "persona_self_image_mode": normalize_persona_self_image_mode(
                record.get("self_image_mode", "hybrid")
            ),
            "persona_appearance_freedom": normalize_persona_appearance_freedom(
                record.get("appearance_freedom")
            ),
            "persona_visual_reference_strength": strength,
            "persona_mood_reference_enabled": bool(
                record.get("mood_reference_enabled", True)
            ),
        }

    def _quick_persona_activation_updates(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build the complete runtime payload for one quick persona."""

        saved_fallbacks = getattr(self, "_quick_persona_fallbacks", {})
        fallback_builder = getattr(self, "_persona_fallback_updates", None)
        fallback_updates = (
            dict(saved_fallbacks)
            if saved_fallbacks
            else (
                fallback_builder()
                if callable(fallback_builder)
                else _extract_quick_persona_fallbacks(
                    self._application.config.snapshot().values
                )
            )
        )
        updates: dict[str, Any] = dict(fallback_updates)
        presence_reader = getattr(self, "_saved_quick_persona_field_names", None)
        present_fields = (
            presence_reader(int(record.get("slot", -1)))
            if callable(presence_reader)
            else {str(key) for key in record}
        )
        if "system_prompt" in present_fields:
            updates["system_prompt"] = str(record.get("system_prompt") or "")
        updates["persona_prompt_type"] = normalize_type(record.get("persona_prompt_type"))
        if "emotional_instructions" in present_fields:
            updates["emotional_instructions"] = str(
                record.get("emotional_instructions") or ""
            )
        if "voice_path" in present_fields:
            updates["voice_path"] = str(record.get("voice_path") or "")
        if "use_cloned_voice" in present_fields:
            updates["tts_use_cloned_voice"] = bool(
                record.get("use_cloned_voice", True)
            )
        updates.update(self._persona_runtime_updates(record))
        visual_policy = normalize_persona_visual_reply_policy(
            record.get("visual_reply_policy", "inherit")
        )
        if "visual_reply_policy" in present_fields and visual_policy != "inherit":
            updates.update(
                {
                    "persona_visual_reply_policy": visual_policy,
                    "visual_reply_mode": "off" if visual_policy == "off" else "auto",
                    "visual_replies_enabled": visual_policy != "off",
                }
            )
        visual_auto_show = record.get("visual_reply_auto_show")
        if "visual_reply_auto_show" in present_fields and isinstance(
            visual_auto_show, bool
        ):
            updates["visual_reply_auto_show_dock"] = visual_auto_show
        return updates

    def _restore_active_quick_persona(self) -> None:
        """Apply the saved active persona before the native runtime can start."""

        active_persona = self._quick_personas.active_persona()
        if active_persona is None:
            return
        self._application.config.update_many(
            self._quick_persona_activation_updates(active_persona)
        )

    def _apply_identity_relay_payload(
        self,
        payload: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        active = self._quick_personas.active_persona() or {}
        slot = int(active.get("slot", -1))
        present_fields = (
            self._saved_quick_persona_field_names(slot) if slot >= 0 else set()
        )
        explicit = "identity_relay_ref" in present_fields
        persona_ref = str(active.get("identity_relay_ref") or "")
        pending = dict(self._identity_relay_pending_selection or {})
        if (
            pending
            and int(pending.get("slot", -2)) == slot
            and str(pending.get("persona_id") or "")
            == str(active.get("id") or "")
        ):
            persona_ref = str(pending.get("artifact_ref") or "")
            explicit = True
        next_state = _identity_relay_state_for_qml(
            payload,
            persona_ref=persona_ref,
            persona_has_explicit_ref=explicit,
        )
        if next_state != self._identity_relay_state:
            self._identity_relay_state = next_state
            self.identityRelayChanged.emit()
        return dict(self._identity_relay_state)

    def _identity_relay_command(
        self,
        capability: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return _invoke_identity_relay_capability(
            self._application.addons,
            capability,
            payload,
        )

    @QtCore.Property("QVariantMap", notify=identityRelayChanged)
    def identityRelayState(self) -> dict[str, Any]:
        return dict(self._identity_relay_state)

    @QtCore.Slot(result="QVariantMap")
    def refreshIdentityRelayState(self) -> dict[str, Any]:
        payload = self._identity_relay_command(
            "runtime.identity_artifacts.snapshot",
        )
        return self._apply_identity_relay_payload(payload)

    def _track_identity_relay_review_operation(
        self,
        payload: Mapping[str, Any],
    ) -> None:
        self._apply_identity_relay_payload(payload)
        if bool(payload.get("connection_pending", False)):
            self._identity_relay_pending_deadline = time.monotonic() + 300.0
            self._identity_relay_timer.start()
            return
        self._complete_identity_relay_persona_selection(payload)

    def _notify_identity_relay_review_rejected(self) -> None:
        self.notificationRaised.emit(
            "error",
            "Identity Relay review was not applied",
            "Check the highlighted review values and try again.",
        )

    @QtCore.Slot("QVariantMap", result=bool)
    def applyIdentityRelayReview(self, result: Mapping[str, Any]) -> bool:
        payload = self._identity_relay_command(
            "runtime.identity_artifacts.apply_connection_review",
            result,
        )
        if payload is None:
            refreshed = self._identity_relay_command(
                "runtime.identity_artifacts.snapshot"
            )
            if refreshed is not None:
                self._apply_identity_relay_payload(refreshed)
            self._notify_identity_relay_review_rejected()
            return False
        self._track_identity_relay_review_operation(payload)
        if str(payload.get("connection_phase") or "") == "review_ready":
            self._notify_identity_relay_review_rejected()
            return False
        return True

    @QtCore.Slot(result=bool)
    def cancelIdentityRelayReview(self) -> bool:
        payload = self._identity_relay_command(
            "runtime.identity_artifacts.cancel_connection_review",
        )
        if payload is None:
            refreshed = self._identity_relay_command(
                "runtime.identity_artifacts.snapshot"
            )
            if refreshed is not None:
                self._apply_identity_relay_payload(refreshed)
            self.notificationRaised.emit(
                "error",
                "Identity Relay review was not cancelled",
                "The Identity Relay addon is unavailable.",
            )
            return False
        self._track_identity_relay_review_operation(payload)
        return str(payload.get("connection_phase") or "") != "review_ready"

    def _sync_persona_identity_relay(
        self,
        record: Mapping[str, Any],
        present_fields: set[str] | None = None,
    ) -> bool:
        fields = (
            set(present_fields)
            if present_fields is not None
            else self._saved_quick_persona_field_names(
                int(record.get("slot", -1))
            )
        )
        if "identity_relay_ref" not in fields:
            self.refreshIdentityRelayState()
            return True
        payload = self._identity_relay_command(
            "runtime.identity_artifacts.activate_persona",
            {"artifact_ref": str(record.get("identity_relay_ref") or "")},
        )
        self._apply_identity_relay_payload(payload)
        return payload is not None

    def _save_persona_identity_relay_ref(
        self,
        slot: int,
        persona_id: str,
        artifact_ref: str,
    ) -> bool:
        current = self._quick_personas.persona(slot)
        if current is None or str(current.get("id") or "") != str(persona_id or ""):
            return False
        self._quick_personas.save_persona(
            slot,
            {"identity_relay_ref": str(artifact_ref or "")},
            strict=True,
        )
        self.quickPersonaChanged.emit()
        self.personaChanged.emit()
        return True

    def _complete_identity_relay_persona_selection(
        self,
        payload: Mapping[str, Any],
    ) -> bool:
        pending = dict(self._identity_relay_pending_selection or {})
        if not pending or bool(payload.get("connection_pending", False)):
            return False
        requested_ref = str(pending.get("artifact_ref") or "")
        connected_ref = str(payload.get("connected_ref") or "")
        saved = connected_ref == requested_ref and self._save_persona_identity_relay_ref(
            int(pending.get("slot", -1)),
            str(pending.get("persona_id") or ""),
            requested_ref,
        )
        self._identity_relay_pending_selection = {}
        self._identity_relay_pending_deadline = 0.0
        self._identity_relay_timer.stop()
        self._apply_identity_relay_payload(payload)
        if saved:
            self.notificationRaised.emit(
                "success",
                "Persona Identity Relay updated",
                "Disconnected" if not requested_ref else "Imported identity connected",
            )
        return saved

    @QtCore.Slot()
    def _poll_identity_relay_persona_selection(self) -> None:
        if not self._identity_relay_pending_selection:
            self._identity_relay_timer.stop()
            return
        if time.monotonic() >= self._identity_relay_pending_deadline:
            self._identity_relay_pending_selection = {}
            self._identity_relay_timer.stop()
            self.refreshIdentityRelayState()
            return
        payload = self._identity_relay_command(
            "runtime.identity_artifacts.snapshot",
        )
        if payload is None:
            return
        self._apply_identity_relay_payload(payload)
        self._complete_identity_relay_persona_selection(payload)

    @QtCore.Slot(str, result=bool)
    def setPersonaIdentityRelayRef(self, artifact_ref: str) -> bool:
        active = self._quick_personas.active_persona()
        if active is None:
            self.notificationRaised.emit(
                "warning",
                "Save the persona first",
                "Identity Relay associations belong to a saved quick persona.",
            )
            return False
        requested_ref = str(artifact_ref or "").strip()
        known_refs = {
            str(item.get("value") or "")
            for item in list(self._identity_relay_state.get("options") or [])
        }
        if requested_ref not in known_refs:
            self.notificationRaised.emit(
                "error",
                "Identity Relay was not changed",
                "Choose an imported identity from the list.",
            )
            return False
        pending = {
            "slot": int(active.get("slot", -1)),
            "persona_id": str(active.get("id") or ""),
            "artifact_ref": requested_ref,
        }
        self._identity_relay_pending_selection = pending
        payload = self._identity_relay_command(
            "runtime.identity_artifacts.request_connection",
            {"artifact_ref": requested_ref},
        )
        if payload is None:
            self._identity_relay_pending_selection = {}
            self.refreshIdentityRelayState()
            self.notificationRaised.emit(
                "error",
                "Identity Relay was not changed",
                "The Identity Relay addon is unavailable.",
            )
            return False
        self._apply_identity_relay_payload(payload)
        if bool(payload.get("connection_pending", False)):
            self._identity_relay_pending_deadline = time.monotonic() + 300.0
            self._identity_relay_timer.start()
            return True
        return self._complete_identity_relay_persona_selection(payload)

    @QtCore.Slot(bool, result=bool)
    def setIdentityRelayEnabled(self, enabled: bool) -> bool:
        payload = self._identity_relay_command(
            "runtime.identity_artifacts.set_enabled",
            {"enabled": bool(enabled)},
        )
        if payload is None:
            self.refreshIdentityRelayState()
            self.notificationRaised.emit(
                "error",
                "Identity Relay was not changed",
                "Connect an available imported identity first.",
            )
            return False
        self._apply_identity_relay_payload(payload)
        return True

    @QtCore.Property("QVariantMap", notify=personaChanged)
    def personaState(self) -> dict[str, Any]:
        config = dict(self._application.config.snapshot().values)
        voice_path = str(config.get("voice_path") or "")
        active_persona = self._quick_personas.active_persona() or {}
        backend = str(config.get("tts_backend") or "none").strip().lower()
        liquid_settings = dict(config)
        if backend == "liquidai":
            for key in ("liquidai_tts_voice", "liquidai_tts_language"):
                value = (active_persona.get("overrides") or {}).get(key)
                if value:
                    liquid_settings[key] = value
        visual_reply_policy = resolve_persona_visual_reply_policy(config)
        return {
            "systemPrompt": str(config.get("system_prompt") or ""),
            "emotionalInstructions": str(config.get("emotional_instructions") or ""),
            "ttsBackend": backend,
            "liquidaiVoice": str(liquid_settings.get("liquidai_tts_voice") or ""),
            "liquidaiLanguage": str(liquid_settings.get("liquidai_tts_language") or ""),
            "voicePath": voice_path,
            "voiceName": Path(voice_path).name if voice_path else "",
            "useClonedVoice": bool(config.get("tts_use_cloned_voice", True)),
            "activeQuickPersonaName": str(active_persona.get("name") or ""),
            "visualIdentityPrompt": self._persona_visual_identity_seed(active_persona),
            "portraitPrompt": str(active_persona.get("portrait_prompt") or ""),
            "selfImageMode": normalize_persona_self_image_mode(
                active_persona.get("self_image_mode", "hybrid")
            ),
            "appearanceFreedom": normalize_persona_appearance_freedom(
                active_persona.get("appearance_freedom")
            ),
            "visualReferenceStrength": _bounded_strength(
                active_persona.get("visual_reference_strength"), 0.75
            ),
            "moodReferenceEnabled": bool(
                active_persona.get("mood_reference_enabled", True)
            ),
            "portraitTransparencyEnabled": bool(
                active_persona.get("portrait_transparency_enabled", True)
            ),
            "visualReferenceReady": bool(
                self._persona_reference_path(active_persona)
            ),
            "visualReplyPolicy": visual_reply_policy,
            "visualReplyEnabled": bool(
                config.get("visual_replies_enabled", True)
                and str(config.get("visual_reply_mode", "off") or "off").strip().lower()
                != "off"
            ),
            "visualReplyAutoShow": bool(
                config.get("visual_reply_auto_show_dock", True)
            ),
        }

    def _quick_persona_record_for_qml(self, record: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(record or {})
        payload["slotLabel"] = (
            f"Slot {int(payload.get('slot', 0)) + 1} - "
            f"{str(payload.get('name') or 'Empty slot')}"
        )
        avatar_path = str(payload.get("avatar_path") or "").strip()
        payload["avatarUrl"] = _local_asset_url(avatar_path)
        mood_urls = {}
        for mood, path in dict(payload.get("mood_images") or {}).items():
            url = _local_asset_url(str(path or ""))
            if url:
                mood_urls[str(mood)] = url
        payload["moodAvatarUrls"] = mood_urls
        return _plain(payload)

    @QtCore.Property("QVariantList", notify=quickPersonaChanged)
    def quickPersonaSlots(self) -> list[dict[str, Any]]:
        return [
            self._quick_persona_record_for_qml(item)
            for item in self._quick_personas.page(self._quick_persona_page)
        ]

    @QtCore.Property(int, notify=quickPersonaChanged)
    def quickPersonaRows(self) -> int:
        return self._quick_persona_rows

    @QtCore.Property(bool, notify=quickPersonaRowsBusyChanged)
    def quickPersonaRowsBusy(self) -> bool:
        return self._quick_persona_rows_busy

    @QtCore.Property(int, notify=quickPersonaChanged)
    def quickPersonaPageSize(self) -> int:
        return QUICK_PERSONA_PAGE_SIZE * self._quick_persona_rows

    @QtCore.Property("QVariantList", notify=quickPersonaChanged)
    def quickPersonaChoices(self) -> list[dict[str, Any]]:
        """Return every saved quick persona for compact runtime selectors."""

        payload = self._quick_personas.load()
        active_slot = int(payload.get("active_slot", -1))
        choices = []
        for raw_slot, raw_record in sorted(
            dict(payload.get("personas") or {}).items(),
            key=lambda item: int(item[0]),
        ):
            record = {
                **dict(raw_record or {}),
                "slot": int(raw_slot),
                "empty": False,
                "active": int(raw_slot) == active_slot,
            }
            choices.append(self._quick_persona_record_for_qml(record))
        return choices

    @QtCore.Property(int, notify=quickPersonaChanged)
    def quickPersonaPage(self) -> int:
        return self._quick_persona_page

    @QtCore.Property(int, notify=quickPersonaChanged)
    def quickPersonaPageCount(self) -> int:
        return self._quick_personas.page_count()

    @QtCore.Property("QVariantMap", notify=quickPersonaChanged)
    def activeQuickPersona(self) -> dict[str, Any]:
        persona = self._quick_personas.active_persona()
        return self._quick_persona_record_for_qml(persona or {})

    @QtCore.Property("QVariantMap", notify=configurationChanged)
    def personaOverrideDefaults(self) -> dict[str, Any]:
        config = self._application.config.snapshot().values
        return {
            "provider": str(config.get("chat_provider") or ""),
            "model": str(config.get("model_name") or ""),
            "contextMessages": int(config.get("chat_context_window_messages", 20)),
        }

    @QtCore.Slot(result="QVariantMap")
    def personaOverrideCatalog(self) -> dict[str, Any]:
        # Reuse the existing asynchronous configured-connection catalog. This
        # only reads models and never changes the globally selected provider.
        return self._remote_llm_model_state()

    @QtCore.Slot(str, result="QVariantMap")
    def personaTechnicalRulesCatalog(self, persona_id: str) -> dict[str, Any]:
        from ui.qml_bridge.provider_prompt_rules import catalog
        return catalog(self, persona_id)

    @QtCore.Slot(str, "QVariantMap", result="QVariantMap")
    def savePersonaTechnicalRules(self, persona_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        from ui.qml_bridge.provider_prompt_rules import save_persona
        return save_persona(self, persona_id, draft)

    @QtCore.Slot(str, str, str, result="QVariantMap")
    def saveProviderTechnicalRules(self, kind: str, provider: str, text: str) -> dict[str, Any]:
        from ui.qml_bridge.provider_prompt_rules import save_default
        return save_default(self, kind, provider, text)

    @QtCore.Slot(str, str)
    def openTechnicalRulesProvider(self, kind: str, provider: str) -> None:
        if kind not in ('avatar', 'tts'):
            return
        if kind == 'avatar':
            self.viewAvatarProvider(provider)
        elif kind == 'tts':
            self.viewSpeechBackend('tts', provider)
        responsibility = 'avatar' if kind == 'avatar' else 'voice'
        self.rememberNavigationSelection('runtime:section', 'runtime')
        self.rememberNavigationSelection('runtime:responsibility', responsibility)
        self.activateMainWorkspace('runtime')
        self.technicalRulesProviderRequested.emit(responsibility)

    @QtCore.Slot(str, result="QVariantMap")
    def personaOverrideRecord(self, persona_id: str) -> dict[str, Any]:
        """Read a saved identity without activating it or touching conversation defaults."""
        record = next((row for row in self._quick_personas.load()["personas"].values()
                       if str(row.get("id") or "") == str(persona_id)), None)
        return self._quick_persona_record_for_qml(record) if record is not None else {}

    @QtCore.Slot(str, "QVariantMap", result="QVariantMap")
    def savePersonaOverrides(self, persona_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        if self.quickPersonaReorderBusy:
            return {"accepted": False, "message": "Wait for the persona order to finish saving."}
        try:
            overrides = normalize_persona_overrides(draft)
            if overrides["llm_enabled"]:
                catalog = self._remote_llm_model_state()
                provider = next((row for row in catalog["providers"]
                                 if row["id"] == overrides["llm_provider"] and row["available"]), None)
                if provider is None:
                    raise ValueError("Choose an available configured language model connection.")
                if provider.get("loading"):
                    raise ValueError("Wait for the model list to finish loading, then save again.")
                if provider.get("message"):
                    raise ValueError(str(provider["message"]))
                if not overrides["llm_model"] or not any(
                    str(row.get("id") or row.get("model") or row.get("name") or "") == overrides["llm_model"]
                    for row in provider.get("models", [])
                ):
                    raise ValueError("Choose a model available on the selected connection.")
            saved = self.personaOverrideRecord(str(persona_id))
            previous = saved.get("overrides") or {}
            # Preserve fields owned by the Voice and technical-rule editors.
            for key in ('technical_rules', 'liquidai_tts_voice', 'liquidai_tts_language'):
                if key in previous:
                    overrides[key] = previous[key]
                else:
                    overrides.pop(key, None)
            package_id = str(overrides.get("document_package_id") or "")
            if package_id:
                package = next((row for row in self.documentMemoryWorkspace.get("packages", [])
                                if str(row.get("id") or "") == package_id), None)
                if package is None and package_id != str(previous.get("document_package_id") or ""):
                    raise ValueError("Choose an existing knowledge package or use the configured default.")
                if package is not None:
                    overrides["document_package_name"] = str(package.get("name") or package_id)
            else:
                overrides["document_package_name"] = ""
            self._quick_personas.save_overrides(str(persona_id), overrides)
        except (OSError, ValueError) as error:
            return {"accepted": False, "message": str(error)}
        self.quickPersonaChanged.emit()
        return {"accepted": True, "message": "Persona overrides saved."}

    def _remote_quick_persona_choices(self) -> list[dict[str, Any]]:
        return [dict(item or {}) for item in self.quickPersonaChoices]

    def _remote_persona_rule_catalog(self, record: Mapping[str, Any]) -> dict[str, Any]:
        from ui.qml_bridge.provider_prompt_rules import phone_catalog
        return phone_catalog(self, record)

    def _remote_apply_persona_prompts(self, record: Mapping[str, Any]) -> None:
        # Called on the UI thread only after the worker has persisted the edit.
        if record.get('active') and record.get('id') == getattr(self, '_remote_prompt_active_id', ''):
            values = {
                'system_prompt': record['system_prompt'],
                'emotional_instructions': record['technical_prompt'],
            }
            # Scoped rules are read from the persona store by request capture;
            # never copy them into global runtime configuration.
            self._application.config.update_many(values)
            self.personaChanged.emit()
            self.configurationChanged.emit()
        self.quickPersonaChanged.emit()

    def _remote_apply_quick_persona(self, slot: int) -> dict[str, Any]:
        normalized_slot = int(slot)
        result = self._activate_quick_persona(normalized_slot)
        active = self._quick_personas.active_persona() or {}
        response = dict(result)
        response["active_slot"] = int(active.get("slot", -1))
        return response

    def _remote_llm_model_state(self) -> dict[str, Any]:
        """Read configured choices on the UI thread; enumerate models on a worker."""
        config = dict(self._application.config.snapshot().values)
        settings_map = _plain(config.get("chat_provider_settings", {})) or {}
        active_provider = self.activeProviderId
        active_model = str(config.get("model_name") or "")
        providers: list[dict[str, Any]] = []
        for provider in self._providers:
            provider_id = str(provider.get("id") or "")
            settings = dict(settings_map.get(provider_id) or {})
            selected = active_model if provider_id == active_provider else str(settings.get("model_name") or "")
            if provider_id != active_provider and not settings and not selected:
                continue
            available = bool(provider.get("available", False)) and not self._closing
            cache = self._remote_model_catalogs.get(provider_id, {})
            future = cache.get("future")
            if available and (future is None or (future.done() and time.monotonic() - cache.get("requested_at", 0.0) >= 60.0)):
                future = self._executor.submit(self._application.providers.list_models, provider_id, quiet=True)
                cache = {"future": future, "requested_at": time.monotonic()}
                self._remote_model_catalogs[provider_id] = cache
            loading = bool(available and future is not None and not future.done())
            models: list[dict[str, Any]] = []
            message = "" if available else "Provider is unavailable on the desktop."
            if available and future is not None and future.done():
                try:
                    models, catalog_error = _normalize_model_catalog(future.result())
                    if catalog_error or not models:
                        message = "Could not load models. Check the provider on the desktop."
                except Exception:
                    message = "Could not load models. Check the provider on the desktop."
            require_vision = bool(settings.get("model_requires_vision", config.get("model_requires_vision", False) if provider_id == active_provider else False))
            models = _filter_model_catalog(models, require_vision=require_vision,
                require_tools=bool(settings.get("model_requires_tools", False)))
            if selected and not any(str(item.get("id") or item.get("model") or item.get("name") or "") == selected for item in models):
                models.insert(0, {"id": selected})
            providers.append({
                "id": provider_id, "label": str(provider.get("label") or provider_id),
                "available": available, "loading": loading, "message": message,
                "models": models,
            })
        return {
            "available": any(item["available"] for item in providers),
            "loading": any(item["loading"] for item in providers),
            "selected_provider_id": active_provider, "selected_model_id": active_model,
            "providers": providers,
        }

    def _remote_apply_llm_model(self, provider_id: str, model_id: str) -> dict[str, Any]:
        """Validate against the catalog and use the desktop's selection commands."""
        state = self._remote_llm_model_state()
        provider = next((item for item in state["providers"] if item["id"] == provider_id and item["available"]), None)
        models = list(provider.get("models") or []) if provider else []
        if not any(str(item.get("id") or item.get("model") or item.get("name") or "") == model_id for item in models):
            return {"accepted": False, "message": "Model is no longer available. Refresh the list."}
        previous_provider, previous_models = self._viewed_provider, self._models
        try:
            self._viewed_provider, self._models = provider_id, models
            if provider_id != self.activeProviderId and not self.activateProvider(provider_id):
                return {"accepted": False, "message": "Provider selection was rejected by the desktop."}
            if not self.selectModel(model_id):
                return {"accepted": False, "message": "Model selection was rejected by the desktop."}
            return {"accepted": True, "message": "Language model selected."}
        finally:
            self._viewed_provider, self._models = previous_provider, previous_models
            self.providerViewChanged.emit()
            self.modelCatalogChanged.emit()

    @QtCore.Property(str, notify=quickPersonaChanged)
    def conversationPersonaAvatarMode(self) -> str:
        return self._quick_personas.avatar_mode()

    @QtCore.Property(int, notify=quickPersonaChanged)
    def conversationPersonaAvatarSize(self) -> int:
        return self._quick_personas.avatar_size()

    @QtCore.Property("QVariantMap", notify=personaAvatarGenerationChanged)
    def personaAvatarGenerationState(self) -> dict[str, Any]:
        return _plain(self._persona_avatar_generation)

    @QtCore.Property("QVariantMap", notify=personaAvatarPromptChanged)
    def personaAvatarPromptState(self) -> dict[str, Any]:
        return _plain(self._persona_avatar_prompt_state)

    @QtCore.Property("QVariantList", notify=personaChanged)
    def promptLibrary(self) -> list[dict[str, Any]]:
        return [
            {
                **dict(record),
                "quick": is_prompt_quick(str(record.get("id") or "")),
            }
            for record in all_prompt_records()
        ]

    @QtCore.Property("QVariantList", notify=voiceOptionsChanged)
    def voiceOptions(self) -> list[dict[str, str]]:
        return _voice_reference_options(
            _APP_ROOT,
            self._application.config.get("voice_path", ""),
        )

    @QtCore.Property("QVariantList", notify=tutorialStateChanged)
    def tutorialCatalog(self) -> list[dict[str, Any]]:
        return [_plain(item) for item in tutorial_catalog.list_tutorials()]

    @QtCore.Slot("QVariantMap", result="QVariantList")
    def tutorialsForContext(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        return tutorial_scope.guides_for_route(self.tutorialCatalog, context)

    @QtCore.Property("QVariantMap", notify=tutorialStateChanged)
    def tutorialBrowserContext(self) -> dict[str, str]:
        return dict(getattr(self, "_tutorial_browser_context", {}))

    @QtCore.Property("QVariantList", notify=tutorialStateChanged)
    def tutorialBrowserCatalog(self) -> list[dict[str, Any]]:
        return tutorial_scope.guides_for_route(self.tutorialCatalog, self.tutorialBrowserContext)

    @QtCore.Slot("QVariantMap")
    def openTutorialBrowser(self, context: dict[str, Any]) -> None:
        self._tutorial_browser_context = tutorial_scope.normalize_route(context)
        self.openAddonWorkspaceSection("core.tutorials", "Overview")
        self.tutorialStateChanged.emit()

    @QtCore.Slot()
    def clearTutorialBrowserContext(self) -> None:
        self._tutorial_browser_context = {}
        self.tutorialStateChanged.emit()

    @QtCore.Slot("QVariantMap", int)
    def reportTutorialContext(self, context: dict[str, Any], token: int) -> None:
        navigation = getattr(self, "_tutorial_scope_navigation", None)
        if navigation is not None and navigation.observe(context, token):
            self.tutorialStateChanged.emit()

    @QtCore.Slot()
    def resumeTutorial(self) -> None:
        if not tutorial_scope.is_scoped(getattr(self, "_tutorial_payload", {})):
            return
        self._tutorial_view_token = getattr(self, "_tutorial_view_token", 0) + 1
        self._tutorial_returning = True
        self._activate_tutorial_step()
        self.tutorialStateChanged.emit()

    @QtCore.Property("QVariantMap", notify=tutorialStateChanged)
    def tutorialState(self) -> dict[str, Any]:
        payload = dict(self._tutorial_payload or {})
        steps = list(payload.get("steps") or [])
        active = bool(payload and steps)
        index = min(max(0, self._tutorial_step_index), max(0, len(steps) - 1))
        step = dict(steps[index] or {}) if active else {}
        scoped = tutorial_scope.is_scoped(payload)
        if scoped:
            step = {**step, **tutorial_scope.step_route(payload, step)}
        navigation = getattr(self, "_tutorial_scope_navigation", None) if scoped else None
        paused = bool(navigation and navigation.paused)
        try_action = dict(step.get("try_action") or {})
        return {
            "active": active,
            "scoped": scoped,
            "guideKind": str(payload.get("kind") or ""),
            "allowGlobalTarget": scoped and payload.get("kind") == "workflow"
                                 and isinstance(payload.get("global_targets"), list)
                                 and step.get("target") in payload["global_targets"],
            "paused": paused,
            "elsewhere": bool(navigation and navigation.elsewhere),
            "viewToken": getattr(self, "_tutorial_view_token", 0),
            "continuousCourse": bool(payload.get("continuous_course")),
            "chapterTitle": str(step.get("chapter_title") or ""),
            "chapters": list(payload.get("chapters") or []),
            "audioStatus": str(getattr(self, "_tutorial_audio_status", "")),
            "launcherButtons": self.tutorialLaunchers.get("buttons", True),
            "launcherContext": self.tutorialLaunchers.get("context", True),
            "navigationToken": navigation.token if navigation else 0,
            "scope": tutorial_scope.step_route(payload, step) if scoped else {},
            "children": list(payload.get("children") or []),
            "audience": "remote" if payload.get("audience") == "remote" else "desktop",
            "remoteView": tutorial_catalog.remote_step_view(step) if payload.get("audience") == "remote" else {},
            "id": str(payload.get("id") or ""),
            "title": str(payload.get("title") or ""),
            "description": str(payload.get("description") or ""),
            "speechBackend": str(payload.get("speech_backend") or "chatterbox"),
            "speechEnabled": bool(self._tutorial_speech_enabled),
            "stepIndex": index,
            "stepNumber": index + 1 if active else 0,
            "stepCount": len(steps),
            "stepTitle": str(step.get("title") or f"Step {index + 1}"),
            "stepBody": str(step.get("body") or step.get("text") or ""),
            "stepTab": str(step.get("tab") or ""),
            "stepTarget": str(step.get("target") or ""),
            "stepWorkspace": self._tutorial_workspace(),
            "stepDemonstration": "console_split" if step.get("demonstration") == "console_split" else "",
            "stepFallbackTarget": str(step.get("fallback_target") or ""),
            "stepTargetHint": str(step.get("target_hint") or ""),
            "stepNotice": str(getattr(self, "_tutorial_navigation_notice", "")),
            "stepNavigation": {
                **{key: str(step.get(key) or "") for key in (
                    "runtime_section", "runtime_responsibility", "persona_tab",
                    "remote_tab", "document_section", "sensory_tab", "subsection", "chat_tab", "persona_override",
                )},
                "studio_section": str(step.get("section") or "") if step.get("addon") == "voice_studio_tab" else "",
            },
            "stepLocation": str(
                step.get("location")
                or step.get("section")
                or step.get("workspace")
                or ""
            ),
            "tryLabel": str(try_action.get("label") or ""),
            "hasTryAction": bool(try_action),
            "canGoBack": active and not paused and index > 0,
            "canGoForward": active and not paused and index + 1 < len(steps),
        }

    @QtCore.Property("QVariantMap", notify=operationsChanged)
    def operationsState(self) -> dict[str, Any]:
        try:
            speech = _plain(self._application.speech_input.snapshot())
        except Exception:
            speech = {}
        try:
            playback_snapshot = self._application.playback.snapshot()
            playback = {
                "active": getattr(playback_snapshot, "current", None) is not None,
                "queued": getattr(playback_snapshot, "next", None) is not None,
                "paused": bool(getattr(playback_snapshot, "paused", False)),
                "terminal": bool(getattr(playback_snapshot, "terminal", False)),
                "stopping": bool(getattr(playback_snapshot, "stopping", False)),
            }
        except Exception:
            playback = {}
        try:
            dry_status = _plain(dry_run.get_status() or {})
        except Exception:
            dry_status = {}
        engine = {
            "running": self.systemRunning,
            "shell_mode": False,
            "engine_connected": self.systemRunning,
            "source": "native_qml",
        }
        return {
            "speechInput": speech,
            "playback": playback,
            "dryRun": dry_status,
            "engine": _plain(engine),
        }

    @QtCore.Property("QVariantMap", notify=speechTimingSettingsChanged)
    def speechTimingSettings(self) -> dict[str, Any]:
        config = dict(self._application.config.snapshot().values)
        return {
            key: _plain(
                config.get(
                    key,
                    UI_SHELL_DEFAULT_CHUNKING_VALUES.get(
                        key,
                        UI_SHELL_CHUNKING_SPECS[key].get("default"),
                    ),
                )
            )
            for key in _SPEECH_TIMING_KEYS
        }

    @QtCore.Property(QtCore.QObject, constant=True)
    def speechTimingProfiles(self):
        controller = getattr(self, "_speech_timing_profiles", None)
        if controller is None:
            from ui.qml_bridge.speech_timing_profiles import SpeechTimingProfiles
            def catalog():
                return {
                    "avatar_mode": {item.id for item in self._application.avatar.provider_catalog()} | {"none", "vseeface"},
                    "tts_backend": {item.id for item in self._application.speech_output.backend_catalog()} | {"none"},
                    "chat_provider": {item.id for item in chat_providers.list_providers()},
                }
            controller = SpeechTimingProfiles(
                self._application.config, persist=self._save_native_session_or_raise,
                catalog=catalog,
                runtime_active=lambda: self.systemRunning or self.runtimeStarting or self.runtimeStopping,
                parent=self,
            )
            controller.profilesChanged.connect(self.operationsChanged.emit)
            controller.applied.connect(self.speechTimingSettingsChanged.emit)
            controller.applied.connect(self.configurationChanged.emit)
            controller.applied.connect(self.speechBackendsChanged.emit)
            self._speech_timing_profiles = controller
        return controller

    @QtCore.Property("QVariantList", notify=operationsChanged)
    def performanceProfiles(self) -> list[dict[str, Any]]:
        try:
            return [_plain(item) for item in dry_run.list_performance_profiles()]
        except Exception:
            return []

    @QtCore.Property("QVariantList", notify=addonsChanged)
    def addonWorkspaces(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._addon_navigation_workspaces]

    @QtCore.Property("QVariantList", notify=addonsChanged)
    def hiddenAddonWorkspaces(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._hidden_addon_navigation_workspaces]

    @QtCore.Property("QVariantList", notify=addonsChanged)
    def allAddonWorkspaces(self) -> list[dict[str, Any]]:
        """All contribution surfaces, including those mounted under Runtime."""

        return [dict(item) for item in self._addon_workspaces]

    @QtCore.Property("QVariantList", notify=addonsChanged)
    def addonRegistry(self) -> list[dict[str, Any]]:
        return [_plain(item) for item in self._addon_registry]

    @QtCore.Property(str, notify=addonViewChanged)
    def selectedAddonId(self) -> str:
        return self._selected_addon

    @QtCore.Property("QVariantMap", notify=addonViewChanged)
    def selectedAddon(self) -> dict[str, Any]:
        for item in self._addon_workspaces:
            if str(item.get("id") or "") == self._selected_addon:
                return dict(item)
        return {
            "id": self._selected_addon,
            "label": "Addon",
            "description": "Addon workspace",
            "sections": ["Overview"],
        }

    @QtCore.Property("QVariantMap", notify=addonSettingsChanged)
    def selectedAddonSettings(self) -> dict[str, Any]:
        payload = dict(self._addon_settings_by_workspace.get(self._selected_addon) or {})
        schema = [dict(item) for item in list(payload.get("schema") or [])]
        config = dict(self._application.config.snapshot().values)
        values: dict[str, Any] = {}
        for field in schema:
            key = str(field.get("key") or "")
            value = config.get(key, field.get("defaultValue"))
            if bool(field.get("json", False)):
                try:
                    value = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
                except TypeError:
                    value = str(value)
            elif bool(field.get("secret", False)) and str(value or ""):
                value = "••••••••"
            values[key] = _plain(value)
        return {
            "addonId": str(payload.get("addonId") or ""),
            "schema": schema,
            "values": values,
            "settingCount": len(schema),
        }

    @QtCore.Property("QVariantList", notify=liveAddonControlsChanged)
    def liveAddonControls(self) -> list[dict[str, Any]]:
        return [_plain(item) for item in self._live_addon_controls]

    @QtCore.Property("QVariantMap", notify=runtimeProviderSettingsChanged)
    def runtimeProviderSettings(self) -> dict[str, Any]:
        return dict(_plain(self._runtime_provider_settings) or {})

    @QtCore.Slot(str)
    def openWorkspace(self, key: str) -> None:
        self.currentWorkspace = key

    @QtCore.Slot(str, result=str)
    def workspaceHost(self, key: str) -> str:
        return self._workspace_host(key)

    @QtCore.Slot(str, result=str)
    def mainWorkspaceZone(self, key: str) -> str:
        return self._main_workspace_zone(key)

    @QtCore.Slot(str)
    def activateMainWorkspace(self, key: str) -> None:
        workspace_key = str(key or "").strip().lower()
        if workspace_key in self._hidden_workspace_tabs():
            return
        zone = self._main_workspace_zone(workspace_key)
        if not zone:
            return
        try:
            self._workspace_layout_state = self._workspace_layout.set_main_pane_active(
                zone,
                workspace_key,
            )
        except (OSError, ValueError):
            return
        workspace_changed = self._workspace != workspace_key
        self._workspace = workspace_key
        self.mainDockLayoutChanged.emit()
        if workspace_changed:
            self.workspaceChanged.emit()
        if workspace_key == "conversation":
            self.refreshConversationState()
            self.refreshLiveSessionState()
        elif workspace_key in {"visuals", "musetalk"}:
            self.refreshVisualState()

    @QtCore.Slot(str)
    def detachWorkspace(self, key: str) -> None:
        if self.panelPositionsLocked:
            self.notificationRaised.emit("info", "Panel positions are locked",
                                         "Unlock panel positions from the NeuralCompanion header menu to change docking.")
            return
        workspace_key = str(key or "").strip().lower()
        if workspace_key not in {item["key"] for item in self._WORKSPACES}:
            return
        current_host = self._workspace_host(workspace_key)
        if current_host != "main":
            current_group = self._workspace_layout_state.get("groups", {}).get(
                current_host,
                {},
            )
            if len(current_group.get("workspaces", [])) <= 1:
                return
        try:
            self._workspace_layout_state = self._workspace_layout.detach_workspace(
                workspace_key
            )
        except (OSError, ValueError) as error:
            self.notificationRaised.emit(
                "error", "Workspace was not detached", str(error)
            )
            return
        if self._workspace == workspace_key:
            remaining = [
                str(item["key"])
                for item in self._WORKSPACES
                if self._workspace_host(str(item["key"])) == "main"
            ]
            self._workspace = remaining[0] if remaining else ""
            self._persist_main_workspace(self._workspace)
            self.workspaceChanged.emit()
        self.mainDockLayoutChanged.emit()
        self.workspaceLayoutChanged.emit()

    @QtCore.Slot(str)
    def dockWorkspaceToMain(self, key: str) -> None:
        self.dockWorkspaceInMain(key, "center")

    @QtCore.Slot(str, str)
    def dockWorkspaceInMain(self, key: str, zone: str) -> None:
        if self.panelPositionsLocked:
            self.notificationRaised.emit("info", "Panel positions are locked",
                                         "Unlock panel positions from the NeuralCompanion header menu to change docking.")
            return
        workspace_key = str(key or "").strip().lower()
        if workspace_key not in {item["key"] for item in self._WORKSPACES}:
            return
        try:
            self._workspace_layout_state = self._workspace_layout.dock_workspace_to_main(
                workspace_key,
                zone,
            )
        except (OSError, ValueError) as error:
            self.notificationRaised.emit(
                "error", "Workspace was not docked", str(error)
            )
            return
        self.workspaceLayoutChanged.emit()
        self._workspace = workspace_key
        self._persist_main_workspace(workspace_key)
        self.mainDockLayoutChanged.emit()
        self.workspaceChanged.emit()

    @QtCore.Slot(str, str)
    def setMainDockPaneActive(self, zone: str, key: str) -> None:
        workspace_key = str(key or "").strip().lower()
        if workspace_key not in {item["key"] for item in self._WORKSPACES}:
            return
        try:
            self._workspace_layout_state = self._workspace_layout.set_main_pane_active(
                zone,
                workspace_key,
            )
        except (OSError, ValueError):
            return
        workspace_changed = self._workspace != workspace_key
        self._workspace = workspace_key
        self.mainDockLayoutChanged.emit()
        if workspace_changed:
            self.workspaceChanged.emit()

    @QtCore.Slot(int, int, int, int)
    def updateMainDockSplitSizes(
        self,
        left_width: int,
        right_width: int,
        top_height: int,
        bottom_height: int,
    ) -> None:
        if self.panelPositionsLocked:
            return
        try:
            self._workspace_layout_state = self._workspace_layout.update_main_splits(
                left_width=left_width,
                right_width=right_width,
                top_height=top_height,
                bottom_height=bottom_height,
            )
        except OSError:
            return

    @QtCore.Slot(int)
    def setPersonaShortcutPaneHeight(self, height: int) -> None:
        try:
            self._workspace_layout_state = (
                self._workspace_layout.update_persona_shortcuts_height(height)
            )
        except OSError:
            return
        self.workspaceLayoutChanged.emit()

    @QtCore.Slot(str, str)
    def dockWorkspaceWithGroup(self, key: str, target_group_id: str) -> None:
        if self.panelPositionsLocked:
            self.notificationRaised.emit("info", "Panel positions are locked",
                                         "Unlock panel positions from the NeuralCompanion header menu to change docking.")
            return
        workspace_key = str(key or "").strip().lower()
        if workspace_key not in {item["key"] for item in self._WORKSPACES}:
            return
        if self._workspace_host(workspace_key) == str(target_group_id or "").strip():
            return
        try:
            self._workspace_layout_state = (
                self._workspace_layout.dock_workspace_with_group(
                    workspace_key,
                    target_group_id,
                )
            )
        except (OSError, ValueError) as error:
            self.notificationRaised.emit(
                "error", "Workspace was not docked", str(error)
            )
            return
        if self._workspace == workspace_key:
            remaining = [
                str(item["key"])
                for item in self._WORKSPACES
                if self._workspace_host(str(item["key"])) == "main"
            ]
            self._workspace = remaining[0] if remaining else ""
            self._persist_main_workspace(self._workspace)
            self.workspaceChanged.emit()
        self.mainDockLayoutChanged.emit()
        self.workspaceLayoutChanged.emit()

    @QtCore.Slot(str)
    def dockFloatingGroupToMain(self, group_id: str) -> None:
        # Window Close still returns its contents safely to main while locked.
        # Manual docking controls remain disabled until the layout is unlocked.
        normalized_group_id = str(group_id or "").strip()
        group = dict(
            self._workspace_layout_state.get("groups", {}).get(normalized_group_id)
            or {}
        )
        if not group:
            return
        active_workspace = str(group.get("active") or "")
        try:
            self._workspace_layout_state = self._workspace_layout.dock_group_to_main(
                normalized_group_id
            )
        except OSError as error:
            self.notificationRaised.emit(
                "error", "Workspace window was not docked", str(error)
            )
            return
        self.workspaceLayoutChanged.emit()
        if active_workspace:
            self._workspace = active_workspace
            self._persist_main_workspace(active_workspace)
            self.mainDockLayoutChanged.emit()
            self.workspaceChanged.emit()

    @QtCore.Slot(str, str)
    def setFloatingGroupActive(self, group_id: str, key: str) -> None:
        try:
            self._workspace_layout_state = self._workspace_layout.set_group_active(
                group_id,
                key,
            )
        except OSError:
            return

    @QtCore.Slot(str, bool, result=bool)
    def setFloatingWorkspaceAlwaysOnTop(self, group_id: str, enabled: bool) -> bool:
        try:
            self._workspace_layout_state = self._workspace_layout.set_group_always_on_top(
                group_id, enabled
            )
        except (OSError, ValueError) as error:
            self.notificationRaised.emit("error", "Window preference was not saved", str(error))
            return False
        return True

    @QtCore.Slot(str, int, int, int, int)
    @QtCore.Slot(str, int, int, int, int, bool)
    def updateFloatingWorkspaceGeometry(
        self,
        group_id: str,
        x: int,
        y: int,
        width: int,
        height: int,
        avatar_only: bool | None = None,
    ) -> None:
        try:
            self._workspace_layout_state = self._workspace_layout.update_group_geometry(
                group_id,
                x=x,
                y=y,
                width=width,
                height=height,
                avatar_only=avatar_only,
            )
        except OSError:
            return

    @QtCore.Slot(int, int, int, int, bool)
    def updateMainWindowGeometry(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        maximized: bool,
    ) -> None:
        try:
            self._workspace_layout_state = self._workspace_layout.update_main_window(
                x=x,
                y=y,
                width=width,
                height=height,
                maximized=maximized,
            )
        except OSError:
            return

    @QtCore.Slot()
    def resetWorkspaceLayout(self) -> None:
        try:
            self._workspace_layout_state = self._workspace_layout.reset_docking()
        except OSError as error:
            self.notificationRaised.emit(
                "error", "Default layout was not restored", str(error)
            )
            return
        needs_default_workspace = self._workspace not in {
            item["key"] for item in self._WORKSPACES
        }
        if needs_default_workspace:
            self._workspace = "runtime"
        self._persist_main_workspace(self._workspace)
        self.workspaceLayoutChanged.emit()
        self.mainDockLayoutChanged.emit()
        if needs_default_workspace:
            self.workspaceChanged.emit()
        self.notificationRaised.emit(
            "success",
            "Default layout restored",
            "All workspaces are back in the main NeuralCompanion window.",
        )

    @QtCore.Property(QtCore.QObject, constant=True)
    def chatContextGuard(self):
        return self._chat_context_guard

    @QtCore.Slot(result=bool)
    def requestDesktopRestartConfirmation(self) -> bool:
        if self._application_closing or self._closing:
            return False
        if not self._desktop_restart_confirmation_pending:
            self._desktop_restart_confirmation_pending = True
            self.desktopRestartConfirmationRequested.emit()
        return True

    @QtCore.Slot()
    def cancelDesktopRestart(self) -> None:
        self._desktop_restart_confirmation_pending = False
        self._desktop_restart_save_choice = None

    @QtCore.Slot(bool, result=bool)
    def requestPowerButtonRestart(self, save_conversation: bool) -> bool:
        """Prepare the explicit chat decision before starting the existing countdown."""
        if self._application_closing or self._closing or self._desktop_restart_confirmation_pending:
            return False
        guard = getattr(self, '_chat_context_guard', None)
        if guard is not None and guard.state['active']:
            return False

        def ready() -> None:
            if not self._application_closing and not self._closing:
                self._desktop_restart_save_choice = bool(save_conversation)
                self.requestDesktopRestartConfirmation()

        if save_conversation:
            if guard is None:
                self.notificationRaised.emit('error', 'Restart was not started', 'The conversation save service is unavailable.')
                return False
            return guard.requestSave('restarting NeuralCompanion', ready)
        ready()
        return True

    @QtCore.Slot(result=bool)
    def confirmDesktopRestart(self) -> bool:
        if not self._desktop_restart_confirmation_pending or self._application_closing or self._closing:
            return False
        self._desktop_restart_confirmation_pending = False
        save_choice = self._desktop_restart_save_choice
        self._desktop_restart_save_choice = None
        guard = getattr(self, '_chat_context_guard', None)
        if save_choice is not None:
            if guard is not None and guard.state['active']:
                return False

            def ready() -> None:
                if not self._application_closing and not self._closing:
                    self._shutdown_chat_preconfirmed = True
                    self.desktopRestartConfirmed.emit()

            # A running reply can add output during the countdown. Preserve it
            # through the same worker before honoring a Save restart.
            if save_choice and guard is not None and guard.isDirty():
                return guard.requestSave('restarting NeuralCompanion', ready)
            ready()
            return True
        if guard is not None and (guard.isDirty() or guard.state['active']):
            def approved():
                if not self._application_closing and not self._closing:
                    self._shutdown_chat_preconfirmed = True
                    self.desktopRestartConfirmed.emit()
            # Arm relaunch only after the cancellable chat decision. Otherwise
            # RestartRequest sees a rejected close and clears its restart latch.
            return guard.request('restarting NeuralCompanion', approved)
        self.desktopRestartConfirmed.emit()
        return True

    @QtCore.Slot(result=bool)
    def beginApplicationShutdown(self) -> bool:
        if getattr(self, "_application_shutdown_ready", False):
            return True
        if self._application_closing:
            return False
        guard = getattr(self, '_chat_context_guard', None)
        if guard is not None and not getattr(self, '_shutdown_chat_preconfirmed', False) and (guard.isDirty() or guard.state['active']):
            def approved():
                self._shutdown_chat_preconfirmed = True
                self.applicationShutdownReady.emit()
            if not guard.request('exiting NeuralCompanion', approved):
                return False
        rule_catalog = getattr(self, '_avatar_rule_catalog', None)
        if rule_catalog is not None:
            rule_catalog.close()
        resource_monitor = getattr(self, '_resource_monitor', None)
        if resource_monitor is not None and not resource_monitor.beginShutdown():
            if not getattr(self, '_resources_shutdown_connected', False):
                resource_monitor.shutdownFinished.connect(self._on_resources_shutdown_finished)
                self._resources_shutdown_connected = True
            self._resources_shutdown_waiting = True
            self._application_closing = True
            self._runtime_controller.set_shutdown_pending(True)
            self.applicationClosingChanged.emit()
            return False
        creator = self._musetalk_creator
        try:
            needs_drain = creator.requiresShutdownDrain() or self._runtime_controller.starting
        except Exception as error:
            if resource_monitor is not None:
                resource_monitor.cancelShutdown()
            self._runtime_controller.set_shutdown_pending(False)
            self.applicationClosingChanged.emit()
            self.notificationRaised.emit("error", "Creator shutdown could not start", str(error))
            return False
        self._application_closing = True
        self._runtime_controller.set_shutdown_pending(True)
        self.applicationClosingChanged.emit()
        if needs_drain:
            if not getattr(self, "_creator_shutdown_connected", False):
                creator.shutdownFinished.connect(self._on_creator_shutdown_finished)
                self._creator_shutdown_connected = True
            creator.beginShutdown(self._runtime_controller.wait_for_startup)
            return False
        self._application_shutdown_ready = True
        memory_workspace = getattr(self, "_memory_workspace", None)
        if memory_workspace is not None:
            memory_workspace.close()
        sensory_image_status = getattr(self, "_sensory_image_status", None)
        if sensory_image_status is not None:
            sensory_image_status.close()
        return True

    @QtCore.Slot()
    def _on_resources_shutdown_finished(self):
        if not getattr(self, '_resources_shutdown_waiting', False):
            return
        self._resources_shutdown_waiting = False
        self._application_closing = False
        if self.beginApplicationShutdown():
            if getattr(self, '_close_after_creator_shutdown', False):
                self.close()
            self.applicationShutdownReady.emit()

    @QtCore.Slot(bool, str)
    def _on_creator_shutdown_finished(self, accepted: bool, error: str) -> None:
        if not accepted:
            resource_monitor = getattr(self, '_resource_monitor', None)
            if resource_monitor is not None:
                resource_monitor.cancelShutdown()
            self._application_closing = False
            self._runtime_controller.set_shutdown_pending(False)
            self.applicationClosingChanged.emit()
            self.notificationRaised.emit("error", "MuseTalk cleanup is incomplete",
                                         str(error) + " Close again to retry; the application remains open.")
            return
        self._application_shutdown_ready = True
        if getattr(self, "_close_after_creator_shutdown", False):
            self.close()
        self.applicationShutdownReady.emit()

    @QtCore.Slot(bool)
    def completeFirstRunPrompt(self, start_tutorial: bool) -> None:
        if not self._should_prompt_first_run:
            return
        self._should_prompt_first_run = False
        self.onboardingChanged.emit()
        if start_tutorial:
            self.currentWorkspace = "addons"
            self.viewAddon("core.tutorials")
            self.startTutorial("first_run")

    @QtCore.Slot(bool)
    def setWelcomeHubStartup(self, enabled: bool) -> None:
        result = self._application.config.update(
            "welcome_hub_show_on_startup", bool(enabled)
        )
        if result.accepted:
            self._save_native_session_or_raise()

    @QtCore.Slot()
    def requestWelcomeHub(self) -> None:
        self.welcomeHubRequested.emit()

    @QtCore.Slot(str)
    def viewProvider(self, provider_id: str) -> None:
        normalized = chat_providers.normalize_provider_id(
            provider_id,
            fallback=self.activeProviderId,
        )
        if normalized == self.viewedProviderId:
            return
        self._viewed_provider = normalized
        self._models = []
        self.providerViewChanged.emit()
        self.modelCatalogChanged.emit()

    def _configure_orb_vision_provider(self, provider_id: str) -> None:
        # Navigation only: never activate the provider or change the chat model.
        self.viewProvider(provider_id)
        self.rememberNavigationSelection('runtime:responsibility', 'language')
        self.rememberNavigationSelection('runtime:section', 'runtime')
        self.currentWorkspace = 'runtime'
        self.orbProviderSettingsRequested.emit()

    @QtCore.Slot()
    def ensureViewedProviderModels(self) -> None:
        """Populate LM Studio and opted-in provider catalogs on opening settings."""

        if (self.viewedProviderId != "lmstudio" and
                chat_providers.provider_metadata(self.viewedProviderId).get(
                    "auto_refresh_model_catalog_on_view") is not True):
            return
        if self._models or self._model_refresh_in_flight or self._provider_test_in_flight:
            return
        self.refreshModels()

    @QtCore.Slot(str)
    def viewAddon(self, addon_id: str) -> None:
        key = str(addon_id or "").strip()
        if not key:
            return
        if not any(
            str(item.get("id") or "") == key
            and bool(item.get("available", True))
            for item in self._addon_workspaces
        ):
            return
        self.rememberNavigationSelection("addons:selected", key)
        if key == self._selected_addon:
            return
        if self._selected_addon == "musetalk_preprocess_tab":
            self._musetalk_creator.requestDeparture()
        self._selected_addon = key
        self.addonViewChanged.emit()
        self.addonSettingsChanged.emit()
        self.refreshLiveAddonControls()
        if key == "musetalk_preprocess_tab":
            self._musetalk_creator.refresh()

    def _addon_rail_candidates(self) -> list[dict[str, Any]]:
        return [
            item
            for item in self._addon_workspaces
            if not bool(item.get("providerSurface", False))
            and item.get("addonId") != "nc.rag_context"
        ]

    def _apply_addon_rail_layout(self, *, preferred_index: int | None = None) -> bool:
        candidates = self._addon_rail_candidates()
        candidate_ids = [str(item.get("id") or "") for item in candidates]
        try:
            layout = self._addon_rail_layout.resolve(candidate_ids)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "[Addons] Addon rail layout could not be read: %s", exc
            )
            layout = {"visible": candidate_ids, "hidden": []}
        items_by_id = {str(item.get("id") or ""): item for item in candidates}
        self._addon_navigation_workspaces = [
            items_by_id[identifier]
            for identifier in layout["visible"]
            if identifier in items_by_id
            and bool(items_by_id[identifier].get("available", True))
        ]
        self._hidden_addon_navigation_workspaces = [
            items_by_id[identifier]
            for identifier in layout["hidden"]
            if identifier in items_by_id
        ]
        visible_ids = [
            str(item.get("id") or "") for item in self._addon_navigation_workspaces
        ]
        if self._selected_addon in visible_ids:
            return False
        previous = self._selected_addon
        if visible_ids:
            index = 0 if preferred_index is None else max(
                0, min(int(preferred_index), len(visible_ids) - 1)
            )
            self._selected_addon = visible_ids[index]
        else:
            self._selected_addon = ""
        if previous == "musetalk_preprocess_tab" and previous != self._selected_addon:
            self._musetalk_creator.requestDeparture()
        if previous != self._selected_addon and self._selected_addon:
            self.rememberNavigationSelection("addons:selected", self._selected_addon)
        return previous != self._selected_addon

    def _emit_addon_rail_change(self, selection_changed: bool) -> None:
        self.addonsChanged.emit()
        if not selection_changed:
            return
        self.addonViewChanged.emit()
        self.addonSettingsChanged.emit()
        self.refreshLiveAddonControls()
        if self._selected_addon == "musetalk_preprocess_tab":
            self._musetalk_creator.refresh()

    @QtCore.Slot(str)
    def hideAddonFromRail(self, addon_id: str) -> None:
        key = str(addon_id or "").strip()
        visible_ids = [
            str(item.get("id") or "") for item in self._addon_navigation_workspaces
        ]
        if key not in visible_ids:
            return
        preferred_index = visible_ids.index(key)
        candidate_ids = [
            str(item.get("id") or "") for item in self._addon_rail_candidates()
            if bool(item.get("available", True))
        ]
        try:
            self._addon_rail_layout.set_hidden(key, True, candidate_ids)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "[Addons] Addon rail visibility could not be saved: %s", exc
            )
            return
        self._emit_addon_rail_change(
            self._apply_addon_rail_layout(preferred_index=preferred_index)
        )

    @QtCore.Slot(str)
    def unhideAddonOnRail(self, addon_id: str) -> None:
        key = str(addon_id or "").strip()
        hidden_ids = {
            str(item.get("id") or "")
            for item in self._hidden_addon_navigation_workspaces
            if bool(item.get("available", True))
        }
        if key not in hidden_ids:
            return
        candidate_ids = [
            str(item.get("id") or "") for item in self._addon_rail_candidates()
            if bool(item.get("available", True))
        ]
        try:
            self._addon_rail_layout.set_hidden(key, False, candidate_ids)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "[Addons] Addon rail visibility could not be saved: %s", exc
            )
            return
        self._apply_addon_rail_layout()
        self._emit_addon_rail_change(False)

    @QtCore.Slot(str, int)
    def moveAddonOnRail(self, addon_id: str, target_index: int) -> None:
        key = str(addon_id or "").strip()
        visible_ids = [
            str(item.get("id") or "") for item in self._addon_navigation_workspaces
        ]
        if key not in visible_ids:
            return
        candidate_ids = [
            str(item.get("id") or "") for item in self._addon_rail_candidates()
            if bool(item.get("available", True))
        ]
        try:
            self._addon_rail_layout.move_visible(key, target_index, candidate_ids)
        except (OSError, TypeError, ValueError) as exc:
            logging.getLogger(__name__).warning(
                "[Addons] Addon rail order could not be saved: %s", exc
            )
            return
        self._apply_addon_rail_layout()
        self._emit_addon_rail_change(False)

    @QtCore.Slot(str, str, result=str)
    def navigationSelection(self, key: str, fallback: str) -> str:
        return self._navigation_selections.get(key, fallback)

    @QtCore.Slot(str, str, result="QVariantMap")
    def checkComposerSpelling(self, text: str, language: str) -> dict[str, Any]:
        return composer_spellcheck.check_text(text, language)

    @QtCore.Slot(str, str, result="QVariantList")
    def composerSpellingSuggestions(self, word: str, language: str) -> list[str]:
        return composer_spellcheck.suggestions(word, language)

    @QtCore.Slot(QtCore.QObject, str, int, int, str, result=bool)
    def applyComposerSpelling(self, editor: QtCore.QObject, original: str,
                             start: int, length: int, replacement: str) -> bool:
        return composer_spellcheck.replace_word(editor, original, start, length, replacement)

    @QtCore.Slot(str, str)
    def rememberNavigationSelection(self, key: str, selection: str) -> None:
        if not key or not selection or self._navigation_selections.get(key) == selection:
            return
        self._navigation_selections[key] = selection
        if self._navigation_read_only:
            return
        try:
            self._workspace_layout_state = self._workspace_layout.set_navigation_selection(key, selection)
        except OSError as exc:
            logging.getLogger(__name__).warning("[Navigation] Tab selection could not be saved: %s", exc)

    @QtCore.Slot(str, result=float)
    def settingsScrollPosition(self, key: str) -> float:
        return self._settings_scroll_positions.get(key, 0.0)

    @QtCore.Slot(str, float)
    def rememberSettingsScrollPosition(self, key: str, position: float) -> None:
        if key and 0 <= position < float("inf"):
            self._settings_scroll_positions[key] = position

    @QtCore.Slot(str, str)
    def openAddonWorkspaceSection(self, addon_id: str, section: str) -> None:
        workspace_id = str(addon_id or "").strip()
        section_name = str(section or "").strip()
        if not workspace_id:
            return
        workspace = next((item for item in self._addon_workspaces
                          if str(item.get("id") or "") == workspace_id), None)
        if workspace is not None and section_name in (workspace.get("sections") or []):
            self.rememberNavigationSelection("addon:" + workspace_id, section_name)
        self.viewAddon(workspace_id)
        self.currentWorkspace = "addons"
        self.addonSectionRequested.emit(workspace_id, section_name)

    @QtCore.Slot(str, str)
    def openRuntimeBackendSettings(self, kind: str, backend_id: str) -> None:
        """Backward-compatible alias for the provider-first Runtime settings view."""

        self.viewRuntimeProviderSettings(kind, backend_id)

    @QtCore.Slot(str, str)
    def viewSpeechBackend(self, kind: str, backend_id: str) -> None:
        self.viewRuntimeProviderSettings(kind, backend_id)

    @QtCore.Slot(str)
    def viewAvatarProvider(self, provider_id: str) -> None:
        self.viewRuntimeProviderSettings("avatar", provider_id)

    @QtCore.Slot(str)
    def viewVisionProvider(self, provider_id: str) -> None:
        self.viewRuntimeProviderSettings("vision", provider_id)

    @QtCore.Slot(str, str)
    def viewRuntimeProviderSettings(self, kind: str, provider_id: str) -> None:
        normalized_kind = str(kind or "").strip().lower()
        normalized_provider = str(provider_id or "").strip().lower()
        if normalized_kind not in {"stt", "tts", "avatar", "vision"}:
            return
        if not normalized_provider:
            normalized_provider = (
                "shared_awareness" if normalized_kind == "vision" else "none"
            )

        if normalized_kind in self._viewed_speech_backends:
            self._viewed_speech_backends[normalized_kind] = normalized_provider
            self.speechBackendsChanged.emit()
        elif normalized_kind == "avatar":
            self._viewed_avatar_provider = normalized_provider
            self.sessionSetupChanged.emit()
        else:
            self._viewed_vision_provider = normalized_provider
            self.coreSettingsChanged.emit()
        self._refresh_runtime_provider_settings(normalized_kind, normalized_provider)

    @QtCore.Slot()
    def refreshRuntimeProviderSettings(self) -> None:
        kind = str(self._runtime_provider_settings.get("kind") or "").strip().lower()
        provider_id = str(
            self._runtime_provider_settings.get("providerId") or ""
        ).strip().lower()
        if kind and provider_id:
            self._refresh_runtime_provider_settings(kind, provider_id)

    def _refresh_runtime_provider_settings(self, kind: str, provider_id: str) -> None:
        label, description = self._runtime_provider_identity(kind, provider_id)
        active_provider = {
            "stt": self.selectedSpeechInputBackend,
            "tts": self.selectedSpeechOutputBackend,
            "avatar": str(self.sessionSetup.get("avatarMode") or "none").lower(),
            "vision": self.activeVisionProvider,
        }.get(kind, "")
        controls: list[dict[str, Any]] = []
        sections: list[str] = []

        if kind == "stt":
            controls = self._stt_runtime_provider_controls(provider_id)
            sections = ["Recognition"] if controls else []
        else:
            targets = self._runtime_provider_workspace_targets(kind, provider_id)
            multiple_targets = len(targets) > 1
            for target in targets:
                workspace_id = str(target.get("id") or "")
                native_adapter = (
                    self._native_surfaces.adapter(workspace_id)
                    or self._native_surfaces.adapter_for_addon(
                        str(target.get("addonId") or "")
                    )
                )
                if native_adapter is not None:
                    try:
                        target_controls = native_adapter.snapshot().to_qml_controls()
                    except (KeyError, RuntimeError, TypeError, ValueError):
                        target_controls = []
                else:
                    target_controls = []
                surface_label = str(
                    target.get("contributionTitle") or target.get("label") or "Settings"
                ).strip()
                for descriptor in target_controls:
                    native_section = str(descriptor.get("section") or "Overview")
                    if (
                        kind == "vision"
                        and provider_id == "companion_orb_target"
                        and native_section not in {"Awareness", "Vision & Actions"}
                    ):
                        continue
                    if (
                        kind == "vision"
                        and provider_id == "spotify_sense"
                        and native_section
                        not in {"Awareness", "Hidden Sense"}
                    ):
                        continue
                    original_id = str(descriptor.get("id") or "")
                    control_id = f"{workspace_id}::{original_id}"
                    section = native_section
                    if multiple_targets:
                        section = f"{surface_label} · {section}"
                    elif section.lower() == "overview":
                        section = "Provider settings"
                    item = {**descriptor, "id": control_id, "section": section}
                    controls.append(item)
                    if section not in sections:
                        sections.append(section)

        is_active = (
            provider_id in self.activeVisionProviders
            if kind == "vision" and provider_id != "off"
            else provider_id == active_provider
        )
        if kind == "vision" and provider_id == "off":
            is_active = not self.activeVisionProviders

        self._runtime_provider_settings = {
            "kind": kind,
            "providerId": provider_id,
            "label": label,
            "description": description,
            "active": is_active,
            "sections": sections,
            "controls": controls,
            "hasSettings": bool(controls),
        }
        self.runtimeProviderSettingsChanged.emit()

    def _runtime_provider_identity(self, kind: str, provider_id: str) -> tuple[str, str]:
        catalogs = {
            "stt": self._speech_input_backends,
            "tts": self._speech_output_backends,
            "avatar": self.avatarOptions,
            "vision": self.visionProviderOptions,
        }
        for item in catalogs.get(kind, []):
            if str(item.get("id") or "").strip().lower() == provider_id:
                return (
                    str(item.get("label") or provider_id),
                    str(item.get("description") or ""),
                )
        return provider_id.replace("_", " ").title(), ""

    def _runtime_provider_workspace_targets(
        self,
        kind: str,
        provider_id: str,
    ) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []
        for item in self._addon_workspaces:
            area = str(item.get("area") or "").strip().lower()
            backend_id = str(item.get("backendId") or "").strip().lower()
            item_provider = str(item.get("providerId") or "").strip().lower()
            parent_id = str(item.get("parentTabId") or "").strip().lower()
            matches = (
                (kind == "tts" and area == "tts_runtime" and backend_id == provider_id)
                or (
                    kind == "avatar"
                    and area in {"top_level", "avatar_tools"}
                    and item_provider == provider_id
                )
                or (
                    kind == "vision"
                    and area == "vision_source"
                    and parent_id == provider_id
                )
                or (
                    kind == "vision"
                    and provider_id == "companion_orb_target"
                    and str(item.get("addonId") or "").strip().lower()
                    == "nc.companion_orb_overlay"
                )
                or (
                    kind == "vision"
                    and provider_id == "spotify_sense"
                    and str(item.get("addonId") or "").strip().lower()
                    == "nc.spotify_sense"
                )
            )
            if matches:
                targets.append(dict(item))
        return targets

    def _stt_runtime_provider_controls(self, backend_id: str) -> list[dict[str, Any]]:
        if backend_id in {"", "none", "disabled"}:
            return []
        spec = next(
            (
                item
                for item in self._speech_input_backends
                if str(item.get("id") or "").strip().lower() == backend_id
            ),
            {},
        )
        metadata = dict(spec.get("metadata") or {})
        language_mode = str(metadata.get("language_mode") or "").strip().lower()
        if language_mode == "disabled":
            return []
        effective = stt_backend_runtime_config(
            self._application.config.snapshot().values, backend_id=backend_id,
        )
        model = str(
            effective.get("stt_model_size")
            or metadata.get("default_model_size")
            or "tiny.en"
        ).strip()
        controls: list[dict[str, Any]] = [
            {
                "id": "stt:model_size",
                "objectName": "stt_model_size",
                "label": "Recognition model",
                "description": "Saved separately for this speech-input provider.",
                "section": "Recognition",
                "type": "choice",
                "value": model,
                "options": [
                    {"label": option, "value": option}
                    for option in WHISPER_MODEL_SIZE_OPTIONS
                ],
                "enabled": True,
                "secret": False,
                "destructive": False,
            }
        ]
        if language_mode == "multilingual":
            raw_language = effective.get(
                "stt_language", metadata.get("default_language", "")
            )
            language = normalize_whisper_language(raw_language) or ""
            controls.append(
                {
                    "id": "stt:language",
                    "objectName": "stt_language",
                    "label": "Recognition language",
                    "description": "Use Auto Detect or pin this provider to one language.",
                    "section": "Recognition",
                    "type": "choice",
                    "value": language,
                    "options": [
                        {"label": label, "value": code}
                        for label, code in WHISPER_LANGUAGE_OPTIONS
                    ],
                    "enabled": True,
                    "secret": False,
                    "destructive": False,
                }
            )
        from ui.qml_bridge.settings_help import field_help
        return [{**control, "toolTip": field_help(control, "stt")} for control in controls]

    @QtCore.Slot(str)
    def activateVisionProvider(self, provider_id: str) -> None:
        selected = str(provider_id or "off").strip().lower() or "off"
        allowed = {
            str(item.get("id") or "").strip().lower()
            for item in self.visionProviderOptions
        }
        if selected not in allowed:
            return
        self.setVisionProviderEnabled(selected, True)

    @QtCore.Slot(str, bool)
    def setVisionProviderEnabled(self, provider_id: str, enabled: bool) -> None:
        selected = str(provider_id or "off").strip().lower() or "off"
        allowed = {
            str(item.get("id") or "").strip().lower()
            for item in self.visionProviderOptions
        }
        if selected not in allowed:
            return

        current = self._application.config.get("sensory_feedback_source", "off")
        current_sources = normalize_source_tokens(current)
        shared_toggle = selected == "shared_awareness"
        previous_source = source_tokens_value(current)
        previous_pingpong = bool(
            self._application.config.get("sensory_pingpong_enabled", False)
        )
        activation_controls = (
            tuple(
                control
                for source in current_sources
                for control in _vision_provider_activation_controls(
                    source, bool(enabled)
                )
            )
            if shared_toggle
            else _vision_provider_activation_controls(selected, enabled)
        )
        adapter_updates: list[tuple[Any, str, Any, Any]] = []
        try:
            for surface_id, control_id, control_value in activation_controls:
                adapter = self._native_surfaces.adapter(surface_id)
                if adapter is None:
                    raise RuntimeError(
                        f"The {selected} settings adapter is unavailable."
                    )
                controls = {
                    str(control.id): control
                    for control in adapter.snapshot().controls
                }
                if control_id not in controls:
                    raise KeyError(
                        f"The {selected} activation control '{control_id}' is unavailable."
                    )
                adapter_updates.append(
                    (adapter, control_id, control_value, controls[control_id].value)
                )
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit(
                "error",
                "Sensory source is not ready",
                str(error),
            )
            return

        updates = (
            {"sensory_pingpong_enabled": bool(enabled)}
            if shared_toggle
            else source_runtime_updates(current, selected, enabled)
        )
        result = self._application.config.update_many(updates)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Sensory source was not changed",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the sensory source selection.",
                    )
                ),
            )
            return

        try:
            for adapter, control_id, control_value, _previous_value in adapter_updates:
                adapter.set_value(control_id, control_value)
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            self._application.config.update_many(
                {
                    "sensory_feedback_source": previous_source,
                    "sensory_pingpong_enabled": previous_pingpong,
                }
            )
            for adapter, control_id, _control_value, previous_value in reversed(
                adapter_updates
            ):
                try:
                    adapter.set_value(control_id, previous_value)
                except (KeyError, RuntimeError, TypeError, ValueError):
                    pass
            self._session_store.save()
            self.coreSettingsChanged.emit()
            self.configurationChanged.emit()
            self.notificationRaised.emit(
                "error",
                "Sensory source is not ready",
                str(error),
            )
            return

        self._session_store.save()
        self.coreSettingsChanged.emit()
        self.configurationChanged.emit()

        if shared_toggle:
            self.viewVisionProvider("shared_awareness")

        viewed = str(self._viewed_vision_provider or selected or "off").strip().lower()
        self._refresh_runtime_provider_settings("vision", viewed)

    @QtCore.Slot(str)
    def testVisionProvider(self, provider_id: str) -> None:
        selected = str(provider_id or "").strip().lower()
        if not selected or selected == "off":
            return
        if bool(self._vision_provider_test.get("inFlight", False)):
            return
        provider = get_sensory_provider(selected)
        if provider is None or not callable(getattr(provider, "capture_handler", None)):
            self._vision_provider_test = {
                "providerId": selected,
                "inFlight": False,
                "status": "error",
                "message": "The provider is not registered with the core sensory runtime.",
                "details": {},
            }
            self.visionProviderTestChanged.emit()
            return

        self._vision_provider_test = {
            "providerId": selected,
            "inFlight": True,
            "status": "testing",
            "message": "Capturing one diagnostic snapshot without calling the language model.",
            "details": {},
        }
        self.visionProviderTestChanged.emit()
        config = dict(self._application.config.snapshot().values)
        selected_sources = normalize_source_tokens(
            config.get("sensory_feedback_source", "off")
        )

        def run_probe() -> dict[str, Any]:
            try:
                snapshot = capture_sensory_snapshot(
                    selected,
                    {
                        "output_dir": str(
                            _APP_ROOT / "runtime" / "sensory_feedback"
                        ),
                        "runtime_config": config,
                        "timestamp": time.time(),
                        "selected_sources": selected_sources,
                    },
                )
            except Exception as error:
                return {
                    "providerId": selected,
                    "inFlight": False,
                    "status": "error",
                    "message": str(error),
                    "details": {"exceptionType": type(error).__name__},
                }
            if not isinstance(snapshot, Mapping):
                return {
                    "providerId": selected,
                    "inFlight": False,
                    "status": "waiting",
                    "message": _empty_sensory_probe_message(selected),
                    "details": {},
                }
            payload = dict(snapshot)
            metadata = (
                dict(payload.get("metadata") or {})
                if isinstance(payload.get("metadata"), Mapping)
                else {}
            )
            image_path = str(payload.get("image_path") or "").strip()
            reason = str(metadata.get("reason") or "").strip()
            details = {
                "source": str(payload.get("source") or selected),
                "imagePath": image_path,
                "imageExists": bool(image_path and Path(image_path).is_file()),
                "reason": reason,
                "captureMode": str(metadata.get("capture_mode") or ""),
            }
            content = str(
                payload.get("content_text")
                or payload.get("content")
                or ""
            ).strip()
            if reason:
                message = content or f"The provider reported: {reason}."
                status = "warning"
            elif details["imageExists"] or content:
                message = (
                    f"Capture succeeded: {Path(image_path).name}"
                    if details["imageExists"]
                    else "Capture succeeded and returned sensory context."
                )
                status = "ready"
            else:
                message = _empty_sensory_probe_message(selected)
                status = "waiting"
            return {
                "providerId": selected,
                "inFlight": False,
                "status": status,
                "message": message,
                "details": details,
            }

        future = self._runtime_executor.submit(run_probe)

        def complete(task: Any) -> None:
            try:
                payload = task.result()
            except BaseException as error:
                payload = {
                    "providerId": selected,
                    "inFlight": False,
                    "status": "error",
                    "message": str(error),
                    "details": {"exceptionType": type(error).__name__},
                }
            self._visionProviderTestReceived.emit(payload)

        future.add_done_callback(complete)

    @QtCore.Slot(object)
    def _on_vision_provider_test_received(self, payload: object) -> None:
        self._vision_provider_test = dict(_plain(payload) or {})
        self.visionProviderTestChanged.emit()

    @QtCore.Slot(str)
    def activateProvider(self, provider_id: str) -> bool:
        normalized = chat_providers.normalize_provider_id(
            provider_id,
            fallback=self.activeProviderId,
        )
        generation_map = _plain(self._application.config.get("chat_provider_generation_settings", {})) or {}
        generation = dict(generation_map.get(normalized) or {})
        settings_map = _plain(self._application.config.get("chat_provider_settings", {})) or {}
        settings = dict(settings_map.get(normalized) or {})
        model = str(settings.get("model_name") or "").strip()
        if not model and normalized == self.activeProviderId:
            model = str(self._application.config.get("model_name", "") or "").strip()
        updates = {"chat_provider": normalized, "model_name": model,
                   "model_supports_images": bool(settings.get("model_supports_images", infer_model_supports_images(model)))}
        updates.update({key: generation[key] for key in GENERATION_DEFAULT_KEYS if key in generation})
        update_selection = getattr(self._application.config, "update_provider_selection", None)
        result = (update_selection(updates) if callable(update_selection)
                  else self._application.config.update_many(updates))
        if not result.accepted:
            message = str(getattr(result.failure, "message", "Could not activate provider."))
            self.notificationRaised.emit("error", "Provider was not changed", message)
            return False
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit(
                "error",
                "Provider was not changed",
                str(error),
            )
            return False
        self.configurationChanged.emit()
        self.refreshProviderState()
        self.notificationRaised.emit(
            "success",
            "Active language provider changed",
            chat_providers.provider_label(normalized),
        )
        return True

    @QtCore.Slot()
    def refreshSpeechBackendState(self) -> None:
        def catalog(commands: Any, kind: str) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            try:
                specs = commands.backend_catalog()
            except Exception:
                specs = ()
            for raw in specs:
                item = dict(_plain(raw) or {})
                backend_id = str(item.get("id") or "").strip().lower()
                if not backend_id:
                    continue
                metadata = dict(item.get("metadata") or {})
                items.append(
                    {
                        **item,
                        "id": backend_id,
                        "label": str(item.get("label") or backend_id),
                        "kind": kind,
                        "description": str(
                            metadata.get("description")
                            or metadata.get("summary")
                            or ("Microphone input backend" if kind == "stt" else "Voice output backend")
                        ),
                    }
                )
            return items

        self._speech_input_backends = catalog(self._application.speech_input, "stt")
        self._speech_output_backends = catalog(self._application.speech_output, "tts")
        if not any(item["id"] == "none" for item in self._speech_input_backends):
            self._speech_input_backends.insert(
                0,
                {
                    "id": "none",
                    "label": "Disabled",
                    "kind": "stt",
                    "description": "Do not listen to a microphone.",
                    "metadata": {},
                },
            )
        if not any(item["id"] == "none" for item in self._speech_output_backends):
            self._speech_output_backends.insert(
                0,
                {
                    "id": "none",
                    "label": "Disabled",
                    "kind": "tts",
                    "description": "Do not synthesize spoken replies.",
                    "metadata": {},
                },
            )
        self.speechBackendsChanged.emit()

    @QtCore.Slot(str, str)
    def selectSpeechBackend(self, kind: str, backend_id: str) -> bool:
        normalized_kind = str(kind or "").strip().lower()
        selected = str(backend_id or "").strip().lower()
        if normalized_kind not in {"stt", "tts"} or not selected:
            return False
        catalog = (
            self._speech_input_backends
            if normalized_kind == "stt"
            else self._speech_output_backends
        )
        if not any(str(item.get("id") or "") == selected for item in catalog):
            self.notificationRaised.emit(
                "error",
                "Runtime was not changed",
                f"Unknown {normalized_kind.upper()} backend: {selected}",
            )
            return False
        config_key = "stt_backend" if normalized_kind == "stt" else "tts_backend"
        previous = str(self._application.config.get(config_key, "none") or "none").strip().lower()
        if previous == selected:
            return True
        if normalized_kind == "stt" and self._runtime_operation:
            self.notificationRaised.emit(
                "warning", "Runtime change is busy",
                "Wait for the current runtime operation to finish and try again.",
            )
            return False
        if normalized_kind == "stt":
            values = self._application.config.snapshot().values
            existing = values.get("stt_backend_settings")
            settings_map = dict(existing) if isinstance(existing, Mapping) else {}
            # Capture legacy settings for the outgoing provider before changing
            # the selection; a newly selected provider gets its own defaults.
            for candidate in (previous, selected):
                if candidate in {"none", "disabled", ""} or isinstance(settings_map.get(candidate), Mapping):
                    continue
                effective = stt_backend_runtime_config(values, backend_id=candidate)
                settings_map[candidate] = {
                    "model_size": effective.get("stt_model_size", "tiny.en"),
                    "language": effective.get("stt_language", ""),
                }
            result = self._application.config.update_many({
                "stt_backend_settings": settings_map, config_key: selected,
            })
        else:
            result = self._application.config.update(config_key, selected)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Runtime was not changed",
                str(getattr(result.failure, "message", "Could not save the backend selection.")),
            )
            return False
        if not self.systemRunning or selected == "none":
            try:
                if normalized_kind == "stt" and selected == "none":
                    # Stop capture before releasing either STT adapter owner.
                    stopped = self._application.speech_input.stop()
                    if not stopped.accepted:
                        raise RuntimeError(stopped.failure.message)
                    released = self._application.speech_input.reinitialize_backend()
                    if not released.accepted or released.value is False:
                        raise RuntimeError(
                            getattr(released.failure, "message", "Could not release speech input.")
                        )
                self._save_native_session_or_raise()
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                if normalized_kind == "stt" and selected == "none":
                    self._application.config.update_many({
                        config_key: previous,
                        "stt_backend_settings": dict(existing) if isinstance(existing, Mapping) else {},
                    })
                elif normalized_kind == "tts":
                    self._application.config.update(config_key, previous)
                self.notificationRaised.emit(
                    "error",
                    "Runtime was not changed",
                    str(error),
                )
                return False
            self.configurationChanged.emit()
            self.notificationRaised.emit(
                "success",
                "Runtime selection saved",
                f"{normalized_kind.upper()} will use {selected} when NeuralCompanion initializes.",
            )
            return True
        if self._runtime_operation:
            self._application.config.update(config_key, previous)
            self.configurationChanged.emit()
            self.notificationRaised.emit(
                "warning",
                "Runtime change is busy",
                "Wait for the current runtime operation to finish and try again.",
            )
            return False

        self._schedule_runtime_reinitialization(
            normalized_kind,
            selected,
            rollback={config_key: previous},
        )
        return True

    def _schedule_runtime_reinitialization(
        self,
        kind: str,
        operation_label: str,
        *,
        rollback: Mapping[str, Any] | None = None,
    ) -> None:
        normalized_kind = str(kind or "").strip().lower()
        self._runtime_operation = normalized_kind
        self._runtime_operation_backend = str(operation_label or "").strip()
        self._runtime_operation_previous = dict(rollback or {}) or None
        self.configurationChanged.emit()
        self.runtimeOperationChanged.emit()
        commands = (
            self._application.speech_input
            if normalized_kind == "stt"
            else self._application.speech_output
        )
        future = self._runtime_executor.submit(commands.reinitialize_backend)

        def complete(task: Any) -> None:
            try:
                command_result = task.result()
                accepted = (
                    bool(getattr(command_result, "accepted", False))
                    and getattr(command_result, "value", None) is not False
                )
                failure = getattr(command_result, "failure", None)
                message = str(getattr(failure, "message", "") or "")
                self._runtimeOperationReceived.emit(
                    normalized_kind,
                    operation_label,
                    accepted,
                    message,
                )
            except BaseException as error:
                self._runtimeOperationReceived.emit(
                    normalized_kind,
                    operation_label,
                    False,
                    str(error),
                )

        future.add_done_callback(complete)

    @QtCore.Slot(str, "QVariant")
    def setSessionField(self, field_id: str, value: Any) -> None:
        key = str(field_id or "").strip()
        config_keys = {
            "inputMode": "input_mode",
            "inputRole": "input_message_role",
            "streamMode": "stream_mode",
            "performanceGuidance": "performance_guidance_visible",
        }
        if key == "avatarMode":
            if not getattr(self, "avatarProviderChangeAllowed", True):
                selected = str(value or "none").strip().lower()
                current = str(self._application.config.get("avatar_mode", "none") or "none").strip().lower()
                if selected != current:
                    self.notificationRaised.emit(
                        "warning",
                        "Avatar provider is locked",
                        "Stop the chat engine before changing the avatar provider. You can still browse its settings.",
                    )
                return
            result = self._application.avatar.select_provider(str(value or "none"))
        elif key in config_keys:
            result = self._application.config.update(config_keys[key], value)
        else:
            return
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Session setting was not saved",
                str(getattr(result.failure, "message", "Could not update the session setting.")),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit(
                "error",
                "Session setting was not saved",
                str(error),
            )
            return
        self.sessionSetupChanged.emit()
        self.configurationChanged.emit()

    @QtCore.Slot(str)
    def viewVisualReplyProvider(self, provider_id: str) -> None:
        selected = str(provider_id or "").strip().lower()
        if not any(
            item.provider_id == selected for item in VISUAL_REPLY_PROVIDER_SPECS
        ):
            return
        if selected == str(self.visualReplySetup.get("provider") or ""):
            return
        self._viewed_visual_reply_provider = selected
        self.visualReplySetupChanged.emit()
        if selected == "comfyui":
            self.refreshComfyUIDetection()

    @QtCore.Slot(str)
    def selectVisualReplyProvider(self, provider_id: str) -> None:
        selected = str(provider_id or "").strip().lower()
        spec = next(
            (item for item in VISUAL_REPLY_PROVIDER_SPECS if item.provider_id == selected),
            None,
        )
        if spec is None:
            return
        config = dict(self._application.config.snapshot().values)
        settings = provider_settings_from_config(config)
        provider_settings = dict(settings.get(selected) or {})
        model = str(provider_settings.get(spec.model_setting_key) or spec.default_model)
        size_options = list(size_labels_for_provider(selected))
        size = str(provider_settings.get(spec.size_setting_key) or (size_options[0] if size_options else "auto"))
        updates = (
            ("visual_reply_provider", selected),
            ("visual_reply_model", model),
            ("visual_reply_size", size),
        )
        for key, value in updates:
            result = self._application.config.update(key, value)
            if not result.accepted:
                self.notificationRaised.emit(
                    "error",
                    "Visual provider was not changed",
                    str(getattr(result.failure, "message", "Could not save visual reply settings.")),
                )
                return
        self._viewed_visual_reply_provider = selected
        self._save_visual_reply_session()
        self.visualReplySetupChanged.emit()
        if selected == "comfyui":
            self.refreshComfyUIDetection()
        self.configurationChanged.emit()
        self.notificationRaised.emit("success", "Visual provider selected", spec.label)

    @QtCore.Slot(str, "QVariant")
    def setVisualReplyField(self, field_id: str, value: Any) -> None:
        key = str(field_id or "").strip()
        direct_keys = {
            "autoShow": "visual_reply_auto_show_dock",
            "storyMode": "visual_reply_story_mode",
        }
        if key == "mode":
            mode = "auto" if str(value or "off").strip().lower() != "off" else "off"
            config = dict(self._application.config.snapshot().values)
            policy = normalize_persona_visual_reply_policy(
                config.get("persona_visual_reply_policy", "inherit")
            )
            if mode == "off":
                policy = "off"
            elif policy in {"inherit", "off"}:
                policy = "requested"
            try:
                policy_result, _persona_owned, _saved_persona = (
                    self._update_persona_owned_setting(
                        "visual_reply_policy",
                        "persona_visual_reply_policy",
                        policy,
                    )
                )
            except (OSError, ValueError) as error:
                self.notificationRaised.emit(
                    "error", "Visual reply setting was not saved", str(error)
                )
                return
            if not policy_result.accepted:
                result = policy_result
            else:
                result = self._application.config.update_many(
                    {
                        "visual_reply_mode": mode,
                        "visual_replies_enabled": mode != "off",
                        "persona_visual_reply_policy": policy,
                    }
                )
        elif key in direct_keys:
            result = self._application.config.update(direct_keys[key], value)
        elif key in {
            "apiKey",
            "model",
            "size",
            "baseUrl",
            "imageToImageEnabled",
            "imageToImageModel",
            "imageToImageStrength",
            "promptingRules",
            "workflowFolder",
        }:
            if isinstance(value, str):
                value = value.strip()
            if value == "••••••••":
                return
            config = dict(self._application.config.snapshot().values)
            active_provider_id = str(
                config.get("visual_reply_provider") or "openai"
            ).strip().lower()
            provider_id = str(
                self._viewed_visual_reply_provider or active_provider_id
            ).strip().lower()
            spec = next(
                (item for item in VISUAL_REPLY_PROVIDER_SPECS if item.provider_id == provider_id),
                VISUAL_REPLY_PROVIDER_SPECS[0],
            )
            if key.startswith("imageToImage") and spec.provider_id not in {"runware", "xai"}:
                return
            if key == "promptingRules" and spec.provider_id != "comfyui":
                return
            if key == "workflowFolder" and spec.provider_id != "comfyui":
                return
            if key == "imageToImageStrength" and spec.provider_id != "runware":
                return
            if key == "imageToImageEnabled":
                value = bool(value)
            elif key == "promptingRules":
                value = normalize_comfyui_rules(value)
            elif key == "workflowFolder":
                folder_url = QtCore.QUrl(str(value))
                folder = folder_url.toLocalFile() if folder_url.isLocalFile() else str(value)
                if not Path(folder).is_absolute():
                    self.notificationRaised.emit("error", "Workflow folder was not saved", "Choose a local workflow folder.")
                    return
                value = str(Path(folder))
            elif key == "imageToImageStrength":
                try:
                    value = max(0.0, min(1.0, float(value)))
                except (TypeError, ValueError):
                    return
            elif key == "imageToImageModel":
                default_model = (
                    XAI_DEFAULT_IMAGE_TO_IMAGE_MODEL
                    if spec.provider_id == "xai"
                    else RUNWARE_DEFAULT_IMAGE_TO_IMAGE_MODEL
                )
                value = str(value or default_model).strip() or default_model
            setting_key = {
                "apiKey": spec.api_key_setting_key,
                "model": spec.model_setting_key,
                "size": spec.size_setting_key,
                "baseUrl": spec.base_url_setting_key,
                "imageToImageEnabled": "image_to_image_enabled",
                "imageToImageModel": "image_to_image_model",
                "imageToImageStrength": "image_to_image_strength",
                "promptingRules": "prompting_rules",
                "workflowFolder": "workflow_folder",
            }[key]
            settings = provider_settings_from_config(config)
            provider_settings = dict(settings.get(spec.provider_id) or {})
            provider_settings[setting_key] = value
            settings[spec.provider_id] = provider_settings
            result = self._application.config.update("visual_reply_provider_settings", settings)
            if (
                result.accepted
                and key in {"model", "size"}
                and spec.provider_id == active_provider_id
            ):
                legacy_key = "visual_reply_model" if key == "model" else "visual_reply_size"
                self._application.config.update(legacy_key, value)
        else:
            return
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Visual reply setting was not saved",
                str(getattr(result.failure, "message", "Could not save visual reply settings.")),
            )
            return
        self._save_visual_reply_session()
        self.visualReplySetupChanged.emit()
        if key in {"model", "baseUrl"} and self.visualReplySetup.get("provider") == "comfyui":
            self.refreshComfyUIDetection()
        if key in {"mode", "autoShow"}:
            self.personaChanged.emit()
        self.configurationChanged.emit()

    @QtCore.Slot(str, "QVariant")
    def setCoreSetting(self, key: str, value: Any) -> None:
        config_key = str(key or "").strip()
        if config_key not in self._CORE_EDITABLE_KEYS:
            return
        persona_owned = False
        try:
            if config_key == "chat_visual_batch_size":
                parsed = int(str(value).strip())
                if parsed != -1 and not 0 < parsed <= 2147483647:
                    raise ValueError("Use a positive visual batch size, or -1 to show all messages.")
                value = parsed
            if config_key in {"system_prompt", "emotional_instructions"}:
                result, persona_owned, _record = (
                    self._update_persona_owned_setting(
                        config_key,
                        config_key,
                        value,
                    )
                )
            elif config_key in {"continuity_memory_auto_summarize", "continuity_memory_update_on_save"}:
                # The old UI exposed one toggle with a compatibility alias.
                result = self._application.config.update_many({
                    "continuity_memory_auto_summarize": bool(value),
                    "continuity_memory_update_on_save": bool(value),
                })
            elif config_key == "continuity_memory_enabled" and bool(value):
                result = self._application.config.update_many({
                    "continuity_memory_enabled": True,
                    "continuity_memory_auto_summarize": True,
                    "continuity_memory_update_on_save": True,
                })
            else:
                result = self._application.config.update(config_key, value)
        except (OSError, ValueError) as error:
            self.notificationRaised.emit("error", "Setting was not saved", str(error))
            return
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Setting was not saved",
                str(getattr(result.failure, "message", f"Could not update {config_key}.")),
            )
            return
        fallback_recorder = getattr(self, "_remember_quick_persona_fallbacks", None)
        if (
            not persona_owned
            and config_key in {"system_prompt", "emotional_instructions"}
            and callable(fallback_recorder)
        ):
            fallback_recorder((config_key,))
        if not persona_owned:
            self._session_store.save()
        if config_key == "chat_visual_batch_size":
            self._conversation_revision = -1
            self.refreshConversationState()
        self.coreSettingsChanged.emit()
        self.configurationChanged.emit()

    @staticmethod
    def _normalized_speech_timing_value(key: str, value: Any) -> int | float:
        spec = UI_SHELL_CHUNKING_SPECS[key]
        minimum = float(spec.get("minimum", 0))
        maximum = float(spec.get("maximum", minimum))
        numeric = max(minimum, min(maximum, float(value)))
        if bool(spec.get("is_int", True)):
            return int(round(numeric))
        return round(numeric, 2)

    def _save_native_session(self) -> None:
        self._session_store.save()

    def _save_native_session_or_raise(self) -> None:
        if self._session_store.save():
            return
        raise RuntimeError("Could not save the session setting.")

    def _save_visual_reply_session(self) -> None:
        """Persist QML Visual Reply changes through the native session store."""

        self._save_native_session()

    def _update_persona_owned_setting(
        self,
        field_name: str,
        config_key: str,
        value: Any,
    ) -> tuple[Any, bool, Mapping[str, Any] | None]:
        builder = getattr(self, "_prompt_builder", None)
        if field_name == "system_prompt" and builder is not None and builder.applying:
            raise ValueError("Wait for Apply to Persona to finish saving before replacing its prompt.")
        active = self._quick_personas.active_persona(strict=True)
        if active is None:
            if field_name == "system_prompt":
                return self._application.config.update_many({config_key: value, "persona_prompt_type": ""}), False, None
            return self._application.config.update(config_key, value), False, None
        updates = {field_name: value}
        if field_name == "system_prompt":
            updates["persona_prompt_type"] = ""
        record = self._quick_personas.save_persona(
            int(active.get("slot", -1)),
            updates,
            strict=True,
        )
        result = (self._application.config.update_many({config_key: record.get(field_name), "persona_prompt_type": ""})
                  if field_name == "system_prompt"
                  else self._application.config.update(config_key, record.get(field_name)))
        return result, True, record

    @QtCore.Slot(str, "QVariant")
    def setSpeechTimingSetting(self, key: str, value: Any) -> None:
        config_key = str(key or "").strip()
        if config_key not in UI_SHELL_CHUNKING_SPECS:
            return
        try:
            normalized = self._normalized_speech_timing_value(config_key, value)
        except (TypeError, ValueError):
            self.notificationRaised.emit(
                "error",
                "Speech timing was not saved",
                f"{config_key} requires a numeric value.",
            )
            return
        current = self._application.config.get(config_key)
        if current == normalized:
            return
        result = self._application.config.update(config_key, normalized)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Speech timing was not saved",
                str(getattr(result.failure, "message", f"Could not update {config_key}.")),
            )
            return
        self._save_native_session()
        self.speechTimingSettingsChanged.emit()
        self.configurationChanged.emit()

    @QtCore.Slot()
    def resetSpeechTimingDefaults(self) -> None:
        defaults = {
            key: self._normalized_speech_timing_value(key, value)
            for key, value in UI_SHELL_DEFAULT_CHUNKING_VALUES.items()
            if key in UI_SHELL_CHUNKING_SPECS
        }
        result = self._application.config.update_many(defaults)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Speech timing defaults were not restored",
                str(getattr(result.failure, "message", "Could not reset speech timing.")),
            )
            return
        self._save_native_session()
        self.speechTimingSettingsChanged.emit()
        self.configurationChanged.emit()
        self.notificationRaised.emit(
            "success",
            "Speech timing restored",
            "The original NeuralCompanion chunking defaults are active.",
        )

    @QtCore.Slot(str)
    def applyTheme(self, theme_id: str) -> None:
        selected = str(theme_id or "").strip().lower()
        if selected not in {"dark_gray", "forest", "midnight"}:
            return
        try:
            result = self._application.config.update("ui_theme_preset", selected)
            if not result.accepted:
                raise RuntimeError(
                    str(getattr(result.failure, "message", "Could not save the theme."))
                )
            self._session_store.save()
            applied = selected
        except Exception as error:
            self.notificationRaised.emit("error", "Theme was not applied", str(error))
            return
        self.themeChanged.emit()
        self.configurationChanged.emit()
        self.notificationRaised.emit(
            "success",
            "Appearance updated",
            applied.replace("_", " ").title(),
        )

    @QtCore.Slot(str, "QVariant")
    def setSelectedAddonSetting(self, key: str, value: Any) -> None:
        payload = dict(self._addon_settings_by_workspace.get(self._selected_addon) or {})
        defaults = dict(payload.get("defaults") or {})
        config_key = str(key or "").strip()
        if config_key not in defaults:
            return
        default_value = defaults[config_key]
        if isinstance(default_value, (dict, list)):
            try:
                value = json.loads(str(value or ""))
            except json.JSONDecodeError as error:
                self.notificationRaised.emit(
                    "error",
                    "JSON setting was not saved",
                    f"{config_key}: {error.msg} at line {error.lineno}, column {error.colno}.",
                )
                return
            if not isinstance(value, type(default_value)):
                self.notificationRaised.emit(
                    "error",
                    "JSON setting was not saved",
                    f"{config_key} must remain a {type(default_value).__name__}.",
                )
                return
        elif isinstance(default_value, bool):
            value = bool(value)
        elif isinstance(default_value, int) and not isinstance(default_value, bool):
            try:
                value = int(value)
            except (TypeError, ValueError):
                return
        elif isinstance(default_value, float):
            try:
                value = float(value)
            except (TypeError, ValueError):
                return
        elif str(value or "") == "••••••••":
            return
        result = self._application.config.update(config_key, value)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Addon setting was not saved",
                str(getattr(result.failure, "message", f"Could not update {config_key}.")),
            )
            return
        self._session_store.save()
        self.addonSettingsChanged.emit()
        self.configurationChanged.emit()

    @QtCore.Slot(str, bool)
    def setAddonEnabled(self, addon_id: str, enabled: bool) -> None:
        selected = str(addon_id or "").strip()
        if not selected:
            return
        result = self._application.addons.set_addon_enabled(selected, bool(enabled))
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Addon selection was not saved",
                str(getattr(result.failure, "message", "Could not update the addon registry.")),
            )
            return
        self._session_store.save()
        self.refreshAddonState()
        self.notificationRaised.emit(
            "warning",
            "Addon selection saved",
            "Restart NeuralCompanion to apply addon enable/disable changes.",
        )

    @QtCore.Slot(str, bool)
    def setAddonCategoryEnabled(self, category_id: str, enabled: bool) -> None:
        selected = str(category_id or "").strip()
        if not selected:
            return
        result = self._application.addons.set_category_enabled(selected, bool(enabled))
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Addon category was not saved",
                str(getattr(result.failure, "message", "Could not update the addon registry.")),
            )
            return
        self._session_store.save()
        self.refreshAddonState()
        self.notificationRaised.emit(
            "warning",
            "Addon category selection saved",
            "Restart NeuralCompanion to apply addon enable/disable changes.",
        )

    @QtCore.Slot(str, bool)
    def setAddonContributionEnabled(self, workspace_id: str, enabled: bool) -> None:
        selected_id = str(workspace_id or "").strip()
        selected = next(
            (
                item
                for item in self._addon_workspaces
                if str(item.get("id") or "") == selected_id
            ),
            None,
        )
        if not selected or not bool(selected.get("contributionCheckable")):
            return
        addon_id = str(selected.get("addonId") or "").strip()
        result = self._application.addons.invoke_addon_capability(
            addon_id,
            "ui.tab_enabled",
            {
                "addon_id": addon_id,
                "tab_id": selected_id,
                "action": "set",
                "enabled": bool(enabled),
            },
        )
        if not result.accepted or not isinstance(result.value, Mapping):
            self.notificationRaised.emit(
                "error",
                "Addon contribution was not changed",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "The addon did not accept the contribution state.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.refreshAddonState()
        self.notificationRaised.emit(
            "success",
            "Vision contribution updated",
            "Enabled" if enabled else "Disabled",
        )

    @QtCore.Property(QtCore.QObject, constant=True)
    def roomConversation(self):
        return self._room_conversation

    def _room_conversation_snapshot(self):
        adapter = self._native_surfaces.adapter('discord_voice_bridge_tab')
        if adapter is None:
            return {}
        controls = adapter.snapshot().to_qml_controls()
        return next((dict(row.get('roomState') or {}) for row in controls
                     if row.get('id') == 'discord_local_room_state'), {})

    def _dispatch_room_conversation_action(self, control_id, payload=None):
        if getattr(self, '_application_closing', False) or getattr(self, '_closing', False):
            return False
        return self._native_surfaces.trigger_async('discord_voice_bridge_tab', str(control_id), payload)

    def _reset_main_for_room(self):
        # The Save/Don't Save guard has already accepted this replacement.
        # Saved files remain on disk; room messages never enter main history.
        self._resetConversationNow()
        return not bool(self._application.chat.history())

    def _show_room_conversation_workspace(self):
        self.setMainTabVisible('conversation', True)
        self.activateMainWorkspace('conversation')
        self.openWorkspace('conversation')

    def _show_local_room_controls(self):
        self.setMainTabVisible('addons', True)
        self.openAddonWorkspaceSection('discord_voice_bridge_tab', 'Local room')
        QtCore.QTimer.singleShot(0, self.localRoomControlsRequested.emit)

    @QtCore.Slot()
    def openLocalRoomConversation(self):
        self._room_conversation.showRoom()

    def _room_blocks_main_chat(self):
        room = getattr(self, '_room_conversation', None)
        return bool(room is not None and room.blocks_main_start())

    @QtCore.Slot()
    def refreshLiveAddonControls(self) -> None:
        native_adapter = self._native_surface_adapter()
        if native_adapter is not None:
            try:
                self._live_addon_controls = native_adapter.snapshot().to_qml_controls()
                if native_adapter.addon_id == "nc.companion_orb_overlay":
                    self._live_addon_controls = [
                        control for control in self._live_addon_controls
                        if control.get("section") not in {"Awareness", "Vision & Actions"}
                    ]
                if native_adapter.addon_id == "nc.spotify_sense":
                    self._live_addon_controls = [
                        control for control in self._live_addon_controls
                        if control.get("section") not in {"Awareness", "Hidden Sense"}
                    ]
            except (KeyError, RuntimeError, TypeError, ValueError) as error:
                self._live_addon_controls = []
                self.notificationRaised.emit(
                    "error",
                    "Native addon surface could not be refreshed",
                    str(error),
                )
            self.liveAddonControlsChanged.emit()
            return
        self._live_addon_controls = []
        self.liveAddonControlsChanged.emit()

    @QtCore.Slot(result='QVariantList')
    def companionOrbWatchRows(self):
        adapter=self._native_surfaces.adapter('companion_orb_overlay_tab')
        reader=getattr(adapter,'watch_rows',None)
        try:
            return reader() if callable(reader) else []
        except (KeyError,RuntimeError,TypeError,ValueError):
            return []

    @QtCore.Property(str, notify=orbWatchDraftChanged)
    def orbWatchDraft(self):
        return getattr(self, '_orb_watch_draft', '')

    @QtCore.Slot(str)
    def setOrbWatchDraft(self, text):
        self._orb_watch_draft = str(text or '')
        self.orbWatchDraftChanged.emit()

    @QtCore.Slot(result='QVariantMap')
    def companionOrbWatchSetup(self):
        adapter = self._native_surfaces.adapter('companion_orb_overlay_tab')
        try:
            if adapter is not None:
                return adapter.watch_setup_snapshot(self.systemRunning)
        except (KeyError, RuntimeError, TypeError, ValueError):
            pass
        return dict(state='Setup needed', action='addon', ready=False,
                    reasons=['Enable the Companion Orb addon, then restart NeuralCompanion.'])

    @QtCore.Slot(str)
    def applyOrbWatchSetup(self, confirmation_key):
        adapter = self._native_surfaces.adapter('companion_orb_overlay_tab')
        try:
            if adapter is None:
                raise ValueError('Enable the Orb addon and restart first.')
            adapter.apply_watch_setup(confirmation_key, self.systemRunning)
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit('warning', 'Watching setup needs review', str(error))

    @QtCore.Slot(str, result=bool)
    def submitOrbWatchRequest(self, text):
        message = str(text or '').strip()
        # Clearing the accepted draft makes repeated Enter/click events idempotent.
        if (not message or message != getattr(self, '_orb_watch_draft', '').strip()
                or getattr(self, '_orb_watch_submitting', False)):
            return False
        if not self.companionOrbWatchSetup().get('ready'):
            self.notificationRaised.emit('warning', 'Watching setup needed', 'Review the current capture target and setup before sending.')
            return False
        self._orb_watch_submitting = True
        try:
            accepted = self._queue_text_message(message)
            if accepted:
                self._orb_watch_draft = ''
                self.orbWatchDraftChanged.emit()
            return accepted
        finally:
            self._orb_watch_submitting = False

    @QtCore.Slot(str)
    def setOrbCaptureScope(self, mode):
        adapter = self._native_surfaces.adapter('companion_orb_overlay_tab')
        try:
            if adapter is not None:
                adapter.set_value('companion_orb_capture_scope_combo', mode)
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit('warning', 'Capture target not changed', str(error))

    @QtCore.Slot(str, 'QVariantMap')
    def triggerOrbWatchAction(self, control_id, payload):
        allowed = {'companion_orb_show_button', 'companion_orb_watch_stop', 'companion_orb_watch_open_capture'}
        if control_id not in allowed:
            return
        adapter = self._native_surfaces.adapter('companion_orb_overlay_tab')
        try:
            if adapter is not None:
                adapter.trigger_with_payload(control_id, dict(payload or {}))
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit('warning', 'Orb action needs attention', str(error))

    @QtCore.Slot(result='QVariantList')
    def companionOrbWatchControls(self):
        """Refresh watch-only presentation without replacing editable settings."""
        adapter = self._native_surfaces.adapter('companion_orb_overlay_tab')
        if adapter is None:
            return []
        try:
            return [control.to_qml("companion_orb_overlay_tab") for control in adapter.snapshot().controls
                    if control.id.startswith('companion_orb_watch_')
                    and control.id != 'companion_orb_watch_setup_apply']
        except (KeyError, RuntimeError, TypeError, ValueError):
            return []

    @QtCore.Slot(str)
    def _on_native_surface_changed(self, surface_id: str) -> None:
        self.refreshLiveAddonControls()
        if str(surface_id or "").strip() == "web_intelligence_tab":
            self.configurationChanged.emit()
        if (str(surface_id or "").strip() == "companion_orb_overlay_tab"
                and self._runtime_provider_settings.get("kind") == "vision"
                and self._runtime_provider_settings.get("providerId") == "companion_orb_target"):
            self.refreshRuntimeProviderSettings()
        if (str(surface_id or "").strip() == "webcam_source_tab"
                and self._runtime_provider_settings.get("kind") == "vision"
                and self._runtime_provider_settings.get("providerId") == "webcam"):
            self.refreshRuntimeProviderSettings()
        if (str(surface_id or "").strip() in {"musetalk_preprocess_tab", "musetalk_avatar_tab"}
                and self._runtime_provider_settings.get("kind") == "avatar"
                and self._runtime_provider_settings.get("providerId") == "musetalk"):
            self.refreshRuntimeProviderSettings()
        if (str(surface_id or "").strip() in {"ditto_preprocess_tab", "ditto_avatar_tab"}
                and self._runtime_provider_settings.get("kind") == "avatar"
                and self._runtime_provider_settings.get("providerId") == "ditto"):
            self.refreshRuntimeProviderSettings()
        if str(surface_id or "").strip() == "rag_context_tab":
            self.documentMemoryChanged.emit()
        if str(surface_id or "").strip() != "user_identity_tab":
            return
        self._conversation_revision = -1
        self._refresh_conversation_if_visible()
        adapter = self._native_surfaces.adapter("user_identity_tab")
        pending = bool(
            adapter is not None
            and callable(getattr(adapter, "generation_pending", None))
            and adapter.generation_pending()
        )
        if pending:
            self._user_identity_avatar_timer.start()
        else:
            self._user_identity_avatar_timer.stop()

    def _native_surface_adapter(self):
        adapter = self._native_surfaces.adapter(self._selected_addon)
        if adapter is not None:
            return adapter
        selected = next(
            (
                item
                for item in self._addon_workspaces
                if str(item.get("id") or "") == self._selected_addon
            ),
            None,
        )
        addon_id = str((selected or {}).get("addonId") or "").strip()
        return self._native_surfaces.adapter_for_addon(addon_id)

    @QtCore.Slot(str, "QVariant")
    def setLiveAddonControl(self, control_id: str, value: Any) -> None:
        normalized_id = str(control_id or "")
        if "::" in normalized_id:
            surface_id, normalized_id = normalized_id.split("::", 1)
            native_adapter = self._native_surfaces.adapter(surface_id)
        else:
            native_adapter = self._native_surface_adapter()
        if native_adapter is not None:
            try:
                native_adapter.set_value(normalized_id, value)
            except (KeyError, RuntimeError, TypeError, ValueError) as error:
                self.notificationRaised.emit(
                    "error", "Addon setting was not changed", str(error)
                )
        return

    @QtCore.Slot(str, "QVariant")
    def previewLiveAddonControl(self, control_id: str, value: Any) -> None:
        native_adapter = self._native_surface_adapter()
        preview_value = getattr(native_adapter, "preview_value", None)
        if not callable(preview_value):
            return
        try:
            preview_value(str(control_id or ""), value)
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit(
                "error", "Addon setting preview failed", str(error)
            )

    @QtCore.Slot(str, "QVariant")
    def setRuntimeProviderControl(self, control_id: str, value: Any) -> None:
        normalized_id = str(control_id or "")
        if normalized_id.startswith("stt:"):
            if str(self._runtime_provider_settings.get("kind") or "") != "stt":
                return
            backend_id = str(
                self._runtime_provider_settings.get("providerId") or ""
            ).strip().lower()
            if not backend_id or backend_id in {"none", "disabled"}:
                return
            if str(self._runtime_operation or "").strip().lower() == "stt":
                self.notificationRaised.emit(
                    "warning",
                    "Runtime change is busy",
                    "Wait for the current runtime operation to finish and try again.",
                )
                return
            settings_map = self._application.config.get(
                "stt_backend_settings", {}
            ) or {}
            settings_map = dict(settings_map) if isinstance(settings_map, Mapping) else {}
            previous_settings_map = _plain(settings_map)
            active_backend = str(self.selectedSpeechInputBackend or "").strip().lower()
            current_config = {
                "stt_backend": active_backend,
                "stt_model_size": self._application.config.get("stt_model_size", "tiny.en"),
                "stt_language": self._application.config.get("stt_language", "en"),
                "stt_backend_settings": settings_map,
            }
            # Preserve any unscoped active-provider legacy settings before an
            # edit to a different provider (including partially migrated maps).
            if (active_backend not in {"", "none", "disabled", backend_id}
                    and not isinstance(settings_map.get(active_backend), Mapping)):
                settings_map[active_backend] = {
                    "model_size": current_config["stt_model_size"],
                    "language": current_config["stt_language"],
                }
            effective = stt_backend_runtime_config(current_config, backend_id=backend_id)
            backend_settings = dict(settings_map.get(backend_id) or {})
            backend_settings.setdefault("model_size", effective["stt_model_size"])
            backend_settings.setdefault("language", effective["stt_language"])
            updates: dict[str, Any] = {}
            rollback: dict[str, Any] = {
                "stt_backend_settings": previous_settings_map,
            }
            if normalized_id == "stt:model_size":
                model = str(value or "").strip()
                if model not in WHISPER_MODEL_SIZE_OPTIONS:
                    return
                backend_settings["model_size"] = model
                if backend_id == active_backend:
                    updates["stt_model_size"] = model
                    rollback["stt_model_size"] = self._application.config.get(
                        "stt_model_size", "tiny.en"
                    )
            elif normalized_id == "stt:language":
                language = normalize_whisper_language(value) or ""
                valid_languages = {str(code or "") for _label, code in WHISPER_LANGUAGE_OPTIONS}
                if language not in valid_languages:
                    return
                backend_settings["language"] = language
                if backend_id == active_backend:
                    updates["stt_language"] = language
                    rollback["stt_language"] = self._application.config.get(
                        "stt_language", "en"
                    )
            else:
                return
            settings_map[backend_id] = backend_settings
            updates["stt_backend_settings"] = settings_map
            result = self._application.config.update_many(updates)
            if not result.accepted:
                self.notificationRaised.emit(
                    "error",
                    "Speech input setting was not saved",
                    str(
                        getattr(
                            result.failure,
                            "message",
                            "Could not update the speech input provider.",
                        )
                    ),
                )
                return
            should_save = True
            if backend_id == active_backend:
                if not self.systemRunning:
                    self.notificationRaised.emit(
                        "success",
                        "Speech input setting saved",
                        "The selected recognition model will load when NeuralCompanion initializes.",
                    )
                elif self._runtime_operation:
                    self._application.config.update_many(rollback)
                    self.configurationChanged.emit()
                    self.notificationRaised.emit(
                        "warning",
                        "Runtime change is busy",
                        "Wait for the current runtime operation to finish and try again.",
                    )
                    should_save = False
                else:
                    label = str(
                        updates.get("stt_model_size")
                        or updates.get("stt_language")
                        or backend_id
                    )
                    self._schedule_runtime_reinitialization(
                        "stt",
                        f"{backend_id} \u00b7 {label}",
                        rollback=rollback,
                    )
                    should_save = False
            if should_save:
                try:
                    self._save_native_session_or_raise()
                except (OSError, RuntimeError, TypeError, ValueError) as error:
                    self.notificationRaised.emit(
                        "error",
                        "Speech input setting was not saved",
                        str(error),
                    )
                    return
            self.configurationChanged.emit()
            QtCore.QTimer.singleShot(0, self.refreshRuntimeProviderSettings)
            return
        if "::" in normalized_id:
            surface_id, native_control_id = normalized_id.split("::", 1)
            native_adapter = self._native_surfaces.adapter(surface_id)
            if native_adapter is not None:
                try:
                    native_adapter.set_value(native_control_id, value)
                except (KeyError, RuntimeError, TypeError, ValueError) as error:
                    self.notificationRaised.emit(
                        "error", "Provider setting was not changed", str(error)
                    )
                QtCore.QTimer.singleShot(0, self.refreshRuntimeProviderSettings)
                return
        return

    @QtCore.Slot(str)
    def triggerLiveAddonAction(self, control_id: str) -> None:
        self._trigger_live_addon_action(control_id, None)

    @QtCore.Slot(str, "QVariant")
    def triggerLiveAddonActionWithPayload(
        self,
        control_id: str,
        payload: Any,
    ) -> None:
        self._trigger_live_addon_action(control_id, _plain(payload))

    def _trigger_live_addon_action(self, control_id: str, payload: Any) -> None:
        native_adapter = self._native_surface_adapter()
        if native_adapter is not None:
            room = getattr(self, '_room_conversation', None)
            if (room is not None and native_adapter.surface_id == 'discord_voice_bridge_tab'
                    and str(control_id) in {'discord_local_room_start', 'discord_local_room_new_conversation'}):
                room.request_start(str(control_id), payload)
                return
            try:
                accepted = self._native_surfaces.trigger_async(
                    native_adapter.surface_id,
                    str(control_id or ""),
                    payload,
                )
                if not accepted:
                    self.notificationRaised.emit(
                        "info",
                        "Addon action is already running",
                        str(control_id or ""),
                    )
            except (KeyError, RuntimeError, TypeError, ValueError) as error:
                self.notificationRaised.emit(
                    "error", "Addon action was not run", str(error)
                )
        return

    @QtCore.Slot(str)
    def triggerRuntimeProviderAction(self, control_id: str) -> None:
        self._trigger_runtime_provider_action(control_id, None)

    @QtCore.Slot(str, "QVariant")
    def triggerRuntimeProviderActionWithPayload(
        self,
        control_id: str,
        payload: Any,
    ) -> None:
        self._trigger_runtime_provider_action(control_id, _plain(payload))

    def _trigger_runtime_provider_action(self, control_id: str, payload: Any) -> None:
        normalized_id = str(control_id or "")
        if "::" in normalized_id:
            surface_id, native_control_id = normalized_id.split("::", 1)
            native_adapter = self._native_surfaces.adapter(surface_id)
            if native_adapter is not None:
                if surface_id == "rag_context_tab" and native_control_id != "rag_context_command":
                    document = native_adapter.document_snapshot()
                    payload = dict(payload) if isinstance(payload, dict) else ({"paths": payload} if native_control_id == "rag_context_add_files" else {})
                    payload.setdefault("_expected_package_id", document.get("activePackageId"))
                    payload.setdefault("_expected_activation_revision", document.get("revision"))
                try:
                    accepted = self._native_surfaces.trigger_async(
                        native_adapter.surface_id,
                        native_control_id,
                        payload,
                    )
                    if not accepted:
                        self.notificationRaised.emit(
                            "info",
                            "Provider action is already running",
                            native_control_id,
                        )
                except (KeyError, RuntimeError, TypeError, ValueError) as error:
                    self.notificationRaised.emit(
                        "error", "Provider action was not run", str(error)
                    )
                QtCore.QTimer.singleShot(0, self.refreshRuntimeProviderSettings)
                return
        return

    @QtCore.Slot(str, str, bool, str)
    def _on_native_action_completed(
        self,
        surface_id: str,
        control_id: str,
        accepted: bool,
        error: str,
    ) -> None:
        room = getattr(self, '_room_conversation', None)
        if room is not None and surface_id == 'discord_voice_bridge_tab':
            room.actionCompleted(control_id, accepted, error)
        if accepted and surface_id == "scenic_pack_creator_tab":
            creator = self._native_surfaces.adapter("scenic_pack_creator_tab")
            provider = self._native_surfaces.adapter("scenic_avatar_tab")
            if creator is not None and provider is not None:
                provider.adopt_catalog(creator.pack_catalog())
            self.configurationChanged.emit()
        if not accepted:
            self.notificationRaised.emit(
                "error",
                "Addon action failed",
                str(error or f"{surface_id}: {control_id}"),
            )
        self.refreshLiveAddonControls()
        self.refreshRuntimeProviderSettings()
        if surface_id == "rag_context_tab":
            self.documentMemoryChanged.emit()

    @QtCore.Slot(str, "QVariant")
    def setPersonaField(self, field_id: str, value: Any) -> None:
        key = str(field_id or "").strip()
        visual_reply_changed = False
        visual_identity_changed = False
        persona_owned = False
        persona_record_fields = {
            "visualIdentityPrompt": "visual_identity_prompt",
            "portraitPrompt": "portrait_prompt",
            "selfImageMode": "self_image_mode",
            "appearanceFreedom": "appearance_freedom",
            "visualReferenceStrength": "visual_reference_strength",
            "moodReferenceEnabled": "mood_reference_enabled",
            "portraitTransparencyEnabled": "portrait_transparency_enabled",
        }
        if key in persona_record_fields:
            active = self._quick_personas.active_persona()
            if active is None:
                self.notificationRaised.emit(
                    "warning",
                    "Save a quick persona first",
                    "Visual identity settings belong to the active quick persona.",
                )
                return
            field_name = persona_record_fields[key]
            normalized: Any = value
            if key == "selfImageMode":
                normalized = normalize_persona_self_image_mode(value)
            elif key == "appearanceFreedom":
                normalized = normalize_persona_appearance_freedom(value)
            elif key == "visualReferenceStrength":
                try:
                    normalized = max(0.0, min(1.0, float(value)))
                except (TypeError, ValueError):
                    normalized = 0.75
            elif key in {"moodReferenceEnabled", "portraitTransparencyEnabled"}:
                normalized = bool(value)
            else:
                normalized = str(value or "").strip()
            try:
                record = self._quick_personas.save_persona(
                    int(active.get("slot", -1)),
                    {field_name: normalized},
                )
            except (OSError, ValueError) as error:
                self.notificationRaised.emit(
                    "error", "Persona setting was not saved", str(error)
                )
                return
            result = self._application.config.update_many(
                self._persona_runtime_updates(record)
            )
            visual_identity_changed = True
            if key == "appearanceFreedom":
                persona_owned = True
        elif key == "visualReplyPolicy":
            try:
                result, persona_owned, saved_record = (
                    self._update_persona_owned_setting(
                        "visual_reply_policy",
                        "persona_visual_reply_policy",
                        normalize_persona_visual_reply_policy(value),
                    )
                )
            except (OSError, ValueError) as error:
                self.notificationRaised.emit(
                    "error", "Persona setting was not saved", str(error)
                )
                return
            if result.accepted:
                saved_policy = normalize_persona_visual_reply_policy(
                    dict(saved_record or {}).get(
                        "visual_reply_policy",
                        value,
                    )
                )
                if saved_policy == "inherit":
                    updates = dict(getattr(self, "_quick_persona_fallbacks", {}))
                    updates = {
                        name: updates[name]
                        for name in (
                            "persona_visual_reply_policy",
                            "visual_reply_mode",
                            "visual_replies_enabled",
                        )
                        if name in updates
                    }
                else:
                    updates = {
                        "persona_visual_reply_policy": saved_policy,
                        "visual_reply_mode": (
                            "off" if saved_policy == "off" else "auto"
                        ),
                        "visual_replies_enabled": saved_policy != "off",
                    }
                if updates:
                    result = self._application.config.update_many(updates)
            visual_reply_changed = True
        elif key == "visualReplyAutoShow":
            result = self._application.config.update(
                "visual_reply_auto_show_dock",
                bool(value),
            )
            visual_reply_changed = True
        else:
            result = None
        config_keys = {
            "systemPrompt": "system_prompt",
            "emotionalInstructions": "emotional_instructions",
            "voicePath": "voice_path",
            "useClonedVoice": "tts_use_cloned_voice",
        }
        if result is None:
            config_key = config_keys.get(key)
            if config_key is None:
                return
            try:
                if key in {"systemPrompt", "emotionalInstructions"}:
                    result, persona_owned, _record = (
                        self._update_persona_owned_setting(
                            config_key,
                            config_key,
                            value,
                        )
                    )
                else:
                    result = self._application.config.update(config_key, value)
            except (OSError, ValueError) as error:
                self.notificationRaised.emit(
                    "error", "Persona setting was not saved", str(error)
                )
                return
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Persona setting was not saved",
                str(getattr(result.failure, "message", "Could not update the persona.")),
            )
            return
        fallback_recorder = getattr(self, "_remember_quick_persona_fallbacks", None)
        if callable(fallback_recorder) and not persona_owned:
            if key in {"visualReplyPolicy", "visualReplyAutoShow"}:
                fallback_recorder(
                    (
                        "persona_visual_reply_policy",
                        "visual_reply_mode",
                        "visual_replies_enabled",
                        "visual_reply_auto_show_dock",
                    )
                )
            elif key in config_keys:
                fallback_recorder(
                    {
                        "systemPrompt": ("system_prompt",),
                        "emotionalInstructions": ("emotional_instructions",),
                        "voicePath": ("voice_path",),
                        "useClonedVoice": ("tts_use_cloned_voice",),
                    }[key]
                )
        if not persona_owned:
            self._save_native_session()
        if visual_identity_changed:
            self.quickPersonaChanged.emit()
        self.personaChanged.emit()
        self.coreSettingsChanged.emit()
        if visual_reply_changed:
            self.visualReplySetupChanged.emit()
        self.configurationChanged.emit()

    @QtCore.Slot(str)
    def setConversationVoiceReference(self, voice_path: str) -> None:
        """Switch the conversation voice without replacing the active persona."""
        self._set_conversation_voice_reference(voice_path)

    def _remote_voice_state(self) -> dict[str, Any]:
        """Scan the existing voice library off Qt's thread; keep paths internal."""
        selected = str(self._application.config.get("voice_path", "") or "")
        if not self._application.config.get("tts_use_cloned_voice", True):
            selected = ""
        future = getattr(self, "_remote_voice_future", None)
        if future is not None and future.done():
            try:
                self._remote_voice_items = future.result()
                self._remote_voice_failed = False
            except Exception:
                self._remote_voice_failed = True
            self._remote_voice_future = future = None
            self._remote_voice_scanned_at = time.monotonic()
        if future is None and not self._closing and (
            time.monotonic() - getattr(self, "_remote_voice_scanned_at", 0.0) > 5.0
        ):
            self._remote_voice_future = future = self._executor.submit(
                _voice_reference_options, _APP_ROOT, selected,
            )
        return {
            "available": not self._closing and not getattr(self, "_remote_voice_failed", False),
            "loading": future is not None,
            "selected": selected,
            "items": list(getattr(self, "_remote_voice_items", [])),
        }

    def _remote_apply_voice(self, voice_path: str) -> dict[str, Any]:
        state = self._remote_voice_state()
        allowed = state["available"] and any(item["value"] == voice_path for item in state["items"])
        return {"accepted": bool(allowed and self._set_conversation_voice_reference(voice_path))}

    def _remote_tts_change_busy(self) -> bool:
        """Read existing owners; never interrupt a turn to change its provider."""
        if self._closing or self._runtime_operation or any(bool(getattr(self, name, False)) for name in (
            "runtimeStarting", "runtimeInitializing", "runtimeStopping", "runtimeCancelling", "runtimeCleanupPending",
        )):
            return True
        try:
            status = self._application.status.snapshot()
            playback = self._application.playback.snapshot()
            return bool(
                status.interaction_pending
                or self._application.chat.has_active_turns()
                or getattr(status.activity, "paused", False)
                or playback.current is not None
                or playback.paused
                or self._application.replay.has_active_replay()
            )
        except Exception:
            # A missing ownership snapshot is not permission to replace TTS.
            return True

    def _remote_tts_provider_state(self) -> dict[str, Any]:
        """Small display catalog, without provider settings or local paths."""
        selected = str(self._application.config.get("tts_backend", "none") or "none").strip().lower()
        loading = self._runtime_operation == "tts"
        failed = bool(getattr(self, "_remote_tts_provider_failed", False))
        providers = []
        # These are the voice-reference backends supported by story routing.
        reference_backends = {"chatterbox", "chatterbox_multilingual", "pockettts", "pockettts_multilingual"}
        for item in self._speech_output_backends:
            backend = str(item.get("id") or "").strip().lower()
            if not backend:
                continue
            metadata = item.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                metadata = {}
            available = item.get("available", metadata.get("available", True)) is not False
            if backend == selected and failed:
                available = False
            providers.append({
                "id": backend,
                "label": str(item.get("label") or backend)[:240],
                "selected": backend == selected,
                "available": available,
                "story_voices": backend in reference_backends,
                "progressive_audio": backend == "liquidai",
                "message": "" if available else "Check this provider's settings on NC desktop.",
            })
        return {
            "available": bool(providers) and not self._closing,
            "selected_provider_id": selected,
            "loading": loading,
            "busy": self._remote_tts_change_busy(),
            "message": "Loading the selected TTS provider…" if loading else str(getattr(self, "_remote_tts_provider_message", "")),
            "providers": providers,
        }

    def _remote_apply_tts_provider(self, provider_id: str) -> dict[str, Any]:
        state = self._remote_tts_provider_state()
        target = next((item for item in state["providers"] if item["id"] == provider_id), None)
        if not state["available"] or target is None or not target["available"]:
            return {"accepted": False, "message": "That TTS provider is unavailable. Check NC desktop."}
        if target["selected"] and not state["loading"]:
            return {"accepted": True, "message": "That TTS provider is already selected."}
        if state["busy"]:
            return {"accepted": False, "message": "Finish or stop the current reply before changing TTS provider."}
        previous = state["selected_provider_id"]
        self._remote_tts_provider_message = ""
        self._remote_tts_provider_failed = False
        try:
            accepted = self.selectSpeechBackend("tts", provider_id)
        except Exception:
            # Executor admission can fail before a worker exists. Restore only
            # this selection; no persona or character voice belongs to the switch.
            if self._runtime_operation == "tts" and self._runtime_operation_backend == provider_id:
                self._runtime_operation = ""
                self._runtime_operation_backend = ""
                self._runtime_operation_previous = None
                self._application.config.update("tts_backend", previous)
                self.configurationChanged.emit()
                self.runtimeOperationChanged.emit()
            accepted = False
        if not accepted:
            self._remote_tts_provider_message = "TTS provider could not be changed. Check NC desktop."
            self._remote_tts_provider_failed = self._application.config.get("tts_backend") != previous
            return {"accepted": False, "message": self._remote_tts_provider_message}
        message = (
            "Loading the selected TTS provider…" if self._runtime_operation == "tts"
            else "TTS selection saved for the next initialization."
        )
        return {"accepted": True, "message": message}

    def _set_conversation_voice_reference(self, voice_path: str) -> bool:
        """Shared desktop/phone setter; saved persona records retain their voice."""

        normalized_path = str(voice_path or "").strip()
        result = self._application.config.update_many(
            {
                "voice_path": normalized_path,
                "tts_use_cloned_voice": bool(normalized_path),
            }
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Conversation voice was not changed",
                str(getattr(result.failure, "message", "Could not update the active voice.")),
            )
            return False
        fallback_recorder = getattr(self, "_remember_quick_persona_fallbacks", None)
        if callable(fallback_recorder):
            fallback_recorder(("voice_path", "tts_use_cloned_voice"))
        self._save_native_session()
        self.personaChanged.emit()
        self.coreSettingsChanged.emit()
        self.configurationChanged.emit()
        self.notificationRaised.emit(
            "success",
            "Conversation voice changed",
            Path(normalized_path).name if normalized_path else "Built-in / default voice",
        )
        return True

    @QtCore.Slot(result=int)
    def refreshVoiceOptions(self) -> int:
        """Rescan local voice references without changing the active selection."""
        count = max(0, len(self.voiceOptions) - 1)
        self.voiceOptionsChanged.emit()
        self.notificationRaised.emit(
            "success",
            "Voice references updated",
            f"Found {count} .wav voice reference{'s' if count != 1 else ''} in the voices folder.",
        )
        return count

    @QtCore.Slot(int)
    def setQuickPersonaPage(self, page: int) -> None:
        page_count = self._quick_personas.page_count()
        normalized = min(max(0, int(page)), max(0, page_count - 1))
        if normalized == self._quick_persona_page:
            return
        self._quick_persona_page = normalized
        self.quickPersonaChanged.emit()

    @QtCore.Slot(int)
    def setQuickPersonaRows(self, rows: int) -> None:
        if self._closing or self._quick_persona_rows_busy or self.quickPersonaReorderBusy:
            return
        if rows == self._quick_persona_rows:
            return
        previous_rows = self._quick_persona_rows
        self._quick_persona_rows_busy = True
        self.quickPersonaRowsBusyChanged.emit()

        def save_rows() -> None:
            try:
                saved_rows = self._quick_personas.set_visible_rows(rows)
                self._quickPersonaRowsSaved.emit(saved_rows, "")
            except (OSError, ValueError) as error:
                self._quickPersonaRowsSaved.emit(previous_rows, str(error))

        try:
            self._persona_executor.submit(save_rows)
        except RuntimeError as error:
            self._on_quick_persona_rows_saved(self._quick_persona_rows, str(error))

    @QtCore.Slot(int, str)
    def _on_quick_persona_rows_saved(self, rows: int, error: str) -> None:
        self._quick_persona_rows_busy = False
        self.quickPersonaRowsBusyChanged.emit()
        if self._closing:
            return
        if error:
            self.notificationRaised.emit("error", "Persona layout was not saved", error)
        else:
            old_page_size = self.quickPersonaPageSize
            first_visible_slot = self._quick_persona_page * old_page_size
            self._quick_persona_rows = rows
            self._quick_persona_page = min(first_visible_slot // self.quickPersonaPageSize,
                                           self._quick_personas.page_count() - 1)
        self.quickPersonaChanged.emit()

    @QtCore.Property(bool, notify=quickPersonaReorderChanged)
    def quickPersonaReorderBusy(self) -> bool:
        return getattr(self, "_quick_persona_reorder_busy", False)

    @QtCore.Slot(int, int, str, result=bool)
    def moveQuickPersona(self, source: int, target: int, persona_id: str) -> bool:
        if self._closing or self.quickPersonaReorderBusy or source == target:
            return False
        if (self._persona_avatar_generation.get("inFlight")
                or self._portrait_editor_state.get("inFlight")
                or self._persona_avatar_prompt_state.get("inFlight")
                or self._identity_relay_pending_selection):
            self.notificationRaised.emit(
                "warning", "Persona is busy", "Wait for the current persona update before moving cards."
            )
            return False
        self._bind_legacy_conversation_personas()
        self._quick_persona_reorder_busy = True
        self.quickPersonaReorderChanged.emit()

        def move() -> None:
            try:
                self._quick_personas.move_persona(source, target, persona_id)
            except Exception as error:
                self._quickPersonaMoved.emit(str(error))
            else:
                self._quickPersonaMoved.emit("")

        try:
            self._persona_executor.submit(move)
        except RuntimeError as error:
            self._on_quick_persona_moved(str(error))
            return False
        return True

    @QtCore.Slot(str)
    def _on_quick_persona_moved(self, error: str) -> None:
        self._quick_persona_reorder_busy = False
        if self._closing:
            return
        self.quickPersonaReorderChanged.emit()
        self.quickPersonaChanged.emit()
        self.personaChanged.emit()
        self._conversation_revision = -1
        self.refreshConversationState()
        if error:
            self.notificationRaised.emit("error", "Persona order was not saved", error)

    @QtCore.Slot(int, str, bool, result=bool)
    def saveQuickPersona(self, slot: int, name: str, save_prompt_library: bool = False) -> bool:
        if self.quickPersonaReorderBusy:
            return False
        builder = getattr(self, "_prompt_builder", None)
        if builder is not None and builder.saving:
            self.notificationRaised.emit("warning", "Persona draft is saving", "Try Save persona again when the draft finishes saving.")
            return False
        builder_snapshot = normalize_builder(builder.state if builder is not None else {})
        self._bind_legacy_conversation_personas()
        config = dict(self._application.config.snapshot().values)
        clean_name = str(name or "").strip() or f"Persona {int(slot) + 1}"
        try:
            voice_snapshot = {}
            if str(config.get("tts_backend") or "").strip().lower() == "liquidai":
                active = self._quick_personas.active_persona(strict=True) or {}
                target = self._quick_personas.persona(slot) or {}
                overrides = dict(target.get("overrides") or {})
                for key in ("liquidai_tts_voice", "liquidai_tts_language"):
                    value = (active.get("overrides") or {}).get(key) or config.get(key)
                    if value:
                        overrides[key] = value
                    else:
                        overrides.pop(key, None)
                voice_snapshot["overrides"] = overrides
            record = self._quick_personas.save_persona(
                slot,
                {
                    **voice_snapshot,
                    "name": clean_name,
                    "system_prompt": str(config.get("system_prompt") or ""),
                    "persona_prompt_type": normalize_type(config.get("persona_prompt_type")),
                    "prompt_builder": builder_snapshot,
                    "emotional_instructions": str(config.get("emotional_instructions") or ""),
                    "voice_path": str(config.get("voice_path") or ""),
                    "use_cloned_voice": bool(config.get("tts_use_cloned_voice", True)),
                    "visual_reply_policy": resolve_persona_visual_reply_policy(config),
                    "visual_reply_auto_show": bool(
                        config.get("visual_reply_auto_show_dock", True)
                    ),
                    "identity_relay_ref": str(
                        self._identity_relay_state.get("connectedRef") or ""
                    ),
                },
            )
            self._quick_personas.set_active(slot)
            if builder is not None:
                builder.adopt_saved_persona(str(record["id"]), builder_snapshot)
        except (OSError, ValueError) as error:
            self.notificationRaised.emit("error", "Persona was not saved", str(error))
            return False
        if save_prompt_library:
            try:
                save_prompt_as(str(record.get("system_prompt") or ""))
            except (OSError, ValueError) as error:
                self.notificationRaised.emit(
                    "warning",
                    "Persona saved; prompt library was not updated",
                    str(error),
                )
        self._sync_persona_identity_relay(
            record,
            {"identity_relay_ref"},
        )
        identity_result = self._application.config.update_many(
            self._persona_runtime_updates(record)
        )
        if not identity_result.accepted:
            self.notificationRaised.emit(
                "error",
                "Persona identity was not activated",
                str(
                    getattr(
                        identity_result.failure,
                        "message",
                        "Could not update the active persona identity.",
                    )
                ),
            )
            return False
        self._quick_persona_page = int(slot) // self.quickPersonaPageSize
        self.quickPersonaChanged.emit()
        self.personaChanged.emit()
        self._conversation_revision = -1
        self.refreshConversationState()
        self.notificationRaised.emit("success", "Quick persona saved", clean_name)
        return True

    @QtCore.Slot(str, int, result=int)
    def createBlankQuickPersona(self, name: str, slot: int = -1) -> int:
        """Create a named persona without copying the current session."""
        if self._closing or self.quickPersonaReorderBusy:
            return -1
        builder = getattr(self, "_prompt_builder", None)
        if builder is not None and (builder.saving or builder.applying):
            self.notificationRaised.emit("warning", "Persona is busy", "Try again when the prompt finishes saving.")
            return -1
        try:
            record = self._quick_personas.create_blank(name, slot=slot if slot >= 0 else None)
        except (OSError, ValueError) as error:
            self.notificationRaised.emit("error", "Blank persona was not created", str(error))
            return -1
        slot = int(record["slot"])
        result = self._activate_quick_persona(slot)
        if not result.get("accepted"):
            self.quickPersonaChanged.emit()
        return slot

    @QtCore.Slot(str, str, result=bool)
    def renameQuickPersona(self, persona_id: str, name: str) -> bool:
        """Rename one saved identity without recapturing its prompt or assets."""
        if self._closing or self.quickPersonaReorderBusy:
            return False
        try:
            record = self._quick_personas.rename_persona(persona_id, name)
        except (OSError, ValueError) as error:
            self.notificationRaised.emit("error", "Persona was not renamed", str(error))
            return False
        active = self._quick_personas.active_persona()
        if active and active["id"] == record["id"]:
            result = self._application.config.update("active_quick_persona_name", record["name"])
            if not result.accepted:
                self.notificationRaised.emit(
                    "warning",
                    "Persona renamed; active name could not be synchronized",
                    str(getattr(result.failure, "message", "Could not update the active name.")),
                )
            else:
                self.configurationChanged.emit()
        self.quickPersonaChanged.emit()
        self.personaChanged.emit()
        self._conversation_revision = -1
        self.refreshConversationState()
        return True

    @QtCore.Slot(str, str, result=bool)
    def setQuickPersonaBio(self, persona_id: str, bio: str) -> bool:
        if self._closing or self.quickPersonaReorderBusy:
            return False

        def save_bio() -> None:
            try:
                self._quick_personas.set_bio(persona_id, bio)
                self._quickPersonaBioSaved.emit("")
            except (OSError, ValueError) as error:
                self._quickPersonaBioSaved.emit(str(error))

        try:
            self._persona_executor.submit(save_bio)
        except RuntimeError as error:
            self.notificationRaised.emit("error", "Persona bio was not saved", str(error))
            return False
        return True

    @QtCore.Slot(str)
    def _on_quick_persona_bio_saved(self, error: str) -> None:
        if self._closing:
            return
        if error:
            self.notificationRaised.emit("error", "Persona bio was not saved", error)
        self.quickPersonaChanged.emit()

    @QtCore.Slot(int)
    def applyQuickPersona(self, slot: int) -> None:
        self._activate_quick_persona(slot)

    def _activate_quick_persona(self, slot: int) -> dict[str, Any]:
        builder = getattr(self, "_prompt_builder", None)
        if builder is not None and builder.applying:
            return {"accepted": False, "message": "Wait for the persona prompt to finish saving."}
        if self.quickPersonaReorderBusy:
            return {"accepted": False, "message": "Wait for the persona order to finish saving."}
        record = self._quick_personas.persona(slot)
        if record is None:
            message = "That quick persona slot is empty."
            self.notificationRaised.emit("error", "Persona was not loaded", message)
            return {"accepted": False, "message": message}
        present_fields = self._saved_quick_persona_field_names(slot)
        self._bind_legacy_conversation_personas()
        updates = self._quick_persona_activation_updates(record)
        result = self._application.config.update_many(updates)
        if not result.accepted:
            message = str(
                getattr(
                    result.failure,
                    "message",
                    "Could not update the active persona.",
                )
            )
            self.notificationRaised.emit(
                "error",
                "Persona was not loaded",
                message,
            )
            return {"accepted": False, "message": message}
        try:
            self._quick_personas.set_active(slot)
        except (OSError, ValueError) as error:
            message = str(error)
            self.notificationRaised.emit("error", "Persona selection was not saved", message)
            return {"accepted": False, "message": message}
        self._identity_relay_pending_selection = {}
        self._identity_relay_timer.stop()
        self._sync_persona_identity_relay(record, present_fields)
        self._quick_persona_page = int(slot) // self.quickPersonaPageSize
        self.quickPersonaChanged.emit()
        self.personaChanged.emit()
        self.coreSettingsChanged.emit()
        self.visualReplySetupChanged.emit()
        self.configurationChanged.emit()
        self._conversation_revision = -1
        self.refreshConversationState()
        persona_name = str(record.get("name") or f"Persona {int(slot) + 1}")
        self.notificationRaised.emit(
            "success",
            "Quick persona active",
            persona_name,
        )
        return {
            "accepted": True,
            "message": f"{persona_name} is active.",
        }

    @QtCore.Slot(int)
    def removeQuickPersona(self, slot: int) -> None:
        if self.quickPersonaReorderBusy:
            return
        builder = getattr(self, "_prompt_builder", None)
        if builder is not None and builder.applying:
            return
        self._bind_legacy_conversation_personas()
        active = self._quick_personas.active_persona()
        removed_active = bool(
            active is not None and int(active.get("slot", -1)) == int(slot)
        )
        try:
            self._quick_personas.clear(slot)
        except OSError as error:
            self.notificationRaised.emit("error", "Persona was not removed", str(error))
            return
        if removed_active:
            self._application.config.update("active_quick_persona_id", "")
            self._sync_persona_identity_relay(
                {"slot": -1, "identity_relay_ref": ""},
                {"identity_relay_ref"},
            )
        self.quickPersonaChanged.emit()
        self.personaChanged.emit()
        self._conversation_revision = -1
        self.refreshConversationState()
        self.notificationRaised.emit("success", "Quick persona removed", f"Slot {int(slot) + 1}")

    @QtCore.Slot(str)
    def setConversationPersonaAvatarMode(self, mode: str) -> None:
        try:
            normalized = self._quick_personas.set_avatar_mode(mode)
        except OSError as error:
            self.notificationRaised.emit("error", "Avatar display was not saved", str(error))
            return
        self.quickPersonaChanged.emit()
        self._conversation_revision = -1
        self.refreshConversationState()
        labels = {
            "off": "Hidden",
            "single": "Single portrait",
            "mood": "Mood portraits",
            "ring": "Portrait with mood ring",
        }
        self.notificationRaised.emit("success", "Conversation avatar display", labels.get(normalized, normalized))

    @QtCore.Slot(int)
    def setConversationPersonaAvatarSize(self, size: int) -> None:
        try:
            normalized = self._quick_personas.set_avatar_size(size)
        except OSError as error:
            self.notificationRaised.emit(
                "error",
                "Avatar size was not saved",
                str(error),
            )
            return
        self.quickPersonaChanged.emit()
        self.notificationRaised.emit(
            "success",
            "Conversation avatar size",
            f"{normalized} px",
        )

    @staticmethod
    def _qml_file_path(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        url = QtCore.QUrl(text)
        return url.toLocalFile() if url.isLocalFile() else text

    @QtCore.Slot(int, str, str)
    def importQuickPersonaAvatar(self, slot: int, source_url: str, mood: str = "") -> None:
        if self.quickPersonaReorderBusy:
            return
        try:
            self._quick_personas.import_avatar(
                slot,
                self._qml_file_path(source_url),
                mood=str(mood or ""),
            )
        except (OSError, ValueError) as error:
            self.notificationRaised.emit("error", "Avatar was not imported", str(error))
            return
        active = self._quick_personas.active_persona() or {}
        if int(active.get("slot", -1)) == int(slot):
            self._application.config.update_many(self._persona_runtime_updates(active))
            self._save_native_session()
        self.quickPersonaChanged.emit()
        self._conversation_revision = -1
        self.refreshConversationState()
        self.notificationRaised.emit("success", "Persona avatar updated", "The portrait is ready for Conversation.")

    @QtCore.Property("QVariantMap", notify=personaPortraitEditorChanged)
    def personaPortraitEditorState(self) -> dict[str, Any]:
        return dict(self._portrait_editor_state)

    @QtCore.Slot(int, result="QVariantList")
    def personaPortraitRows(self, slot: int) -> list[dict[str, str]]:
        record = self._quick_personas.persona(slot) or {}
        paths = {"neutral": str(record.get("avatar_path") or ""), **dict(record.get("mood_images") or {})}
        hints = dict(record.get("mood_descriptions") or {})
        return [{"tag": tag, "path": str(path), "url": _local_asset_url(str(path)),
                 "hint": str(hints.get(tag) or "")} for tag, path in paths.items()]

    @QtCore.Slot()
    def resetPersonaPortraitEditor(self) -> None:
        if not self._portrait_editor_state["inFlight"]:
            self._portrait_editor_state = {"inFlight": False, "error": "", "saved": False}
            self.personaPortraitEditorChanged.emit()

    @QtCore.Slot(int, str, "QVariantList")
    def savePersonaPortraitSet(self, slot: int, persona_id: str, rows: list) -> None:
        if self.quickPersonaReorderBusy:
            return
        if self._portrait_editor_state["inFlight"] or self._persona_avatar_generation["inFlight"]:
            return
        self._bind_legacy_conversation_personas()
        draft = [dict(row) for row in rows]
        for row in draft:
            url = QtCore.QUrl(str(row.get("path") or ""))
            if url.isLocalFile():
                row["path"] = url.toLocalFile()
        self._portrait_editor_state = {"inFlight": True, "error": "", "saved": False}
        self.personaPortraitEditorChanged.emit()

        def save() -> None:
            try:
                self._quick_personas.save_portrait_set(slot, persona_id, draft)
            except Exception as error:
                self._personaPortraitSetSaved.emit(slot, persona_id, str(error))
            else:
                self._personaPortraitSetSaved.emit(slot, persona_id, "")
        self._persona_executor.submit(save)

    @QtCore.Slot(int, str, str)
    def _on_portrait_set_saved(self, slot: int, persona_id: str, error: str) -> None:
        if self._closing:
            return
        self._portrait_editor_state = {"inFlight": False, "error": error, "saved": not bool(error)}
        if not error:
            active = self._quick_personas.active_persona() or {}
            if active.get("id") == persona_id and int(active.get("slot", -1)) == slot:
                self._application.config.update_many(self._persona_runtime_updates(active))
            self.quickPersonaChanged.emit()
            self.personaChanged.emit()
            self._conversation_revision = -1
            self.refreshConversationState()
            self._refresh_conversation_portraits()
        self.personaPortraitEditorChanged.emit()

    @QtCore.Slot(int, str, str, str, bool)
    def generatePersonaPortraitSelection(self, slot: int, scope: str, selected: str,
                                        prompt: str, transparent: bool) -> None:
        record = self._quick_personas.persona(slot) or {}
        try:
            moods = portrait_generation_moods(record, scope, selected)
        except ValueError as error:
            self.notificationRaised.emit("error", "Cannot generate portraits", str(error))
            return
        if not moods:
            self.notificationRaised.emit("info", "Portrait set is complete", "There are no missing portraits to generate.")
            return
        self.generateQuickPersonaAvatar(slot, True, prompt, transparent, _moods=moods)

    def _persona_avatar_base_prompt(self, record: Mapping[str, Any]) -> str:
        saved = str(record.get("portrait_prompt") or "").strip()
        if saved:
            return saved
        name = str(record.get("name") or "NeuralCompanion persona").strip()
        # Appearance freedom applies to scene self-images, not avatar creation.
        identity = self._persona_visual_identity_seed(
            {**record, "appearance_freedom": "strict"}
        )
        return (
            f"Square character portrait avatar for a persona named {name}. "
            f"Stable identity and appearance: {identity}. Consistent recognizable "
            "character design, head and shoulders, centered composition, polished "
            "production chat avatar."
        )

    def _persona_avatar_prompt(
        self,
        record: Mapping[str, Any],
        mood: str,
        prompt_override: str = "",
        transparent_background: bool = True,
    ) -> str:
        mood_text = "neutral, approachable" if mood == "neutral" else mood
        base_prompt = clean_persona_portrait_prompt(prompt_override)
        if not base_prompt:
            base_prompt = self._persona_avatar_base_prompt(record)
        prompt = f"{base_prompt} Expression and mood: {mood_text}."
        if not transparent_background:
            return prompt
        return (
            f"{prompt} Render only the isolated character against one perfectly uniform, evenly lit, "
            "flat studio backdrop whose colour strongly contrasts with every part of the character. "
            "Include no room, furniture, scenery, floor, cast shadow, text, logo, border, or frame. "
            "NeuralCompanion creates the final clear transparent PNG after generation, so do not draw, "
            "paint, or simulate transparency and never render a checkerboard or transparency grid."
        )

    @QtCore.Slot(int, result=str)
    def personaAvatarPrompt(self, slot: int) -> str:
        record = self._quick_personas.persona(slot)
        if record is None:
            return ""
        return clean_persona_portrait_prompt(self._persona_avatar_base_prompt(record))

    @QtCore.Slot(int, result=bool)
    def personaAvatarTransparencyEnabled(self, slot: int) -> bool:
        record = self._quick_personas.persona(slot) or {}
        return bool(record.get("portrait_transparency_enabled", True))

    @QtCore.Slot(str)
    @QtCore.Slot(str, bool)
    def refinePersonaAvatarPrompt(
        self,
        prompt: str,
        transparent_background: bool = True,
    ) -> None:
        text = clean_persona_portrait_prompt(prompt)
        if not text:
            self.notificationRaised.emit("error", "Portrait prompt is empty", "Describe the persona before refining.")
            return
        if bool(self._persona_avatar_prompt_state.get("inFlight", False)):
            return
        self._persona_avatar_prompt_state = {
            "inFlight": True,
            "text": "",
            "error": "",
            "transparentBackground": bool(transparent_background),
        }
        self.personaAvatarPromptChanged.emit()

        def refine() -> None:
            try:
                refined = self._application.prompt_refinement.refine(
                    text,
                    label="Persona portrait prompt",
                    guidance=(
                        "Produce a concise image-generation prompt that preserves the requested identity, "
                        "appearance, art style, and clothing. Compose a square head-and-shoulders chat avatar. "
                        "Describe the character identity, clean silhouette, composition, and visual style. "
                        "Exclude text, logos, borders, and frames. "
                        + (
                            "State that NeuralCompanion will create a genuinely clear transparent PNG with its "
                            "background-removal pass. Require one isolated character on a plain uniform studio "
                            "backdrop with no environment or furniture, and explicitly forbid a checkerboard, "
                            "transparency grid, fake alpha preview, chroma key, or green screen."
                            if bool(transparent_background)
                            else "Keep any requested scene or portrait background and do not request transparency."
                        )
                    ),
                )
            except Exception as error:
                self._personaPromptRefined.emit(False, str(error))
                return
            self._personaPromptRefined.emit(True, str(refined or "").strip())

        self._persona_executor.submit(refine)

    @QtCore.Slot()
    def resetPersonaAvatarPromptState(self) -> None:
        if bool(self._persona_avatar_prompt_state.get("inFlight", False)):
            return
        self._persona_avatar_prompt_state = {
            "inFlight": False,
            "text": "",
            "error": "",
        }
        self.personaAvatarPromptChanged.emit()

    @QtCore.Slot(bool, str)
    def _on_persona_prompt_refined(self, accepted: bool, value: str) -> None:
        if self._closing:
            return
        if accepted and str(value or "").strip():
            refined_text = clean_persona_portrait_prompt(value)
            if bool(self._persona_avatar_prompt_state.get("transparentBackground", True)):
                transparent_instruction = (
                    "NeuralCompanion output target: a genuinely clear transparent PNG cutout. "
                    "Render one isolated character on a plain uniform studio backdrop for the dedicated "
                    "background-removal pass; never draw a checkerboard or transparency grid."
                )
                if "never draw a checkerboard" not in refined_text.lower():
                    refined_text = f"{refined_text} {transparent_instruction}".strip()
            self._persona_avatar_prompt_state = {
                "inFlight": False,
                "text": refined_text,
                "error": "",
            }
            self.notificationRaised.emit("success", "Portrait prompt refined", "Review it, then generate the avatar.")
        else:
            self._persona_avatar_prompt_state = {
                "inFlight": False,
                "text": "",
                "error": str(value or "Prompt refinement failed."),
            }
            self.notificationRaised.emit("error", "Portrait prompt was not refined", str(value or "Provider failure."))
        self.personaAvatarPromptChanged.emit()

    def _begin_persona_avatar_request(self) -> bool:
        state = self._persona_avatar_generation
        remaining = list(state.get("remaining") or [])
        if not remaining:
            state.update(
                {
                    "inFlight": False,
                    "requestId": "",
                    "mood": "",
                    "message": "Portrait set ready",
                    "preparing": False,
                }
            )
            self._persona_avatar_timer.stop()
            self.personaAvatarGenerationChanged.emit()
            self.notificationRaised.emit("success", "Persona portrait ready", "Conversation can now use the saved avatar.")
            return True
        mood = str(remaining.pop(0) or "neutral")
        slot = int(state.get("slot", -1))
        record = self._quick_personas.persona(slot)
        if record is None:
            self._finish_persona_avatar_generation("The quick persona no longer exists.")
            return False
        request_id = f"quick_persona_{slot}_{int(time.time() * 1000)}_{mood}"
        runtime_config = dict(self._application.config.snapshot().values)
        request_provider = str(
            runtime_config.get("visual_reply_provider") or "openai"
        ).strip().lower()
        runtime_config["visual_reply_mode"] = "auto"
        runtime_config["visual_replies_enabled"] = True
        reference_inputs: tuple[Path, ...] = ()
        if mood != "neutral" and bool(record.get("mood_reference_enabled", True)):
            reference = self._persona_reference_path(record)
            if reference is not None:
                reference_inputs = (reference,)
                reference_strength = _bounded_strength(
                    record.get("visual_reference_strength"), 0.75
                )
                runtime_config = persona_visual_request_config(
                    runtime_config,
                    reference_strength=reference_strength,
                )
        try:
            accepted = bool(
                self._application.addon_visual_request.request_generation(
                    self._persona_avatar_prompt(
                        record,
                        mood,
                        str(state.get("prompt") or ""),
                        bool(state.get("transparentBackground", True)),
                    ),
                    inputs=reference_inputs,
                    source_text=f"Quick persona portrait: {record.get('name', '')} / {mood}",
                    request_id=request_id,
                    runtime_config_override=runtime_config,
                )
            )
        except Exception as error:
            self._finish_persona_avatar_generation(str(error))
            return False
        if not accepted:
            self._finish_persona_avatar_generation(
                "Visual Reply did not accept the request. Initialize NC and check the active Visual Reply provider."
            )
            return False
        state.update(
            {
                "inFlight": True,
                "requestId": request_id,
                "mood": mood,
                "remaining": remaining,
                "message": f"Generating {mood} portrait",
                "preparing": False,
                "provider": request_provider,
            }
        )
        self._persona_avatar_started_at = time.monotonic()
        self._persona_avatar_timer.start()
        self.personaAvatarGenerationChanged.emit()
        return True

    @QtCore.Slot(int, bool)
    @QtCore.Slot(int, bool, str)
    @QtCore.Slot(int, bool, str, bool)
    def generateQuickPersonaAvatar(
        self,
        slot: int,
        include_moods: bool = False,
        prompt_override: str = "",
        transparent_background: bool = True,
        *,
        _moods: list[str] | None = None,
    ) -> None:
        if self.quickPersonaReorderBusy:
            return
        if bool(self._persona_avatar_generation.get("inFlight", False)) or bool(getattr(self, "_portrait_editor_state", {}).get("inFlight", False)):
            self.notificationRaised.emit("warning", "Portrait generation is busy", "Wait for the current persona portrait to finish.")
            return
        record = self._quick_personas.persona(slot)
        if record is None:
            self.notificationRaised.emit("error", "Save the persona first", "Choose a quick slot before generating its avatar.")
            return
        base_prompt = clean_persona_portrait_prompt(prompt_override)
        if not base_prompt:
            base_prompt = clean_persona_portrait_prompt(
                self._persona_avatar_base_prompt(record)
            )
        try:
            record = self._quick_personas.save_persona(
                slot,
                {
                    "portrait_prompt": base_prompt,
                    "visual_identity_prompt": clean_persona_portrait_prompt(
                        record.get("visual_identity_prompt") or base_prompt
                    ),
                    "portrait_transparency_enabled": bool(transparent_background),
                },
            )
        except (OSError, ValueError) as error:
            self.notificationRaised.emit(
                "error", "Portrait prompt was not saved", str(error)
            )
            return
        active = self._quick_personas.active_persona() or {}
        if int(active.get("slot", -1)) == int(slot):
            self._application.config.update_many(self._persona_runtime_updates(record))
            self._save_native_session()
        moods = list(_moods if _moods is not None else (_PERSONA_MOOD_PORTRAITS if include_moods else ("neutral",)))
        self._persona_avatar_generation = {
            "inFlight": True,
            "requestId": "",
            "slot": int(slot),
            "mood": "",
            "remaining": moods,
            "message": "Preparing portrait generation",
            "prompt": base_prompt,
            "preparing": False,
            "transparentBackground": bool(transparent_background),
        }
        self.personaAvatarGenerationChanged.emit()
        self._begin_persona_avatar_request()

    def _finish_persona_avatar_generation(self, error: str) -> None:
        self._persona_avatar_timer.stop()
        self._persona_avatar_generation.update(
            {
                "inFlight": False,
                "requestId": "",
                "mood": "",
                "remaining": [],
                "message": str(error or "Portrait generation failed"),
                "preparing": False,
            }
        )
        self.personaAvatarGenerationChanged.emit()
        self.notificationRaised.emit("error", "Persona portrait failed", str(error or "Visual Reply failed."))

    @QtCore.Slot()
    def _poll_persona_avatar_generation(self) -> None:
        state = self._persona_avatar_generation
        if not bool(state.get("inFlight", False)):
            self._persona_avatar_timer.stop()
            return
        if bool(state.get("preparing", False)):
            return
        if time.monotonic() - self._persona_avatar_started_at > 240.0:
            self._finish_persona_avatar_generation("Visual Reply timed out after four minutes.")
            return
        result = self._application.addons.invoke_addon_capability(
            "nc.visual_reply",
            "runtime.current_state",
            {},
        )
        if not result.accepted:
            return
        visual_state = dict(result.value or {})
        if str(visual_state.get("request_id") or "") != str(state.get("requestId") or ""):
            return
        status = str(visual_state.get("status") or "").strip().lower()
        if status == "error":
            self._finish_persona_avatar_generation(
                str(visual_state.get("detail_text") or "Visual Reply could not generate the portrait.")
            )
            return
        if status != "ready":
            return
        image_path = str(visual_state.get("image_path") or "").strip()
        if not image_path or not Path(image_path).is_file():
            self._finish_persona_avatar_generation("Visual Reply completed without an image file.")
            return
        mood = str(state.get("mood") or "neutral")
        slot = int(state.get("slot", -1))
        prepare_transparency = bool(state.get("transparentBackground", True))
        request_provider = str(state.get("provider") or "").strip().lower()
        background_runtime_config = dict(self._application.config.snapshot().values)
        if request_provider:
            background_runtime_config["visual_reply_provider"] = request_provider
        state["preparing"] = True
        state["message"] = (
            f"Removing the {mood} portrait background"
            if prepare_transparency
            else f"Saving {mood} portrait"
        )
        self._persona_avatar_timer.stop()
        self.personaAvatarGenerationChanged.emit()

        def prepare() -> None:
            try:
                import_path = Path(image_path)
                temporary_root = None
                if prepare_transparency and request_provider == "runware":
                    from addons.visual_reply.generation import RunwareVisualReplyClient

                    runtime = VisualReplyRuntime(
                        lambda: dict(background_runtime_config)
                    )
                    cutout_bytes = RunwareVisualReplyClient(
                        api_key=runtime.api_key()
                    ).remove_background(import_path)
                    temporary_root = TemporaryDirectory(
                        prefix="nc_persona_cutout_",
                        ignore_cleanup_errors=True,
                    )
                    import_path = Path(temporary_root.name) / "portrait-cutout.png"
                    import_path.write_bytes(cutout_bytes)
                try:
                    relative_path = self._quick_personas.import_avatar(
                        slot,
                        import_path,
                        mood="" if mood == "neutral" else mood,
                        prepare_transparency=prepare_transparency,
                    )
                finally:
                    if temporary_root is not None:
                        temporary_root.cleanup()
            except Exception as error:
                self._personaAvatarPrepared.emit(slot, mood, False, str(error))
                return
            self._personaAvatarPrepared.emit(slot, mood, True, relative_path)

        self._persona_executor.submit(prepare)

    @QtCore.Slot()
    def _poll_user_identity_avatar_generation(self) -> None:
        adapter = self._native_surfaces.adapter("user_identity_tab")
        if adapter is None or not callable(getattr(adapter, "poll_generation", None)):
            self._user_identity_avatar_timer.stop()
            return
        try:
            adapter.poll_generation()
        except (RuntimeError, TypeError, ValueError) as error:
            self._user_identity_avatar_timer.stop()
            self.notificationRaised.emit(
                "error",
                "User portrait generation failed",
                str(error),
            )
            return
        if not bool(
            callable(getattr(adapter, "generation_pending", None))
            and adapter.generation_pending()
        ):
            self._user_identity_avatar_timer.stop()

    @QtCore.Slot(int, str, bool, str)
    def _on_persona_avatar_prepared(
        self,
        slot: int,
        mood: str,
        accepted: bool,
        value: str,
    ) -> None:
        if self._closing:
            return
        state = self._persona_avatar_generation
        if (
            not bool(state.get("inFlight", False))
            or int(state.get("slot", -1)) != int(slot)
            or str(state.get("mood") or "") != str(mood or "")
        ):
            return
        if not accepted:
            self._finish_persona_avatar_generation(str(value or "Could not prepare persona portrait."))
            return
        state["preparing"] = False
        if str(mood or ""):
            active = self._quick_personas.active_persona() or {}
            if int(active.get("slot", -1)) == int(slot):
                self._application.config.update_many(
                    self._persona_runtime_updates(active)
                )
                self._save_native_session()
        self.quickPersonaChanged.emit()
        self.personaChanged.emit()
        self._conversation_revision = -1
        self.refreshConversationState()
        self._begin_persona_avatar_request()

    @QtCore.Slot(str)
    def applyPromptRecord(self, prompt_id: str) -> None:
        builder = getattr(self, "_prompt_builder", None)
        if builder is not None and builder.applying:
            self.notificationRaised.emit("warning", "Prompt is saving", "Wait for Apply to Persona to finish before loading another prompt.")
            return
        record = find_prompt(str(prompt_id or "").strip())
        if not record:
            return
        result = self._application.config.update_many({
            "system_prompt": str(record.get("prompt") or ""), "persona_prompt_type": "",
        })
        if not result.accepted:
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit("error", "Prompt was not saved", str(error))
            return
        self.personaChanged.emit()
        self.coreSettingsChanged.emit()
        self.notificationRaised.emit(
            "success",
            "System prompt loaded",
            str(record.get("name") or "Prompt"),
        )
        builder = getattr(self, "_prompt_builder", None)
        if builder is not None:
            builder.synchronize()
            builder.useApplied()

    @QtCore.Slot()
    def saveCurrentPrompt(self) -> None:
        prompt = str(self._application.config.get("system_prompt", "") or "").strip()
        try:
            record = save_prompt_as(prompt)
        except ValueError as error:
            self.notificationRaised.emit("error", "Prompt was not saved", str(error))
            return
        self.personaChanged.emit()
        self.notificationRaised.emit(
            "success",
            "Prompt saved",
            str(record.get("name") or "Custom prompt"),
        )

    @QtCore.Slot(str, bool)
    def setPromptQuick(self, prompt_id: str, quick: bool) -> None:
        selected = str(prompt_id or "").strip()
        try:
            if quick:
                add_prompt_to_quick(selected)
            else:
                remove_prompt_from_quick(selected)
        except ValueError as error:
            self.notificationRaised.emit("error", "Quick prompt was not changed", str(error))
            return
        self.personaChanged.emit()

    @QtCore.Slot(str, result=bool)
    def deletePromptRecord(self, prompt_id: str) -> bool:
        return self.deletePromptRecords([prompt_id])

    @QtCore.Slot("QVariantList", result=bool)
    def deletePromptRecords(self, prompt_ids: list[Any]) -> bool:
        try:
            deleted = delete_custom_prompts(
                [str(prompt_id or "").strip() for prompt_id in list(prompt_ids or [])]
            )
        except (OSError, ValueError) as error:
            self.notificationRaised.emit("error", "Prompts were not deleted", str(error))
            return False
        self.personaChanged.emit()
        count = len(deleted)
        self.notificationRaised.emit(
            "success",
            "Saved prompts deleted" if count != 1 else "Saved prompt deleted",
            f"Removed {count} custom prompt{'s' if count != 1 else ''}.",
        )
        return True

    @QtCore.Slot(str)
    def startTutorial(self, tutorial_id: str) -> None:
        payload = tutorial_catalog.load_tutorial(str(tutorial_id or "").strip())
        if not isinstance(payload, dict) or not list(payload.get("steps") or []):
            self.notificationRaised.emit(
                "error",
                "Tutorial could not start",
                "The selected tutorial has no readable steps.",
            )
            return
        try:
            payload, start_index = prepare_tutorial(payload, tutorial_catalog.load_tutorial)
        except ValueError as error:
            self.notificationRaised.emit("error", "Tutorial could not start", str(error))
            return
        errors = tutorial_scope.validate_tutorial(payload)
        if errors:
            self.notificationRaised.emit("error", "Tutorial could not start", errors[0])
            return
        self._restore_tutorial_widget_states()
        self._tutorial_narration.stop()
        self._tutorial_scope_navigation = None
        self._tutorial_payload = dict(payload)
        self._tutorial_step_index = start_index
        self._tutorial_audio_status = ""
        if payload.get("audience") == "remote":
            saved = self.navigationSelection("tutorials:progress:" + str(payload['id']), "0")
            try:
                self._tutorial_step_index = min(max(0, int(saved)), len(payload['steps']) - 1)
            except (TypeError, ValueError):
                self._tutorial_step_index = 0
        self._activate_tutorial_step()
        self.tutorialStateChanged.emit()

    @QtCore.Slot()
    def nextTutorialStep(self) -> None:
        if self.tutorialState.get("paused"):
            return
        steps = list(self._tutorial_payload.get("steps") or [])
        if self._tutorial_step_index + 1 >= len(steps):
            if self._tutorial_payload.get("audience") == "remote":
                self.rememberNavigationSelection("tutorials:progress:" + str(self._tutorial_payload['id']), "done")
            self.closeTutorial()
            return
        self._tutorial_narration.stop()
        self._tutorial_step_index += 1
        self._activate_tutorial_step()
        self.tutorialStateChanged.emit()

    @QtCore.Slot()
    def previousTutorialStep(self) -> None:
        if self.tutorialState.get("paused"):
            return
        if self._tutorial_step_index <= 0:
            return
        self._tutorial_narration.stop()
        self._tutorial_step_index -= 1
        self._activate_tutorial_step()
        self.tutorialStateChanged.emit()

    @QtCore.Slot()
    def closeTutorial(self) -> None:
        self._restore_tutorial_widget_states()
        self._tutorial_narration.stop()
        self._tutorial_payload = {}
        self._tutorial_step_index = 0
        self._tutorial_scope_navigation = None
        self._refresh_tutorial_layout()
        self.tutorialStateChanged.emit()

    def _activate_tutorial_step(self) -> None:
        steps = list(self._tutorial_payload.get("steps") or [])
        if not steps or not (0 <= self._tutorial_step_index < len(steps)):
            return
        step = dict(steps[self._tutorial_step_index] or {})
        scoped = tutorial_scope.is_scoped(self._tutorial_payload)
        if scoped:
            route = tutorial_scope.step_route(self._tutorial_payload, step)
            step.update(route)
            token = getattr(self, "_tutorial_scope_token", 0) + 1
            self._tutorial_scope_token = token
            previous = getattr(self, "_tutorial_scope_navigation", None)
            returning = getattr(self, "_tutorial_returning", False)
            self._tutorial_returning = False
            if returning and previous is not None:
                previous.elsewhere = False
                previous.ready = False
                previous.unmatched_reports = 0
            else:
                navigation = tutorial_scope.TutorialNavigation(route, token)
                navigation.elsewhere = bool(previous and previous.elsewhere)
                self._tutorial_scope_navigation = navigation
                self._tutorial_target_ready = False
                self._tutorial_audio_status = ""
                if navigation.elsewhere:
                    return
        if self._tutorial_payload.get("audience") == "remote":
            self.rememberNavigationSelection("tutorials:progress:" + str(self._tutorial_payload['id']), str(self._tutorial_step_index))
        addon_id = str(step.get("addon") or "").strip()
        section = str(step.get("section") or "").strip()
        workspace = str(step.get("workspace") or "").strip().lower()
        runtime_section = str(step.get("runtime_section") or "").strip().lower()
        self._tutorial_navigation_notice = ""
        if hasattr(self, "_workspace_layout_state"):
            self._refresh_tutorial_layout()
            destination_key = self._tutorial_workspace()
            if destination_key in self._workspace_layout_state.get("hidden_main_tabs", []):
                self._tutorial_navigation_notice = (
                    "This hidden workspace is shown temporarily for this step. "
                    "Your saved tab visibility and panel positions are unchanged."
                )
        workspaces = getattr(self, "_addon_workspaces", None)
        if addon_id and workspaces is not None:
            destination = next((item for item in workspaces if item.get("id") == addon_id), None)
            if destination is None:
                self._tutorial_navigation_notice = (
                    "This addon is unavailable in this installation. Open Addon Manager "
                    "to install or enable it, then restart NC if requested. You can still read this guide."
                )
                if not scoped:
                    self.openAddonWorkspaceSection("core.addons", "Overview")
                return
            if not destination.get("core") and (not destination.get("effectiveEnabled", True)
                    or (scoped and not destination.get("available", True))):
                self._tutorial_navigation_notice = (
                    "This addon is not loaded. Enable it in Addon Manager and restart NC "
                    "before trying its controls. Reading this guide does not enable it."
                )
                if scoped:
                    return
        if addon_id:
            self.openAddonWorkspaceSection(addon_id, section)
        elif workspace:
            self.openWorkspace(workspace)
        if workspace == "runtime" and runtime_section:
            chat_tab = str(step.get("chat_tab") or "").strip().lower()
            if runtime_section == "chat" and chat_tab in {"conversation", "writing", "proactive", "memory"}:
                self.rememberNavigationSelection("runtime:chat-tab", chat_tab)
            self.rememberNavigationSelection("runtime:section", runtime_section)
            self.runtimeSectionRequested.emit(runtime_section)
        vision_provider = str(step.get("vision_provider") or "").strip()
        if workspace == "runtime" and runtime_section == "vision" and vision_provider:
            self.viewVisionProvider(vision_provider)
        if scoped and workspace == "runtime":
            provider_kind = str(step.get("provider_kind") or "")
            provider_id = str(step.get("provider_id") or "")
            if provider_kind == "language" and provider_id:
                self.viewProvider(provider_id)
            elif provider_kind in {"stt", "tts", "avatar", "vision"} and provider_id:
                self.viewRuntimeProviderSettings(provider_kind, provider_id)

    @QtCore.Slot(int, int, result="QVariantMap")
    def tutorialScreenGeometry(self, x: int, y: int) -> dict[str, int]:
        """Use QScreen's work area (including taskbar offsets) for the guide."""
        screen = QtGui.QGuiApplication.screenAt(QtCore.QPoint(x, y)) or QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return {}
        bounds = screen.availableGeometry()
        return {"x": bounds.x(), "y": bounds.y(), "width": bounds.width(), "height": bounds.height()}

    @QtCore.Slot(bool)
    def setTutorialSpeechEnabled(self, enabled: bool) -> None:
        normalized = bool(enabled)
        self._tutorial_speech_enabled = normalized
        self._application.config.update("tutorial_read_aloud_enabled", normalized)
        self._session_store.save()
        if not normalized:
            self._tutorial_narration.stop()
            if tutorial_scope.is_scoped(self._tutorial_payload):
                self._tutorial_audio_status = "stopped"
        self.tutorialStateChanged.emit()

    @QtCore.Slot()
    def stopTutorialSpeech(self) -> None:
        """Stop tutorial narration without changing conversation playback or progress."""
        self._tutorial_narration.stop()
        if tutorial_scope.is_scoped(self._tutorial_payload):
            self._tutorial_audio_status = "stopped"
            self.tutorialStateChanged.emit()

    @QtCore.Property("QVariantMap", notify=tutorialStateChanged)
    def tutorialLaunchers(self) -> dict[str, bool]:
        config = getattr(self, "_application", None)
        values = config.config.snapshot().values if config is not None else {}
        return {"buttons": bool(values.get("tutorial_show_buttons", True)),
                "context": bool(values.get("tutorial_show_context_menus", True))}

    @QtCore.Slot(str, bool)
    def setTutorialLauncherVisible(self, kind: str, visible: bool) -> None:
        key = {"buttons": "tutorial_show_buttons", "context": "tutorial_show_context_menus"}.get(kind)
        if key is None:
            return
        self._application.config.update(key, bool(visible))
        self._session_store.save()
        self.tutorialStateChanged.emit()

    @QtCore.Slot("QVariantMap", result=bool)
    def tutorialMarksContext(self, context: dict[str, Any]) -> bool:
        state = self.tutorialState
        route = tutorial_scope.normalize_route(context)
        return bool(state["active"] and state["scoped"] and route
                    and tutorial_scope.route_matches(route, state["scope"]))

    @QtCore.Slot(int, bool)
    def reportTutorialTarget(self, token: int, ready: bool) -> None:
        navigation = getattr(self, "_tutorial_scope_navigation", None)
        if navigation is None or navigation.token != token:
            return
        self._tutorial_target_ready = bool(ready)
        if ready:
            self._advance_completed_tutorial_audio()

    @QtCore.Slot(int, int, str)
    def _tutorial_narration_finished(self, token: int, request: int, reason: str) -> None:
        navigation = getattr(self, "_tutorial_scope_navigation", None)
        if (navigation is None or navigation.token != token
                or request != getattr(self, "_tutorial_audio_request", 0)
                or getattr(self, "_tutorial_audio_status", "") != "playing"):
            return
        self._tutorial_audio_status = reason
        self._advance_completed_tutorial_audio()
        self.tutorialStateChanged.emit()

    def _advance_completed_tutorial_audio(self) -> None:
        payload = self._tutorial_payload
        navigation = getattr(self, "_tutorial_scope_navigation", None)
        steps = payload.get("steps") or []
        if (not payload.get("continuous_course") or not navigation or navigation.elsewhere
                or not getattr(self, "_tutorial_target_ready", False)
                or getattr(self, "_tutorial_audio_status", "") != "completed"
                or not self._tutorial_speech_enabled or not steps):
            return
        step = steps[self._tutorial_step_index]
        if step.get("advance_mode") == "audio_finish" and self._tutorial_step_index + 1 < len(steps):
            self.nextTutorialStep()

    @QtCore.Slot()
    def speakTutorialStep(self) -> None:
        state = self.tutorialState
        if state.get("paused"):
            return
        body = str(state.get("stepBody") or "").strip()
        if not body:
            self.notificationRaised.emit(
                "warning",
                "Tutorial narration unavailable",
                "This tutorial step has no narration text.",
            )
            return
        if not self._tutorial_narration.active:
            try:
                playback_active = (
                    getattr(self._application.playback.snapshot(), "current", None)
                    is not None
                )
            except Exception:
                playback_active = False
            if playback_active:
                self.notificationRaised.emit(
                    "warning",
                    "Tutorial narration is waiting",
                    "Finish or skip the current speech before reading this tutorial step.",
                )
                return
        runtime_config = dict(self._application.config.snapshot().values)
        if state.get("scoped"):
            token = int(state["navigationToken"])
            request = getattr(self, "_tutorial_audio_request", 0) + 1
            self._tutorial_audio_request = request
            self._tutorial_audio_status = "playing"
            self._tutorial_narration.speak(body, runtime_config,
                on_finished=lambda reason: self.tutorialNarrationFinished.emit(token, request, reason))
            self.tutorialStateChanged.emit()
        else:
            self._tutorial_narration.speak(body, runtime_config)

    @QtCore.Slot()
    def performTutorialTryAction(self) -> None:
        if self.tutorialState.get("paused"):
            return
        steps = list(self._tutorial_payload.get("steps") or [])
        if not steps or not (0 <= self._tutorial_step_index < len(steps)):
            return
        action = dict(dict(steps[self._tutorial_step_index] or {}).get("try_action") or {})
        action_type = str(action.get("type") or "").strip().lower()
        target_name = str(action.get("target") or "").strip()
        if not target_name:
            return
        result = self._application.addons.invoke_addon_capability(
            "nc.companion_orb_overlay",
            "companion_orb.tutorial.try_action",
            action,
        )
        payload = dict(result.value or {}) if result.accepted else {}
        if not result.accepted or not bool(payload.get("accepted", False)):
            self.notificationRaised.emit(
                "warning",
                "Try action is not available",
                str(
                    payload.get("error")
                    or getattr(getattr(result, "failure", None), "message", "")
                    or "That exercise is not present in the current addon configuration."
                ),
            )
            return
        restore = dict(payload.get("restore") or {})
        restore_key = str(restore.get("key") or "").strip()
        if action_type == "temporary_checkbox" and restore_key:
            self._tutorial_temporary_widget_states.setdefault(
                restore_key,
                bool(restore.get("value", False)),
            )
        self.notificationRaised.emit(
            "success",
            "Tutorial exercise started",
            str(action.get("label") or "Try action"),
        )

    @QtCore.Slot(int, bool)
    def startDryRun(self, target_samples: int, auto_replies: bool) -> None:
        try:
            self._dry_run.start(target_samples, auto_replies)
        except Exception as error:
            self.notificationRaised.emit("error", "Performance check could not start", str(error))
            return
        self.operationsChanged.emit()

    @QtCore.Slot()
    def stopDryRun(self) -> None:
        try:
            self._dry_run.stop()
        except Exception as error:
            self.notificationRaised.emit("error", "Performance check could not stop", str(error))
            return
        self.operationsChanged.emit()

    @QtCore.Slot()
    def applyDryRunRecommendation(self) -> None:
        try:
            changed = self._dry_run.apply_recommendation()
        except Exception as error:
            self.notificationRaised.emit("error", "Recommendation was not applied", str(error))
            return
        if changed:
            self.configurationChanged.emit()
        self.operationsChanged.emit()

    @QtCore.Slot(str)
    def loadPerformanceProfile(self, profile_name: str) -> None:
        selected = str(profile_name or "").strip()
        if not selected:
            return
        try:
            changed = self._dry_run.load_profile(selected)
        except Exception as error:
            self.notificationRaised.emit("error", "Profile was not loaded", str(error))
            return
        if changed:
            self.configurationChanged.emit()
        self.operationsChanged.emit()
        self.notificationRaised.emit("success", "Performance profile loaded", selected)

    @QtCore.Slot()
    def refreshOperationsState(self) -> None:
        self.operationsChanged.emit()

    def _refresh_operations_if_visible(self) -> None:
        result = self._dry_run.synchronize()
        if bool(result.get("completed")) and self.systemRunning:
            self.terminateSystem()
        if self._workspace != "addons" or self._selected_addon not in {
            "core.speech_timing",
            "core.performance",
        }:
            return
        self.operationsChanged.emit()

    def _restore_tutorial_widget_states(self) -> None:
        if self._tutorial_temporary_widget_states:
            self._application.addons.invoke_addon_capability(
                "nc.companion_orb_overlay",
                "companion_orb.tutorial.restore_settings",
                {"settings": dict(self._tutorial_temporary_widget_states)},
            )
        self._tutorial_temporary_widget_states.clear()

    @QtCore.Slot(str)
    def selectPreset(self, preset_name: str) -> None:
        name = str(preset_name or "").strip()
        result = self._application.config.update("active_preset_name", name)
        if result.accepted:
            try:
                self._save_native_session_or_raise()
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                self.notificationRaised.emit(
                    "error",
                    "Session setting was not saved",
                    str(error),
                )
                return
            self.sessionSetupChanged.emit()

    @QtCore.Slot(str)
    def loadPreset(self, preset_name: str) -> None:
        name = str(preset_name or "").strip()
        if not name:
            return
        builder = getattr(self, "_prompt_builder", None)
        if builder is not None and builder.applying:
            self.notificationRaised.emit("warning", "Prompt is being applied", "Wait for the prompt to finish saving before loading a preset.")
            return
        if self.systemRunning:
            self.notificationRaised.emit(
                "warning",
                "Preset loading is locked",
                "Terminate the active session before loading a preset.",
            )
            return
        try:
            self._preset_store.load(name)
            self._session_store.save()
            self.refreshProviderState()
            self.sessionSetupChanged.emit()
            self.personaChanged.emit()
            if builder is not None:
                builder.synchronize()
                builder.useApplied()
            self.notificationRaised.emit("success", "Preset loaded", name)
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit("error", "Preset was not loaded", str(error))

    @QtCore.Slot(str)
    def savePreset(self, preset_name: str) -> None:
        name = str(preset_name or "").strip()
        if not name:
            return
        try:
            self._preset_store.save(name)
            self._session_store.save()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit("error", "Preset was not saved", str(error))
            return
        self.sessionSetupChanged.emit()
        self.notificationRaised.emit("success", "Preset saved", name)

    @QtCore.Slot(str)
    def deletePreset(self, preset_name: str) -> None:
        name = str(preset_name or "").strip()
        if not name:
            return
        try:
            self._preset_store.delete(name)
        except (FileNotFoundError, OSError, ValueError) as error:
            self.notificationRaised.emit("error", "Preset was not deleted", str(error))
            return
        if str(self._application.config.get("active_preset_name", "") or "") == name:
            self._application.config.update("active_preset_name", "")
        self._session_store.save()
        self.sessionSetupChanged.emit()
        self.notificationRaised.emit("success", "Preset deleted", name)

    @QtCore.Slot(str, "QVariant")
    def setProviderField(self, field_id: str, value: Any) -> None:
        provider_id = self.viewedProviderId
        field_key = str(field_id or "").strip()
        if not field_key:
            return
        if provider_id == "lmstudio" and field_key == "context_length":
            length = lmstudio_runtime.configured_chat_context_length(value)
            if length is None:
                self.notificationRaised.emit(
                    "error", "Setting was not saved",
                    "Context Length must be a whole number from 512 to 1048576 tokens.",
                )
                return
            value = length
        settings_map = _plain(self._application.config.get("chat_provider_settings", {})) or {}
        provider_settings = dict(settings_map.get(provider_id) or {})
        if isinstance(value, str):
            value = value.strip()
            if value == "••••••••":
                return
        if value in (None, ""):
            provider_settings.pop(field_key, None)
        else:
            provider_settings[field_key] = value
        settings_map[provider_id] = provider_settings
        result = self._application.config.update("chat_provider_settings", settings_map)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Setting was not saved",
                str(getattr(result.failure, "message", "Could not update provider settings.")),
            )
            return
        try:
            chat_providers.set_provider_settings(settings_map)
        except Exception:
            pass
        self._session_store.save()
        self.refreshProviderState()

    @QtCore.Slot(str, "QVariant")
    def setGenerationField(self, field_id: str, value: Any) -> None:
        provider_id = self.viewedProviderId
        field_key = str(field_id or "").strip()
        if not field_key or field_key.startswith("_"):
            return
        field_spec = next(
            (
                dict(item)
                for item in list(self.viewedProvider.get("generationFields") or [])
                if str(item.get("id") or "") == field_key
            ),
            {},
        )
        kind = str(field_spec.get("kind") or "").strip().lower()
        try:
            if kind == "bool":
                value = bool(value)
            elif kind == "int":
                value = int(value)
            elif kind == "float":
                value = float(value)
        except (TypeError, ValueError):
            self.notificationRaised.emit(
                "error",
                "Generation setting was not saved",
                f"{field_spec.get('label') or field_key} has an invalid value.",
            )
            return
        settings_map = _plain(
            self._application.config.get("chat_provider_generation_settings", {})
        ) or {}
        provider_settings = dict(settings_map.get(provider_id) or {})
        provider_settings[field_key] = value
        settings_map[provider_id] = provider_settings
        updates = {"chat_provider_generation_settings": settings_map}
        # The serializer also reads the flat active-provider compatibility keys.
        # Commit both representations in one revision so stale defaults cannot win.
        if (provider_id == str(self._application.config.get("chat_provider", "") or "").strip().lower()
                and field_key in GENERATION_DEFAULT_KEYS):
            updates[field_key] = value
        changed = any(_plain(self._application.config.get(key)) != current
                      for key, current in updates.items())
        if not changed:
            # A focused editor can emit editingFinished again while a provider
            # refresh rebuilds it. Saving is safe (and retries failed disk writes),
            # but another refresh here recursively invalidates generationFields.
            try:
                self._save_native_session_or_raise()
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                self.notificationRaised.emit("error", "Generation setting was not saved", str(error))
            return
        result = (self._application.config.update_many(updates) if len(updates) > 1 else
                  self._application.config.update("chat_provider_generation_settings", settings_map))
        if result.accepted:
            try:
                self._save_native_session_or_raise()
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                self.notificationRaised.emit(
                    "error",
                    "Generation setting was not saved",
                    str(error),
                )
                return
            self.refreshProviderState()
        else:
            self.notificationRaised.emit(
                "error",
                "Generation setting was not saved",
                str(getattr(result.failure, "message", "Could not update generation settings.")),
            )

    @QtCore.Slot(str)
    def selectModel(self, model_name: str) -> bool:
        selected = str(model_name or "").strip()
        if not selected:
            return False
        supports_images = infer_model_supports_images(selected)
        for item in self._models:
            item_id = str(
                item.get("id") or item.get("model") or item.get("name") or ""
            ).strip()
            if item_id == selected:
                supports_images = _model_catalog_entry_supports_images(item)
                break

        provider_id = self.viewedProviderId
        settings_map = _plain(
            self._application.config.get("chat_provider_settings", {})
        ) or {}
        provider_settings = dict(settings_map.get(provider_id) or {})
        provider_settings.update(
            {
                "model_name": selected,
                "model_supports_images": supports_images,
            }
        )
        settings_map[provider_id] = provider_settings
        updates: dict[str, Any] = {"chat_provider_settings": settings_map}
        if provider_id == self.activeProviderId:
            updates.update(
                {
                    "model_name": selected,
                    "model_supports_images": supports_images,
                }
            )
        result = self._application.config.update_many(updates)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Model selection was not saved",
                str(getattr(result.failure, "message", "Could not update the selected model.")),
            )
            return False
        try:
            chat_providers.set_provider_settings(settings_map)
        except Exception:
            pass
        saved = self._session_store.save()
        self.refreshProviderState()
        return saved is not False

    @QtCore.Slot(bool)
    def setModelRequiresTools(self, enabled: bool) -> None:
        settings_map = _plain(self._application.config.get("chat_provider_settings", {})) or {}
        provider_id = self.viewedProviderId
        provider_settings = dict(settings_map.get(provider_id) or {})
        provider_settings["model_requires_tools"] = bool(enabled)
        settings_map[provider_id] = provider_settings
        result = self._application.config.update_many({"chat_provider_settings": settings_map})
        if not result.accepted:
            self.notificationRaised.emit("error", "Tool model filter was not saved",
                str(getattr(result.failure, "message", "Could not update the model filter.")))
            return
        try:
            chat_providers.set_provider_settings(settings_map)
        except Exception:
            pass
        self._session_store.save()
        self.refreshProviderState()
        self.modelCatalogChanged.emit()

    @QtCore.Slot(bool)
    def setModelRequiresVision(self, enabled: bool) -> None:
        required = bool(enabled)
        provider_id = self.viewedProviderId
        settings_map = _plain(
            self._application.config.get("chat_provider_settings", {})
        ) or {}
        provider_settings = dict(settings_map.get(provider_id) or {})
        provider_settings["model_requires_vision"] = required
        settings_map[provider_id] = provider_settings
        updates: dict[str, Any] = {"chat_provider_settings": settings_map}
        if provider_id == self.activeProviderId:
            updates["model_requires_vision"] = required
        result = self._application.config.update_many(updates)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Vision model filter was not saved",
                str(getattr(result.failure, "message", "Could not update the model filter.")),
            )
            return
        try:
            chat_providers.set_provider_settings(settings_map)
        except Exception:
            pass

        compatible_names = [
            str(item.get("id") or item.get("model") or item.get("name") or "")
            for item in _filter_model_catalog(self._models, require_vision=required,
                                             require_tools=self.modelRequiresTools)
        ]
        selected = str(provider_settings.get("model_name") or "").strip()
        if required and not self.modelRequiresTools and compatible_names and selected not in compatible_names:
            self.selectModel(compatible_names[0])
        else:
            self.refreshProviderState()
        self._session_store.save()
        self.modelCatalogChanged.emit()

    @QtCore.Slot()
    def refreshModels(self) -> None:
        if self._model_refresh_in_flight or self._provider_test_in_flight:
            return
        provider_id = self.viewedProviderId
        self._model_refresh_in_flight = True
        self._model_refresh_provider = provider_id
        self._model_refresh_message = ""
        self.modelRefreshChanged.emit()

        future = self._executor.submit(
            self._application.providers.list_models,
            provider_id,
            quiet=True,
        )

        def complete(task: Any) -> None:
            try:
                items = [_plain(item) for item in task.result()]
                self._modelsReceived.emit(provider_id, items, "")
            except BaseException as error:
                self._modelsReceived.emit(provider_id, [], str(error))

        future.add_done_callback(complete)

    @QtCore.Slot()
    def testViewedProvider(self) -> None:
        """Run the provider facade's existing safe catalog probe off the UI thread."""

        if self._provider_test_in_flight or self._model_refresh_in_flight:
            return
        provider_id = self.viewedProviderId
        self._provider_test_in_flight = True
        self._provider_test_provider = provider_id
        self.providerTestChanged.emit()

        future = self._executor.submit(
            self._application.providers.list_models,
            provider_id,
            quiet=False,
        )

        def complete(task: Any) -> None:
            try:
                items = [_plain(item) for item in task.result()]
                self._providerTestReceived.emit(provider_id, items, "")
            except BaseException as error:
                self._providerTestReceived.emit(provider_id, [], str(error))

        future.add_done_callback(complete)

    @QtCore.Slot()
    def initializeSystem(self) -> None:
        if getattr(self, '_room_blocks_main_chat', lambda: False)():
            self.notificationRaised.emit('warning', 'Room is active',
                'Stop the room before initializing normal chat.')
            return
        if self.systemRunning or self._application_closing:
            return
        if self.runtimeCleanupPending:
            self.notificationRaised.emit(
                "warning",
                "Runtime cleanup is incomplete",
                "Retry cleanup before initializing NeuralCompanion again.",
            )
            return
        if not self._runtime_controller.start():
            self.notificationRaised.emit(
                "warning",
                "Runtime is already starting",
                "Wait for the current startup operation to finish.",
            )

    @QtCore.Slot()
    def terminateSystem(self) -> None:
        if not self.systemRunning and not self.runtimeStarting and not self.runtimeCleanupPending:
            return
        memory_workspace = getattr(self, "_memory_workspace", None)
        if memory_workspace is not None:
            memory_workspace.invalidate()
        try:
            self._runtime_controller.request_stop()
        except RuntimeError as error:
            self.notificationRaised.emit("error", "Runtime did not stop", str(error))

    def _queue_text_message(self, text: str) -> bool:
        if getattr(self, '_room_blocks_main_chat', lambda: False)():
            self.notificationRaised.emit('warning', 'Room is active',
                'Use the room conversation to send a message, or stop the room first.')
            return False
        message = str(text or "").strip()
        if not message:
            return False
        if not self.systemRunning:
            self.notificationRaised.emit(
                "warning",
                "Initialize NeuralCompanion first",
                "The runtime must be active before a message can be queued.",
            )
            return False
        result = self._application.chat.queue_typed(
            message,
            metadata={"source": "qml_composer"},
        )
        if not result.accepted or not bool(dict(result.value or {}).get("queued", False)):
            failure = getattr(result, "failure", None)
            detail = str(
                getattr(failure, "message", "")
                or dict(result.value or {}).get("reason", "Could not queue the message.")
            )
            self.notificationRaised.emit("error", "Message was not queued", detail)
            return False
        self.refreshConversationState()
        return True

    @QtCore.Slot(str)
    def submitText(self, text: str) -> None:
        self._queue_text_message(text)

    @staticmethod
    def _local_image_path(url_or_path: str) -> Path:
        raw = str(url_or_path or "").strip()
        if not raw:
            raise ValueError("No image was provided.")
        url = QtCore.QUrl(raw)
        candidate = Path(url.toLocalFile()) if url.isLocalFile() else Path(raw)
        try:
            resolved = candidate.expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("The dropped image could not be found.") from exc
        if not resolved.is_file():
            raise ValueError("The dropped item is not a file.")
        if resolved.suffix.lower() not in _CHAT_IMAGE_EXTENSIONS:
            raise ValueError("Use a PNG, JPEG, WebP, BMP, or GIF image.")
        reader = QtGui.QImageReader(str(resolved))
        if not reader.canRead():
            raise ValueError("The selected file is not a readable image.")
        return resolved

    @QtCore.Slot(result=bool)
    def pasteConversationImage(self) -> bool:
        """Consume image paste; return False to leave ordinary text paste to Qt."""
        clipboard = QtGui.QGuiApplication.clipboard()
        mime = clipboard.mimeData() if clipboard is not None else None
        if mime is None or not mime.hasImage():
            return False
        # Image paste appends without replacing existing attachments or text.
        if self.conversationEditMode:
            return True
        image = clipboard.image()
        try:
            if image.isNull():
                raise ValueError("The clipboard does not contain a readable image.")
            directory = _APP_ROOT / "runtime" / "clipboard_inputs"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"clipboard_{uuid.uuid4().hex}.png"
            if not image.save(str(path), "PNG"):
                raise OSError("The clipboard image could not be saved.")
            self.stageConversationImage(str(path))
        except (OSError, ValueError) as exc:
            self.notificationRaised.emit("warning", "Image was not attached", str(exc))
        return True

    @staticmethod
    def _pending_image_rows(attachment):
        rows = attachment.get("images")
        return [dict(row) for row in rows] if isinstance(rows, (list, tuple)) else ([dict(attachment)] if attachment else [])

    @QtCore.Slot(str, result=bool)
    def stageConversationImage(self, url_or_path: str) -> bool:
        return QmlApplicationBridge.stageConversationImages(self, [url_or_path])

    @QtCore.Slot("QVariantList", result=bool)
    def stageConversationImages(self, urls: list) -> bool:
        if self.conversationEditMode:
            return False
        rows = QmlApplicationBridge._pending_image_rows(self._conversation_attachment)
        try:
            # Validate the whole selection before changing the pending message.
            for url in urls:
                path = self._local_image_path(str(url))
                if any(row.get("path") == str(path) for row in rows):
                    continue
                size = max(0, int(path.stat().st_size))
                rows.append({
                    "active": True,
                    "path": str(path),
                    "url": QtCore.QUrl.fromLocalFile(str(path)).toString(),
                    "name": path.name,
                    "sizeBytes": size,
                    "sizeLabel": f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024 else f"{max(1, (size + 1023) // 1024)} KB",
                })
        except (OSError, ValueError) as exc:
            self.notificationRaised.emit("warning", "Image was not attached", str(exc))
            return False
        if not rows:
            return False
        self._conversation_attachment = {**rows[0], "images": rows}
        self.conversationAttachmentChanged.emit()
        return True

    @QtCore.Slot(int)
    def removeConversationImage(self, index: int) -> None:
        rows = QmlApplicationBridge._pending_image_rows(self._conversation_attachment)
        if not 0 <= index < len(rows):
            return
        rows.pop(index)
        self._conversation_attachment = {**rows[0], "images": rows} if rows else {}
        self.conversationAttachmentChanged.emit()

    @QtCore.Slot()
    def clearConversationAttachment(self) -> None:
        if not self._conversation_attachment:
            return
        self._conversation_attachment = {}
        self.conversationAttachmentChanged.emit()

    @QtCore.Slot(str, result=bool)
    def stageVisualReplyComment(self, image_url: str) -> bool:
        if not self.stageConversationImage(str(image_url or "")):
            return False
        self.notificationRaised.emit(
            "success",
            "Visual Reply attached",
            "Add a question or comment, then send it to the model.",
        )
        return True

    @QtCore.Slot(int, result=bool)
    def addVisualReplyVariation(self, history_index: int) -> bool:
        if not self.systemRunning:
            self.notificationRaised.emit(
                "warning",
                "Initialize NeuralCompanion first",
                "The runtime must be active before a visual variation can be generated.",
            )
            return False
        history = self._application.chat.history()
        position = int(history_index)
        if position < 0 or position >= len(history):
            return False
        item = dict(_plain(history[position]) or {})
        metadata = dict(item.get("metadata") or {})
        role = str(item.get("role") or "").strip().lower()
        origin = str(
            item.get("origin") or metadata.get("origin") or ""
        ).strip().lower()
        prompt = str(
            item.get("visual_reply_prompt")
            or metadata.get("visual_reply_prompt")
            or ""
        ).strip()
        if role != "assistant" or origin == "input" or not prompt:
            self.notificationRaised.emit(
                "warning",
                "Variation is unavailable",
                "This image does not have a reusable Visual Reply prompt.",
            )
            return False
        original_request_id = str(
            item.get("visual_reply_request_id")
            or metadata.get("visual_reply_request_id")
            or ""
        ).strip()
        runtime_config = dict(self._application.config.snapshot().values)
        runtime_config["visual_reply_mode"] = "auto"
        runtime_config["visual_replies_enabled"] = True
        request_id = f"visual_variation_{int(time.time() * 1000)}"
        try:
            accepted = bool(
                self._application.addon_visual_request.request_generation(
                    prompt,
                    source_text=str(item.get("content") or ""),
                    request_id=request_id,
                    runtime_config_override=runtime_config,
                    asset_metadata={
                        "append_visual_variation": True,
                        "variation_of_request_id": original_request_id,
                    },
                )
            )
        except Exception as error:
            self.notificationRaised.emit(
                "error",
                "Visual variation was not started",
                str(error),
            )
            return False
        if not accepted:
            self.notificationRaised.emit(
                "error",
                "Visual variation was not started",
                "Check the active Visual Reply provider and its credentials.",
            )
            return False
        self.notificationRaised.emit(
            "success",
            "Visual variation started",
            "The original image will remain in the conversation.",
        )
        return True

    @QtCore.Slot(str, result=bool)
    def copyVisualReplyImage(self, url_or_path: str) -> bool:
        try:
            path = self._local_image_path(url_or_path)
        except (OSError, ValueError) as error:
            self.notificationRaised.emit(
                "error", "Image was not copied", str(error)
            )
            return False

        def worker() -> QtGui.QImage:
            image = QtGui.QImage(str(path))
            if image.isNull():
                raise ValueError("The generated image could not be read.")
            return image

        future = self._runtime_executor.submit(worker)

        def complete(task: Any) -> None:
            try:
                self._visualAssetCopied.emit(task.result(), "")
            except BaseException as error:
                self._visualAssetCopied.emit(None, str(error))

        future.add_done_callback(complete)
        return True

    @QtCore.Slot(str, str, result=bool)
    def saveVisualReplyImage(self, source_url: str, target_url: str) -> bool:
        try:
            source = self._local_image_path(source_url)
            target_qurl = QtCore.QUrl(str(target_url or ""))
            target = (
                Path(target_qurl.toLocalFile())
                if target_qurl.isLocalFile()
                else Path(str(target_url or ""))
            ).expanduser()
            if not str(target).strip():
                raise ValueError("No save location was selected.")
            if target.suffix.lower() != source.suffix.lower():
                target = target.with_suffix(source.suffix)
            target = target.resolve()
            if not target.parent.is_dir():
                raise ValueError("The selected save folder does not exist.")
        except (OSError, RuntimeError, ValueError) as error:
            self.notificationRaised.emit(
                "error", "Image was not saved", str(error)
            )
            return False

        def worker() -> str:
            if source.resolve() != target:
                shutil.copy2(source, target)
            return str(target)

        future = self._runtime_executor.submit(worker)

        def complete(task: Any) -> None:
            try:
                self._visualAssetSaved.emit(True, str(task.result()))
            except BaseException as error:
                self._visualAssetSaved.emit(False, str(error))

        future.add_done_callback(complete)
        return True

    @QtCore.Slot(str, result=bool)
    def openVisualReplyLocation(self, url_or_path: str) -> bool:
        try:
            path = self._local_image_path(url_or_path)
        except (OSError, ValueError) as error:
            self.notificationRaised.emit(
                "error", "Image folder was not opened", str(error)
            )
            return False
        opened = QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(path.parent))
        )
        if not opened:
            self.notificationRaised.emit(
                "error",
                "Image folder was not opened",
                str(path.parent),
            )
        return bool(opened)

    @QtCore.Slot(int, result=bool)
    def copyConversationMessage(self, history_index: int) -> bool:
        history = self._application.chat.history()
        position = int(history_index)
        if position < 0 or position >= len(history):
            return False
        item = dict(_plain(history[position]) or {})
        text = str(item.get("content") or "")
        if not text:
            return False
        clipboard = QtGui.QGuiApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(text)
        metadata = dict(item.get("metadata") or {})
        role = str(item.get("role") or "").strip().lower()
        origin = str(item.get("origin") or metadata.get("origin") or "").strip().lower()
        assistant_response = role == "assistant" and origin != "input"
        self.notificationRaised.emit(
            "success",
            "Response copied" if assistant_response else "Message copied",
            (
                "The assistant response is on the clipboard."
                if assistant_response
                else "Your message is on the clipboard."
            ),
        )
        return True

    @QtCore.Slot(int, result=bool)
    def replayConversationMessage(self, history_index: int) -> bool:
        history = self._application.chat.history()
        position = int(history_index)
        if position < 0 or position >= len(history):
            return False
        item = dict(_plain(history[position]) or {})
        metadata = dict(item.get("metadata") or {})
        role = str(item.get("role") or "").strip().lower()
        origin = str(item.get("origin") or metadata.get("origin") or "").strip().lower()
        if role != "assistant" or origin == "input":
            return False
        result = self._application.replay.replay_assistant_at_history_index(position)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Response could not be replayed",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "The selected assistant response is not available for replay.",
                    )
                ),
            )
            return False
        self.refreshLiveSessionState()
        return True

    @QtCore.Slot(result=bool)
    def stopConversationReplay(self) -> bool:
        result = self._application.replay.cancel_all("user_stopped_replay")
        if not result.accepted:
            self.notificationRaised.emit("error", "Replay could not be stopped",
                                         str(getattr(result.failure, "message", "") or "Could not stop replay."))
        self.refreshLiveSessionState()
        return bool(result.accepted)

    @QtCore.Property(bool, notify=conversationMessageDeletionAvailabilityChanged)
    def conversationMessageDeletionAvailable(self) -> bool:
        owner = self._application.playback
        playback = getattr(owner, 'activity_snapshot', owner.snapshot)()
        return not (self._application.chat.has_active_turns() or playback.current
                    or playback.next or playback.stopping)

    @QtCore.Property('QVariantMap', notify=conversationActionsChanged)
    def conversationActionsState(self):
        return dict(self._conversation_actions_state)

    def _refresh_conversation_actions(self):
        state = self._application.chat.conversation_actions_snapshot()
        if self._conversation_action_future is not None:
            state = dict(state, end_waiting=None, disabled_reason='action_pending')
        if state != self._conversation_actions_state:
            self._conversation_actions_state = state
            self.conversationActionsChanged.emit()

    @QtCore.Slot(str, int, int, result=bool)
    def endWaitingForMessage(self, message_id, expected_revision, expected_session):
        from core.runtime.conversation_actions import ConversationActionRequest, ConversationActionTarget
        if self._conversation_action_future is not None or self._message_deletion_ui_busy():
            return False
        target = dict(message_id=message_id, revision=expected_revision, session_generation=expected_session)
        if self._application.chat.conversation_actions_snapshot().get('end_waiting') != target:
            self.notificationRaised.emit('warning', 'Reply not started', 'The conversation changed or is still busy.')
            return False
        request = ConversationActionRequest(uuid.uuid4().hex, 'end_waiting', ConversationActionTarget(**target))
        future = self._application.chat.conversation_action(request)
        self._conversation_action_future = future
        self._refresh_conversation_actions()
        future.add_done_callback(lambda done: self._conversationActionReceived.emit(done))
        return True

    @QtCore.Slot(object)
    def _on_conversation_action_received(self, future):
        if future is not self._conversation_action_future:
            return
        self._conversation_action_future = None
        try:
            result = future.result()  # Already settled; never blocks the Qt thread.
            if result.status != 'accepted':
                self.notificationRaised.emit('warning', 'Reply not started', result.reason or result.status)
        except Exception:
            self.notificationRaised.emit('warning', 'Reply not started', 'Conversation action unavailable.')
        self._refresh_conversation_actions()
        self.refreshConversationState()

    def _message_deletion_ui_busy(self) -> bool:
        return bool(self._conversation_context_operation or self._conversation_edit_mode
                    or int(self._conversation_draft_state.get('inlineResponseHistoryIndex', -1)) >= 0
                    or not self.conversationMessageDeletionAvailable)

    @QtCore.Slot(int, result='QVariantMap')
    def prepareConversationMessageDeletion(self, history_index: int) -> dict[str, Any]:
        if self._message_deletion_ui_busy():
            self.notificationRaised.emit('warning', 'Message cannot be deleted yet',
                                         'Finish the current reply, playback or chat edit first.')
            return {}
        snapshot = self._application.chat.snapshot()
        if not 0 <= history_index < len(snapshot.messages):
            return {}
        message = snapshot.messages[history_index]
        if message.role.lower() not in {'user', 'assistant'}:
            return {}
        return dict(messageId=message.message_id, revision=snapshot.revision,
                    session=snapshot.session_generation.value, preview=message.content[:280],
                    role=message.role)

    @QtCore.Slot(str, int, int, bool, result=bool)
    def deleteConversationMessage(self, message_id: str, expected_revision: int,
                                  expected_session: int, remove_memories: bool) -> bool:
        # Retain the Qt slot signature for older callers; standard deletion
        # always reconciles associated memories with the edited conversation.
        remove_memories = True
        if self._message_deletion_ui_busy():
            self.notificationRaised.emit('warning', 'Message was not deleted',
                                         'Finish the current reply, playback or chat edit first.')
            return False
        result = self._application.chat.delete_message(message_id, expected_revision=expected_revision,
                    expected_session=expected_session, remove_memories=remove_memories)
        if not result.accepted or not result.value or not result.value.get('deleted'):
            self.notificationRaised.emit('error', 'Message was not deleted',
                str(getattr(result.failure, 'message', 'Deletion could not be completed.')))
            return False
        memory = dict(result.value.get('memory') or {})
        self._conversation_revision = -1
        self.refreshConversationState()
        details = 'The message and its attachments were removed from this conversation.'
        unknown = int(memory.get('unknown_provenance', 0))
        shared = int(memory.get('shared_assets_preserved', 0))
        if remove_memories and (unknown or shared):
            details += f' Preserved {unknown} memory item(s) with unknown source and {shared} shared image asset(s).'
        if not remove_memories:
            details += ' Learned memories were kept and may still be recalled.'
        self.notificationRaised.emit('warning' if remove_memories and (unknown or shared) else 'success',
                                     'Message deleted', details)
        return True

    @QtCore.Slot(int, str, result=bool)
    def updateConversationAssistantMessage(
        self,
        history_index: int,
        content: str,
    ) -> bool:
        return QmlApplicationBridge._update_conversation_message(self, history_index, content)

    @QtCore.Slot(int, str, result=bool)
    def updateConversationMessage(self, history_index: int, content: str) -> bool:
        return QmlApplicationBridge._update_conversation_message(
            self, history_index, content, allow_user=True
        )

    def _update_conversation_message(
        self, history_index: int, content: str, *, allow_user: bool = False
    ) -> bool:
        snapshot = self._application.chat.snapshot()
        expected_revision = int(getattr(snapshot, "revision", -1))
        history = tuple(self._application.chat.history())
        draft = getattr(self, "_conversation_draft_state", {})
        if int(draft.get("inlineResponseHistoryIndex", -1)) == int(history_index):
            if not QmlApplicationBridge._validate_inline_response_draft(self, history):
                self.notificationRaised.emit(
                    "warning",
                    "Response was not changed",
                    "The original response changed while its draft was being edited.",
                )
                return False
        try:
            replacement = _conversation_history_with_edited_assistant(
                history,
                int(history_index),
                str(content or ""),
                edited_at=time.time(),
                allow_user=allow_user,
            )
        except (IndexError, ValueError) as error:
            self.notificationRaised.emit(
                "warning",
                "Response was not changed",
                str(error),
            )
            return False
        result = self._application.chat.edit_history(
            replacement,
            expected_revision=expected_revision,
            source_indices=tuple(range(1, len(history)+1)),
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Response edit could not be saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "The conversation changed while the response was being edited.",
                    )
                ),
            )
            return False
        # This revision-checked edit keeps row order, even when replacing an
        # untagged message assigns a fresh opaque ID. Preserve the visual window
        # before projecting it, rather than falling back to the newest batch.
        self._conversation_window.remap_edited_message(
            snapshot.messages[int(history_index)].message_id,
            result.value.messages[int(history_index)].message_id,
        )
        if int(draft.get("inlineResponseHistoryIndex", -1)) == int(history_index):
            self.clearConversationInlineResponseDraft()
        self._conversation_revision = -1
        self.refreshConversationState()
        self.notificationRaised.emit(
            "success",
            "Message updated" if allow_user else "Response updated",
            "The edited message has been saved in the conversation." if allow_user
            else "Replay now uses the saved edited response.",
        )
        return True

    @QtCore.Slot()
    def beginConversationEdit(self) -> None:
        if self._conversation_edit_mode:
            return
        source: list[dict[str, Any]] = []
        decorated: list[dict[str, Any]] = []
        edit_revision = -1
        for _attempt in range(2):
            self._conversation_revision = -1
            self.refreshConversationState()
            source = [
                dict(_plain(item) or {})
                for item in self._application.chat.history()
            ]
            edit_revision = int(
                getattr(self._application.chat.snapshot(), "revision", -1)
            )
            decorated = [dict(item) for item in self._conversation_messages]
            if (
                edit_revision == self._conversation_revision
                and all(0 <= int(item["historyIndex"]) < len(source) for item in decorated)
            ):
                break
        else:
            self.notificationRaised.emit(
                "warning",
                "Conversation is still changing",
                "Wait for the active turn to finish before entering edit mode.",
            )
            return
        for index, item in enumerate(decorated):
            item["index"] = index
            item["selected"] = False
        self._conversation_edit_source = source
        self._conversation_edit_messages = decorated
        self._conversation_edit_deleted = set()
        self._conversation_edit_anchor = -1
        self._conversation_edit_revision = edit_revision
        self._conversation_edit_mode = True
        self.conversationEditChanged.emit()

    @QtCore.Slot(int, str)
    def setConversationEditContent(self, index: int, content: str) -> None:
        if not self._conversation_edit_mode:
            return
        position = int(index)
        if position < 0 or position >= len(self._conversation_edit_messages):
            return
        value = str(content or "")
        if self._conversation_edit_messages[position]["content"] == value:
            return
        self._conversation_edit_messages[position]["content"] = value
        display_model = getattr(self, "_conversation_display_model", None)
        if display_model is not None:
            display_model.update_row(position, _plain(self._conversation_edit_messages[position]))

    @QtCore.Slot(int, bool)
    def selectConversationEditMessage(self, index: int, extend: bool) -> None:
        if not self._conversation_edit_mode:
            return
        rows = self._conversation_edit_messages
        position = int(index)
        if not 0 <= position < len(rows):
            return
        anchor = self._conversation_edit_anchor
        if extend and 0 <= anchor < len(rows):
            start, end = sorted((anchor, position))
            for row in rows[start:end + 1]:
                row["selected"] = True
        else:
            rows[position]["selected"] = not bool(rows[position].get("selected"))
            self._conversation_edit_anchor = position
        self.conversationEditChanged.emit()

    @QtCore.Slot()
    def clearConversationEditSelection(self) -> None:
        for row in self._conversation_edit_messages:
            row["selected"] = False
        self._conversation_edit_anchor = -1
        self.conversationEditChanged.emit()

    @QtCore.Slot()
    def deleteSelectedConversationEditMessages(self) -> None:
        if not self._conversation_edit_mode or not self.conversationEditSelectionCount:
            return
        self._conversation_edit_deleted.update(
            int(row["historyIndex"]) for row in self._conversation_edit_messages if row.get("selected"))
        self._conversation_edit_messages = [row for row in self._conversation_edit_messages
                                            if not row.get("selected")]
        for index, row in enumerate(self._conversation_edit_messages):
            row["index"] = index
        self._conversation_edit_anchor = -1
        self.conversationEditChanged.emit()

    @QtCore.Slot()
    def applyConversationEdit(self) -> None:
        if not self._conversation_edit_mode:
            return
        current_snapshot = self._application.chat.snapshot()
        current_revision = int(getattr(current_snapshot, "revision", -1))
        if (
            current_revision != self._conversation_edit_revision
            or any(not 0 <= int(item["historyIndex"]) < len(self._conversation_edit_source)
                   for item in self._conversation_edit_messages)
        ):
            self.notificationRaised.emit(
                "error",
                "Conversation edit could not be applied",
                "The conversation changed while edit mode was active. Cancel and try again.",
            )
            return
        replacement = [dict(raw) for raw in self._conversation_edit_source]
        for edited in self._conversation_edit_messages:
            replacement[int(edited["historyIndex"])]["content"] = str(edited.get("content") or "")
        replacement = [raw for index, raw in enumerate(replacement)
                       if index not in self._conversation_edit_deleted]
        result = self._application.chat.edit_history(tuple(replacement), expected_revision=current_revision,
            source_indices=tuple(n+1 for n in range(len(self._conversation_edit_source))
                                 if n not in self._conversation_edit_deleted))
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Conversation edit could not be applied",
                str(getattr(result.failure, "message", "Could not replace conversation history.")),
            )
            return
        # Canonical replacement advances the session and may replace every ID.
        # Keep the existing visual window attached to surviving rows before
        # refreshing it; deleted focus endpoints use their nearest predecessor.
        next_position = 0
        surviving = result.value.messages
        mapped = surviving[0] if surviving else None
        for index, previous in enumerate(current_snapshot.messages):
            if index not in self._conversation_edit_deleted:
                mapped = surviving[next_position]
                next_position += 1
            if mapped is not None:
                self._conversation_window.remap_edited_message(previous.message_id, mapped.message_id)
        self._conversation_window.generation = result.value.session_generation
        self._conversation_edit_mode = False
        self._conversation_edit_revision = -1
        self._conversation_edit_source = []
        self._conversation_edit_messages = []
        self._conversation_edit_deleted = set()
        self._conversation_edit_anchor = -1
        # Publish the committed projection before closing the draft view;
        # publishing the pre-edit history here would reinsert deleted rows.
        self._conversation_revision = -1
        self.refreshConversationState()
        self.conversationEditChanged.emit()
        self.notificationRaised.emit(
            "success",
            "Conversation updated",
            "The edited messages now own the canonical conversation history.",
        )

    @QtCore.Slot()
    def cancelConversationEdit(self) -> None:
        if not self._conversation_edit_mode:
            return
        self._conversation_edit_mode = False
        self._conversation_edit_revision = -1
        self._conversation_edit_source = []
        self._conversation_edit_messages = []
        self._conversation_edit_deleted = set()
        self._conversation_edit_anchor = -1
        self.conversationEditChanged.emit()
        QmlApplicationBridge._queue_conversation_refresh(self)

    @staticmethod
    def _set_conversation_draft_value(owner: Any, key: str, value: Any) -> None:
        state = dict(owner._conversation_draft_state)
        if state.get(key) == value:
            return
        state[key] = value
        owner._conversation_draft_state = state
        owner.conversationDraftStateChanged.emit()

    @QtCore.Slot(str)
    def setConversationComposerDraft(self, text: str) -> None:
        QmlApplicationBridge._set_conversation_draft_value(
            self, "composerText", str(text or "")
        )

    @QtCore.Slot()
    def clearConversationComposerDraft(self) -> None:
        QmlApplicationBridge.setConversationComposerDraft(self, "")

    @QtCore.Slot(str)
    def setConversationCopiedPromptDraft(self, text: str) -> None:
        QmlApplicationBridge._set_conversation_draft_value(
            self, "copiedPromptText", str(text or "")
        )

    @QtCore.Slot()
    def clearConversationCopiedPromptDraft(self) -> None:
        QmlApplicationBridge.setConversationCopiedPromptDraft(self, "")

    @QtCore.Slot(int, str)
    def beginConversationInlineResponseDraft(self, history_index: int, text: str) -> None:
        history = tuple(self._application.chat.history())
        position = int(history_index)
        if position < 0 or position >= len(history):
            QmlApplicationBridge.clearConversationInlineResponseDraft(self)
            return
        self._conversation_inline_response_identity = _conversation_inline_edit_identity(
            history[position]
        )
        state = dict(self._conversation_draft_state)
        next_state = {
            **state,
            "inlineResponseHistoryIndex": position,
            "inlineResponseText": str(text or ""),
        }
        if next_state == state:
            return
        self._conversation_draft_state = next_state
        self.conversationDraftStateChanged.emit()

    @QtCore.Slot(str)
    def setConversationInlineResponseDraftText(self, text: str) -> None:
        QmlApplicationBridge._set_conversation_draft_value(
            self, "inlineResponseText", str(text or "")
        )

    @QtCore.Slot()
    def clearConversationInlineResponseDraft(self) -> None:
        self._conversation_inline_response_identity = None
        state = dict(self._conversation_draft_state)
        next_state = {
            **state,
            "inlineResponseHistoryIndex": -1,
            "inlineResponseText": "",
        }
        if next_state == state:
            return
        self._conversation_draft_state = next_state
        self.conversationDraftStateChanged.emit()
        QmlApplicationBridge._queue_conversation_refresh(self)
        QmlApplicationBridge._flush_deferred_conversation_turn(self)

    @staticmethod
    def _validate_inline_response_draft(
        owner: Any,
        history: Iterable[Mapping[str, Any]],
    ) -> bool:
        state = getattr(owner, "_conversation_draft_state", {})
        position = int(state.get("inlineResponseHistoryIndex", -1))
        if position < 0:
            return True
        messages = tuple(history)
        identity = getattr(owner, "_conversation_inline_response_identity", None)
        if position < len(messages) and identity == _conversation_inline_edit_identity(
            messages[position]
        ):
            return True
        QmlApplicationBridge.clearConversationInlineResponseDraft(owner)
        return False

    @QtCore.Slot(result=bool)
    def validateConversationInlineResponseDraft(self) -> bool:
        if int(self._conversation_draft_state.get("inlineResponseHistoryIndex", -1)) < 0:
            return True
        return QmlApplicationBridge._validate_inline_response_draft(
            self, self._application.chat.history()
        )

    def _set_conversation_console_preference(
        self,
        config_key: str,
        enabled: bool,
        error_title: str,
    ) -> None:
        selected = bool(enabled)
        if bool(self._application.config.get(config_key, True)) == selected:
            return
        result = self._application.config.update(config_key, selected)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                error_title,
                str(getattr(result.failure, "message", "Could not update the preference.")),
            )
            return
        try:
            if not self._session_store.save():
                raise RuntimeError("Could not save the session setting.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit("error", error_title, str(error))
            return
        self.configurationChanged.emit()

    @QtCore.Slot(bool)
    def setConversationLiveSessionVisible(self, visible: bool) -> None:
        QmlApplicationBridge._set_conversation_console_preference(
            self,
            "conversation_live_session_visible",
            visible,
            "Live session card preference was not saved",
        )

    @QtCore.Slot(bool)
    def setConversationConsoleVisible(self, visible: bool) -> None:
        QmlApplicationBridge._set_conversation_console_preference(
            self,
            "conversation_console_visible",
            visible,
            "Conversation split preference was not saved",
        )

    @QtCore.Slot(bool)
    def setConversationConsoleAutoScroll(self, enabled: bool) -> None:
        QmlApplicationBridge._set_conversation_console_preference(
            self,
            "conversation_console_auto_scroll",
            enabled,
            "Console autoscroll preference was not saved",
        )

    @QtCore.Slot(int)
    def setConversationConsoleFontSize(self, size: int) -> None:
        selected = _normalize_console_font_size(size)
        previous = self.conversationConsoleFontSize
        if selected == previous:
            return
        result = self._application.config.update("conversation_console_font_size", selected)
        if not result.accepted:
            self.notificationRaised.emit(
                "error", "Console font size was not saved",
                str(getattr(result.failure, "message", "Could not update the console font size.")),
            )
            return
        try:
            if not self._session_store.save():
                raise RuntimeError("Could not save the console font size.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._application.config.update("conversation_console_font_size", previous)
            self.notificationRaised.emit("error", "Console font size was not saved", str(error))
        self.configurationChanged.emit()

    @QtCore.Slot()
    def toggleConversationResetButtonVisible(self) -> None:
        QmlApplicationBridge._set_conversation_console_preference(
            self,
            "conversation_reset_button_visible",
            not self.conversationResetButtonVisible,
            "Reset button preference was not saved",
        )

    @QtCore.Slot()
    def toggleConversationSaveButtonVisible(self) -> None:
        QmlApplicationBridge._set_conversation_console_preference(
            self,
            "conversation_save_button_visible",
            not self.conversationSaveButtonVisible,
            "Save button preference was not saved",
        )

    @QtCore.Slot()
    def toggleConversationSaveAsButtonVisible(self) -> None:
        QmlApplicationBridge._set_conversation_console_preference(
            self,
            "conversation_save_as_button_visible",
            not self.conversationSaveAsButtonVisible,
            "Save as button preference was not saved",
        )

    @QtCore.Slot()
    def toggleConversationLoadButtonVisible(self) -> None:
        QmlApplicationBridge._set_conversation_console_preference(
            self,
            "conversation_load_button_visible",
            not self.conversationLoadButtonVisible,
            "Load button preference was not saved",
        )

    @QtCore.Slot()
    def toggleConversationMemoryButtonVisible(self) -> None:
        QmlApplicationBridge._set_conversation_console_preference(
            self,
            "conversation_memory_button_visible",
            not self.conversationMemoryButtonVisible,
            "Memory button preference was not saved",
        )

    @QtCore.Slot()
    def toggleConversationWebSearchVisible(self) -> None:
        QmlApplicationBridge._set_conversation_console_preference(
            self,
            "conversation_web_search_visible",
            not self.conversationWebSearchVisible,
            "Web Search control preference was not saved",
        )

    @QtCore.Slot(bool, result="QVariantMap")
    def setConversationWebSearchEnabled(self, enabled: bool) -> dict[str, Any]:
        selected = bool(enabled)
        status = QmlApplicationBridge._conversation_web_search_status(self)
        if status is None:
            self.notificationRaised.emit(
                "warning",
                "Web Search addon is unavailable",
                "Enable the Web Search addon and restart NeuralCompanion before using this control.",
            )
            self.configurationChanged.emit()
            return {
                "accepted": False,
                "reason": "addon_unavailable",
                "enabled": False,
                "starting": False,
            }

        if selected and not status.get("enabled", True):
            self.notificationRaised.emit(
                "warning", "Web Search is globally disabled",
                "Turn on Enable web search in the Web Search add-on before enabling it for this conversation.")
            self.configurationChanged.emit()
            return {"accepted": False, "reason": "globally_disabled", "enabled": False, "starting": False}

        previous_mode = str(status.get("mode") or "auto").strip().lower()
        backend = dict(status.get("backend") or {})
        if selected:
            servers = dict(backend.get("servers") or {})
            installation = dict(backend.get("installation") or {})
            has_launcher = any(
                bool(dict(server or {}).get("launcher_available"))
                for server in servers.values()
            ) or int(installation.get("installed_count") or 0) > 0
            if not has_launcher:
                self.configurationChanged.emit()
                return {
                    "accepted": False,
                    "reason": "servers_not_installed",
                    "enabled": False,
                    "starting": False,
                }
        mode = "auto" if selected else "off"
        if previous_mode == mode:
            should_start = selected and int(backend.get("online_count") or 0) < 1
            if should_start:
                self._queue_conversation_web_search_action("start")
            elif not selected:
                self._queue_conversation_web_search_action("stop")
            return {
                "accepted": True,
                "reason": "",
                "enabled": selected,
                "starting": should_start,
            }

        result = self._application.addons.invoke_addon_capability(
            "nc.web_intelligence",
            "runtime.web_intelligence.configure",
            {"settings": {"mode": mode}},
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Web Search was not changed",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "The Web Search addon did not accept the new mode.",
                    )
                ),
            )
            self.configurationChanged.emit()
            return {
                "accepted": False,
                "reason": "configuration_failed",
                "enabled": previous_mode != "off",
                "starting": False,
            }
        try:
            if not self._session_store.save():
                raise RuntimeError("Could not save the Web Search setting.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._application.addons.invoke_addon_capability(
                "nc.web_intelligence",
                "runtime.web_intelligence.configure",
                {"settings": {"mode": previous_mode}},
            )
            self.notificationRaised.emit(
                "error", "Web Search setting was not saved", str(error)
            )
            self.configurationChanged.emit()
            return {
                "accepted": False,
                "reason": "persistence_failed",
                "enabled": previous_mode != "off",
                "starting": False,
            }
        should_start = selected and int(backend.get("online_count") or 0) < 1
        if should_start:
            self._queue_conversation_web_search_action("start")
        elif not selected:
            self._queue_conversation_web_search_action("stop")
        self.addonSettingsChanged.emit()
        self.configurationChanged.emit()
        return {
            "accepted": True,
            "reason": "",
            "enabled": selected,
            "starting": should_start,
        }

    def _queue_conversation_web_search_action(self, action: str) -> None:
        selected = str(action or "").strip().lower()
        if selected not in {"start", "stop"}:
            return
        future = self._executor.submit(
            self._application.addons.invoke_addon_capability,
            "nc.web_intelligence",
            "runtime.web_intelligence.action",
            {"action": selected, "payload": {}},
        )

        def complete(task: Any) -> None:
            try:
                self._webSearchActionReceived.emit(selected, task.result(), "")
            except BaseException as error:
                self._webSearchActionReceived.emit(selected, None, str(error))

        future.add_done_callback(complete)

    @QtCore.Slot(str, object, str)
    def _on_conversation_web_search_action_received(
        self,
        action: str,
        command_result: Any,
        error: str,
    ) -> None:
        if self._closing:
            return
        selected = str(action or "").strip().lower()
        accepted = bool(getattr(command_result, "accepted", False))
        backend = dict(getattr(command_result, "value", None) or {}) if accepted else {}
        if selected == "stop":
            self.addonSettingsChanged.emit()
            self.configurationChanged.emit()
            if not accepted:
                failure = getattr(command_result, "failure", None)
                self.notificationRaised.emit(
                    "error",
                    "Web Search servers did not stop",
                    str(
                        error
                        or getattr(failure, "message", "")
                        or "The Web Search addon rejected the stop request."
                    ),
                )
            return

        current = QmlApplicationBridge._conversation_web_search_status(self)
        if current is not None and (not current.get("enabled", True)
                                    or str(current.get("mode") or "auto") == "off"):
            return
        if accepted and int(backend.get("online_count") or 0) > 0:
            self.addonSettingsChanged.emit()
            self.configurationChanged.emit()
            self.notificationRaised.emit(
                "success", "Web Search is ready", "At least one search server is online."
            )
            return

        self._application.addons.invoke_addon_capability(
            "nc.web_intelligence",
            "runtime.web_intelligence.configure",
            {"settings": {"mode": "off"}},
        )
        try:
            if not self._session_store.save():
                raise RuntimeError("Could not save the disabled Web Search mode.")
        except (OSError, RuntimeError, TypeError, ValueError) as save_error:
            error = str(error or save_error)
        self.addonSettingsChanged.emit()
        self.configurationChanged.emit()
        failure = getattr(command_result, "failure", None)
        self.notificationRaised.emit(
            "error",
            "Web Search servers did not start",
            str(
                error
                or getattr(failure, "message", "")
                or "The installed search servers did not report Online."
            ),
        )

    @QtCore.Slot(int)
    def setConversationFontSize(self, size: int) -> None:
        selected = _normalize_chat_font_size(size)
        if selected == self.conversationFontSize:
            return
        result = self._application.config.update("chat_font_size", selected)
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Chat font size was not saved",
                str(getattr(result.failure, "message", "Could not update the chat font size.")),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot(float, int)
    def setConversationResponseFrameSize(
        self,
        width_ratio: float,
        minimum_height: int,
    ) -> None:
        selected_width = _normalize_conversation_response_width_ratio(width_ratio)
        selected_height = _normalize_conversation_response_min_height(minimum_height)
        if (
            abs(selected_width - self.conversationResponseWidthRatio) < 0.0001
            and selected_height == self.conversationResponseMinHeight
        ):
            return
        result = self._application.config.update_many(
            {
                "conversation_response_width_ratio": selected_width,
                "conversation_response_min_height": selected_height,
            }
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Response frame size was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the response frame size.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot(float, int)
    def setConversationUserFrameSize(
        self,
        width_ratio: float,
        minimum_height: int,
    ) -> None:
        selected_width = _normalize_conversation_user_width_ratio(width_ratio)
        selected_height = _normalize_conversation_user_min_height(minimum_height)
        if (
            abs(selected_width - self.conversationUserWidthRatio) < 0.0001
            and selected_height == self.conversationUserMinHeight
        ):
            return
        result = self._application.config.update_many(
            {
                "conversation_user_width_ratio": selected_width,
                "conversation_user_min_height": selected_height,
            }
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "User message frame size was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the user message frame size.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot("QVariantMap")
    def setConversationResponseActionLayout(self, layout: Mapping[str, Any]) -> None:
        selected = normalize_conversation_response_action_layout(layout)
        if selected == self.conversationResponseActionLayout:
            return
        result = self._application.config.update(
            "conversation_response_action_layout",
            selected,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Response action placement was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the response action placement.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot("QVariantMap")
    def setConversationUserActionLayout(self, layout: Mapping[str, Any]) -> None:
        selected = normalize_conversation_user_action_layout(layout)
        if selected == self.conversationUserActionLayout:
            return
        result = self._application.config.update(
            "conversation_user_action_layout",
            selected,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "User message action placement was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the user message action placement.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot()
    def toggleConversationActionLabels(self) -> None:
        enabled = not self.conversationActionLabelsEnabled
        result = self._application.config.update(
            "conversation_action_labels_enabled",
            enabled,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Conversation icon label preference was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the conversation icon labels.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot()
    def toggleConversationResponsePlacementGuides(self) -> None:
        enabled = not self.conversationResponsePlacementGuidesEnabled
        result = self._application.config.update(
            "conversation_response_placement_guides_enabled",
            enabled,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Placement guide preference was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the response action placement guides.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot()
    def toggleConversationTimestamps(self) -> None:
        enabled = not self.conversationTimestampsEnabled
        result = self._application.config.update(
            "chat_message_timestamps_enabled",
            enabled,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Timestamp preference was not saved",
                str(getattr(result.failure, "message", "Could not update timestamps.")),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot(str)
    def setConversationSpeechHighlightMode(self, mode: str) -> None:
        selected = _normalize_speech_highlight_mode(mode)
        if selected == self.conversationSpeechHighlightMode:
            return
        result = self._application.config.update(
            "conversation_speech_highlight_mode",
            selected,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Spoken-text highlight was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the spoken-text highlight mode.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot(str)
    def setConversationSpeechHighlightStyle(self, style: str) -> None:
        selected = _normalize_speech_highlight_style(style)
        if selected == self.conversationSpeechHighlightStyle:
            return
        result = self._application.config.update(
            "conversation_speech_highlight_style",
            selected,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Spoken-text appearance was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the spoken-text highlight appearance.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot(str)
    def setConversationVisualReplyDisplayMode(self, mode: str) -> None:
        selected = _normalize_visual_reply_display_mode(mode)
        if selected == self.conversationVisualReplyDisplayMode:
            return
        result = self._application.config.update(
            "conversation_visual_reply_display_mode",
            selected,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Visual Reply display preference was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the Visual Reply display mode.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot()
    def toggleConversationVisualRepliesVisible(self) -> None:
        result = self._application.config.update(
            "conversation_visual_replies_visible", not self.conversationVisualRepliesVisible,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error", "Visual Reply visibility preference was not saved",
                str(getattr(result.failure, "message", "Could not update image visibility.")),
            )
            return
        self._session_store.save()
        self._conversation_revision = -1
        self.configurationChanged.emit()
        self.refreshConversationState()

    @QtCore.Slot()
    def toggleConversationVisualReplyAutoFollow(self) -> None:
        enabled = not self.conversationVisualReplyAutoFollow
        result = self._application.config.update(
            "conversation_visual_reply_auto_follow",
            enabled,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Visual Reply follow preference was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update automatic Visual Reply following.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot()
    def toggleConversationMessageBorders(self) -> None:
        enabled = not self.conversationMessageBordersEnabled
        result = self._application.config.update(
            "conversation_message_borders_enabled",
            enabled,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Message border preference was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update conversation message borders.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot()
    def clearConversationDisplay(self) -> None:
        """Clear only the rendered transcript, preserving canonical chat memory."""

        self.cancelConversationEdit()
        self._conversation_window.clear(self._application.chat.snapshot())
        self._conversation_revision = -1
        self.refreshConversationState()

    def _start_conversation_context_operation(self, operation: str) -> bool:
        if self._conversation_context_operation:
            self.notificationRaised.emit(
                "warning",
                "Chat context operation is busy",
                "Wait for the current Quick Save or Quick Load operation to finish.",
            )
            return False
        self._conversation_context_operation = str(operation)
        self.conversationContextChanged.emit()
        return True

    def _run_conversation_context_operation(self, operation: str) -> None:
        target = _quick_chat_context_path()

        def worker() -> str:
            generation = self._application.chat.snapshot().session_generation
            if operation == "save":
                guard = getattr(self, '_chat_context_guard', None)
                return _write_quick_chat_context(self._application, target,
                    on_saved=(lambda signature: guard._saved.emit((signature, generation))) if guard is not None else None)
            if not target.is_file():
                raise FileNotFoundError(f"Quick chat context not found: {target}")
            guard = getattr(self, '_chat_context_guard', None)
            def loaded(signature):
                if guard is not None:
                    guard._saved.emit((signature, self._application.chat.snapshot().session_generation))
            return _load_quick_chat_context(self._application, target, on_loaded=loaded)

        future = self._runtime_executor.submit(worker)

        def complete(task: Any) -> None:
            try:
                self._conversationContextReceived.emit(operation, True, str(task.result()))
            except BaseException as error:
                self._conversationContextReceived.emit(operation, False, str(error))

        future.add_done_callback(complete)

    @QtCore.Slot()
    def quickSaveConversationContext(self) -> None:
        if self._start_conversation_context_operation("save"):
            self._run_conversation_context_operation("save")

    @QtCore.Slot()
    def quickLoadConversationContext(self) -> None:
        guard = getattr(self, '_chat_context_guard', None)
        if guard is not None:
            guard.request('loading the quick-save conversation', self._quickLoadConversationContextNow)
        else:
            self._quickLoadConversationContextNow()

    def _quickLoadConversationContextNow(self):
        if self._start_conversation_context_operation("load"):
            memory_workspace = getattr(self, "_memory_workspace", None)
            if memory_workspace is not None:
                memory_workspace.invalidate()
            self._run_conversation_context_operation("load")

    @QtCore.Slot()
    def exportSessionMemoryReport(self) -> None:
        """Export the current memory report without blocking the QML thread."""

        def worker() -> str:
            target = str(self._application.memory.export_default_path() or "")
            result = self._application.memory.export_session_report(target)
            if not bool(getattr(result, "accepted", False)):
                failure = getattr(result, "failure", None)
                raise RuntimeError(
                    str(
                        getattr(
                            failure,
                            "message",
                            "Could not export the current session memory.",
                        )
                    )
                )
            payload = dict(getattr(result, "value", {}) or {})
            return str(payload.get("path", target) or target)

        future = self._runtime_executor.submit(worker)

        def complete(task: Any) -> None:
            try:
                self._memoryReportReceived.emit(True, str(task.result()))
            except BaseException as error:
                self._memoryReportReceived.emit(False, str(error))

        future.add_done_callback(complete)

    @QtCore.Slot(bool, str)
    def _on_memory_report_received(self, accepted: bool, detail: str) -> None:
        if self._closing:
            return
        self.notificationRaised.emit(
            "success" if accepted else "error",
            "Session memory exported" if accepted else "Memory export failed",
            detail
            or (
                "The readable memory report is ready."
                if accepted
                else "The session memory report could not be exported."
            ),
        )

    @QtCore.Slot(bool, str)
    def _on_visual_asset_saved(self, accepted: bool, detail: str) -> None:
        if self._closing:
            return
        self.notificationRaised.emit(
            "success" if accepted else "error",
            "Image saved" if accepted else "Image was not saved",
            str(detail or ""),
        )

    @QtCore.Slot(object, str)
    def _on_visual_asset_copied(self, image: Any, error: str) -> None:
        if self._closing:
            return
        clipboard = QtGui.QGuiApplication.clipboard()
        if error or clipboard is None or not isinstance(image, QtGui.QImage):
            self.notificationRaised.emit(
                "error",
                "Image was not copied",
                str(error or "The system clipboard is unavailable."),
            )
            return
        clipboard.setImage(image)
        self.notificationRaised.emit(
            "success",
            "Image copied",
            "The Visual Reply image is on the clipboard.",
        )

    @QtCore.Slot(str, bool, str)
    def _on_conversation_context_received(
        self,
        operation: str,
        accepted: bool,
        detail: str,
    ) -> None:
        if self._closing:
            return
        self._conversation_context_operation = ""
        self.conversationContextChanged.emit()
        if not accepted:
            self.notificationRaised.emit(
                "error",
                "Quick Save failed" if operation == "save" else "Quick Load failed",
                detail or "The chat context operation did not complete.",
            )
            return
        if operation == "load":
            self._apply_quick_loaded_context()
        self.notificationRaised.emit(
            "success",
            "Quick Save complete" if operation == "save" else "Quick Load complete",
            detail,
        )

    @QtCore.Slot(bool)
    def _on_phone_chat_context_loaded(self, manual: bool) -> None:
        if self._closing:
            return
        if manual:
            self._apply_quick_loaded_context()
            self.notificationRaised.emit("success", "Quick Load complete", "Chat restored from the phone Quick Save.")
        else:
            self.cancelConversationEdit()
            self._conversation_persona_fallbacks.clear()
            self._conversation_window.reset()
            self._conversation_revision = -1
            self.refreshConversationState()
        self._addon_runtime.publish_main_chat_remote_history()

    def _apply_quick_loaded_context(self) -> None:
        self.cancelConversationEdit()
        self._conversation_persona_fallbacks.clear()
        self._application.config.update_many(
            {
                "active_chat_context_path": "",
                "active_chat_context_name": "",
                "quick_chat_context_active": True,
                "continuity_memory_id": "",
                "continuity_memory_enabled": False,
                "continuity_memory_auto_summarize": False,
                "continuity_memory_update_on_save": False,
                "continuity_memory_inject": False,
                "long_term_memory_retrieval_enabled": False,
                "long_term_memory_embedding_enabled": False,
            }
        )
        self._session_store.save()
        self._conversation_window.reset()
        self._conversation_revision = -1
        self.refreshConversationState()
        self.configurationChanged.emit()

    @staticmethod
    def _flush_deferred_conversation_turn(owner: Any) -> None:
        pending = getattr(owner, "_conversation_deferred_turn", None)
        if not pending:
            return
        owner._conversation_deferred_turn = None
        message = str(pending.get("text") or "").strip()
        attachment = dict(pending.get("attachment") or {})
        if attachment:
            owner._conversation_attachment = attachment
            QmlApplicationBridge.submitConversationTurn(owner, message)
            return
        QmlApplicationBridge._queue_text_message(owner, message)

    @QtCore.Slot(str, result=bool)
    def submitConversationTurn(self, text: str) -> bool:
        if getattr(self, '_room_blocks_main_chat', lambda: False)():
            self.notificationRaised.emit('warning', 'Room is active', 'Use the room conversation to send a message, or stop the room first.')
            return False
        message = str(text or "").strip()
        attachment = dict(self._conversation_attachment)
        if int(self._conversation_draft_state.get("inlineResponseHistoryIndex", -1)) >= 0:
            if not message and not attachment:
                return False
            self._conversation_deferred_turn = {
                "text": message,
                "attachment": attachment,
            }
            if attachment:
                self._conversation_attachment = {}
                self.conversationAttachmentChanged.emit()
            self.notificationRaised.emit(
                "info",
                "Reply queued",
                "The reply will be sent when response editing finishes.",
            )
            return True
        if not attachment:
            return self._queue_text_message(message)
        if not self.systemRunning:
            self.notificationRaised.emit(
                "warning",
                "Initialize NeuralCompanion first",
                "The runtime must be active before an image can be queued.",
            )
            return False
        try:
            paths = [str(self._local_image_path(str(row.get("path") or "")))
                     for row in QmlApplicationBridge._pending_image_rows(attachment)]
            options = {"image_paths": paths} if len(paths) > 1 else {}
            self._runtime_controller.queue_image_turn(
                paths[0],
                content=message or None,
                source="qml_conversation",
                **options,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self.notificationRaised.emit(
                "error",
                "Image message was not queued",
                str(exc),
            )
            return False
        self._conversation_attachment = {}
        self.conversationAttachmentChanged.emit()
        self.refreshConversationState()
        return True

    @QtCore.Slot(str)
    def triggerRuntimeAction(self, action: str) -> None:
        if getattr(self, '_room_blocks_main_chat', lambda: False)():
            self.notificationRaised.emit('warning', 'Room is active',
                'Stop the room before using normal chat actions.')
            return
        result = dict(self._runtime_controller.trigger_action(str(action or "")) or {})
        if result.get("accepted") is False:
            self.notificationRaised.emit(
                "error",
                "Runtime action failed",
                str(result.get("message") or "The action was not accepted."),
            )
        self.runtimeChanged.emit()

    @QtCore.Slot()
    def resetConversation(self) -> None:
        guard = getattr(self, '_chat_context_guard', None)
        if guard is not None:
            guard.request('starting a new conversation', self._resetConversationNow)
        else:
            self._resetConversationNow()

    def _resetConversationNow(self):
        self.cancelConversationEdit()
        memory_workspace = getattr(self, "_memory_workspace", None)
        if memory_workspace is not None:
            memory_workspace.invalidate()
        try:
            self._runtime_controller.reset_conversation()
        except RuntimeError as error:
            self.notificationRaised.emit(
                "error",
                "Conversation was not reset",
                str(error),
            )
            return
        self._conversation_persona_fallbacks.clear()
        self._conversation_window.reset()
        self._conversation_revision = -1
        self.refreshConversationState()
        guard = getattr(self, '_chat_context_guard', None)
        if guard is not None:
            guard.markSaved(self._application.chat.history())
        # A deliberate New conversation must also forget the previous file for
        # the next app launch; stopping the engine never takes this path.
        self._on_named_context_changed('reset_context')

    @QtCore.Slot(str)
    def setConversationVoiceIndicatorStyle(self, style: str) -> None:
        selected = _normalize_voice_indicator_style(style)
        if selected == self.conversationVoiceIndicatorStyle:
            return
        result = self._application.config.update(
            "conversation_voice_indicator_style",
            selected,
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            self.notificationRaised.emit(
                "error",
                "Voice display was not changed",
                str(getattr(failure, "message", "Could not save the display style.")),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.notificationRaised.emit(
                "error",
                "Voice display was not changed",
                str(error),
            )
            return
        self.configurationChanged.emit()

    @QtCore.Slot(str)
    def setConversationCanvasStyle(self, style: str) -> None:
        selected = str(style or "").strip().lower()
        if selected not in _CONVERSATION_CANVAS_STYLES:
            self.notificationRaised.emit(
                "error",
                "Conversation appearance was not changed",
                "Choose one of the available conversation styles.",
            )
            return
        if selected == self.conversationCanvasStyle:
            return
        previous = self._application.config.get(
            "conversation_canvas_style", "original"
        )
        result = self._application.config.update(
            "conversation_canvas_style",
            selected,
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            self.notificationRaised.emit(
                "error",
                "Conversation appearance was not changed",
                str(getattr(failure, "message", "Could not save the appearance.")),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QmlApplicationBridge._rollback_conversation_appearance(
                self, {"conversation_canvas_style": previous}
            )
            self.notificationRaised.emit(
                "error",
                "Conversation appearance was not changed",
                str(error),
            )
            return
        self.configurationChanged.emit()

    @QtCore.Slot(str)
    def setConversationBackgroundImage(self, source: str) -> None:
        try:
            candidate = QmlApplicationBridge._local_image_path(source)
        except ValueError as error:
            self.notificationRaised.emit(
                "error",
                "Conversation background was not changed",
                str(error),
            )
            return
        selected_path = str(candidate)
        current_path = str(
            self._application.config.get("conversation_background_path", "") or ""
        )
        if selected_path == current_path:
            return
        result = self._application.config.update(
            "conversation_background_path",
            selected_path,
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            self.notificationRaised.emit(
                "error",
                "Conversation background was not changed",
                str(getattr(failure, "message", "Could not save the background.")),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QmlApplicationBridge._rollback_conversation_appearance(
                self, {"conversation_background_path": current_path}
            )
            self.notificationRaised.emit(
                "error",
                "Conversation background was not changed",
                str(error),
            )
            return
        self.configurationChanged.emit()

    @QtCore.Slot()
    def clearConversationBackgroundImage(self) -> None:
        current_path = str(
            self._application.config.get("conversation_background_path", "") or ""
        )
        if not current_path:
            return
        result = self._application.config.update("conversation_background_path", "")
        if not result.accepted:
            failure = getattr(result, "failure", None)
            self.notificationRaised.emit(
                "error",
                "Conversation background was not changed",
                str(getattr(failure, "message", "Could not clear the background.")),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QmlApplicationBridge._rollback_conversation_appearance(
                self, {"conversation_background_path": current_path}
            )
            self.notificationRaised.emit(
                "error",
                "Conversation background was not changed",
                str(error),
            )
            return
        self.configurationChanged.emit()

    @QtCore.Slot(bool)
    def setConversationTransparentMessageCards(self, enabled: bool) -> None:
        selected = bool(enabled)
        if selected == self.conversationTransparentMessageCardsEnabled:
            return
        previous = bool(
            self._application.config.get(
                "conversation_transparent_message_cards_enabled", False
            )
        )
        result = self._application.config.update(
            "conversation_transparent_message_cards_enabled",
            selected,
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            self.notificationRaised.emit(
                "error",
                "Conversation cards were not changed",
                str(getattr(failure, "message", "Could not save card transparency.")),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QmlApplicationBridge._rollback_conversation_appearance(
                self,
                {"conversation_transparent_message_cards_enabled": previous},
            )
            self.notificationRaised.emit(
                "error",
                "Conversation cards were not changed",
                str(error),
            )
            return
        self.configurationChanged.emit()

    @QtCore.Slot(str)
    def setConversationMessageTextColor(self, color: str) -> None:
        requested = str(color or "").strip()
        selected = _normalize_conversation_message_text_color(requested)
        if requested and not selected:
            self.notificationRaised.emit(
                "error",
                "Conversation text color was not changed",
                "Choose a valid six-digit color.",
            )
            return
        current = _normalize_conversation_message_text_color(
            self._application.config.get("conversation_message_text_color", "")
        )
        if selected == current:
            return
        previous = self._application.config.get("conversation_message_text_color", "")
        result = self._application.config.update(
            "conversation_message_text_color", selected
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            self.notificationRaised.emit(
                "error",
                "Conversation text color was not changed",
                str(getattr(failure, "message", "Could not save the text color.")),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QmlApplicationBridge._rollback_conversation_appearance(
                self, {"conversation_message_text_color": previous}
            )
            self.notificationRaised.emit(
                "error", "Conversation text color was not changed", str(error)
            )
            return
        self.configurationChanged.emit()

    @QtCore.Slot(str)
    def setConversationMessageFontFamily(self, family: str) -> None:
        requested = str(family or "").strip()
        selected = _normalize_conversation_message_font_family(requested)
        if requested and not selected:
            self.notificationRaised.emit(
                "error",
                "Conversation font was not changed",
                "Choose a valid installed font family.",
            )
            return
        current = _normalize_conversation_message_font_family(
            self._application.config.get("conversation_message_font_family", "")
        )
        if selected == current:
            return
        previous = self._application.config.get("conversation_message_font_family", "")
        result = self._application.config.update(
            "conversation_message_font_family", selected
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            self.notificationRaised.emit(
                "error",
                "Conversation font was not changed",
                str(getattr(failure, "message", "Could not save the font.")),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QmlApplicationBridge._rollback_conversation_appearance(
                self, {"conversation_message_font_family": previous}
            )
            self.notificationRaised.emit(
                "error", "Conversation font was not changed", str(error)
            )
            return
        self.configurationChanged.emit()

    @QtCore.Slot(bool)
    def setConversationBionicReadingEnabled(self, enabled: bool) -> None:
        selected = bool(enabled)
        if selected == self.conversationBionicReadingEnabled:
            return
        previous = bool(
            self._application.config.get("conversation_bionic_reading_enabled", False)
        )
        result = self._application.config.update(
            "conversation_bionic_reading_enabled", selected
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            self.notificationRaised.emit(
                "error",
                "Bionic reading was not changed",
                str(getattr(failure, "message", "Could not save bionic reading.")),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QmlApplicationBridge._rollback_conversation_appearance(
                self, {"conversation_bionic_reading_enabled": previous}
            )
            self.notificationRaised.emit(
                "error", "Bionic reading was not changed", str(error)
            )
            return
        self.configurationChanged.emit()

    @QtCore.Slot()
    def restoreConversationAppearance(self) -> None:
        previous_style = self._application.config.get(
            "conversation_canvas_style", "original"
        )
        previous_transparency = bool(
            self._application.config.get(
                "conversation_transparent_message_cards_enabled", False
            )
        )
        previous_text_color = self._application.config.get(
            "conversation_message_text_color", ""
        )
        previous_font_family = self._application.config.get(
            "conversation_message_font_family", ""
        )
        previous_bionic_reading = bool(
            self._application.config.get("conversation_bionic_reading_enabled", False)
        )
        current_path = str(
            self._application.config.get("conversation_background_path", "") or ""
        )
        if (
            self.conversationCanvasStyle == "original"
            and not current_path
            and not self.conversationTransparentMessageCardsEnabled
            and not self.conversationMessageTextColor
            and not _normalize_conversation_message_font_family(previous_font_family)
            and not self.conversationBionicReadingEnabled
        ):
            return
        result = self._application.config.update_many(
            {
                "conversation_canvas_style": "original",
                "conversation_background_path": "",
                "conversation_transparent_message_cards_enabled": False,
                "conversation_message_text_color": "",
                "conversation_message_font_family": "",
                "conversation_bionic_reading_enabled": False,
            }
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            self.notificationRaised.emit(
                "error",
                "Conversation appearance was not restored",
                str(getattr(failure, "message", "Could not restore the appearance.")),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QmlApplicationBridge._rollback_conversation_appearance(
                self,
                {
                    "conversation_canvas_style": previous_style,
                    "conversation_background_path": current_path,
                    "conversation_transparent_message_cards_enabled": previous_transparency,
                    "conversation_message_text_color": previous_text_color,
                    "conversation_message_font_family": previous_font_family,
                    "conversation_bionic_reading_enabled": previous_bionic_reading,
                },
            )
            self.notificationRaised.emit(
                "error",
                "Conversation appearance was not restored",
                str(error),
            )
            return
        self.configurationChanged.emit()

    @staticmethod
    def _rollback_conversation_appearance(
        owner: Any,
        previous: Mapping[str, Any],
    ) -> None:
        rollback = owner._application.config.update_many(dict(previous))
        if not rollback.accepted:
            owner.configurationChanged.emit()

    @QtCore.Slot()
    def refreshLiveSessionState(self) -> None:
        try:
            runtime_snapshot = self._application.status.snapshot()
            activity = runtime_snapshot.activity
            recording = bool(activity.recording)
            listening = bool(activity.listening)
            activity_paused = bool(activity.paused)
            interaction_pending = int(runtime_snapshot.interaction_pending or 0)
        except Exception:
            recording = False
            listening = False
            activity_paused = False
            interaction_pending = 0

        try:
            playback_snapshot = self._application.playback.snapshot()
            playback_paused = bool(playback_snapshot.paused)
            playback_active = getattr(playback_snapshot, "current", None) is not None
        except Exception:
            playback_paused = False
            playback_active = False

        try:
            replay_active = bool(self._application.replay.has_active_replay())
        except AttributeError:
            replay_active = False

        if playback_active and self._tutorial_narration.fallback_active:
            self._tutorial_narration.stop()

        running = self.systemRunning
        try:
            presence = dict(visual_presence_runtime.snapshot_state() or {})
        except Exception:
            presence = {}
        audio_level = max(0.0, min(float(presence.get("audio_level", 0.0) or 0.0), 1.0))
        mood = str(presence.get("mood", "neutral") or "neutral").strip().lower()
        ai_state = str(presence.get("ai_state", "idle") or "idle").strip().lower()
        avatar_mode = str(self._application.config.get("avatar_mode", "musetalk") or "none").strip().lower()
        # Audio-only and Scenic speech publish to the shared TTS pipeline store.
        # Read preview images separately from the selected avatar provider.
        pipeline_result = self._application.addons.invoke_service_capability(
            "avatar_provider_registry",
            "runtime.pipeline_snapshot",
            {},
            provider_id="musetalk" if avatar_mode in {"none", "scenic"} else avatar_mode,
        )
        preview_result = self._application.addons.invoke_service_capability(
            "avatar_provider_registry",
            "runtime.preview.current_state",
            {},
            provider_id=avatar_mode,
        )
        pipeline = dict(pipeline_result.value or {}) if pipeline_result.accepted else {}
        if avatar_mode in {"none", "scenic"} and pipeline.get("engine_mode") != avatar_mode:
            pipeline = {}
        buffer_state = normalize_pipeline_progress(
            pipeline,
            dict(preview_result.value or {}) if preview_result.accepted else {},
            include_speech_progress=not self._tutorial_narration.active,
            conversation=self._application.chat.snapshot(),
            remote_presentation=getattr(self, '_remote_progress_presentation', None),
        )

        now = time.monotonic()
        provider_failed = bool(self._voice_error_message and now < self._voice_error_until)
        if not running:
            state = "stopped"
            state_label = "Runtime stopped"
        elif provider_failed or bool(buffer_state.get("failed", False)):
            state = "failure"
            state_label = "Provider failure" if provider_failed else "TTS buffer failure"
        elif recording:
            state = "recording"
            state_label = "Recording"
        elif ai_state == "speaking" or audio_level > 0.015:
            state = "speaking"
            state_label = "Speaking"
        elif self._document_memory_retrieving(now):
            state = "thinking"
            state_label = self._document_memory_retrieval_label()
        elif ai_state == "thinking" or interaction_pending > 0:
            state = "thinking"
            state_label = "Thinking"
        else:
            state = "ready"
            state_label = "Waiting for voice or text"

        ready = bool(
            running
            and state == "ready"
            and not recording
        )
        palette = dict(resolve_mood_colors(mood) or {})
        next_state = {
            "state": state,
            "stateLabel": state_label,
            "ready": ready,
            "recording": recording,
            "paused": activity_paused or playback_paused,
            "playbackActive": playback_active,
            "replayActive": replay_active,
            "listening": listening,
            "audioLevel": audio_level,
            "mood": str(palette.get("moodName") or mood or "neutral"),
            **palette,
            "buffer": buffer_state,
            "faultMessage": self._voice_error_message if provider_failed else "",
        }
        if next_state != self._live_session_state:
            self._live_session_state = next_state
            self.liveSessionChanged.emit()
        # Turn/playback ownership can change without a presence-display change.
        # Notify this separate QML binding on both busy and idle transitions.
        deletion_available = self.conversationMessageDeletionAvailable
        self._refresh_conversation_actions()
        if deletion_available != self._conversation_message_deletion_available:
            self._conversation_message_deletion_available = deletion_available
            self.conversationMessageDeletionAvailabilityChanged.emit()

    @QtCore.Slot()
    def clearConsole(self) -> None:
        self._console_text = ""
        self.consoleChanged.emit()

    def _user_identity_profile_snapshot(self) -> dict[str, Any]:
        result = self._application.addons.invoke_addon_capability(
            "nc.user_identity",
            "runtime.user_identity.snapshot",
            {},
        )
        if not result.accepted or not isinstance(result.value, Mapping):
            return {}
        return dict(result.value)

    @QtCore.Slot()
    def refreshConversationState(self) -> None:
        self._refresh_conversation_actions()
        if self._closing or self._conversation_edit_mode:
            return
        snapshot = self._application.chat.snapshot()
        revision = int(getattr(snapshot, "revision", 0) or 0)
        if revision == self._conversation_revision:
            return
        if self._conversation_selection_active:
            displayed_ids = {row["messageId"] for row in self._conversation_messages}
            if (snapshot.session_generation == self._conversation_window.generation
                    and any(row.message_id in displayed_ids for row in snapshot.messages)):
                return
            # A reset/replaced conversation invalidates the selection too.
            self._conversation_selection_active = False
        QmlApplicationBridge.validateConversationInlineResponseDraft(self)
        if self._conversation_window_protected():
            return
        self._conversation_revision = revision
        active_persona = self._quick_personas.active_persona() or {}
        avatar_mode = self._quick_personas.avatar_mode()
        persona_records = [
            dict(record)
            for record in dict(self._quick_personas.load().get("personas") or {}).values()
            if isinstance(record, Mapping)
        ]
        user_profile = self._user_identity_profile_snapshot()
        user_identity_enabled = bool(user_profile.get("enabled", False))
        user_avatar_path = str(user_profile.get("avatar_path") or "").strip()
        user_avatar_url = _local_asset_url(user_avatar_path)
        user_display_name = (
            str(user_profile.get("name") or "You").strip() or "You"
        )
        user_initials = "".join(
            part[0].upper() for part in user_display_name.split() if part
        )[:2] or "YOU"
        user_avatar_visible = bool(
            user_identity_enabled
            and user_profile.get("show_avatar_in_conversation", True)
            and user_avatar_url
        )
        active_attribution = _quick_persona_attribution(active_persona)
        messages = []
        indexes = self._conversation_window.update(
            snapshot, self._application.config.get("chat_visual_batch_size", 200),
            show_visual_replies=self.conversationVisualRepliesVisible,
        )
        for history_index in indexes:
            raw = snapshot.messages[history_index]
            item = {"role": raw.role, "content": raw.content, **dict(_plain(raw.metadata) or {})}
            role = str(item.get("role") or "user").strip().lower()
            metadata = dict(item.get("metadata") or {})
            origin = str(item.get("origin") or metadata.get("origin") or "").strip().lower()
            is_assistant = role == "assistant" and origin != "input"
            is_user = role == "user" or origin == "input"
            persona_attribution = (
                _conversation_persona_attribution_for_message(
                    item,
                    metadata,
                    active_attribution,
                    self._conversation_persona_fallbacks,
                )
                if is_assistant
                else {}
            )
            message_persona = (
                _quick_persona_for_attribution(persona_attribution, persona_records)
                if is_assistant and persona_attribution
                else {}
            )
            persona_name = (
                str(message_persona.get("name") or "Assistant").strip()
                or "Assistant"
            )
            avatar_path = str(message_persona.get("avatar_path") or "").strip()
            avatar_url = _local_asset_url(avatar_path)
            mood_images = dict(message_persona.get("mood_images") or {})
            initials = "".join(
                part[0].upper()
                for part in persona_name.split()
                if part
            )[:2] or "NC"
            mood = _message_mood(item.get("content"), metadata, {"neutral", *mood_images})
            mood_url = _local_asset_url(str(mood_images.get(mood) or ""))
            resolved_avatar_url = mood_url if avatar_mode == "mood" and mood_url else avatar_url
            mood_colors = resolve_mood_colors(mood)
            attachment_path = str(
                item.get("attachment_image_path")
                or metadata.get("attachment_image_path")
                or ""
            ).strip()
            visual_reply_assets = (
                _conversation_visual_reply_assets(
                    item,
                    metadata,
                    history_index=history_index,
                )
                if is_assistant and self.conversationVisualRepliesVisible
                else []
            )
            watch_capture = item.get('orb_watch_capture') or metadata.get('orb_watch_capture')
            watch_captures = item.get('orb_watch_captures') or metadata.get('orb_watch_captures') or []
            capture_previews = []
            if is_assistant and isinstance(watch_captures,(list,tuple)):
                for entry in watch_captures:
                    if not isinstance(entry,Mapping):
                        continue
                    try:
                        stamp=time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(float(entry.get('captured_at') or 0)))
                    except (ValueError,TypeError,OverflowError,OSError):
                        stamp='Unknown time'
                    capture_previews.append(dict(imageUrl=_local_asset_url(str(entry.get('image_path') or '')),
                        timestamp=stamp,watchIds=list(entry.get('watch_ids') or [])))
            capture_preview = {}
            if is_assistant and isinstance(watch_capture, Mapping):
                try:
                    capture_stamp = time.strftime('%Y-%m-%d %H:%M:%S',
                        time.localtime(float(watch_capture.get('captured_at') or 0)))
                except (ValueError, TypeError, OverflowError, OSError):
                    capture_stamp = 'Unknown time'
                capture_preview = dict(
                    imageUrl=_local_asset_url(str(watch_capture.get('image_path') or '')),
                    timestamp=capture_stamp,
                    observationId=str(watch_capture.get('observation_id') or ''))
            messages.append(
                {
                    **item,
                    "watchCaptures": capture_previews,
                    "role": role,
                    "origin": origin,
                    "historyIndex": history_index,
                    "messageId": raw.message_id,
                    "isAssistant": is_assistant,
                    "isUser": is_user,
                    "isUserEdited": bool(
                        item.get("nc_user_edited")
                        or metadata.get("nc_user_edited")
                    ),
                    "displayRole": (
                        persona_name
                        if is_assistant
                        else user_display_name if is_user else "System"
                    ),
                    "displayTimestamp": conversation_history_runtime.format_turn_timestamp(item),
                    "avatarVisible": bool(
                        (
                            is_assistant
                            and avatar_mode != "off"
                            and (avatar_path or persona_attribution)
                        )
                        or (is_user and user_avatar_visible)
                    ),
                    "avatarMode": "single" if is_user else avatar_mode,
                    "avatarUrl": user_avatar_url if is_user else resolved_avatar_url,
                    "neutralAvatarUrl": avatar_url,
                    "moodAvatarUrls": {name: _local_asset_url(str(path)) for name, path in mood_images.items()},
                    "avatarInitials": user_initials if is_user else initials,
                    "avatarMood": mood,
                    "avatarMoodColor": (
                        "#a78bfa"
                        if is_user
                        else str(mood_colors.get("primaryColor") or "#38bdf8")
                    ),
                    "hasAttachment": bool(attachment_path),
                    "watchCapture": capture_preview,
                    "attachmentUrl": _local_asset_url(attachment_path),
                    "attachmentName": Path(attachment_path).name if attachment_path else "",
                    "attachments": [dict(url=_local_asset_url(path), name=Path(path).name)
                                    for path in (image_paths(item) or image_paths(metadata))],
                    "hasVisualReply": bool(visual_reply_assets),
                    "visualReplies": visual_reply_assets,
                    "visualReplyPrompt": str(
                        item.get("visual_reply_prompt")
                        or metadata.get("visual_reply_prompt")
                        or ""
                    ).strip(),
                }
            )
        latest_assistant_index = latest_user_index = -1
        for index in range(len(snapshot.messages) - 1, -1, -1):
            raw = snapshot.messages[index]
            metadata = raw.metadata
            origin = str(metadata.get("origin") or (metadata.get("metadata") or {}).get("origin") or "").strip().lower()
            if latest_assistant_index < 0 and raw.role == "assistant" and origin != "input":
                latest_assistant_index = index
            if latest_user_index < 0 and (raw.role == "user" or origin == "input"):
                latest_user_index = index
            if latest_assistant_index >= 0 and latest_user_index >= 0:
                break
        for message in messages:
            message["isLatestAssistant"] = message["historyIndex"] == latest_assistant_index
            message["isLatestUser"] = message["historyIndex"] == latest_user_index
        if messages != self._conversation_messages:
            self.conversationAboutToChange.emit()
        self._conversation_messages = messages
        if messages and bool(messages[-1].get("isAssistant", False)):
            self._voice_error_until = 0.0
            self._voice_error_message = ""
        self.conversationChanged.emit()
        self.conversationViewportChanged.emit()

    def _bind_legacy_conversation_personas(self) -> None:
        """Bind untagged turns, including unloaded rows, before the persona changes."""

        active = _quick_persona_attribution(self._quick_personas.active_persona() or {})
        for raw in self._application.chat.snapshot().messages:
            if raw.role == "assistant":
                item = {"role": raw.role, "content": raw.content, **dict(_plain(raw.metadata) or {})}
                _conversation_persona_attribution_for_message(
                    item, dict(item.get("metadata") or {}), active, self._conversation_persona_fallbacks
                )
        self._conversation_revision = -1
        self.refreshConversationState()

    @QtCore.Slot(str, bool)
    def setConversationViewVisible(self, view_id: str, visible: bool) -> None:
        if self._closing:
            return
        if visible:
            if view_id not in self._conversation_views:
                self._conversation_views.add(view_id)
                # Catch up after QML has finished mounting the visible view.
                QmlApplicationBridge._queue_conversation_refresh(self)
        else:
            self._conversation_views.discard(view_id)

    @QtCore.Slot(str, "QVariantMap")
    def saveConversationViewState(self, view_id: str, state: dict[str, Any]) -> None:
        # A departing dock delegate must not overwrite a newer active view.
        if self._closing or self._conversation_views - {view_id}:
            return
        self._conversation_view_state = dict(state)
        self._conversation_view_generation = self._application.chat.snapshot().session_generation

    @QtCore.Slot(result="QVariantMap")
    def conversationViewState(self) -> dict[str, Any]:
        snapshot = self._application.chat.snapshot()
        if snapshot.session_generation != self._conversation_view_generation:
            return {}
        ids = ({row["messageId"] for row in self._conversation_edit_messages}
               if self._conversation_edit_mode else {row.message_id for row in snapshot.messages})
        if self._conversation_view_state.get("firstId") not in ids:
            return {}
        return dict(self._conversation_view_state)

    def _refresh_conversation_if_visible(self) -> None:
        if self._conversation_views:
            self.refreshConversationState()

    def _refresh_live_session_if_visible(self) -> None:
        if self._conversation_views:
            self.refreshLiveSessionState()
            self._refresh_conversation_portraits()

    @QtCore.Property("QVariantMap", notify=conversationPortraitsChanged)
    def conversationPortraitMoods(self) -> dict[str, str]:
        return dict(self._conversation_portrait_moods)

    def _refresh_conversation_portraits(self) -> None:
        if self._closing:
            return
        snapshot = self._application.chat.snapshot()
        if snapshot.session_generation != self._portrait_session_generation:
            self._portrait_session_generation = snapshot.session_generation
            self._conversation_portrait_moods.clear()
            self.conversationPortraitsChanged.emit()
        state = getattr(self._application.avatar.snapshot(), "portrait_playback", None)
        message_id = portrait_message_id(state, snapshot)
        if message_id and self._conversation_portrait_moods.get(message_id) != state.expression:
            self._conversation_portrait_moods[message_id] = state.expression
            self.conversationPortraitsChanged.emit()

    @QtCore.Slot()
    def refreshVisualState(self) -> None:
        if self._closing:
            return
        self._visual_reply_toolbar.request_state()
        self.refreshMusetalkPreview()

    @QtCore.Slot(object)
    def _apply_visual_state(self, next_visual: dict[str, Any]) -> None:
        if self._closing:
            return
        if next_visual != self._visual_state:
            self._visual_state = next_visual
            self.visualStateChanged.emit()

    @QtCore.Slot(str, bool)
    def setVisualReplyPreviewVisible(self, view_id: str, visible: bool) -> None:
        if self._closing:
            return
        if visible:
            self._visual_reply_views.add(view_id)
            self.refreshVisualState()
        else:
            self._visual_reply_views.discard(view_id)

    @QtCore.Slot(str, bool)
    def setMusetalkPreviewVisible(self, view_id: str, visible: bool) -> None:
        if self._closing:
            return
        if visible:
            self._musetalk_preview_views.add(view_id)
            self.refreshMusetalkPreview()
            self._musetalk_preview_timer.start()
        else:
            self._musetalk_preview_views.discard(view_id)
            if not self._musetalk_preview_views:
                self._musetalk_preview_timer.stop()

    @QtCore.Slot()
    def refreshMusetalkPreview(self) -> None:
        if self._closing:
            return
        ditto_preview = {}
        try:
            result = self._application.addons.invoke_addon_capability(
                "nc.ditto_avatar", "runtime.preview.current_state", {},
            )
            if (result.accepted and isinstance(result.value, Mapping)
                    and result.value.get("creator_preview_active")):
                ditto_preview = dict(result.value)
        except Exception:
            pass  # An unavailable Ditto addon leaves the selected provider intact.
        creator = getattr(self, "_musetalk_creator", None)
        creator_preview = dict(creator.renderPreviewState) if creator is not None else {}
        if creator_preview and not ditto_preview:
            # Presentation only: never publish Creator renders into runtime playback.
            self._musetalk_preview_timer.setInterval(100)
            if creator_preview != self._musetalk_state:
                self._musetalk_state = creator_preview
                self.musetalkStateChanged.emit()
            return
        if (self._musetalk_state.get("creatorPreview")
                or (self._musetalk_state.get("creator_preview_active") and not ditto_preview)):
            # Phone-owned presentation holds desktop frames; it must not hold
            # a Creator result across the startup handoff.
            self._musetalk_state = {}
            self.musetalkStateChanged.emit()
        phone_owned = False
        try:
            ownership = self._application.addons.invoke_addon_capability(
                "nc.main_chat_remote", "runtime.main_chat_remote.presentation", {},
            )
            phone_owned = bool(ownership.accepted and isinstance(ownership.value, Mapping)
                               and ownership.value.get("phone_owns_presentation") is True)
            self._remote_progress_presentation = dict(ownership.value) if phone_owned else None
        except Exception:
            self._remote_progress_presentation = None
            pass  # Disabled/older remote addons leave normal desktop preview intact.
        if phone_owned != getattr(self, "_musetalk_phone_presentation", False):
            self._musetalk_phone_presentation = phone_owned
            logging.getLogger("nc.musetalk.presentation").info(
                "Desktop preview %s; phone presentation ownership=%s; media generation unchanged",
                "paused" if phone_owned else "resumed", phone_owned,
            )
        if phone_owned and not ditto_preview:
            # Keep the last image, but do not advance desktop frame consumption.
            # Phone media generation uses the independent addon/runtime path.
            self._musetalk_preview_timer.setInterval(100)
            return
        next_musetalk: dict[str, Any] = {}
        if ditto_preview:
            next_musetalk = ditto_preview
        else:
            musetalk_result = self._application.addons.invoke_service_capability(
                "avatar_provider_registry",
                "runtime.preview.current_state",
                {},
                provider_id=str(self._application.config.get("avatar_mode", "musetalk") or "none").strip().lower(),
            )
            if musetalk_result.accepted and isinstance(musetalk_result.value, Mapping):
                next_musetalk = dict(musetalk_result.value or {})
        memory_url = str(next_musetalk.get("image_url") or "")
        memory_frame = memory_url.startswith("image://ditto/") and next_musetalk.get("provider_id") == "ditto"
        if memory_frame:
            preview_path, frame_index = memory_url, int(next_musetalk.get("preview_frame_index", 0))
        else:
            preview_path, frame_index = self._musetalk_preview.current_frame(next_musetalk, time.time())
        next_musetalk["frame_index"] = frame_index
        # Presentation metadata only; do not alter the audio/frame clock.
        next_musetalk["loopFadeMs"] = max(0, int(
            self._application.config.get("musetalk_loop_fade_ms", 180) or 0
        ))
        if memory_frame:
            next_musetalk["imageUrl"] = memory_url
        elif preview_path:
            next_musetalk["imageUrl"] = QtCore.QUrl.fromLocalFile(
                str(Path(preview_path).resolve())
            ).toString()
        else:
            next_musetalk["imageUrl"] = ""

        interval = self._musetalk_preview.interval_ms(next_musetalk) if preview_path else 100
        if self._musetalk_preview_timer.interval() != interval:
            self._musetalk_preview_timer.setInterval(interval)
        if next_musetalk == self._musetalk_state:
            return
        self._musetalk_state = next_musetalk
        self.musetalkStateChanged.emit()

    def _refresh_visuals_if_visible(self) -> None:
        if self._conversation_views or self._visual_reply_views or self._workspace in {"visuals", "musetalk"}:
            self.refreshVisualState()

    @QtCore.Slot()
    def refreshSpotifySenseState(self) -> None:
        next_state: dict[str, Any] = {"available": False}
        result = self._application.addons.invoke_addon_capability(
            "nc.spotify_sense",
            "runtime.spotify.native_snapshot",
            {},
        )
        if result.accepted and isinstance(result.value, Mapping):
            next_state = dict(_plain(result.value) or {})
            next_state["available"] = True
        if next_state == self._spotify_sense_state:
            return
        self._spotify_sense_state = next_state
        self.spotifySenseStateChanged.emit()

    def _refresh_spotify_sense_if_visible(self) -> None:
        if self._workspace in {"addons", "conversation"}:
            self.refreshSpotifySenseState()

    @QtCore.Slot(str, "QVariant")
    def triggerSpotifySenseAction(self, action: str, payload: Any) -> None:
        action_name = str(action or "").strip().lower()
        if not action_name:
            return
        action_payload = _plain(payload)
        request = (
            dict(action_payload)
            if isinstance(action_payload, Mapping)
            else {}
        )
        request["action"] = action_name
        result = self._application.addons.invoke_addon_capability(
            "nc.spotify_sense",
            "runtime.spotify.native_action",
            request,
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Spotify Sense action failed",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Spotify Sense is unavailable.",
                    )
                ),
            )
            return
        QtCore.QTimer.singleShot(0, self.refreshSpotifySenseState)

    @QtCore.Slot()
    def resetMusetalkZoom(self) -> None:
        self._application.addons.invoke_service_capability(
            "avatar_provider_registry",
            "runtime.preview.reset_zoom",
            {},
            provider_id="musetalk",
        )

    @QtCore.Slot()
    def showVisualReply(self) -> None:
        self.openWorkspace("visuals")

    @QtCore.Slot()
    def clearVisualReply(self) -> None:
        self._visual_reply_toolbar.clear()

    @QtCore.Slot(str, result=bool)
    def loadVisualReplyImage(self, url_or_path: str) -> bool:
        return self._visual_reply_toolbar.load_image(url_or_path)

    @QtCore.Slot(result=bool)
    def prepareVisualReplyStorage(self) -> bool:
        return self._visual_reply_toolbar.prepare_storage()

    @QtCore.Slot(int, result=bool)
    def navigateVisualReply(self, offset: int) -> bool:
        return self._visual_reply_toolbar.navigate(offset)

    @QtCore.Slot(str, result=bool)
    def setVisualReplyCaption(self, caption: str) -> bool:
        return self._visual_reply_toolbar.set_caption(caption)

    @QtCore.Slot(result=bool)
    @QtCore.Slot(str, result=bool)
    def deleteVisualReplyImage(self, expected_path: str | None = None) -> bool:
        return self._visual_reply_toolbar.delete_current(expected_path)

    @QtCore.Slot(result=bool)
    def deleteAllVisualReplyImages(self) -> bool:
        return self._visual_reply_toolbar.delete_all()

    @QtCore.Slot(result=bool)
    def loadCurrentStoryVisualReply(self) -> bool:
        return self._visual_reply_toolbar.load_current_story_image()

    @QtCore.Slot(result=bool)
    def useCurrentVisualReplyStyle(self) -> bool:
        return self._visual_reply_toolbar.use_current_image_style()

    @QtCore.Slot(bool)
    def setVisualReplyToolbarExpanded(self, expanded: bool) -> None:
        selected = bool(expanded)
        if selected == self.visualReplyToolbarExpanded:
            return
        result = self._application.config.update(
            "visual_reply_toolbar_expanded", selected
        )
        if not result.accepted:
            self.notificationRaised.emit(
                "error",
                "Visual Reply toolbar preference was not saved",
                str(
                    getattr(
                        result.failure,
                        "message",
                        "Could not update the Visual Reply toolbar layout.",
                    )
                ),
            )
            return
        self._session_store.save()
        self.configurationChanged.emit()

    @QtCore.Slot()
    def showMusetalkPreview(self) -> None:
        self.openWorkspace("musetalk")

    @QtCore.Slot()
    def toggleAvatarFocus(self) -> None:
        avatar_mode = str(
            self._application.config.snapshot().values.get("avatar_mode", "") or ""
        ).strip()
        self.externalAvatarFocusRequested.emit(avatar_mode or "Avatar")

    @QtCore.Slot()
    def refreshProviderState(self) -> None:
        from ui.qml_bridge.settings_help import field_help
        config = dict(self._application.config.snapshot().values)
        settings_map = _plain(config.get("chat_provider_settings", {})) or {}
        generation_map = _plain(config.get("chat_provider_generation_settings", {})) or {}
        items: list[dict[str, Any]] = []
        for provider in chat_providers.list_providers():
            summary = _plain(provider.to_summary())
            provider_id = str(summary.get("id") or "").strip().lower()
            if not provider_id:
                continue
            settings = dict(settings_map.get(provider_id) or {})
            generation = dict(generation_map.get(provider_id) or {})
            metadata = dict(summary.get("metadata") or {})
            config_fields = list(summary.get("config_fields") or metadata.get("config_fields") or [])
            generation_fields = list(summary.get("generation_fields") or metadata.get("generation_fields") or [])
            field_items = []
            for raw_field in config_fields:
                field = dict(raw_field or {})
                field_id = str(field.get("id") or "").strip()
                if not field_id or field_id.startswith("_"):
                    continue
                secret = bool(field.get("secret", False)) or field_id in {"api_key", "token"}
                current_value = settings.get(field_id, field.get("default", ""))
                field_items.append(
                    {
                        **field,
                        "toolTip": field_help(field, f"chat_provider:{provider_id}"),
                        "id": field_id,
                        "label": str(field.get("label") or field_id.replace("_", " ").title()),
                        "value": "••••••••" if secret and current_value else current_value,
                        "secret": secret,
                    }
                )
            generation_items = []
            for raw_field in generation_fields:
                field = dict(raw_field or {})
                field_id = str(field.get("id") or "").strip()
                # Runtime-only frozen metadata participates in request binding
                # but is not a user-editable provider control.
                if not field_id or field_id.startswith("_"):
                    continue
                generation_items.append(
                    {
                        **field,
                        "toolTip": field_help(field, f"chat_provider:{provider_id}"),
                        "id": field_id,
                        "label": str(field.get("label") or field_id.replace("_", " ").title()),
                        "value": generation.get(field_id, field.get("default", "")),
                    }
                )
            normal_chat = dict(summary.get("normal_chat") or {})
            model_name = str(settings.get("model_name") or "")
            items.append(
                {
                    **summary,
                    "id": provider_id,
                    "label": str(summary.get("label") or provider_id),
                    "description": str(summary.get("description") or normal_chat.get("message") or "Language model provider"),
                    "available": bool(normal_chat.get("available", True)),
                    "active": provider_id == self.activeProviderId,
                    "modelName": model_name,
                    "status": "active" if provider_id == self.activeProviderId else "ready" if model_name else "needs-model",
                    "fields": field_items,
                    "generationFields": generation_items,
                }
            )
        self._providers = items
        if not self._viewed_provider:
            self._viewed_provider = self.activeProviderId
        self.providersChanged.emit()
        self.providerViewChanged.emit()
        self.configurationChanged.emit()

    @staticmethod
    def _addon_setting_section(key: str, sections: list[str]) -> str:
        if not sections:
            return "Overview"
        lowered = str(key or "").lower()
        rules = (
            (("hotkey", "shortcut", "binding"), ("hotkey", "binding")),
            (("eye", "gaze", "dwell", "blink"), ("eye", "gaze")),
            (("vision", "lfm", "ground", "ocr", "bounding", "click", "action"), ("vision", "action")),
            (("read", "clipboard", "text_select"), ("read", "clipboard")),
            (("aware", "sensory", "supervisor", "background", "proactive"), ("aware", "overview")),
            (("audio", "spectrum", "react", "voice", "tts", "duck"), ("audio", "voice", "tts", "duck")),
            (("look", "color", "opacity", "particle", "shader", "glow", "size", "style"), ("look", "visual", "display", "effect")),
            (("connect", "server", "host", "port", "url", "lan", "pair"), ("connect", "lan", "pair", "setup")),
            (("play", "pause", "track", "music"), ("playback", "play", "music")),
            (("debug", "diagnostic", "log", "advanced"), ("debug", "diagnostic", "advanced")),
        )
        normalized_sections = [(section, section.lower()) for section in sections]
        for key_tokens, section_tokens in rules:
            if not any(token in lowered for token in key_tokens):
                continue
            for section, section_lower in normalized_sections:
                if any(token in section_lower for token in section_tokens):
                    return section
        return sections[0]

    @classmethod
    def _addon_setting_schema(
        cls,
        defaults: dict[str, Any],
        sections: list[str],
    ) -> list[dict[str, Any]]:
        schema: list[dict[str, Any]] = []
        for key, default_value in defaults.items():
            config_key = str(key or "").strip()
            if not config_key:
                continue
            lowered = config_key.lower()
            secret = any(token in lowered for token in ("api_key", "token", "password", "secret"))
            json_value = isinstance(default_value, (dict, list))
            if isinstance(default_value, bool):
                field_type = "boolean"
            elif isinstance(default_value, int):
                field_type = "integer"
            elif isinstance(default_value, float):
                field_type = "number"
            elif json_value or any(
                token in lowered
                for token in ("prompt", "template", "instructions", "mapping", "personas")
            ):
                field_type = "multiline"
            else:
                field_type = "text"
            label = config_key.replace("_", " ").strip().title()
            schema.append(
                {
                    "key": config_key,
                    "label": label,
                    "description": "",
                    "type": field_type,
                    "section": cls._addon_setting_section(config_key, sections),
                    "defaultValue": _plain(default_value),
                    "secret": secret,
                    "json": json_value,
                    "height": 148 if field_type == "multiline" else 0,
                }
            )
        return schema

    @QtCore.Slot()
    def refreshAddonState(self) -> None:
        catalog_result = self._application.addons.registry_snapshot()
        recovery_failure = getattr(catalog_result, "failure", None)
        recovery_required = (
            getattr(recovery_failure, "category", "") == "addon_registry_recovery_required"
        )
        recovery_message = str(getattr(recovery_failure, "message", "")) if recovery_required else ""
        if recovery_message != getattr(self, "_addon_registry_recovery_message", ""):
            self._addon_registry_recovery_message = recovery_message
            if recovery_message:
                self.notificationRaised.emit(
                    "error", "Addon registry recovery required", recovery_message,
                )
        manager = (
            _NativeAddonCatalogView(
                [dict(item or {}) for item in list(catalog_result.value or ())]
            )
            if catalog_result.accepted or recovery_required
            else None
        )
        items = [
            {
                **dict(item),
                "icon": _local_asset_url(str(item.get("iconAsset") or "")),
                "addonId": "",
                "status": "ready",
                "sections": ["Overview"],
                "core": True,
            }
            for item in self._CORE_ADDON_WORKSPACES
        ]
        settings_by_workspace: dict[str, dict[str, Any]] = {
            str(item.get("id") or ""): {
                "addonId": "",
                "schema": [],
                "defaults": {},
            }
            for item in items
        }
        registry: list[dict[str, Any]] = []
        if manager is not None:
            try:
                registry = [_plain(item) for item in manager.get_addon_registry_snapshot()]
            except Exception:
                registry = []
            contributions = []
            for contribution_area in (
                "top_level",
                "host_settings",
                "tts_runtime",
                "vision_source",
                "avatar_tools",
                "visual_reply_runtime",
            ):
                try:
                    area_items = list(
                        manager.get_tab_contributions(area=contribution_area) or []
                    )
                except Exception:
                    area_items = []
                contributions.extend(area_items)
            for contribution in contributions:
                addon_id = str(getattr(contribution, "addon_id", "") or "").strip()
                contribution_id = str(getattr(contribution, "id", "") or addon_id).strip()
                if not contribution_id:
                    continue
                record = manager.get_addon_record(addon_id) if addon_id else None
                if record is None:
                    continue
                initialized = record.state == "initialized"
                manifest = getattr(record, "manifest", None)
                metadata = dict(getattr(contribution, "metadata", {}) or {})
                icon_text = str(
                    getattr(contribution, "icon_path", "")
                    or metadata.get("icon_path")
                    or ""
                ).strip()
                if icon_text:
                    icon_path = Path(icon_text)
                    if not icon_path.is_absolute() and manifest is not None:
                        try:
                            icon_path = manifest.root_dir / icon_path
                        except Exception:
                            pass
                    if icon_path.exists():
                        icon_text = QtCore.QUrl.fromLocalFile(str(icon_path.resolve())).toString()
                    else:
                        icon_text = ""
                contribution_area = str(
                    getattr(contribution, "area", "top_level") or "top_level"
                ).strip().lower()
                if not icon_text:
                    fallback_asset = self._ADDON_ICON_ASSETS.get(
                        addon_id,
                        self._CONTRIBUTION_AREA_ICON_ASSETS.get(
                            contribution_area,
                            "ui_icons/side_tabs/brain.png",
                        ),
                    )
                    icon_text = _local_asset_url(fallback_asset)
                manifest_name = str(getattr(manifest, "name", "") or addon_id)
                manifest_category = str(
                    getattr(manifest, "category", "") or ""
                ).strip().lower()
                contribution_title = str(
                    getattr(contribution, "title", "") or manifest_name or contribution_id
                )
                label = (
                    contribution_title
                    if contribution_area == "top_level"
                    else f"{manifest_name} · {contribution_title}"
                )
                description = str(
                    getattr(contribution, "tooltip", "")
                    or getattr(manifest, "description", "")
                    or "NeuralCompanion addon workspace"
                )
                sections = list(self._ADDON_SECTIONS.get(addon_id, ("Overview",)))
                native_adapter = (
                    (self._native_surfaces.adapter(contribution_id)
                     or self._native_surfaces.adapter_for_addon(addon_id))
                    if initialized else None
                )
                if native_adapter is not None:
                    try:
                        sections = list(native_adapter.snapshot().sections)
                    except (KeyError, RuntimeError, TypeError, ValueError):
                        sections = sections or ["Overview"]
                if addon_id == "nc.companion_orb_overlay":
                    # Keep the native surface complete for the Vision Sensors host.
                    sections = [section for section in sections
                                if section not in {"Awareness", "Vision & Actions"}]
                if addon_id == "nc.spotify_sense":
                    # Sensory controls stay in the complete adapter for Vision sensors.
                    sections = [section for section in sections
                                if section not in {"Awareness", "Hidden Sense"}]
                runtime_defaults: dict[str, Any] = dict(
                    getattr(manifest, "runtime_defaults", {}) or {}
                )
                manifest_path = getattr(manifest, "manifest_path", None)
                if not runtime_defaults and manifest_path is not None:
                    try:
                        manifest_payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                        raw_defaults = manifest_payload.get("runtime_defaults", {})
                        if isinstance(raw_defaults, dict):
                            runtime_defaults = {
                                str(key): value
                                for key, value in raw_defaults.items()
                            }
                    except (OSError, ValueError, TypeError):
                        runtime_defaults = {}
                schema = self._addon_setting_schema(runtime_defaults, sections) if initialized else []
                contribution_checkable = bool(metadata.get("checkable", False))
                contribution_enabled = True
                if contribution_checkable and initialized:
                    enabled_result = self._application.addons.invoke_addon_capability(
                        addon_id,
                        "ui.tab_enabled",
                        {
                            "addon_id": addon_id,
                            "tab_id": contribution_id,
                            "action": "get",
                        },
                    )
                    if enabled_result.accepted and isinstance(
                        enabled_result.value, Mapping
                    ):
                        contribution_enabled = bool(
                            enabled_result.value.get("enabled", True)
                        )
                addon_enabled = bool(getattr(manifest, "enabled", True))
                effective_enabled = addon_enabled
                if record is not None:
                    try:
                        override = manager._addon_enabled_override(addon_id)
                        addon_enabled = bool(getattr(manifest, "enabled", True) if override is None else override)
                        effective_enabled = bool(manager._manifest_effectively_enabled(manifest))
                    except Exception:
                        effective_enabled = addon_enabled
                provider_id = str(metadata.get("provider_id") or "").strip().lower()
                is_musetalk_creator = (
                    addon_id == "nc.musetalk_preprocess"
                    and contribution_id == "musetalk_preprocess_tab"
                )
                if is_musetalk_creator:
                    label = "MuseTalk Avatar Creator"
                provider_surface = bool(
                    not is_musetalk_creator
                    and (
                        contribution_area
                        in {
                            "tts_runtime",
                            "vision_source",
                            "avatar_tools",
                            "visual_reply_runtime",
                        }
                    or (
                        contribution_area == "top_level"
                        and manifest_category == "avatar"
                        and provider_id
                    )
                    )
                )
                items.append(
                    {
                        "id": contribution_id,
                        "addonId": addon_id,
                        "label": label,
                        "description": description,
                        "area": contribution_area,
                        "areaLabel": contribution_area.replace("_", " ").title(),
                        "parentTabId": str(getattr(contribution, "parent_tab_id", "") or ""),
                        "backendId": str(metadata.get("backend_id") or "").strip().lower(),
                        "providerId": provider_id,
                        "providerSurface": provider_surface,
                        "category": manifest_category,
                        "contributionTitle": contribution_title,
                        "contributionCheckable": contribution_checkable,
                        "contributionEnabled": contribution_enabled,
                        "glyph": "◇",
                        "icon": icon_text,
                        "status": str(getattr(record, "state", "initialized") or "initialized"),
                        "sections": sections,
                        "core": False,
                        "version": str(getattr(manifest, "version", "") or ""),
                        "enabled": addon_enabled,
                        "effectiveEnabled": effective_enabled,
                        "available": initialized and addon_enabled and effective_enabled,
                        "settingCount": len(schema),
                        "nativeSurface": native_adapter is not None,
                    }
                )
                if initialized and addon_enabled and effective_enabled:
                    settings_by_workspace[contribution_id] = {
                        "addonId": addon_id,
                        "schema": schema,
                        "defaults": runtime_defaults,
                    }
        self._addon_workspaces = items
        self._apply_addon_rail_layout()
        self._addon_registry = registry
        self._addon_settings_by_workspace = settings_by_workspace
        self.addonsChanged.emit()
        self.addonViewChanged.emit()
        self.addonSettingsChanged.emit()
        self._musetalk_creator.refresh()
        QtCore.QTimer.singleShot(0, self.refreshLiveAddonControls)

    @QtCore.Slot()
    def close(self) -> None:
        if self._closing:
            return
        # Main.qml guards the cancellable close request. This final disposer is
        # also called after Qt has already committed to quitting.
        self._shutdown_chat_preconfirmed = True
        if not getattr(self, "_application_shutdown_ready", False):
            self._close_after_creator_shutdown = True
            if not self.beginApplicationShutdown():
                return
        if not self._application_closing:
            self._application_closing = True
            self.applicationClosingChanged.emit()
        self._closing = True
        resource_monitor = getattr(self, '_resource_monitor', None)
        if resource_monitor is not None:
            resource_monitor.close()
        room = getattr(self, '_room_conversation', None)
        if room is not None:
            room.close()
        guard = getattr(self, '_chat_context_guard', None)
        if guard is not None:
            self._chat_guard_binding.close()
            guard.close()
        prompt_builder = getattr(self, "_prompt_builder", None)
        if prompt_builder is not None:
            prompt_builder.close()
        self._conversation_commands.close()
        self._visual_reply_toolbar.close()
        embedding_setup = getattr(self, '_embedding_setup', None)
        if embedding_setup is not None:
            embedding_setup.close()
        memory_workspace = getattr(self, "_memory_workspace", None)
        if memory_workspace is not None:
            memory_workspace.close()
        sensory_image_status = getattr(self, "_sensory_image_status", None)
        if sensory_image_status is not None:
            sensory_image_status.close()
        self._restore_tutorial_widget_states()
        self._tutorial_narration.stop()
        self._conversation_timer.stop()
        self._conversation_views.clear()
        self._conversation_refresh_timer.stop()
        self._live_session_timer.stop()
        self._document_memory_timer.stop()
        document_adapter = self._native_surfaces.adapter("rag_context_tab")
        if document_adapter is not None:
            document_adapter.close()
        self._visual_timer.stop()
        self._musetalk_preview_timer.stop()
        self._operations_timer.stop()
        self._persona_avatar_timer.stop()
        self._user_identity_avatar_timer.stop()
        if self._config_subscription is not None:
            try:
                self._config_subscription.close()
            except Exception:
                pass
            self._config_subscription = None
        notice_subscription = getattr(self, '_mcp_model_notice_subscription', None)
        if notice_subscription is not None:
            notice_subscription.close()
            self._mcp_model_notice_subscription = None
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._comfyui_executor.shutdown(wait=False, cancel_futures=True)
        self._runtime_executor.shutdown(wait=False, cancel_futures=True)
        self._persona_executor.shutdown(wait=False, cancel_futures=True)
        self._audio_controls.close()
        self._ui_review_notes.close()
        self._musetalk_creator.close()
        self._native_surfaces.close()
        self._runtime_controller.close()
        self._addon_runtime.close()
        self._console_capture.close()

    @QtCore.Slot(bool, str)
    def _on_native_runtime_finished(self, accepted: bool, error: str) -> None:
        if self._closing:
            return
        self.runtimeChanged.emit()
        self.refreshLiveSessionState()
        if not accepted and error:
            self.notificationRaised.emit("error", "Runtime stopped with an error", error)

    @QtCore.Slot(str)
    def _append_console_text(self, text: str) -> None:
        if self._closing:
            return
        incoming = str(text or "")
        self._console_text += incoming
        if len(self._console_text) > self._console_max_characters:
            self._console_text = self._console_text[-self._console_max_characters :]
        failure_message = _provider_failure_message(incoming)
        if failure_message:
            self._voice_error_message = failure_message
            self._voice_error_until = time.monotonic() + 8.0
            self.refreshLiveSessionState()
        self.consoleChanged.emit()

    @QtCore.Slot(object)
    def _on_mcp_model_notice(self, event: Any) -> None:
        if getattr(self, '_closing', False):
            return
        payload = getattr(event, 'payload', None)
        message = payload.get('message') if isinstance(payload, Mapping) else None
        if isinstance(message, str) and message:
            self.notificationRaised.emit('warning', 'MCP tools unavailable for this model', message)

    @QtCore.Slot(object)
    def _on_configuration_received(self, _event: Any) -> None:
        if not self._closing:
            if normalize_visual_batch_size(self._application.config.get("chat_visual_batch_size", 200)) != self._conversation_window.batch_size:
                self._conversation_revision = -1
                self.refreshConversationState()
            self.refreshProviderState()
            self.sessionSetupChanged.emit()
            self.visualReplySetupChanged.emit()
            self.coreSettingsChanged.emit()
            self.speechTimingSettingsChanged.emit()
            self.themeChanged.emit()
            self.personaChanged.emit()

    @QtCore.Slot(str, object, str)
    def _on_models_received(self, provider_id: str, models: Any, error: str) -> None:
        if self._closing:
            return
        normalized_models, catalog_error = _normalize_model_catalog(models)
        refresh_message = str(error or catalog_error or "").strip()
        if catalog_error and provider_id == "lmstudio" and not error:
            refresh_message = "LM Studio is not running or its local server is unavailable."
        if not normalized_models and not refresh_message:
            refresh_message = (
                f"No models were returned by {chat_providers.provider_label(provider_id)}."
            )
        if provider_id == self._model_refresh_provider:
            self._model_refresh_in_flight = False
            self._model_refresh_provider = ""
            self._model_refresh_message = refresh_message
            self.modelRefreshChanged.emit()
        if provider_id != self.viewedProviderId:
            self.ensureViewedProviderModels()
            return
        self._models = normalized_models
        visible_names = self.modelNames
        selected = str(self.viewedProvider.get("modelName") or "").strip()
        restored_model = _single_loaded_lmstudio_model(
            provider_id,
            selected,
            normalized_models,
        )
        if restored_model:
            self.selectModel(restored_model)
            selected = restored_model
        if self.modelRequiresVision and not self.modelRequiresTools and visible_names and selected not in visible_names:
            self.selectModel(visible_names[0])
        self.modelCatalogChanged.emit()
        if error:
            self.notificationRaised.emit("error", "Model refresh failed", str(error))

    @QtCore.Slot(str, object, str)
    def _on_provider_test_received(self, provider_id: str, models: Any, error: str) -> None:
        if self._closing:
            return
        if provider_id == self._provider_test_provider:
            self._provider_test_in_flight = False
            self._provider_test_provider = ""
            self.providerTestChanged.emit()
        if provider_id != self.viewedProviderId:
            self.ensureViewedProviderModels()
            return
        normalized_models, catalog_error = _normalize_model_catalog(models)
        test_error = str(error or catalog_error or "").strip()
        if test_error:
            self.notificationRaised.emit("error", "Provider test failed", test_error)
            return
        self._models = normalized_models
        visible_names = self.modelNames
        selected = str(self.viewedProvider.get("modelName") or "").strip()
        restored_model = _single_loaded_lmstudio_model(
            provider_id,
            selected,
            normalized_models,
        )
        if restored_model:
            self.selectModel(restored_model)
            selected = restored_model
        if self.modelRequiresVision and not self.modelRequiresTools and visible_names and selected not in visible_names:
            self.selectModel(visible_names[0])
        self.modelCatalogChanged.emit()
        count = len(self._models)
        detail = f"Connected. {count} model{'s' if count != 1 else ''} available."
        self.notificationRaised.emit("success", "Provider is ready", detail)

    @QtCore.Slot(str, str, bool, str)
    def _on_runtime_operation_received(
        self,
        kind: str,
        backend_id: str,
        accepted: bool,
        error: str,
    ) -> None:
        if self._closing:
            return
        pending_kind = str(self._runtime_operation or "").strip().lower()
        pending_backend = str(self._runtime_operation_backend or "").strip().lower()
        callback_kind = str(kind or "").strip().lower()
        callback_backend = str(backend_id or "").strip().lower()
        if not pending_kind or pending_kind != callback_kind:
            return
        if pending_backend and pending_backend != callback_backend:
            return
        previous = self._runtime_operation_previous
        self._runtime_operation = ""
        self._runtime_operation_backend = ""
        self._runtime_operation_previous = None
        self.runtimeOperationChanged.emit()
        if not accepted:
            if callback_kind == "tts":
                self._remote_tts_provider_failed = True
                self._remote_tts_provider_message = "TTS provider could not start. Check its settings on NC desktop."
            if previous is not None:
                self._application.config.update_many(previous)
                self.configurationChanged.emit()
            self.notificationRaised.emit(
                "error",
                f"{str(kind).upper()} runtime could not start",
                str(error or f"The {backend_id} backend rejected reinitialization."),
            )
            return
        try:
            self._save_native_session_or_raise()
        except (OSError, RuntimeError, TypeError, ValueError) as save_error:
            if callback_kind == "tts":
                self._remote_tts_provider_failed = True
                self._remote_tts_provider_message = "TTS provider changed but its selection could not be saved. Check NC desktop."
            if previous is not None:
                self._application.config.update_many(previous)
                self.configurationChanged.emit()
            self.notificationRaised.emit(
                "error",
                "Runtime was not changed",
                str(save_error),
            )
            return
        if callback_kind == "tts":
            self._remote_tts_provider_failed = False
            self._remote_tts_provider_message = "TTS provider is ready for new replies."
        self.notificationRaised.emit(
            "success",
            f"{str(kind).upper()} runtime ready",
            str(backend_id),
        )


__all__ = ["QmlApplicationBridge"]
