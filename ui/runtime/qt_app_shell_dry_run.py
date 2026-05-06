"""Dry Run shell-local bindings for the Designer UI."""

_DEPENDENCIES = {}


def configure_qt_app_shell_dry_run_dependencies(dependencies):
    _DEPENDENCIES.update(dict(dependencies or {}))
    globals().update(_DEPENDENCIES)


def _ui_shell_dry_run_status_text(latest, *, target_samples=0, auto_replies=True, preview_state="idle"):
    latest = dict(latest or {})
    if preview_state == "armed":
        target_text = "Auto" if int(target_samples or 0) <= 0 else str(int(target_samples))
        return f"Dry Run shell preview armed for {target_text} sample(s)." + (" Hands-free preview enabled." if auto_replies else "")
    if latest:
        confidence = float(latest.get("confidence", 0.0) or 0.0)
        stability = float(latest.get("stability", 0.0) or 0.0)
        return f"Dry Run idle. Last saved profile confidence {confidence:.2f}, stability {stability:.2f}."
    return "Dry Run idle."


def _ui_shell_dry_run_summary_text(latest, *, target_samples=0, auto_replies=True, preview_state="idle"):
    latest = dict(latest or {})
    if preview_state == "armed":
        target_text = "Auto" if int(target_samples or 0) <= 0 else str(int(target_samples))
        return (
            "Shell preview only.\n"
            f"- Requested target samples: {target_text}\n"
            f"- Hands-free preview: {'enabled' if auto_replies else 'disabled'}\n"
            "- Starting a real Dry Run session remains deferred in --ui-shell.\n"
            "- No engine, model, or profiling worker was started."
        )
    if not latest:
        return "Arm a Dry Run to collect reply samples and generate machine-specific recommendations."
    summary = dict(latest.get("summary") or {})
    recommendation = dict(latest.get("recommendation") or {})
    settings = dict(recommendation.get("settings") or {})
    lines = [
        "Latest saved Dry Run profile:",
        f"- Name: {str(latest.get('saved_name') or latest.get('display_name') or '<unnamed>').strip()}",
        f"- Sample count: {int(latest.get('sample_count', 0) or 0)}",
        f"- Confidence: {float(latest.get('confidence', 0.0) or 0.0):.2f}",
        f"- Stability: {float(latest.get('stability', 0.0) or 0.0):.2f}",
    ]
    updated_at = latest.get("updated_at")
    try:
        lines.append(f"- Updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(updated_at)))}")
    except Exception:
        pass
    if summary:
        lines.extend([
            "",
            "Measured startup profile:",
            f"- Avg first audio chunk: {float(summary.get('avg_first_audio_chunk_ms', 0.0) or 0.0):.1f} ms",
            f"- Avg first visual buffer wait: {float(summary.get('avg_buffer_wait_ms', 0.0) or 0.0):.1f} ms",
            f"- Avg chunk quality: {float(summary.get('avg_chunk_quality', 0.0) or 0.0):.2f}",
            f"- Avg emitted chunk chars: {float(summary.get('avg_chunk_chars', 0.0) or 0.0):.1f}",
        ])
    if settings:
        lines.extend([
            "",
            "Recommended visible settings:",
            f"- Stream mode: {'On' if bool(settings.get('stream_mode')) else 'Off'}",
            f"- MuseTalk VRAM: {UI_SHELL_MUSE_VRAM_MODE_LABELS.get(str(settings.get('musetalk_vram_mode') or '').strip().lower(), 'Quality')}",
        ])
        for key in (
            "stream_chunk_target_chars",
            "stream_chunk_max_chars",
            "stream_first_chunk_min_chars",
            "musetalk_chunk_target_chars",
            "musetalk_chunk_max_chars",
            "musetalk_quickstart_1_target_chars",
        ):
            if key in settings:
                title = str(_ui_shell_chunking_slider_spec(key).get("title") or key).strip()
                lines.append(f"- {title}: {_ui_shell_format_chunking_value(settings.get(key))}")
        lines.extend([
            "",
            "Use Apply Recommendation to preview the shell-visible subset only.",
        ])
    else:
        lines.extend([
            "",
            "No saved recommendation settings were found in the latest profile.",
        ])
    lines.extend([
        "",
        "Shell preview note:",
        "- Dry Run start/stop remains deferred here.",
    ])
    return "\n".join(lines)


