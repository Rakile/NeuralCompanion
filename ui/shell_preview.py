"""Visual-only Designer shell preview runner."""


def configure_ui_shell_preview_dependencies(namespace):
    """Inject qt_app-owned shell helpers without importing the heavy app module."""
    globals().update(dict(namespace or {}))


def run_ui_shell_preview(raw_path):
    from PySide6 import QtCore as _QtCore
    from PySide6 import QtWidgets as _QtWidgets

    ui_path = _resolve_ui_path(raw_path)
    print(f"[UI Shell] Loading visual-only Designer shell: {ui_path}")
    if not ui_path.exists():
        raise FileNotFoundError(f"UI file not found: {ui_path}")
    app, window = _load_ui_shell_for_smoke(ui_path)
    current_title = str(window.windowTitle() or "").strip()
    window.setWindowTitle(f"{current_title} [UI Shell Preview]" if current_title else "UI Shell Preview")
    if isinstance(window, _QtWidgets.QMainWindow):
        window.setTabPosition(_QtCore.Qt.AllDockWidgetAreas, _QtWidgets.QTabWidget.North)
    summary = _apply_ui_shell_preview_status(window)
    config_summary = _apply_ui_shell_read_only_config(window)
    console_chat_summary = _bind_ui_shell_console_chat_local_controls(window)
    lifecycle_summary = _bind_ui_shell_lifecycle_local_controls(window)
    runtime_control_summary = _bind_ui_shell_runtime_action_controls(window)
    input_action_summary = _bind_ui_shell_input_action_controls(window)
    tutorial_summary = _bind_ui_shell_tutorial_controls(window)
    addon_report = _ui_shell_addon_mount_report(window)
    live_mount_report = _ui_shell_mount_live_addons(window, addon_report)
    host_core_summary = _bind_ui_shell_host_core_controls(window, sensory_providers=live_mount_report.get("sensory_providers", []))
    chunking_profile_summary = _bind_ui_shell_chunking_profile_controls(window)
    dry_run_summary = _bind_ui_shell_dry_run_controls(window)
    persona_avatar_summary = _bind_ui_shell_persona_body_vam_controls(window)
    chat_runtime_summary = _bind_ui_shell_chat_runtime(window, live_mount_report.get("chat_providers", []))
    avatar_runtime_summary = _bind_ui_shell_avatar_runtime(window, live_mount_report.get("avatar_providers", []))
    tts_runtime_summary = _bind_ui_shell_tts_runtime(window, live_mount_report.get("tts_backends", []))
    preset_session_summary = _bind_ui_shell_preset_session_controls(window, live_mount_report.get("chat_providers", []))
    chat_context_summary = _bind_ui_shell_chat_context_controls(window)
    placeholder_targets = _apply_ui_shell_addon_placeholders(
        window,
        addon_report,
        exclude_addon_ids=set(live_mount_report["mounted_ids"]),
        live_chat_providers=[] if chat_runtime_summary.get("bound") else live_mount_report.get("chat_providers", []),
    )
    try:
        app.aboutToQuit.connect(lambda: _ui_shell_cleanup_live_addons(window))
    except Exception:
        pass
    print("[UI Shell] Runtime started: no")
    print("[UI Shell] Broad addons initialized: no")
    print("[UI Shell] Engine lifecycle connected: shell-local only")
    print(f"[UI Shell] Bindings checked: {summary['bound']}/{summary['checked']}")
    print(
        f"[UI Shell] Session-backed shell config: "
        f"{'loaded' if config_summary['session_loaded'] else 'not found'} "
        f"({len(config_summary['applied'])} widget(s) populated)"
    )
    print(
        "[UI Shell] Host/Core shell-local controls: "
        + ", ".join(host_core_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell] Chunking/profile shell-local controls: "
        + ", ".join(chunking_profile_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell] Chunking/profile deferred controls: "
        + ", ".join(chunking_profile_summary.get("deferred") or ["none"])
    )
    print(
        "[UI Shell] Dry Run shell-local controls: "
        + ", ".join(dry_run_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell] Dry Run deferred controls: "
        + ", ".join(dry_run_summary.get("deferred") or ["none"])
    )
    print(
        "[UI Shell] Persona/body/VaM shell-local controls: "
        + ", ".join(persona_avatar_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell] Persona/body/VaM deferred controls: "
        + ", ".join(persona_avatar_summary.get("deferred") or ["none"])
    )
    print(
        "[UI Shell] Console/chat shell-local controls: "
        + ", ".join(console_chat_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell] Console/chat deferred controls: "
        + ", ".join(console_chat_summary.get("deferred") or ["none"])
    )
    print(
        "[UI Shell] Lifecycle shell-local controls: "
        + ", ".join(lifecycle_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell] Runtime action shell-local controls: "
        + ", ".join(runtime_control_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell] Input/action shell-local controls: "
        + ", ".join(input_action_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell] Input/action deferred controls: "
        + ", ".join(input_action_summary.get("deferred") or ["none"])
    )
    print(f"[UI Shell] Runtime status snapshot: {_ui_shell_compose_status_line(window)}")
    print(
        "[UI Shell] Tutorial shell-local controls: "
        + f"{tutorial_summary.get('tutorials', 0)} tutorial(s), "
        + ", ".join(tutorial_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell] Chat Runtime binding: "
        + (
            f"{chat_runtime_summary['providers']} provider(s), selected={chat_runtime_summary['selected_provider'] or '<none>'}"
            if chat_runtime_summary.get("bound")
            else "deferred"
        )
    )
    print(
        "[UI Shell] Preset/session binding: "
        + (
            f"{preset_session_summary['presets']} preset(s), selected={preset_session_summary['selected'] or '<none>'}"
            if preset_session_summary.get("bound")
            else "deferred"
        )
    )
    print(
        "[UI Shell] Avatar Runtime binding: "
        + (
            f"{avatar_runtime_summary['providers']} provider(s), selected={avatar_runtime_summary['selected_provider'] or '<none>'}"
            if avatar_runtime_summary.get("bound")
            else "deferred"
        )
    )
    print(
        "[UI Shell] TTS Runtime binding: "
        + (
            f"{tts_runtime_summary['backends']} backend(s), selected={tts_runtime_summary['selected_backend'] or '<none>'}"
            if tts_runtime_summary.get("bound")
            else "deferred"
        )
    )
    print(
        "[UI Shell] Chat context shell-local controls: "
        + ", ".join(chat_context_summary.get("bound") or ["none"])
    )
    print(
        f"[UI Shell] Addon manifests discovered: "
        f"{addon_report['total_count']} ({addon_report['enabled_count']} effectively enabled)"
    )
    print(
        "[UI Shell] Live addon mounts: "
        + (", ".join(live_mount_report["mounted"]) if live_mount_report["mounted"] else "none")
    )
    print(
        "[UI Shell] Live chat providers: "
        + (
            ", ".join(
                str(provider.get("label") or provider.get("id") or "")
                for provider in live_mount_report.get("chat_providers", [])
            )
            if live_mount_report.get("chat_providers")
            else "none"
        )
    )
    print(
        "[UI Shell] Live avatar providers: "
        + (
            ", ".join(
                str(provider.get("label") or provider.get("id") or "")
                for provider in live_mount_report.get("avatar_providers", [])
            )
            if live_mount_report.get("avatar_providers")
            else "none"
        )
    )
    print(
        "[UI Shell] Live sensory providers: "
        + (
            ", ".join(
                str(provider.get("label") or provider.get("id") or "")
                for provider in live_mount_report.get("sensory_providers", [])
            )
            if live_mount_report.get("sensory_providers")
            else "none"
        )
    )
    if live_mount_report["failures"]:
        print("[UI Shell] Live addon mount failures:")
        for failure in live_mount_report["failures"]:
            print(f"  - {failure}")
    print(
        "[UI Shell] Addon mount placeholders: "
        + (", ".join(placeholder_targets) if placeholder_targets else "none")
    )
    _print_ui_shell_static_addon_comparison(ui_path, addon_report, live_mount_report, prefix="[UI Shell]")
    print("[UI Shell] Close the shell window to return to the terminal.")
    window.show()
    return app.exec()
