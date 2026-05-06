from PySide6 import QtCore, QtWidgets

from ui.runtime.shell_session_config import _ui_shell_combo_select_label, _ui_shell_combo_set_items
from ui.runtime.shell_status_layout import _ui_shell_audio_device_labels
from ui.shell_specs import UI_SHELL_DEFAULT_CHUNKING_VALUES, UI_SHELL_MUSE_VRAM_MODE_LABELS
from ui.widgets.basic import CollapsibleSection, ContextTokenStepper, DecimalStepper, NoWheelComboBox, NoWheelSpinBox, NoWheelTabWidget


QT_MUSETALK_LOOP_FADE_MS = 180
DEFAULT_LOCAL_VAM_ROOT = ""


def _engine():
    import engine

    return engine


def _update_runtime_config(key, value):
    from engine import update_runtime_config

    return update_runtime_config(key, value)


def _default_chat_provider_id():
    from core import chat_providers

    return chat_providers.DEFAULT_PROVIDER_ID


class BackendSystemShapingPanelMixin:
    """Build the backend System Shaping and Workspace panels."""

from ui.runtime.backend_system_shaping_builders import BackendSystemShapingBuilderMixin
from ui.runtime.backend_system_shaping_runtime import BackendSystemShapingRuntimeMixin


class BackendSystemShapingPanelMixin(BackendSystemShapingRuntimeMixin, BackendSystemShapingBuilderMixin):
    pass
