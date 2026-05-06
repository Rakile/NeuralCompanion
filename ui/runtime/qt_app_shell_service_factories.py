"""Service factory accessors for the Designer shell wiring."""

_DEPENDENCIES = {}


def configure_qt_app_shell_service_factory_dependencies(dependencies):
    _DEPENDENCIES.update(dict(dependencies or {}))


def _configure_services():
    configure = _DEPENDENCIES.get("_configure_ui_shell_service_dependencies")
    if callable(configure):
        configure()


def _service(window, attr_name, class_name):
    _configure_services()
    service = getattr(window, attr_name, None)
    if service is None:
        service_cls = _DEPENDENCIES[class_name]
        service = service_cls(window)
        setattr(window, attr_name, service)
    return service


def _ui_shell_runtime_status_service(window):
    return _service(window, "_nc_ui_shell_runtime_status_service", "_UiShellRuntimeStatusService")


def _ui_shell_model_refresh_service(window):
    return _service(window, "_nc_ui_shell_model_refresh_service", "_UiShellModelRefreshService")


def _ui_shell_chat_replay_service(window):
    return _service(window, "_nc_ui_shell_chat_replay_service", "_UiShellChatReplayService")


def _ui_shell_tutorial_service(window):
    return _service(window, "_nc_ui_shell_tutorial_service", "_UiShellTutorialService")


def _ui_shell_chat_context_service(window):
    return _service(window, "_nc_ui_shell_chat_context_service", "_UiShellChatContextService")


def _ui_shell_input_settings_service(window):
    return _service(window, "_nc_ui_shell_input_settings_service", "_UiShellInputSettingsService")


def _ui_shell_performance_profile_service(window):
    return _service(window, "_nc_ui_shell_performance_profile_service", "_UiShellPerformanceProfileService")


def _ui_shell_dry_run_service(window):
    return _service(window, "_nc_ui_shell_dry_run_service", "_UiShellDryRunService")


def _ui_shell_persona_avatar_service(window):
    return _service(window, "_nc_ui_shell_persona_avatar_service", "_UiShellPersonaAvatarService")


def _ui_shell_input_actions_service(window):
    return _service(window, "_nc_ui_shell_input_actions_service", "_UiShellInputActionService")


def _ui_shell_runtime_controls_service(window):
    return _service(window, "_nc_ui_shell_runtime_controls_service", "_UiShellRuntimeControlService")


def _ui_shell_engine_lifecycle_service(window):
    return _service(window, "_nc_ui_shell_engine_lifecycle_service", "_UiShellEngineLifecycleService")
