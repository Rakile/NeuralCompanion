"""Chunking and performance-profile shell helpers for the Designer UI."""


def configure_shell_chunking_profiles_dependencies(namespace):
    """Inject qt_app-owned helpers without importing the heavy app module."""
    globals().update(dict(namespace or {}))


def _ui_shell_chunking_slider_spec(key):
    return dict(UI_SHELL_CHUNKING_SPECS.get(str(key), {}) or {})


def _ui_shell_chunking_slider_widget(window, key):
    spec = _ui_shell_chunking_slider_spec(key)
    return _ui_shell_find_object(window, spec.get("widget", ""))


def _ui_shell_chunking_label_widget(window, key):
    spec = _ui_shell_chunking_slider_spec(key)
    return _ui_shell_find_object(window, spec.get("label", ""))


def _ui_shell_format_chunking_value(value):
    try:
        number = float(value)
    except Exception:
        return str(value)
    if abs(number - round(number)) < 0.001:
        return str(int(round(number)))
    return f"{number:.2f}"


def _ui_shell_update_chunking_label(window, key, value=None):
    label = _ui_shell_chunking_label_widget(window, key)
    if label is None or not hasattr(label, "setText"):
        return
    spec = _ui_shell_chunking_slider_spec(key)
    base_text = str(getattr(label, "_nc_ui_shell_base_text", "") or "").strip()
    if not base_text:
        base_text = str(label.text() or spec.get("title") or str(key)).strip() or str(key)
        setattr(label, "_nc_ui_shell_base_text", base_text)
    current = value
    if current is None:
        widget = _ui_shell_chunking_slider_widget(window, key)
        if widget is not None and hasattr(widget, "value"):
            try:
                current = float(widget.value()) / float(spec.get("scale", 1) or 1)
            except Exception:
                current = spec.get("default")
    label.setText(f"{base_text}: {_ui_shell_format_chunking_value(current)}")


def _ui_shell_configure_chunking_slider(window, key, *, value=None):
    spec = _ui_shell_chunking_slider_spec(key)
    slider = _ui_shell_chunking_slider_widget(window, key)
    if slider is None:
        return False
    initial_value = value if value is not None else spec.get("default", 0)
    scale = float(spec.get("scale", 1) or 1)
    minimum = float(spec.get("minimum", 0) or 0)
    maximum = float(spec.get("maximum", 100) or 100)
    try:
        slider.blockSignals(True)
        if hasattr(slider, "setRange"):
            slider.setRange(int(round(minimum * scale)), int(round(maximum * scale)))
        if hasattr(slider, "setSingleStep"):
            slider.setSingleStep(1)
        if hasattr(slider, "setPageStep"):
            slider.setPageStep(max(1, int(((maximum - minimum) * scale) / 10)))
        if hasattr(slider, "setValue"):
            slider.setValue(int(round(float(initial_value) * scale)))
        if hasattr(slider, "setToolTip"):
            slider.setToolTip("Shell-local chunking preview. Changes are not saved or applied to runtime.")
    except Exception:
        return False
    finally:
        try:
            slider.blockSignals(False)
        except Exception:
            pass
    _ui_shell_update_chunking_label(window, key, initial_value)
    return True


def _ui_shell_current_chunking_values(window):
    values = {}
    session = dict(_read_ui_shell_session_snapshot() or {})
    for key, spec in UI_SHELL_CHUNKING_SPECS.items():
        slider = _ui_shell_chunking_slider_widget(window, key)
        default = session.get(key, spec.get("default", 0))
        if slider is not None and hasattr(slider, "value"):
            try:
                scale = float(spec.get("scale", 1) or 1)
                current = float(slider.value()) / scale
                values[key] = int(round(current)) if bool(spec.get("is_int", True)) else round(current, 2)
                continue
            except Exception:
                pass
        values[key] = int(round(float(default))) if bool(spec.get("is_int", True)) else round(float(default), 2)
    return values


