"""Qt host service catalog exposed to addons.

This module keeps addon-facing host services out of the lifecycle mixin so the
main window remains a host shell rather than the owner of each addon contract.
"""

from core.addons.qt_host_services import (
    AddonCapabilityBridgeService,
    QtAvatarProviderService,
    QtChatContextService,
    QtChatProviderService,
    QtChatReplayService,
    QtDialogService,
    QtDryRunService,
    QtEngineLifecycleService,
    QtHotkeyService,
    QtInputActionService,
    QtInputSettingsService,
    QtModelRefreshService,
    QtMuseTalkUIService,
    QtPerformanceProfileService,
    QtPersonaAvatarService,
    QtRuntimeControlService,
    QtRuntimeStatusService,
    QtSensoryService,
    QtShellService,
    QtTutorialService,
    QtVisualReplyService,
)


def build_qt_host_services(window):
    """Return the stable service map addons may request from their context."""

    return {
        "qt.chat_context": QtChatContextService(window),
        "qt.dialogs": QtDialogService(window),
        "qt.dry_run": QtDryRunService(window),
        "qt.engine_lifecycle": QtEngineLifecycleService(window),
        "qt.hotkeys": QtHotkeyService(window),
        "qt.input_actions": QtInputActionService(window),
        "qt.input_settings": QtInputSettingsService(window),
        "qt.persona_avatar": QtPersonaAvatarService(window),
        "qt.performance_profiles": QtPerformanceProfileService(window),
        "qt.model_refresh": QtModelRefreshService(window),
        "qt.runtime_controls": QtRuntimeControlService(window),
        "qt.runtime_status": QtRuntimeStatusService(window),
        "qt.shell": QtShellService(window),
        "qt.tutorials": QtTutorialService(window),
        "qt.musetalk_ui": QtMuseTalkUIService(window),
        "qt.visual_reply": QtVisualReplyService(window),
        "qt.avatar_providers": QtAvatarProviderService(window),
        "qt.sensory": QtSensoryService(window),
        "qt.chat_providers": QtChatProviderService(window),
        "qt.chat_replay": QtChatReplayService(window),
        "qt.bind_designer_widgets": window._bind_designer_widgets,
        "addons.capabilities": AddonCapabilityBridgeService(lambda: window._addon_manager),
    }
