"""Complete typed native-QML adapter for the Companion Orb addon."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from PySide6 import QtCore, QtGui

from addons.companion_orb_overlay.native_contract import NATIVE_CONTROL_SPECS
from ui.qml_bridge.adapters.companion_orb_layout import (
    apply_companion_orb_layout,
    ordered_companion_orb_sections,
)
from ui.qml_bridge.adapters.parity_contract import (
    controls_from_specs,
    sections_from_specs,
)
from ui.qml_bridge.native_contracts import NativeControl, NativeSurface, choices
from ui.qml_bridge.native_registry import NativeSurfaceAdapter
from core import chat_providers
from ui.qml_bridge.model_catalog import model_catalog_entry_supports_images

_VISION_PROVIDER = 'companion_orb_vision_provider_id_edit'
_VISION_MODEL = 'companion_orb_vision_model_id_edit'
_VISION_REFRESH = 'companion_orb_vision_models_refresh'
_VISION_CONFIGURE = 'companion_orb_vision_provider_configure'
_VISION_STATUS = 'companion_orb_vision_catalog_status'

_ACTION_IDS = {
    str(spec["id"])
    for spec in NATIVE_CONTROL_SPECS
    if str(spec.get("kind")) == "action"
}

_ACTION_METADATA: dict[str, dict[str, Any]] = {
    str(spec["id"]): dict(spec.get("metadata") or {})
    for spec in NATIVE_CONTROL_SPECS
    if str(spec.get("kind")) == "action"
}

_COLOR_ACTIONS = {
    "companion_orb_eye_tracking_gaze_timer_color_pick_button",
    "companion_orb_eye_tracking_bounding_box_normal_color_pick_button",
    "companion_orb_eye_tracking_bounding_box_hover_color_pick_button",
    "companion_orb_eye_tracking_bounding_box_selected_color_pick_button",
    "companion_orb_primary_color_pick_button",
    "companion_orb_secondary_color_pick_button",
    "companion_orb_accent_color_pick_button",
    "companion_orb_glow_color_pick_button",
    "companion_orb_idle_color_pick_button",
    "companion_orb_thinking_color_pick_button",
    "companion_orb_speaking_color_pick_button",
}

_ACTION_METADATA.update(
    {
        "btn_companion_orb_open_debug_log_folder": {"execution": "ui"},
        "btn_companion_orb_clear_debug_log": {"destructive": True},
        "btn_companion_orb_copy_debug_log_path": {"execution": "ui"},
        "btn_companion_orb_copy_latest_vision_trace_path": {"execution": "ui"},
        "companion_orb_vision_pipeline_details_button": {
            "execution": "ui",
            "textViewer": True,
            "dialogTitle": "Companion Orb vision pipeline details",
            "viewerDescription": (
                "Current auxiliary-vision route, model ownership, and pipeline state."
            ),
        },
        "btn_companion_orb_supervisor_add_persona": {
            "execution": "ui",
            "inputPrompt": True,
            "dialogTitle": "Add Companion Orb supervisor persona",
            "inputLabel": "Persona name",
            "placeholderText": "Orb Supervisor",
        },
        "btn_companion_orb_supervisor_rename_persona": {
            "execution": "ui",
            "inputPrompt": True,
            "dialogTitle": "Rename Companion Orb supervisor persona",
            "inputLabel": "New persona name",
        },
        "btn_companion_orb_supervisor_delete_persona": {"destructive": True},
        "btn_companion_orb_supervisor_reset_template": {"destructive": True},
        "btn_companion_orb_reply_style_reset_all": {"destructive": True},
        "btn_companion_orb_reader_commentary_default": {"destructive": True},
        "companion_orb_eye_tracking_calibration_reset_button": {
            "destructive": True
        },
        "companion_orb_eye_tracking_browse_button": {
            "execution": "ui",
            "filePicker": True,
            "dialogTitle": "Select Tobii Stream Engine DLL",
            "nameFilters": ["Windows DLL (*.dll)", "All files (*)"],
        },
        "companion_orb_preset_save_as_button": {
            "execution": "ui",
            "inputPrompt": True,
            "dialogTitle": "Save Companion Orb preset as",
            "inputLabel": "Preset name",
            "placeholderText": "My Companion Orb",
        },
        "companion_orb_preset_delete_button": {"destructive": True},
    }
)

for _action_id in _COLOR_ACTIONS:
    _ACTION_METADATA[_action_id] = {
        "execution": "ui",
        "inputPrompt": True,
        "dialogTitle": "Choose Companion Orb color",
        "inputLabel": "Hex color",
        "placeholderText": "#38bdf8",
    }

for _index in range(1, 7):
    _remove_id = (
        "unnamed_qpushbutton_remove"
        if _index == 1
        else f"unnamed_qpushbutton_remove#{_index}"
    )
    _ACTION_METADATA[_remove_id] = {"destructive": True}


def _build_controls() -> tuple[NativeControl, ...]:
    rendered: list[NativeControl] = []
    for control in controls_from_specs(NATIVE_CONTROL_SPECS):
        if control.id in _ACTION_METADATA:
            rendered.append(replace(control, metadata=dict(_ACTION_METADATA[control.id])))
        else:
            rendered.append(control)
    return apply_companion_orb_layout(rendered)


class CompanionOrbNativeAdapter(NativeSurfaceAdapter):
    """Expose all reviewed Companion Orb controls through one typed surface."""

    def __init__(
        self,
        application_facade: Any,
        *,
        persist: Callable[[], object] | None = None,
        configure_provider: Callable[[str], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__("companion_orb_overlay_tab", "nc.companion_orb_overlay", parent)
        self._application = application_facade
        self._persist = persist
        self._configure_provider = configure_provider
        self._vision_lock = threading.RLock()
        self._vision_catalogs = {}
        self._vision_catalog_endpoints = {}
        self._vision_messages = {}
        self._revision = 0
        self._surface = NativeSurface(
            id=self.surface_id,
            title="Companion Orb",
            addon_id=self.addon_id,
            sections=ordered_companion_orb_sections(
                sections_from_specs(NATIVE_CONTROL_SPECS)
            ),
            description=(
                "Orb activation, desktop grounding, auxiliary vision, gaze interaction, "
                "reading, behavior rules, appearance, diagnostics, and reusable presets."
            ),
            controls=_build_controls(),
        )

    def _invoke(self, capability: str, payload: dict[str, Any] | None = None) -> Any:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Companion Orb is unavailable."))
            )
        return result.value

    @staticmethod
    def _pipeline_viewer_text(state: dict[str, Any]) -> str:
        vision = dict(state.get("vision_runtime") or {})
        safe = {
            key: vision.get(key)
            for key in (
                "state",
                "message",
                "runtime_location",
                "provider_id",
                "base_url",
                "model_id",
                "model_handling",
                "capability_mode",
                "loaded",
                "pipeline_status",
                "pipeline",
                "last_error",
            )
            if key in vision
        }
        return json.dumps(safe or {"state": "inactive"}, ensure_ascii=False, indent=2)

    def snapshot(self) -> NativeSurface:
        state = dict(self._invoke("runtime.companion_orb.native_snapshot") or {})
        controls_state = dict(state.get("controls") or {})
        values = dict(controls_state.get("values") or {})
        provider = str(values.get(_VISION_PROVIDER, 'lmstudio') or '')
        selected_model = str(values.get(_VISION_MODEL, '') or '')
        provider_options = [(p.id, p.label) for p in chat_providers.list_providers()]
        with self._vision_lock:
            models = self._current_vision_catalog(provider)
            status = self._vision_messages.get(provider, 'Refresh to discover vision-capable models.')
        if selected_model and selected_model not in {v for v, label in models}:
            status += f' Saved selection: {selected_model} (not verified in the current vision catalog).'
        if provider not in {v for v, label in provider_options}:
            status = f'Provider {provider or "(none)"} is unavailable. ' + status
        option_overrides = dict(controls_state.get("options") or {})
        enabled_overrides = dict(controls_state.get("enabled") or {})
        viewer_text = self._pipeline_viewer_text(state)
        rendered: list[NativeControl] = []
        for control in self._surface.controls:
            dynamic = option_overrides.get(control.id)
            replacement_choices = (
                choices(tuple(tuple(item) for item in dynamic))
                if isinstance(dynamic, (list, tuple)) and dynamic
                else control.choices
            )
            metadata = dict(control.metadata or {})
            if control.id == _VISION_PROVIDER:
                replacement_choices = choices(provider_options or [('', 'No registered providers')])
                metadata['selectionLabel'] = next((label for v, label in provider_options if v == provider), f'{provider} (unavailable)')
            elif control.id == _VISION_MODEL:
                replacement_choices = choices(models or [('', 'No vision models — refresh')])
                metadata['selectionLabel'] = selected_model or 'Select a vision model'
            elif control.id == _VISION_STATUS:
                values[control.id] = status
            elif control.id == _VISION_CONFIGURE:
                enabled_overrides[control.id] = callable(self._configure_provider) and provider in {v for v, label in provider_options}
            if control.id == "companion_orb_vision_pipeline_details_button":
                metadata["viewerText"] = viewer_text
            rendered.append(
                replace(
                    control,
                    value=values.get(control.id, control.default_value),
                    choices=replacement_choices,
                    enabled=bool(enabled_overrides.get(control.id, control.enabled)),
                    metadata=metadata,
                )
            )
        return replace(
            self._surface,
            controls=tuple(rendered),
            revision=self._revision,
        )

    def watch_rows(self):
        state=dict(self._invoke('runtime.companion_orb.native_snapshot') or {})
        return list((state.get('controls') or {}).get('watch_rows') or [])

    def _current_vision_catalog(self, provider):
        endpoint = chat_providers.provider_base_url(provider).rstrip('/')
        if self._vision_catalog_endpoints.get(provider) != endpoint:
            return []
        return list(self._vision_catalogs.get(provider, []))

    def watch_setup_snapshot(self, system_running: bool) -> dict:
        from addons.companion_orb_overlay.watch_setup import build_setup_snapshot
        from urllib.parse import urlsplit
        import hashlib
        config = dict(self._application.config.snapshot().values)
        try:
            native = dict(self._invoke('runtime.companion_orb.native_snapshot') or {})
            loaded = True
        except (RuntimeError, KeyError):
            native, loaded = {}, False
        controls = dict(native.get('controls') or {})
        provider = str(config.get('companion_orb_vision_provider_id') or '')
        model = str(config.get('companion_orb_vision_model_id') or '')
        with self._vision_lock:
            catalog = self._current_vision_catalog(provider)
        vision = dict(native.get('vision_runtime') or {})
        separate = config.get('companion_orb_vision_runtime_location', 'primary') in {'separate_local', 'lan'}
        vision_endpoint = (str(config.get('companion_orb_vision_base_url') or '') if separate
                           else chat_providers.provider_base_url(provider))
        known = not separate and model in {value for value, label in catalog}
        resident_endpoint = str(vision.get('endpoint') or '')
        if resident_endpoint == 'primary' and not separate:
            resident_endpoint = vision_endpoint
        matching_runtime = (vision.get('model_id') == model and vision.get('provider_id') == provider
                            and resident_endpoint.rstrip('/') == vision_endpoint.rstrip('/'))
        known = known or bool(vision.get('state') == 'ready' and matching_runtime)
        if matching_runtime and vision.get('state') in {'degraded', 'failed', 'unavailable'}:
            known = False
        metadata = chat_providers.provider_metadata(provider)
        credentials_ready = not metadata.get('supports_hosted_runtime') or bool(chat_providers.provider_api_key(provider))
        recipients, signatures = [], []
        for role, identity in [('Vision', provider), ('Chat', str(config.get('chat_provider') or 'lmstudio'))]:
            endpoint = vision_endpoint if role == 'Vision' else chat_providers.provider_base_url(identity)
            hostname = urlsplit(endpoint).hostname or ''
            remote = hostname not in {'localhost', '127.0.0.1', '::1'}
            selected_model = model if role == 'Vision' else str(config.get('model_name') or '')
            recipients.append(dict(label=f'{role}: {chat_providers.provider_label(identity)} / {selected_model}', remote=remote,
                                   may_charge=remote, location=hostname or 'remote/unknown'))
            signatures.append((identity, endpoint, selected_model))
        raw = config.get('sensory_feedback_source', '')
        sources = list(raw) if isinstance(raw, (list, tuple)) else str(raw).split(',')
        rows = controls.get('watch_rows') or []
        facts = dict(addon_loaded=loaded, system_running=system_running,
                     scope=controls.get('capture_scope') or {}, model_ready=bool(model and known and credentials_ready and chat_providers.get_provider(provider)),
                     model_reason=('Configure the selected provider’s API key.' if not credentials_ready else
                                   'Choose a vision model, then use Refresh models to verify its availability.'),
                     image_recipients=recipients, enabled_sources=[s for s in sources if s],
                     watch_count=sum(r.get('status') in {'watching', 'matched_pending'} for r in rows),
                     paused_reasons=controls.get('watch_paused_reasons') or [],
                     provider_signature=hashlib.sha256(repr((signatures, model)).encode()).hexdigest())
        result = build_setup_snapshot(config, facts)
        result['watch_rows'] = rows
        return result

    def apply_watch_setup(self, confirmation_key: str, system_running: bool) -> dict:
        preview = self.watch_setup_snapshot(system_running)
        if preview['confirmation_key'] != confirmation_key or preview['action'] != 'enable':
            raise ValueError('Setup changed. Review the current capture scope and providers again.')
        self.trigger_with_payload('companion_orb_watch_setup_apply', {'changes': preview['changes']})
        return self.watch_setup_snapshot(system_running)

    def set_value(self, control_id: str, value: Any) -> None:
        if control_id == _VISION_PROVIDER:
            if value not in {p.id for p in chat_providers.list_providers()}:
                raise ValueError('Choose a registered provider.')
            state = dict(self._invoke('runtime.companion_orb.native_snapshot') or {})
            previous = (state.get('controls') or {}).get('values', {}).get(_VISION_PROVIDER, 'lmstudio')
            if value == previous:
                return
            self._invoke('runtime.companion_orb.native_update_control', {'control_id': _VISION_MODEL, 'value': ''})
        elif control_id == _VISION_MODEL:
            state = dict(self._invoke('runtime.companion_orb.native_snapshot') or {})
            provider = (state.get('controls') or {}).get('values', {}).get(_VISION_PROVIDER, 'lmstudio')
            with self._vision_lock:
                allowed = {v for v, label in self._current_vision_catalog(provider)}
            if value not in allowed:
                raise ValueError('Choose a vision-capable model from this provider’s refreshed catalog.')
        self._invoke(
            "runtime.companion_orb.native_update_control",
            {"control_id": str(control_id or "").strip(), "value": value},
        )
        if callable(self._persist):
            self._persist()
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        key = str(control_id or "").strip()
        if key in {_VISION_REFRESH, _VISION_CONFIGURE}:
            state = dict(self._invoke('runtime.companion_orb.native_snapshot') or {})
            provider = str((state.get('controls') or {}).get('values', {}).get(_VISION_PROVIDER, 'lmstudio') or '')
            if provider not in {p.id for p in chat_providers.list_providers()}:
                raise ValueError('Choose an available provider first.')
            if key == _VISION_CONFIGURE:
                if callable(self._configure_provider):
                    self._configure_provider(provider)
                return
            models, status = [], ''
            catalog_endpoint = chat_providers.provider_base_url(provider).rstrip('/')
            try:
                catalog = self._application.providers.list_models(provider, quiet=True)
                for raw in catalog:
                    item = dict(raw) if isinstance(raw, Mapping) else {'id': str(raw or '')}
                    identity = str(item.get('id') or item.get('model') or item.get('name') or '').strip()
                    if identity.lower().startswith('error: check '):
                        status = 'Model catalog could not be retrieved. Check the shared provider settings.'
                    elif identity and model_catalog_entry_supports_images(item):
                        if identity not in {v for v, label in models}:
                            models.append((identity, str(item.get('label') or identity)))
                status = status or (f'{len(models)} vision-capable model(s). Shared provider connection; main chat unchanged.' if models
                    else 'No vision-capable models reported. Check the provider connection and installed models.')
            except Exception:
                status = 'Model catalog could not be retrieved. Check the shared provider settings.'
            with self._vision_lock:
                self._vision_catalogs[provider] = models
                self._vision_catalog_endpoints[provider] = catalog_endpoint
                self._vision_messages[provider] = status
            self._revision += 1
            self.changed.emit()
            return
        if key not in _ACTION_IDS:
            raise KeyError(f"Unknown Companion Orb action {control_id!r}.")
        metadata = _ACTION_METADATA[key]
        request: dict[str, Any] = {"payload": payload}
        if bool(metadata.get("destructive")):
            request["confirmed"] = True
        result = self._invoke(
            "runtime.companion_orb.native_control_action",
            {"control_id": key, "payload": request},
        )
        presentation = (
            dict((result or {}).get("presentation") or {})
            if isinstance(result, dict)
            else {}
        )
        clipboard_text = str(presentation.get("clipboard_suggestion") or "")
        if clipboard_text:
            clipboard = QtGui.QGuiApplication.clipboard()
            if clipboard is None:
                raise RuntimeError("The system clipboard is unavailable.")
            clipboard.setText(clipboard_text)
        open_folder = str(presentation.get("open_folder") or "").strip()
        if open_folder:
            if not QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(open_folder)
            ):
                raise RuntimeError(f"Could not open Companion Orb folder: {open_folder}")
        open_file = str(presentation.get('open_file') or '').strip()
        if open_file and key == 'companion_orb_watch_open_capture':
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(open_file)):
                raise RuntimeError('Could not open the observed watch capture.')
        self._revision += 1
        self.changed.emit()


def build_companion_orb_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
    configure_provider: Callable[[str], object] | None = None,
) -> CompanionOrbNativeAdapter:
    # Keep the setup surface available while the optional addon is disabled.
    # Native actions still reject unavailable runtime capabilities normally.
    return CompanionOrbNativeAdapter(application_facade, persist=persist, configure_provider=configure_provider)


__all__ = ["CompanionOrbNativeAdapter", "build_companion_orb_adapter"]
