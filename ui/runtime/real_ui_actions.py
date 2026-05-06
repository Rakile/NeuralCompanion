from PySide6 import QtCore

from ui.runtime.real_ui_actions_avatar import RealUiActionsAvatarMixin, configure_real_ui_actions_avatar_dependencies
from ui.runtime.real_ui_actions_chat_sensory import RealUiActionsChatSensoryMixin, configure_real_ui_actions_chat_sensory_dependencies
from ui.runtime.real_ui_actions_media import RealUiActionsMediaMixin, configure_real_ui_actions_media_dependencies
from ui.runtime.real_ui_actions_profiles import RealUiActionsProfileMixin, configure_real_ui_actions_profiles_dependencies
from ui.runtime.real_ui_actions_runtime import RealUiActionsRuntimeMixin, configure_real_ui_actions_runtime_dependencies


def configure_real_ui_actions_dependencies(namespace):
    """Inject qt_app-owned globals used by the extracted real-UI action mixins."""
    globals().update(dict(namespace or {}))
    configure_real_ui_actions_runtime_dependencies(globals())
    configure_real_ui_actions_avatar_dependencies(globals())
    configure_real_ui_actions_profiles_dependencies(globals())
    configure_real_ui_actions_chat_sensory_dependencies(globals())
    configure_real_ui_actions_media_dependencies(globals())


class MainUiRealActionsMixin(RealUiActionsRuntimeMixin, RealUiActionsAvatarMixin, RealUiActionsProfileMixin, RealUiActionsChatSensoryMixin, RealUiActionsMediaMixin):
    """Frontend action callbacks for the runtime-backed main.ui bridge."""

    pass
