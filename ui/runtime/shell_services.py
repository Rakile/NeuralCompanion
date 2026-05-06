"""Shell-preview service facades used by the Designer UI."""

from ui.runtime.shell_services_runtime import (
    configure_shell_services_runtime_dependencies,
    _UiShellRuntimeStatusService,
    _UiShellModelRefreshService,
    _UiShellEngineLifecycleService,
    _UiShellRuntimeControlService,
)
from ui.runtime.shell_services_settings import (
    configure_shell_services_settings_dependencies,
    _UiShellChatContextService,
    _UiShellInputSettingsService,
    _UiShellPerformanceProfileService,
    _UiShellDryRunService,
    _UiShellPersonaAvatarService,
)
from ui.runtime.shell_services_actions import (
    configure_shell_services_actions_dependencies,
    _UiShellInputActionService,
    _UiShellChatReplayService,
    _UiShellTutorialService,
    _UiShellDialogService,
)
from ui.runtime.shell_services_providers import (
    configure_shell_services_providers_dependencies,
    _UiShellSensoryService,
    _UiShellAvatarProviderService,
    _UiShellChatProviderRegistry,
    _UiShellHotkeyService,
    _UiShellShellService,
    _UiShellVisualReplyService,
)


def configure_shell_service_dependencies(namespace):
    """Inject qt_app helper functions/constants used by these boundary services."""
    globals().update(dict(namespace or {}))
    configure_shell_services_runtime_dependencies(globals())
    configure_shell_services_settings_dependencies(globals())
    configure_shell_services_actions_dependencies(globals())
    configure_shell_services_providers_dependencies(globals())


__all__ = [
    "configure_shell_service_dependencies",
    "_UiShellRuntimeStatusService",
    "_UiShellModelRefreshService",
    "_UiShellEngineLifecycleService",
    "_UiShellRuntimeControlService",
    "_UiShellChatContextService",
    "_UiShellInputSettingsService",
    "_UiShellPerformanceProfileService",
    "_UiShellDryRunService",
    "_UiShellPersonaAvatarService",
    "_UiShellInputActionService",
    "_UiShellChatReplayService",
    "_UiShellTutorialService",
    "_UiShellDialogService",
    "_UiShellSensoryService",
    "_UiShellAvatarProviderService",
    "_UiShellChatProviderRegistry",
    "_UiShellHotkeyService",
    "_UiShellShellService",
    "_UiShellVisualReplyService",
]