def _bind_ui_shell_dry_run_controls(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    service = _ui_shell_dry_run_service(window)
    bound = []
    deferred = ["btn_dry_run_start", "btn_dry_run_stop"]

    target_spin = _ui_shell_find_object(window, "dry_run_target_spin")
    auto_replies_checkbox = _ui_shell_find_object(window, "dry_run_auto_replies_checkbox")
    start_button = _ui_shell_find_object(window, "btn_dry_run_start")
    stop_button = _ui_shell_find_object(window, "btn_dry_run_stop")
    apply_button = _ui_shell_find_object(window, "btn_dry_run_apply")
    status_label = _ui_shell_find_object(window, "dry_run_status_label")
    summary_edit = _ui_shell_find_object(window, "dry_run_summary")

    if target_spin is not None:
        _ui_shell_set_spin_value(target_spin, int(session.get("dry_run_target_samples", 0) or 0))
        if hasattr(target_spin, "setToolTip"):
            target_spin.setToolTip("Shell-local Dry Run preview target. No profiling session is started.")
    if auto_replies_checkbox is not None:
        _ui_shell_set_checked(auto_replies_checkbox, bool(session.get("dry_run_auto_replies", True)))
        if hasattr(auto_replies_checkbox, "setToolTip"):
            auto_replies_checkbox.setToolTip("Shell-local Dry Run hands-free preview. No profiling session is started.")
    if summary_edit is not None:
        try:
            summary_edit.setReadOnly(True)
        except Exception:
            pass
        if hasattr(summary_edit, "setToolTip"):
            summary_edit.setToolTip("Shell-local Dry Run preview summary. No profiling metrics are collected here.")

    def refresh_preview():
        snapshot = service.refresh_preview()
        if status_label is not None and hasattr(status_label, "setText"):
            status_label.setText(str(snapshot.get("status_text") or "Dry Run idle."))
        if summary_edit is not None and hasattr(summary_edit, "setPlainText"):
            summary_edit.setPlainText(str(snapshot.get("summary_text") or ""))
        if stop_button is not None and hasattr(stop_button, "setEnabled"):
            stop_button.setEnabled(str(snapshot.get("state") or "idle") == "armed")
        if start_button is not None and hasattr(start_button, "setEnabled"):
            start_button.setEnabled(str(snapshot.get("state") or "idle") != "armed")
        if apply_button is not None and hasattr(apply_button, "setEnabled"):
            apply_button.setEnabled(bool(snapshot.get("has_recommendation")))
        return snapshot

    def bind_spin(widget, attr_name, on_log):
        if widget is None or not hasattr(widget, "valueChanged"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_value=None):
            refresh_preview()
            _ui_shell_append_console(window, on_log())

        widget.valueChanged.connect(handle)
        setattr(widget, attr_name, True)

    def bind_check(widget, attr_name, on_log):
        if widget is None or not hasattr(widget, "toggled"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_checked=False):
            refresh_preview()
            _ui_shell_append_console(window, on_log())

        widget.toggled.connect(handle)
        setattr(widget, attr_name, True)

    def bind_button(widget, attr_name, handler):
        if widget is None or not hasattr(widget, "clicked"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_checked=False):
            handler()

        widget.clicked.connect(handle)
        setattr(widget, attr_name, True)

    bind_spin(
        target_spin,
        "_nc_ui_shell_dry_run_bound",
        lambda: f"[UI Shell] Dry Run target preview: {int(target_spin.value()) if hasattr(target_spin, 'value') else 0} sample(s); no profiling session was started.",
    )
    bind_check(
        auto_replies_checkbox,
        "_nc_ui_shell_dry_run_bound",
        lambda: f"[UI Shell] Dry Run hands-free preview: {'enabled' if auto_replies_checkbox.isChecked() else 'disabled'}; no profiling session was started.",
    )
    bind_button(
        start_button,
        "_nc_ui_shell_dry_run_bound",
        lambda: (
            service.start_session(),
            refresh_preview(),
            _ui_shell_append_console(window, "[UI Shell] Dry Run arm request deferred; no engine, model, or profiling worker was started."),
        ),
    )
    bind_button(
        stop_button,
        "_nc_ui_shell_dry_run_bound",
        lambda: (
            service.stop_session(),
            refresh_preview(),
            _ui_shell_append_console(window, "[UI Shell] Dry Run stop request deferred; no profiling session was running."),
        ),
    )

    def apply_recommendation():
        result = service.apply_recommendation()
        refresh_preview()
        if result.get("applied"):
            deferred_keys = [str(key) for key in list(result.get("deferred_keys") or []) if str(key).strip()]
            deferred_suffix = f" Deferred keys: {', '.join(deferred_keys)}." if deferred_keys else ""
            _ui_shell_append_console(window, f"[UI Shell] Dry Run recommendation preview applied to the shell-visible subset only.{deferred_suffix}")
        else:
            _ui_shell_append_console(window, f"[UI Shell] {result.get('message') or 'No saved Dry Run recommendation is available.'}")

    bind_button(apply_button, "_nc_ui_shell_dry_run_bound", apply_recommendation)

    refresh_preview()
    return {
        "bound": bound,
        "deferred": sorted(set(deferred)),
        "has_recommendation": bool(service.snapshot().get("has_recommendation")),
    }
