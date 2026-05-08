import sys
from ui.runtime.qt_app_cli import maybe_handle_ui_shell, maybe_handle_validate_ui, resolve_ui_path as _resolve_ui_path_base, validate_ui_file as _validate_ui_file
from ui.runtime.qt_app_shell_namespace import export_qt_app_shell_namespace

globals().update(export_qt_app_shell_namespace())
def validate_ui_file(raw_path):
    return _validate_ui_file(raw_path, base_path=__file__)
def _resolve_ui_path(raw_path):
    return _resolve_ui_path_base(raw_path, base_path=__file__)
maybe_handle_validate_ui(sys.argv, base_path=__file__)
from ui.runtime.qt_app_shell_config import (
    configure_qt_app_shell_dependencies,
    _configure_app_entry_dependencies,
    _configure_real_ui_bridge_dependencies,
    _configure_ui_shell_preview_dependencies,
    _configure_ui_shell_smoke_dependencies,
)

configure_qt_app_shell_dependencies(globals())

maybe_handle_ui_shell(
    sys.argv,
    configure_ui_shell_smoke_dependencies=_configure_ui_shell_smoke_dependencies,
    configure_ui_shell_preview_dependencies=_configure_ui_shell_preview_dependencies,
    run_ui_shell_smoke=run_ui_shell_smoke,
    run_ui_shell_preview=run_ui_shell_preview,
)

_ui_shell_enable_stdio_unicode_fallback()

from ui.runtime.qt_app_runtime_namespace import configure_runtime_environment, export_qt_app_runtime_namespace

configure_runtime_environment()
globals().update(export_qt_app_runtime_namespace())

from ui.main_window import *

def main():
    configure_qt_app_shell_dependencies(globals())
    _configure_app_entry_dependencies()
    run_qt_app()

if __name__ == "__main__":
    main()

