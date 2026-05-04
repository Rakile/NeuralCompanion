"""Shell-preview Persona, body-pose, and VaM helpers.

These functions are used by the Designer shell/read-only preview path. Keeping
them outside qt_app.py makes the app entrypoint smaller while preserving the
same shell-safe behavior.
"""

from pathlib import Path

from core.runtime_paths import (
    derive_vam_bridge_root as _derive_vam_bridge_root_safe,
    legacy_vam_bridge_roots as _legacy_vam_bridge_roots_safe,
    normalize_vam_root as _normalize_vam_root_safe,
)
from ui.designer_loader import ui_shell_find_object as _ui_shell_find_object
from ui.runtime.shell_addon_reports import _read_ui_shell_session_snapshot
from ui.runtime.shell_session_config import (
    _ui_shell_body_config_payload,
    _ui_shell_checkbox_value,
    _ui_shell_combo_select_label,
    _ui_shell_combo_set_items,
    _ui_shell_combo_text_value,
    _ui_shell_current_voice_file,
    _ui_shell_line_edit_value,
    _ui_shell_list_body_configs,
    _ui_shell_selected_body_name,
    _ui_shell_set_checked,
    _ui_shell_set_spin_value,
    _ui_shell_voice_options,
)
from ui.runtime.shell_services import _UiShellPersonaAvatarService
from ui.runtime.shell_status_layout import _ui_shell_append_console
from ui.shell_specs import UI_SHELL_BODY_EMOTIONS, UI_SHELL_BODY_POSE_SPECS, UI_SHELL_DEFAULT_LOCAL_VAM_ROOT


def _ui_shell_body_pose_spec(key):
    return dict(UI_SHELL_BODY_POSE_SPECS.get(str(key), {}) or {})


def _ui_shell_body_slider_widget(window, key):
    spec = _ui_shell_body_pose_spec(key)
    return _ui_shell_find_object(window, spec.get("widget", ""))


def _ui_shell_body_label_widget(window, key):
    spec = _ui_shell_body_pose_spec(key)
    return _ui_shell_find_object(window, spec.get("label", ""))


def _ui_shell_body_value_to_slider_raw(key, value):
    spec = _ui_shell_body_pose_spec(key)
    scale = int(spec.get("scale", 1) or 1)
    try:
        return int(round(float(value) * scale))
    except Exception:
        return 0


def _ui_shell_body_slider_raw_to_value(key, raw_value):
    spec = _ui_shell_body_pose_spec(key)
    scale = float(spec.get("scale", 1) or 1)
    try:
        value = float(raw_value) / scale
    except Exception:
        value = float(spec.get("default", 0.0) or 0.0)
    if int(spec.get("scale", 1) or 1) == 1:
        return int(round(value))
    return round(value, 2)


def _ui_shell_format_body_value(key, value):
    spec = _ui_shell_body_pose_spec(key)
    if int(spec.get("scale", 1) or 1) == 1:
        try:
            return str(int(round(float(value))))
        except Exception:
            return str(value)
    try:
        return f"{float(value):.2f}"
    except Exception:
        return str(value)


def _ui_shell_update_body_label(window, key, value=None):
    label = _ui_shell_body_label_widget(window, key)
    if label is None or not hasattr(label, "setText"):
        return
    spec = _ui_shell_body_pose_spec(key)
    base_text = str(getattr(label, "_nc_ui_shell_base_text", "") or "").strip()
    if not base_text:
        base_text = str(label.text() or spec.get("title") or str(key)).strip() or str(key)
        setattr(label, "_nc_ui_shell_base_text", base_text)
    current = value
    if current is None:
        slider = _ui_shell_body_slider_widget(window, key)
        if slider is not None and hasattr(slider, "value"):
            try:
                current = _ui_shell_body_slider_raw_to_value(key, slider.value())
            except Exception:
                current = spec.get("default", 0.0)
    label.setText(f"{base_text}: {_ui_shell_format_body_value(key, current)}")


