import threading
import time

from PySide6 import QtCore, QtWidgets

from core import chat_providers
from ui.widgets.basic import NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox


DEFAULT_MAX_RESPONSE_TOKENS = 600


def _runtime_config():
    from ui.runtime import engine_access as engine

    return getattr(engine, "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


def _get_chat_models(provider=None, quiet=True):
    from ui.runtime.engine_access import get_chat_models

    return get_chat_models(provider=provider, quiet=quiet)

from ui.runtime.backend_chat_model_catalog import BackendChatModelCatalogMixin
from ui.runtime.backend_chat_provider_fields import BackendChatProviderFieldsMixin
from ui.runtime.backend_chat_provider_selection import BackendChatProviderSelectionMixin
from ui.runtime.backend_chat_runtime_events import BackendChatRuntimeEventsMixin


class BackendChatRuntimeMixin(BackendChatProviderSelectionMixin, BackendChatModelCatalogMixin, BackendChatProviderFieldsMixin, BackendChatRuntimeEventsMixin):
    pass
