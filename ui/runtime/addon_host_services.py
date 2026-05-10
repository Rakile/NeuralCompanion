"""Qt host service catalog exposed to addons.

This module keeps addon-facing host services out of the lifecycle mixin so the
main window remains a host shell rather than the owner of each addon contract.
"""

import importlib
import json
from pathlib import Path

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
    QtPerformanceProfileService,
    QtPersonaAvatarService,
    QtRuntimeConfigService,
    QtRuntimeControlService,
    QtRuntimeStatusService,
    QtSensoryService,
    QtShellService,
    QtTutorialService,
    QtUserImageTurnService,
)


APP_ROOT = Path(__file__).resolve().parents[2]


def _iter_manifest_host_service_specs():
    addons_root = APP_ROOT / "addons"
    for manifest_path in sorted(addons_root.glob("*/addon.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entry in list(payload.get("host_services", []) or []):
            if not isinstance(entry, dict):
                continue
            service_id = str(entry.get("id") or "").strip()
            module_name = str(entry.get("module") or "").strip()
            class_name = str(entry.get("class") or entry.get("class_name") or "").strip()
            if service_id and module_name and class_name:
                yield service_id, module_name, class_name


def _build_manifest_host_services(window):
    services = {}
    for service_id, module_name, class_name in _iter_manifest_host_service_specs():
        try:
            module = importlib.import_module(module_name)
            service_cls = getattr(module, class_name)
            services[service_id] = service_cls(window)
        except Exception as exc:
            print(f"⚠️ [Addons] Failed to load host service {service_id} from {module_name}.{class_name}: {exc}")
    return services


def build_qt_host_services(window):
    """Return the stable service map addons may request from their context."""

    services = {
        "qt.chat_context": QtChatContextService(window),
        "qt.dialogs": QtDialogService(window),
        "qt.dry_run": QtDryRunService(window),
        "qt.engine_lifecycle": QtEngineLifecycleService(window),
        "qt.hotkeys": QtHotkeyService(window),
        "qt.input_actions": QtInputActionService(window),
        "qt.input_settings": QtInputSettingsService(window),
        "qt.persona_avatar": QtPersonaAvatarService(window),
        "qt.performance_profiles": QtPerformanceProfileService(window),
        "qt.runtime_config": QtRuntimeConfigService(window),
        "qt.model_refresh": QtModelRefreshService(window),
        "qt.runtime_controls": QtRuntimeControlService(window),
        "qt.runtime_status": QtRuntimeStatusService(window),
        "qt.shell": QtShellService(window),
        "qt.tutorials": QtTutorialService(window),
        "qt.user_image_turns": QtUserImageTurnService(window),
        "qt.avatar_providers": QtAvatarProviderService(window),
        "qt.sensory": QtSensoryService(window),
        "qt.chat_providers": QtChatProviderService(window),
        "qt.chat_replay": QtChatReplayService(window),
        "qt.bind_designer_widgets": window._bind_designer_widgets,
        "addons.capabilities": AddonCapabilityBridgeService(lambda: window._addon_manager),
    }
    services.update(_build_manifest_host_services(window))
    return services
