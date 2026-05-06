from PySide6 import QtCore, QtGui, QtWidgets

from ui.runtime.real_ui_sync_copy import RealUiSyncCopyMixin, configure_real_ui_sync_copy_dependencies
from ui.runtime.real_ui_sync_frontend import RealUiSyncFrontendMixin, configure_real_ui_sync_frontend_dependencies
from ui.runtime.real_ui_sync_mirrors import RealUiSyncMirrorMixin, configure_real_ui_sync_mirrors_dependencies
from ui.runtime.real_ui_sync_scroll import RealUiSyncScrollMixin, configure_real_ui_sync_scroll_dependencies


def configure_real_ui_sync_dependencies(namespace):
    """Inject qt_app-owned globals used by the extracted real-UI sync mixins."""
    globals().update(dict(namespace or {}))
    configure_real_ui_sync_frontend_dependencies(globals())
    configure_real_ui_sync_copy_dependencies(globals())
    configure_real_ui_sync_mirrors_dependencies(globals())
    configure_real_ui_sync_scroll_dependencies(globals())


class MainUiRealSyncMixin(RealUiSyncFrontendMixin, RealUiSyncCopyMixin, RealUiSyncMirrorMixin, RealUiSyncScrollMixin):
    """Frontend/backend mirroring and polling sync helpers for the runtime-backed main.ui bridge."""

    pass
