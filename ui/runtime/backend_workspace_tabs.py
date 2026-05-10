from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import LabeledSlider, NoWheelComboBox, NoWheelSpinBox


DEFAULT_MAX_RESPONSE_TOKENS = 600


def _runtime_config():
    # Imported lazily because qt_app imports this mixin before it imports engine.
    from ui.runtime import engine_access as engine

    return engine.RUNTIME_CONFIG

from ui.runtime.backend_workspace_addons import BackendWorkspaceAddonsMixin
from ui.runtime.backend_workspace_builders import BackendWorkspaceBuilderMixin
from ui.runtime.backend_workspace_focus import BackendWorkspaceFocusMixin


class BackendWorkspaceTabsMixin(BackendWorkspaceFocusMixin, BackendWorkspaceBuilderMixin, BackendWorkspaceAddonsMixin):
    pass
