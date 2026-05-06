from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import shiboken6
except Exception:
    shiboken6 = None

from ui.widgets.basic import NoWheelTabWidget

from ui.runtime.backend_addon_controls import BackendAddonControlMixin
from ui.runtime.backend_addon_lifecycle import BackendAddonLifecycleMixin
from ui.runtime.backend_addon_tab_mounts import BackendAddonTabMountMixin


class BackendAddonMountMixin(BackendAddonLifecycleMixin, BackendAddonControlMixin, BackendAddonTabMountMixin):
    """Mount addon-provided Qt tab contributions into backend tab containers."""

    pass
