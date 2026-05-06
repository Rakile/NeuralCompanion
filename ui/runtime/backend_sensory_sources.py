from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import NoWheelTabWidget


def _engine():
    import engine

    return engine


def _sensory():
    from core import sensory

    return sensory

from ui.runtime.backend_sensory_config import BackendSensoryConfigMixin
from ui.runtime.backend_sensory_metadata import BackendSensoryMetadataMixin
from ui.runtime.backend_sensory_tabs import BackendSensoryTabsMixin


class BackendSensorySourcesMixin(BackendSensoryConfigMixin, BackendSensoryMetadataMixin, BackendSensoryTabsMixin):
    pass
