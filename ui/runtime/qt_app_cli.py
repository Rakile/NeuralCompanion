"""Command-line helpers for the thin qt_app.py compatibility entrypoint."""

import sys

from ui.validation import resolve_ui_path as _resolve_ui_path_base, validate_ui_file as _validate_ui_file_base


def resolve_ui_path(raw_path, *, base_path):
    return _resolve_ui_path_base(raw_path, base_path=base_path)


def validate_ui_file(raw_path, *, base_path):
    return _validate_ui_file_base(raw_path, base_path=base_path)


def maybe_handle_validate_ui(argv, *, base_path):
    if len(argv) >= 2 and str(argv[1] or "").strip().lower() == "--validate-ui":
        ui_arg = argv[2] if len(argv) >= 3 else "main.ui"
        sys.exit(validate_ui_file(ui_arg, base_path=base_path))


def maybe_handle_ui_shell(
    argv,
    *,
    configure_ui_shell_smoke_dependencies,
    configure_ui_shell_preview_dependencies,
    run_ui_shell_smoke,
    run_ui_shell_preview,
):
    if len(argv) >= 2 and str(argv[1] or "").strip().lower() == "--ui-shell":
        shell_smoke = any(str(item or "").strip().lower() == "--shell-smoke" for item in argv[2:])
        ui_arg = argv[2] if len(argv) >= 3 and not str(argv[2] or "").startswith("--") else "main.ui"
        if shell_smoke:
            configure_ui_shell_smoke_dependencies()
            sys.exit(run_ui_shell_smoke(ui_arg))
        configure_ui_shell_preview_dependencies()
        sys.exit(run_ui_shell_preview(ui_arg))