def _ui_shell_configure_body_slider(window, key, value=None):
    spec = _ui_shell_body_pose_spec(key)
    slider = _ui_shell_body_slider_widget(window, key)
    if slider is None:
        return False
    scale = int(spec.get("scale", 1) or 1)
    initial_value = spec.get("default", 0.0) if value is None else value
    minimum = _ui_shell_body_value_to_slider_raw(key, spec.get("minimum", 0.0))
    maximum = _ui_shell_body_value_to_slider_raw(key, spec.get("maximum", 0.0))
    raw_value = _ui_shell_body_value_to_slider_raw(key, initial_value)
    try:
        slider.blockSignals(True)
        if hasattr(slider, "setRange"):
            slider.setRange(minimum, maximum)
        if hasattr(slider, "setSingleStep"):
            slider.setSingleStep(max(1, scale // 10 if scale > 1 else 1))
        if hasattr(slider, "setPageStep"):
            page_step = max(1, int((maximum - minimum) / 10))
            slider.setPageStep(page_step)
        if hasattr(slider, "setValue"):
            slider.setValue(max(minimum, min(maximum, raw_value)))
        if hasattr(slider, "setToolTip"):
            slider.setToolTip("Shell-local body-pose preview. Changes are not saved or applied to runtime.")
    except Exception:
        return False
    finally:
        try:
            slider.blockSignals(False)
        except Exception:
            pass
    _ui_shell_update_body_label(window, key, initial_value)
    return True


def _ui_shell_current_body_pose_values(window):
    values = {}
    for key, spec in UI_SHELL_BODY_POSE_SPECS.items():
        slider = _ui_shell_body_slider_widget(window, key)
        if slider is not None and hasattr(slider, "value"):
            try:
                values[key] = _ui_shell_body_slider_raw_to_value(key, slider.value())
                continue
            except Exception:
                pass
        values[key] = spec.get("default", 0.0)
    return values


def _ui_shell_selected_body_profile(window):
    payload = getattr(window, "_nc_ui_shell_body_profile_payload", None)
    if isinstance(payload, dict):
        return payload
    return {}


def _ui_shell_set_selected_body_profile(window, payload):
    setattr(window, "_nc_ui_shell_body_profile_payload", dict(payload or {}))


def _ui_shell_apply_body_profile_for_emotion(window, emotion_label=None):
    emotion = str(emotion_label or _ui_shell_combo_text_value(window, "emotion_combo", "Neutral")).strip().lower() or "neutral"
    payload = _ui_shell_selected_body_profile(window)
    profile = dict(payload.get("profile") or payload or {})
    emotion_values = dict(profile.get(emotion) or profile.get("neutral") or {})
    applied = []
    for key in UI_SHELL_BODY_POSE_SPECS:
        if _ui_shell_configure_body_slider(window, key, value=emotion_values.get(key, UI_SHELL_BODY_POSE_SPECS[key].get("default", 0.0))):
            applied.append(key)
    return applied


def _ui_shell_refresh_body_combo(window, preferred_name=""):
    configs = _ui_shell_list_body_configs()
    combo = _ui_shell_find_object(window, "body_combo")
    if combo is None or not hasattr(combo, "addItem"):
        return configs
    preferred = str(preferred_name or _ui_shell_selected_body_name(window) or "").strip()
    combo.blockSignals(True)
    try:
        combo.clear()
        if configs:
            for name in configs:
                combo.addItem(name)
            target_index = 0
            if preferred and preferred in configs:
                target_index = configs.index(preferred)
            combo.setCurrentIndex(target_index)
        else:
            combo.addItem("No Configs")
            combo.setCurrentIndex(0)
        combo.setToolTip("Shell-local body preset list. Reads body_configs/*.json only.")
    finally:
        combo.blockSignals(False)
    return configs


def _ui_shell_load_body_preview(window, name=""):
    target = str(name or "").strip() or _ui_shell_selected_body_name(window)
    if not target or target == "No Configs":
        return {
            "accepted": False,
            "loaded": False,
            "body_name": "",
            "message": "No body preset selected.",
        }
    payload = _ui_shell_body_config_payload(target)
    if not payload:
        return {
            "accepted": False,
            "loaded": False,
            "body_name": target,
            "message": f"Could not load body preset: {target}",
        }
    _ui_shell_set_selected_body_profile(window, payload)
    _ui_shell_refresh_body_combo(window, preferred_name=target)
    applied = _ui_shell_apply_body_profile_for_emotion(window)
    return {
        "accepted": True,
        "loaded": True,
        "body_name": target,
        "applied_keys": applied,
        "message": f"Loaded shell preview for body preset: {target}",
    }


def _ui_shell_normalize_vam_root(raw_value=""):
    app_root = Path(__file__).resolve().parents[2]
    default_root = str(_read_ui_shell_session_snapshot().get("vam_root", "") or UI_SHELL_DEFAULT_LOCAL_VAM_ROOT).strip()
    legacy_roots = _legacy_vam_bridge_roots_safe(app_root=app_root)
    return _normalize_vam_root_safe(raw_value, default_vam_root=default_root, legacy_roots=legacy_roots, migrate_legacy=True)


def _ui_shell_derive_vam_bridge_root(vam_root):
    return _derive_vam_bridge_root_safe(vam_root, app_root=Path(__file__).resolve().parents[2])


def _ui_shell_current_vam_settings(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    vam_root = _ui_shell_line_edit_value(window, "vam_root_edit", str(session.get("vam_root", "") or UI_SHELL_DEFAULT_LOCAL_VAM_ROOT))
    normalized_root = _ui_shell_normalize_vam_root(vam_root)
    port_spin = _ui_shell_find_object(window, "vam_vmc_port_spin")
    return {
        "vam_root": normalized_root,
        "vam_bridge_root": _ui_shell_line_edit_value(window, "vam_bridge_root_edit", _ui_shell_derive_vam_bridge_root(normalized_root)),
        "vam_target_atom_uid": _ui_shell_line_edit_value(window, "vam_target_atom_uid_edit", str(session.get("vam_target_atom_uid", "Person") or "Person")),
        "vam_target_storable_id": _ui_shell_line_edit_value(window, "vam_target_storable_id_edit", str(session.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge")),
        "vam_vmc_host": _ui_shell_line_edit_value(window, "vam_vmc_host_edit", str(session.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1")),
        "vam_vmc_port": int(port_spin.value()) if port_spin is not None and hasattr(port_spin, "value") else int(session.get("vam_vmc_port", 39539) or 39539),
        "vam_vmc_enabled": _ui_shell_checkbox_value(window, "vam_vmc_enabled_checkbox", bool(session.get("vam_vmc_enabled", True))),
        "vam_bridge_enabled": _ui_shell_checkbox_value(window, "vam_bridge_enabled_checkbox", bool(session.get("vam_bridge_enabled", True))),
        "vam_play_audio_in_vam": _ui_shell_checkbox_value(window, "vam_play_audio_in_vam_checkbox", bool(session.get("vam_play_audio_in_vam", False))),
        "vam_timeline_auto_resume": _ui_shell_checkbox_value(window, "vam_timeline_auto_resume_checkbox", bool(session.get("vam_timeline_auto_resume", True))),
    }


def _ui_shell_refresh_vam_status_labels(window):
    settings = _ui_shell_current_vam_settings(window)
    runtime_label = _ui_shell_find_object(window, "vam_runtime_label")
    bridge_status_label = _ui_shell_find_object(window, "vam_bridge_status_label")
    bridge_detail_label = _ui_shell_find_object(window, "vam_bridge_detail_label")
    runtime_text = "Runtime: shell preview only"
    bridge_modes = []
    if settings.get("vam_vmc_enabled"):
        bridge_modes.append("VMC on")
    if settings.get("vam_bridge_enabled"):
        bridge_modes.append("Bridge on")
    bridge_text = ", ".join(bridge_modes) if bridge_modes else "all off"
    if runtime_label is not None and hasattr(runtime_label, "setText"):
        runtime_label.setText(runtime_text)
    if bridge_status_label is not None and hasattr(bridge_status_label, "setText"):
        bridge_status_label.setText(f"Bridge status: {bridge_text}")
    if bridge_detail_label is not None and hasattr(bridge_detail_label, "setText"):
        bridge_detail_label.setText(
            f"Root: {settings.get('vam_root') or '<unset>'} | Bridge: {settings.get('vam_bridge_root') or '<unset>'}"
        )
    return settings


def _ui_shell_persona_avatar_service(window):
    service = getattr(window, "_nc_ui_shell_persona_avatar_service", None)
    if service is None:
        service = _UiShellPersonaAvatarService(window)
        setattr(window, "_nc_ui_shell_persona_avatar_service", service)
    return service


def _bind_ui_shell_persona_body_vam_controls(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    service = _ui_shell_persona_avatar_service(window)
    bound = []
    deferred = [
        "btn_body_save",
        "btn_body_save_as",
        "btn_body_delete",
        "btn_hand_doctor",
        "btn_vseeface_hide_interface",
        "btn_start_vam_desktop",
        "btn_start_vam_vr",
        "btn_vam_hide_interface",
    ]

    voice_combo = _ui_shell_find_object(window, "voice_combo")
    emotional_text = _ui_shell_find_object(window, "emotional_text")
    system_prompt_text = _ui_shell_find_object(window, "system_prompt_text")
    apply_text_button = _ui_shell_find_object(window, "btn_apply_text_config")
    body_combo = _ui_shell_find_object(window, "body_combo")
    emotion_combo = _ui_shell_find_object(window, "emotion_combo")
    live_sync_checkbox = _ui_shell_find_object(window, "live_sync_checkbox")
    btn_body_load = _ui_shell_find_object(window, "btn_body_load")
    btn_body_save = _ui_shell_find_object(window, "btn_body_save")
    btn_body_save_as = _ui_shell_find_object(window, "btn_body_save_as")
    btn_body_delete = _ui_shell_find_object(window, "btn_body_delete")
    btn_hand_doctor = _ui_shell_find_object(window, "btn_hand_doctor")
    btn_vseeface_hide_interface = _ui_shell_find_object(window, "btn_vseeface_hide_interface")
    vam_root_edit = _ui_shell_find_object(window, "vam_root_edit")
    vam_bridge_root_edit = _ui_shell_find_object(window, "vam_bridge_root_edit")
    vam_target_atom_uid_edit = _ui_shell_find_object(window, "vam_target_atom_uid_edit")
    vam_target_storable_id_edit = _ui_shell_find_object(window, "vam_target_storable_id_edit")
    vam_vmc_host_edit = _ui_shell_find_object(window, "vam_vmc_host_edit")
    vam_vmc_port_spin = _ui_shell_find_object(window, "vam_vmc_port_spin")
    vam_vmc_enabled_checkbox = _ui_shell_find_object(window, "vam_vmc_enabled_checkbox")
    vam_bridge_enabled_checkbox = _ui_shell_find_object(window, "vam_bridge_enabled_checkbox")
    vam_play_audio_in_vam_checkbox = _ui_shell_find_object(window, "vam_play_audio_in_vam_checkbox")
    vam_timeline_auto_resume_checkbox = _ui_shell_find_object(window, "vam_timeline_auto_resume_checkbox")
    btn_start_vam_desktop = _ui_shell_find_object(window, "btn_start_vam_desktop")
    btn_start_vam_vr = _ui_shell_find_object(window, "btn_start_vam_vr")
    btn_vam_hide_interface = _ui_shell_find_object(window, "btn_vam_hide_interface")

    if voice_combo is not None:
        _ui_shell_combo_set_items(voice_combo, _ui_shell_voice_options(window))
        _ui_shell_combo_select_label(voice_combo, str(session.get("voice_file", "") or ""))
        voice_combo.setToolTip("Shell-local voice preview. No TTS backend is reloaded.")
    if emotional_text is not None and hasattr(emotional_text, "setPlainText"):
        emotional_text.setPlainText(str(session.get("emotional_instructions", "") or ""))
        emotional_text.setToolTip("Shell-local persona preview. Changes are not saved or applied to runtime.")
    if system_prompt_text is not None and hasattr(system_prompt_text, "setPlainText"):
        system_prompt_text.setPlainText(str(session.get("system_prompt", "") or ""))
        system_prompt_text.setToolTip("Shell-local system-prompt preview. Changes are not saved or applied to runtime.")

    configs = _ui_shell_refresh_body_combo(window, preferred_name=str(session.get("last_body", "") or ""))
    if emotion_combo is not None:
        _ui_shell_combo_set_items(emotion_combo, list(UI_SHELL_BODY_EMOTIONS))
        _ui_shell_combo_select_label(emotion_combo, "Neutral")
        emotion_combo.setToolTip("Shell-local emotion preview. Changes update only the visible shell sliders.")
    if live_sync_checkbox is not None:
        _ui_shell_set_checked(live_sync_checkbox, bool(session.get("live_sync", False)))
        live_sync_checkbox.setToolTip("Shell-local body sync preview. No avatar runtime mode changes occur.")
    for key in UI_SHELL_BODY_POSE_SPECS:
        _ui_shell_configure_body_slider(window, key)
    selected_body = str(session.get("last_body", "") or "").strip()
    if selected_body and selected_body in configs:
        _ui_shell_load_body_preview(window, selected_body)
    else:
        _ui_shell_set_selected_body_profile(window, {})
        _ui_shell_apply_body_profile_for_emotion(window)

    initial_vam_root = _ui_shell_normalize_vam_root(str(session.get("vam_root", "") or UI_SHELL_DEFAULT_LOCAL_VAM_ROOT))
    if vam_root_edit is not None and hasattr(vam_root_edit, "setText"):
        vam_root_edit.setText(initial_vam_root)
        vam_root_edit.setToolTip("Shell-local VaM root preview. Launch and bridge behavior remain deferred.")
    if vam_bridge_root_edit is not None and hasattr(vam_bridge_root_edit, "setText"):
        vam_bridge_root_edit.setText(_ui_shell_derive_vam_bridge_root(initial_vam_root))
        vam_bridge_root_edit.setReadOnly(True)
        vam_bridge_root_edit.setToolTip("Derived from VaM Root in shell preview.")
    if vam_target_atom_uid_edit is not None and hasattr(vam_target_atom_uid_edit, "setText"):
        vam_target_atom_uid_edit.setText(str(session.get("vam_target_atom_uid", "Person") or "Person"))
        vam_target_atom_uid_edit.setToolTip("Shell-local VaM target preview. Changes are not saved or applied to runtime.")
    if vam_target_storable_id_edit is not None and hasattr(vam_target_storable_id_edit, "setText"):
        vam_target_storable_id_edit.setText(str(session.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge"))
        vam_target_storable_id_edit.setToolTip("Shell-local VaM target preview. Changes are not saved or applied to runtime.")
    if vam_vmc_host_edit is not None and hasattr(vam_vmc_host_edit, "setText"):
        vam_vmc_host_edit.setText(str(session.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1"))
        vam_vmc_host_edit.setToolTip("Shell-local VaM VMC host preview. No socket is opened.")
    if vam_vmc_port_spin is not None:
        _ui_shell_set_spin_value(vam_vmc_port_spin, int(session.get("vam_vmc_port", 39539) or 39539))
        vam_vmc_port_spin.setToolTip("Shell-local VaM VMC port preview. No socket is opened.")
    for object_name, default_value, detail in (
        ("vam_vmc_enabled_checkbox", bool(session.get("vam_vmc_enabled", True)), "Shell-local VaM VMC preview. No runtime connector is started."),
        ("vam_bridge_enabled_checkbox", bool(session.get("vam_bridge_enabled", True)), "Shell-local VaM bridge preview. No file bridge is started."),
        ("vam_play_audio_in_vam_checkbox", bool(session.get("vam_play_audio_in_vam", False)), "Shell-local VaM audio preview. No audio routing changes occur."),
        ("vam_timeline_auto_resume_checkbox", bool(session.get("vam_timeline_auto_resume", True)), "Shell-local VaM timeline preview. No runtime bridge is started."),
    ):
        widget = _ui_shell_find_object(window, object_name)
        if widget is not None:
            _ui_shell_set_checked(widget, default_value)
            widget.setToolTip(detail)

    _ui_shell_refresh_vam_status_labels(window)

    def bind_signal(widget, attr_name, signal_name, handler):
        signal = getattr(widget, signal_name, None) if widget is not None else None
        if signal is None:
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return
        signal.connect(handler)
        setattr(widget, attr_name, True)

    bind_signal(voice_combo, "_nc_ui_shell_persona_avatar_bound", "currentIndexChanged", lambda _index=None: _ui_shell_append_console(window, f"[UI Shell] Voice preview: {_ui_shell_current_voice_file(window) or 'No .wav found'} selected; no TTS backend was reloaded."))
    bind_signal(apply_text_button, "_nc_ui_shell_persona_avatar_bound", "clicked", lambda _checked=False: (service.apply_persona(), _ui_shell_append_console(window, f"[UI Shell] Persona/body/VaM preview applied locally only. Voice={_ui_shell_current_voice_file(window) or '<none>'}, body={_ui_shell_selected_body_name(window) or '<none>'}.")))
    bind_signal(body_combo, "_nc_ui_shell_persona_avatar_bound", "currentIndexChanged", lambda _index=None: _ui_shell_append_console(window, f"[UI Shell] Body preset selected: {_ui_shell_selected_body_name(window) or 'No Configs'}. Use Load to apply the shell-safe preview."))
    bind_signal(btn_body_load, "_nc_ui_shell_persona_avatar_bound", "clicked", lambda _checked=False: _ui_shell_append_console(window, f"[UI Shell] {_ui_shell_load_body_preview(window).get('message') or 'No body preset selected.'}"))
    bind_signal(btn_body_save, "_nc_ui_shell_persona_avatar_bound", "clicked", lambda _checked=False: _ui_shell_append_console(window, "[UI Shell] Body save is deferred in shell preview; no files were written."))
    bind_signal(btn_body_save_as, "_nc_ui_shell_persona_avatar_bound", "clicked", lambda _checked=False: _ui_shell_append_console(window, "[UI Shell] Body save-as is deferred in shell preview; no files were written."))
    bind_signal(btn_body_delete, "_nc_ui_shell_persona_avatar_bound", "clicked", lambda _checked=False: _ui_shell_append_console(window, "[UI Shell] Body delete is deferred in shell preview; no files were removed."))
    bind_signal(emotion_combo, "_nc_ui_shell_persona_avatar_bound", "currentIndexChanged", lambda _index=None: (_ui_shell_apply_body_profile_for_emotion(window), _ui_shell_append_console(window, f"[UI Shell] Body emotion preview: {_ui_shell_combo_text_value(window, 'emotion_combo', 'Neutral')} selected; visible shell sliders were updated.")))
    bind_signal(live_sync_checkbox, "_nc_ui_shell_persona_avatar_bound", "toggled", lambda _checked=False: _ui_shell_append_console(window, f"[UI Shell] Live Sync preview: {'enabled' if _ui_shell_checkbox_value(window, 'live_sync_checkbox', False) else 'disabled'}; avatar runtime mode remains unchanged."))
    bind_signal(btn_hand_doctor, "_nc_ui_shell_persona_avatar_bound", "clicked", lambda _checked=False: _ui_shell_append_console(window, "[UI Shell] Hand Doctor is deferred in shell preview; no debugger window was opened."))
    bind_signal(btn_vseeface_hide_interface, "_nc_ui_shell_persona_avatar_bound", "clicked", lambda _checked=False: _ui_shell_append_console(window, "[UI Shell] VSeeFace interface-hide action is deferred in shell preview."))

    for key in UI_SHELL_BODY_POSE_SPECS:
        slider = _ui_shell_body_slider_widget(window, key)
        bind_signal(
            slider,
            "_nc_ui_shell_persona_avatar_bound",
            "valueChanged",
            lambda _value=None, key_name=key, slider_widget=slider: (
                _ui_shell_update_body_label(window, key_name, _ui_shell_body_slider_raw_to_value(key_name, slider_widget.value() if slider_widget is not None and hasattr(slider_widget, "value") else 0)),
                _ui_shell_append_console(window, f"[UI Shell] Body pose preview: {str(_ui_shell_body_pose_spec(key_name).get('title') or key_name)} -> {_ui_shell_format_body_value(key_name, _ui_shell_body_slider_raw_to_value(key_name, slider_widget.value() if slider_widget is not None and hasattr(slider_widget, 'value') else 0))}; runtime pose state remains unchanged."),
            ),
        )

    def on_vam_root_changed():
        normalized_root = _ui_shell_normalize_vam_root(_ui_shell_line_edit_value(window, "vam_root_edit", UI_SHELL_DEFAULT_LOCAL_VAM_ROOT))
        if vam_root_edit is not None and hasattr(vam_root_edit, "setText"):
            vam_root_edit.setText(normalized_root)
        if vam_bridge_root_edit is not None and hasattr(vam_bridge_root_edit, "setText"):
            vam_bridge_root_edit.setText(_ui_shell_derive_vam_bridge_root(normalized_root))
        _ui_shell_refresh_vam_status_labels(window)
        _ui_shell_append_console(window, f"[UI Shell] VaM root preview: {normalized_root or '<unset>'}; bridge path was derived locally only.")

    def on_vam_text_changed(label, object_name):
        _ui_shell_refresh_vam_status_labels(window)
        _ui_shell_append_console(window, f"[UI Shell] {label} preview: {_ui_shell_line_edit_value(window, object_name)}; runtime bridge settings remain unchanged.")

    def on_vam_check_changed(label, object_name):
        _ui_shell_refresh_vam_status_labels(window)
        _ui_shell_append_console(window, f"[UI Shell] {label} preview: {'enabled' if _ui_shell_checkbox_value(window, object_name, False) else 'disabled'}; no VaM connector was started.")

    bind_signal(vam_root_edit, "_nc_ui_shell_persona_avatar_bound", "editingFinished", on_vam_root_changed)
    bind_signal(vam_target_atom_uid_edit, "_nc_ui_shell_persona_avatar_bound", "editingFinished", lambda: on_vam_text_changed("VaM target atom UID", "vam_target_atom_uid_edit"))
    bind_signal(vam_target_storable_id_edit, "_nc_ui_shell_persona_avatar_bound", "editingFinished", lambda: on_vam_text_changed("VaM target storable ID", "vam_target_storable_id_edit"))
    bind_signal(vam_vmc_host_edit, "_nc_ui_shell_persona_avatar_bound", "editingFinished", lambda: on_vam_text_changed("VaM VMC host", "vam_vmc_host_edit"))
    bind_signal(vam_vmc_port_spin, "_nc_ui_shell_persona_avatar_bound", "valueChanged", lambda _value=None: (_ui_shell_refresh_vam_status_labels(window), _ui_shell_append_console(window, f"[UI Shell] VaM VMC port preview: {int(vam_vmc_port_spin.value()) if vam_vmc_port_spin is not None and hasattr(vam_vmc_port_spin, 'value') else 39539}; no socket was opened.")))
    bind_signal(vam_vmc_enabled_checkbox, "_nc_ui_shell_persona_avatar_bound", "toggled", lambda _checked=False: on_vam_check_changed("VaM VMC", "vam_vmc_enabled_checkbox"))
    bind_signal(vam_bridge_enabled_checkbox, "_nc_ui_shell_persona_avatar_bound", "toggled", lambda _checked=False: on_vam_check_changed("VaM file bridge", "vam_bridge_enabled_checkbox"))
    bind_signal(vam_play_audio_in_vam_checkbox, "_nc_ui_shell_persona_avatar_bound", "toggled", lambda _checked=False: on_vam_check_changed("VaM in-engine audio", "vam_play_audio_in_vam_checkbox"))
    bind_signal(vam_timeline_auto_resume_checkbox, "_nc_ui_shell_persona_avatar_bound", "toggled", lambda _checked=False: on_vam_check_changed("VaM timeline auto-resume", "vam_timeline_auto_resume_checkbox"))
    bind_signal(btn_start_vam_desktop, "_nc_ui_shell_persona_avatar_bound", "clicked", lambda _checked=False: _ui_shell_append_console(window, "[UI Shell] Start VaM Desktop is deferred in shell preview; no process was launched."))
    bind_signal(btn_start_vam_vr, "_nc_ui_shell_persona_avatar_bound", "clicked", lambda _checked=False: _ui_shell_append_console(window, "[UI Shell] Start VaM VR is deferred in shell preview; no process was launched."))
    bind_signal(btn_vam_hide_interface, "_nc_ui_shell_persona_avatar_bound", "clicked", lambda _checked=False: _ui_shell_append_console(window, "[UI Shell] VaM interface-hide action is deferred in shell preview."))

    return {
        "bound": bound,
        "deferred": sorted(set(deferred)),
        "voices": len([item for item in _ui_shell_voice_options(window) if item != "No .wav found"]),
        "body_configs": len(configs),
    }
