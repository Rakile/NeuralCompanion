"""Heavy runtime compatibility namespace for qt_app.py."""

import os
import warnings

import dry_run
import tutorial_framework

try:
    import cv2
except Exception:
    cv2 = None

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6 import QtWidgets as _QtWidgets

try:
    import shiboken6
except Exception:  # pragma: no cover - defensive for tooling without full PySide install
    shiboken6 = None

import engine
import shared_state
from core import avatar_runtime, chat_providers, sensory
from core.addons import AddonManager
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
    QtRuntimeControlService,
    QtRuntimeStatusService,
    QtSensoryService,
    QtShellService,
    QtTutorialService,
)
from addons.musetalk_avatar.host_service import QtMuseTalkUIService
from addons.visual_reply.host_service import QtVisualReplyService
from engine import (
    AVATAR_PROFILE,
    HAND_CALIBRATION,
    RUNTIME_CONFIG,
    collect_replayable_assistant_messages,
    export_chat_session_state,
    get_chat_models,
    import_chat_session_state,
    replace_chat_conversation_history,
    reset_session_state,
    run_companion,
    shutdown_avatar_engine,
    stop_flag,
    trigger_manual_action,
    update_runtime_config,
)
from musetalk_bridge import MuseTalkBridge

try:
    from pynvml import (
        nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetMemoryInfo,
        nvmlInit,
        nvmlShutdown,
    )
except Exception:
    nvmlInit = None
    nvmlShutdown = None
    nvmlDeviceGetHandleByIndex = None
    nvmlDeviceGetMemoryInfo = None


def configure_runtime_environment():
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    warnings.filterwarnings(
        "ignore",
        message=r".*LoRACompatibleLinear.*deprecated.*",
        category=FutureWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*Reference mel length is not equal to 2 \* reference token length\..*",
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*pkg_resources is deprecated as an API.*",
        category=UserWarning,
    )


def export_qt_app_runtime_namespace():
    excluded = {"configure_runtime_environment", "export_qt_app_runtime_namespace"}
    return {name: value for name, value in globals().items() if not name.startswith("__") and name not in excluded}