def _ui_shell_apply_chunking_values(window, values):
    applied = []
    for key, spec in UI_SHELL_CHUNKING_SPECS.items():
        target_value = values.get(key, UI_SHELL_DEFAULT_CHUNKING_VALUES.get(key, spec.get("default", 0)))
        if _ui_shell_configure_chunking_slider(window, key, value=target_value):
            applied.append(key)
    return applied


def _ui_shell_profile_selected_name(window, source="dry_run"):
    combo_name = "chunking_profile_combo" if str(source or "").strip().lower() == "chunking" else "performance_profile_combo"
    combo = _ui_shell_find_object(window, combo_name)
    if combo is None or not hasattr(combo, "currentData"):
        return ""
    try:
        return str(combo.currentData() or "").strip()
    except Exception:
        return ""


def _ui_shell_refresh_performance_profile_combos(window, preferred_name=""):
    profiles = _ui_shell_list_performance_profiles()
    combos = []
    for object_name in ("performance_profile_combo", "chunking_profile_combo"):
        combo = _ui_shell_find_object(window, object_name)
        if combo is not None and hasattr(combo, "addItem"):
            combos.append(combo)
    preferred = str(preferred_name or "").strip()
    if not preferred:
        for combo in combos:
            try:
                preferred = str(combo.currentData() or "").strip()
            except Exception:
                preferred = ""
            if preferred:
                break
    for combo in combos:
        combo.blockSignals(True)
        try:
            combo.clear()
            if not profiles:
                combo.addItem("No Saved Profiles", "")
            else:
                for item in profiles:
                    combo.addItem(_ui_shell_performance_profile_label(item), str(item.get("name") or ""))
                target_index = 0
                if preferred:
                    for index in range(combo.count()):
                        if str(combo.itemData(index) or "").strip() == preferred:
                            target_index = index
                            break
                combo.setCurrentIndex(target_index)
            combo.setToolTip("Shell-local performance profile list. Reads performance_profiles/*.json only.")
        finally:
            combo.blockSignals(False)
    has_profiles = bool(profiles)
    for object_name in ("btn_profile_load", "btn_chunking_profile_load"):
        button = _ui_shell_find_object(window, object_name)
        if button is not None and hasattr(button, "setEnabled"):
            button.setEnabled(has_profiles)
    for object_name in ("btn_profile_refresh", "btn_chunking_profile_refresh"):
        button = _ui_shell_find_object(window, object_name)
        if button is not None and hasattr(button, "setToolTip"):
            button.setToolTip("Shell-local profile refresh. Reads performance_profiles/*.json only.")
    for object_name in ("btn_profile_load", "btn_chunking_profile_load"):
        button = _ui_shell_find_object(window, object_name)
        if button is not None and hasattr(button, "setToolTip"):
            button.setToolTip("Shell-local profile preview. Applies only the visible shell-safe subset.")
    for object_name in ("btn_profile_save_latest", "btn_chunking_profile_save", "btn_profile_delete", "btn_chunking_profile_delete"):
        button = _ui_shell_find_object(window, object_name)
        if button is not None and hasattr(button, "setToolTip"):
            button.setToolTip("Deferred in shell preview. File-mutation profile actions remain disabled.")
    return profiles


def _ui_shell_apply_profile_settings(window, settings):
    applied = []
    deferred = []
    settings = dict(settings or {})

    for key in PERFORMANCE_PROFILE_APPLY_KEYS:
        if key not in settings:
            continue
        if key in UI_SHELL_CHUNKING_SPECS:
            if _ui_shell_configure_chunking_slider(window, key, value=settings.get(key)):
                applied.append(key)
            else:
                deferred.append(key)
            continue
        if key == "stream_mode":
            combo = _ui_shell_find_object(window, "stream_mode_combo")
            if combo is not None and _ui_shell_combo_select_label(combo, "On" if bool(settings.get(key)) else "Off"):
                applied.append(key)
            else:
                deferred.append(key)
            continue
        if key == "musetalk_vram_mode":
            combo = _ui_shell_find_object(window, "musetalk_vram_combo")
            label = UI_SHELL_MUSE_VRAM_MODE_LABELS.get(str(settings.get(key) or "").strip().lower(), "Quality")
            if combo is not None and _ui_shell_combo_select_label(combo, label):
                applied.append(key)
            else:
                deferred.append(key)
            continue
        deferred.append(key)
    return applied, deferred


