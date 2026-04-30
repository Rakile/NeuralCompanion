"""Smoke-test support for the lightweight Designer UI shell path."""

import sys


def configure_ui_shell_smoke_dependencies(namespace):
    """Inject qt_app-owned shell helpers without importing the heavy app module."""
    globals().update(dict(namespace or {}))

def run_ui_shell_smoke(raw_path):
    ui_path = _resolve_ui_path(raw_path)
    print(f"[UI Shell Smoke] File: {ui_path}")
    if not ui_path.exists():
        print("[UI Shell Smoke] ERROR: UI file not found.")
        return 2
    app = None
    window = None
    try:
        app, window = _load_ui_shell_for_smoke(ui_path)
    except Exception as exc:
        print(f"[UI Shell Smoke] ERROR: Could not load Designer shell: {exc}")
        return 2

    missing = []
    mismatched = []
    bound_total = 0
    for group_name, requirements in UI_VALIDATION_REQUIRED_GROUPS:
        group_bound = 0
        group_missing = []
        group_mismatched = []
        for object_name, expected_class in requirements:
            obj = _ui_shell_find_object(window, object_name)
            if obj is None:
                group_missing.append((object_name, expected_class))
                missing.append((group_name, object_name, expected_class))
                continue
            if not _ui_shell_class_matches(obj, expected_class):
                actual_class = obj.__class__.__name__
                group_mismatched.append((object_name, expected_class, actual_class))
                mismatched.append((group_name, object_name, expected_class, actual_class))
                continue
            group_bound += 1
        bound_total += group_bound
        print(f"[UI Shell Smoke] {group_name}: bound {group_bound}/{len(requirements)}")
        for object_name, expected_class in group_missing:
            print(f"  MISSING {object_name} ({expected_class})")
        for object_name, expected_class, actual_class in group_mismatched:
            print(f"  TYPE {object_name}: expected {expected_class}, found {actual_class}")

    print(f"[UI Shell Smoke] Total checked bindings: {bound_total}")
    print("[UI Shell Smoke] Runtime started: no")
    print("[UI Shell Smoke] Broad addons initialized: no")
    print("[UI Shell Smoke] Engine lifecycle connected: shell-local only")
    config_summary = _apply_ui_shell_read_only_config(window)
    lifecycle_summary = _bind_ui_shell_lifecycle_local_controls(window)
    runtime_control_summary = _bind_ui_shell_runtime_action_controls(window)
    input_action_summary = _bind_ui_shell_input_action_controls(window)
    print(
        f"[UI Shell Smoke] Session-backed shell config: "
        f"{'loaded' if config_summary['session_loaded'] else 'not found'} "
        f"({len(config_summary['applied'])} widget(s) populated)"
    )
    print(
        "[UI Shell Smoke] Lifecycle shell-local controls: "
        + ", ".join(lifecycle_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell Smoke] Runtime action shell-local controls: "
        + ", ".join(runtime_control_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell Smoke] Input/action shell-local controls: "
        + ", ".join(input_action_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell Smoke] Input/action deferred controls: "
        + ", ".join(input_action_summary.get("deferred") or ["none"])
    )
    print(f"[UI Shell Smoke] Runtime status snapshot: {_ui_shell_compose_status_line(window)}")
    tutorial_summary = _bind_ui_shell_tutorial_controls(window)
    addon_report = _ui_shell_addon_mount_report(window)
    _print_ui_shell_addon_mount_report(addon_report)
    live_mount_report = _ui_shell_mount_live_addons(window, addon_report)
    host_core_summary = _bind_ui_shell_host_core_controls(window, sensory_providers=live_mount_report.get("sensory_providers", []))
    chunking_profile_summary = _bind_ui_shell_chunking_profile_controls(window)
    dry_run_summary = _bind_ui_shell_dry_run_controls(window)
    persona_avatar_summary = _bind_ui_shell_persona_body_vam_controls(window)
    print(
        "[UI Shell Smoke] Host/Core shell-local controls: "
        + ", ".join(host_core_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell Smoke] Chunking/profile shell-local controls: "
        + ", ".join(chunking_profile_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell Smoke] Chunking/profile deferred controls: "
        + ", ".join(chunking_profile_summary.get("deferred") or ["none"])
    )
    print(
        "[UI Shell Smoke] Dry Run shell-local controls: "
        + ", ".join(dry_run_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell Smoke] Dry Run deferred controls: "
        + ", ".join(dry_run_summary.get("deferred") or ["none"])
    )
    print(
        "[UI Shell Smoke] Persona/body/VaM shell-local controls: "
        + ", ".join(persona_avatar_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell Smoke] Persona/body/VaM deferred controls: "
        + ", ".join(persona_avatar_summary.get("deferred") or ["none"])
    )
    chat_runtime_summary = _bind_ui_shell_chat_runtime(window, live_mount_report.get("chat_providers", []))
    avatar_runtime_summary = _bind_ui_shell_avatar_runtime(window, live_mount_report.get("avatar_providers", []))
    tts_runtime_summary = _bind_ui_shell_tts_runtime(window, live_mount_report.get("tts_backends", []))
    preset_session_summary = _bind_ui_shell_preset_session_controls(window, live_mount_report.get("chat_providers", []))
    chat_context_summary = _bind_ui_shell_chat_context_controls(window)
    print(
        "[UI Shell Smoke] Chat Runtime binding: "
        + (
            f"{chat_runtime_summary['providers']} provider(s), selected={chat_runtime_summary['selected_provider'] or '<none>'}"
            if chat_runtime_summary.get("bound")
            else "deferred"
        )
    )
    print(
        "[UI Shell Smoke] Preset/session binding: "
        + (
            f"{preset_session_summary['presets']} preset(s), selected={preset_session_summary['selected'] or '<none>'}"
            if preset_session_summary.get("bound")
            else "deferred"
        )
    )
    print(
        "[UI Shell Smoke] Avatar Runtime binding: "
        + (
            f"{avatar_runtime_summary['providers']} provider(s), selected={avatar_runtime_summary['selected_provider'] or '<none>'}"
            if avatar_runtime_summary.get("bound")
            else "deferred"
        )
    )
    print(
        "[UI Shell Smoke] TTS Runtime binding: "
        + (
            f"{tts_runtime_summary['backends']} backend(s), selected={tts_runtime_summary['selected_backend'] or '<none>'}"
            if tts_runtime_summary.get("bound")
            else "deferred"
        )
    )
    print(
        "[UI Shell Smoke] Chat context shell-local controls: "
        + ", ".join(chat_context_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell Smoke] Tutorial shell-local controls: "
        + f"{tutorial_summary.get('tutorials', 0)} tutorial(s), "
        + ", ".join(tutorial_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell Smoke] Live addon mounts: "
        + (", ".join(live_mount_report["mounted"]) if live_mount_report["mounted"] else "none")
    )
    print(
        "[UI Shell Smoke] Live chat providers: "
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
        "[UI Shell Smoke] Live avatar providers: "
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
        "[UI Shell Smoke] Live sensory providers: "
        + (
            ", ".join(
                str(provider.get("label") or provider.get("id") or "")
                for provider in live_mount_report.get("sensory_providers", [])
            )
            if live_mount_report.get("sensory_providers")
            else "none"
        )
    )
    engine_imported = "engine" in sys.modules
    print(f"[UI Shell Smoke] Heavy engine imported: {'yes' if engine_imported else 'no'}")
    if live_mount_report["failures"]:
        print("[UI Shell Smoke] Live addon mount failures:")
        for failure in live_mount_report["failures"]:
            print(f"  - {failure}")
    placeholder_targets = _apply_ui_shell_addon_placeholders(
        window,
        addon_report,
        exclude_addon_ids=set(live_mount_report["mounted_ids"]),
        live_chat_providers=[] if chat_runtime_summary.get("bound") else live_mount_report.get("chat_providers", []),
    )
    print(
        "[UI Shell Smoke] Addon mount placeholders: "
        + (", ".join(placeholder_targets) if placeholder_targets else "none")
    )
    _print_ui_shell_static_addon_comparison(ui_path, addon_report, live_mount_report)

    try:
        _ui_shell_cleanup_live_addons(window)
        window.close()
        if app is not None:
            app.quit()
    except Exception:
        pass

    if engine_imported:
        mismatched.append(("Safety", "engine", "not imported", "imported"))

    if missing or mismatched:
        print("[UI Shell Smoke] Result: NOT READY for shell binding.")
        return 1
    print("[UI Shell Smoke] Result: READY for the checked shell binding surface.")
    return 0

def _ui_shell_binding_summary(window):
    checked = 0
    bound = 0
    missing = []
    mismatched = []
    for group_name, requirements in UI_VALIDATION_REQUIRED_GROUPS:
        for object_name, expected_class in requirements:
            checked += 1
            obj = _ui_shell_find_object(window, object_name)
            if obj is None:
                missing.append(f"{group_name}:{object_name}")
                continue
            if not _ui_shell_class_matches(obj, expected_class):
                mismatched.append(f"{group_name}:{object_name}")
                continue
            bound += 1
    return {
        "checked": checked,
        "bound": bound,
        "missing": missing,
        "mismatched": mismatched,
    }