def _ui_shell_load_profile_preview(window, name="", source="dry_run"):
    target_name = str(name or "").strip() or _ui_shell_profile_selected_name(window, source=source)
    if not target_name:
        return {
            "accepted": False,
            "loaded": False,
            "profile_name": "",
            "message": "No performance profile selected.",
        }
    payload = _ui_shell_performance_profile_payload(target_name)
    if not payload:
        return {
            "accepted": False,
            "loaded": False,
            "profile_name": target_name,
            "message": f"Could not load performance profile: {target_name}",
        }
    _ui_shell_refresh_performance_profile_combos(window, preferred_name=target_name)
    applied, deferred = _ui_shell_apply_profile_settings(window, payload.get("settings_to_apply") or {})
    _ui_shell_refresh_host_core_status(window)
    return {
        "accepted": True,
        "loaded": True,
        "profile_name": target_name,
        "applied_keys": applied,
        "deferred_keys": deferred,
        "message": f"Loaded shell preview for performance profile: {target_name}",
    }


def _ui_shell_reset_chunking_defaults(window):
    applied = _ui_shell_apply_chunking_values(window, UI_SHELL_DEFAULT_CHUNKING_VALUES)
    _ui_shell_refresh_host_core_status(window)
    return {
        "accepted": True,
        "action": "reset_chunking_defaults",
        "applied_keys": applied,
        "message": "Chunking defaults restored in shell preview.",
    }


def _bind_ui_shell_chunking_profile_controls(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    service = _ui_shell_performance_profile_service(window)
    applied_defaults = _ui_shell_apply_chunking_values(window, session)
    profiles = _ui_shell_refresh_performance_profile_combos(window)
    bound = []
    deferred = [
        "btn_chunking_profile_save",
        "btn_profile_save_latest",
        "btn_chunking_profile_delete",
        "btn_profile_delete",
    ]

    reset_button = _ui_shell_find_object(window, "btn_reset_chunking_defaults")
    chunking_combo = _ui_shell_find_object(window, "chunking_profile_combo")
    performance_combo = _ui_shell_find_object(window, "performance_profile_combo")
    chunking_refresh = _ui_shell_find_object(window, "btn_chunking_profile_refresh")
    performance_refresh = _ui_shell_find_object(window, "btn_profile_refresh")
    chunking_load = _ui_shell_find_object(window, "btn_chunking_profile_load")
    performance_load = _ui_shell_find_object(window, "btn_profile_load")
    chunking_save = _ui_shell_find_object(window, "btn_chunking_profile_save")
    performance_save = _ui_shell_find_object(window, "btn_profile_save_latest")
    chunking_delete = _ui_shell_find_object(window, "btn_chunking_profile_delete")
    performance_delete = _ui_shell_find_object(window, "btn_profile_delete")

    if reset_button is not None and hasattr(reset_button, "setToolTip"):
        reset_button.setToolTip("Shell-local chunking reset. Restores visible defaults only.")

    def bind_slider(key):
        slider = _ui_shell_chunking_slider_widget(window, key)
        if slider is None or not hasattr(slider, "valueChanged"):
            return
        object_name = str(slider.objectName() if hasattr(slider, "objectName") else key)
        bound.append(object_name)
        if getattr(slider, "_nc_ui_shell_chunking_bound", False):
            return

        def on_changed(value):
            _ui_shell_update_chunking_label(window, key, value)
            _ui_shell_refresh_host_core_status(window)
            title = str(_ui_shell_chunking_slider_spec(key).get("title") or key).strip()
            _ui_shell_append_console(window, f"[UI Shell] Chunking preview: {title} -> {_ui_shell_format_chunking_value(value)}; runtime chunking remains unchanged.")

        slider.valueChanged.connect(on_changed)
        setattr(slider, "_nc_ui_shell_chunking_bound", True)

    def bind_combo(combo, source, label):
        if combo is None or not hasattr(combo, "currentIndexChanged"):
            return
        object_name = str(combo.objectName() if hasattr(combo, "objectName") else f"{source}_profile_combo")
        bound.append(object_name)
        if getattr(combo, "_nc_ui_shell_chunking_profile_bound", False):
            return

        def on_changed(_index=None):
            profile_name = _ui_shell_profile_selected_name(window, source=source)
            if profile_name:
                _ui_shell_append_console(window, f"[UI Shell] {label} selected: {profile_name}. Use Load Profile to apply the shell-safe subset.")

        combo.currentIndexChanged.connect(on_changed)
        setattr(combo, "_nc_ui_shell_chunking_profile_bound", True)

    def bind_button(button, attr_name, handler):
        if button is None or not hasattr(button, "clicked"):
            return
        object_name = str(button.objectName() if hasattr(button, "objectName") else attr_name)
        bound.append(object_name)
        if getattr(button, attr_name, False):
            return

        def on_clicked(_checked=False):
            handler()

        button.clicked.connect(on_clicked)
        setattr(button, attr_name, True)

    for key in UI_SHELL_CHUNKING_SPECS:
        bind_slider(key)

    bind_combo(chunking_combo, "chunking", "Chunking profile")
    bind_combo(performance_combo, "dry_run", "Performance profile")

    bind_button(
        reset_button,
        "_nc_ui_shell_chunking_profile_bound",
        lambda: (
            service.reset_chunking_defaults(),
            _ui_shell_append_console(window, "[UI Shell] Chunking defaults restored in shell preview; no runtime configuration was changed."),
        ),
    )
    bind_button(
        chunking_refresh,
        "_nc_ui_shell_chunking_profile_bound",
        lambda: (
            service.refresh_profiles(preferred_name=_ui_shell_profile_selected_name(window, "chunking")),
            _ui_shell_append_console(window, f"[UI Shell] Performance profiles refreshed for chunking preview: {len(_ui_shell_list_performance_profiles())} JSON profile(s) found."),
        ),
    )
    bind_button(
        performance_refresh,
        "_nc_ui_shell_chunking_profile_bound",
        lambda: (
            service.refresh_profiles(preferred_name=_ui_shell_profile_selected_name(window, "dry_run")),
            _ui_shell_append_console(window, f"[UI Shell] Performance profiles refreshed for Dry Run preview: {len(_ui_shell_list_performance_profiles())} JSON profile(s) found."),
        ),
    )

    def load_profile(source, label):
        result = service.load_profile(source=source)
        if result.get("loaded"):
            deferred_keys = [str(key) for key in list(result.get("deferred_keys") or []) if str(key).strip()]
            deferred_suffix = f" Deferred keys: {', '.join(deferred_keys)}." if deferred_keys else ""
            _ui_shell_append_console(window, f"[UI Shell] {label} loaded in shell preview: {result.get('profile_name')}.{deferred_suffix}")
        else:
            _ui_shell_append_console(window, f"[UI Shell] {result.get('message') or 'No performance profile selected.'}")

    bind_button(chunking_load, "_nc_ui_shell_chunking_profile_bound", lambda: load_profile("chunking", "Chunking profile"))
    bind_button(performance_load, "_nc_ui_shell_chunking_profile_bound", lambda: load_profile("dry_run", "Performance profile"))

    def deferred_action(action_label):
        deferred.append(action_label)
        _ui_shell_append_console(window, f"[UI Shell] {action_label} is deferred in shell preview; no profile files were modified.")

    bind_button(chunking_save, "_nc_ui_shell_chunking_profile_bound", lambda: deferred_action("Chunking profile save"))
    bind_button(performance_save, "_nc_ui_shell_chunking_profile_bound", lambda: deferred_action("Performance profile save"))
    bind_button(chunking_delete, "_nc_ui_shell_chunking_profile_bound", lambda: deferred_action("Chunking profile delete"))
    bind_button(performance_delete, "_nc_ui_shell_chunking_profile_bound", lambda: deferred_action("Performance profile delete"))

    _ui_shell_refresh_host_core_status(window)
    return {
        "bound": bound,
        "profiles": len(profiles),
        "chunking_controls": len(applied_defaults),
        "deferred": sorted(set(deferred)),
    }

