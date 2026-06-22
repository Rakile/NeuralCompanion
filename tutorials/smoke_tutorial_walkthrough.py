from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TUTORIAL_IDS = {
    "first_run",
    "multi_persona_roleplay",
    "spotify_sense",
    "ai_presence_and_overlays",
    "neural_face_presence",
    "companion_orb_overlay",
    "vision_supervisors_overview",
    "screen_and_clipboard",
    "presence_sources",
    "main_chat_remote",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Walk tutorial overlays against the real Qt main.ui frontend.")
    parser.add_argument(
        "tutorial_ids",
        nargs="*",
        help="Tutorial ids to walk. Defaults to the high-risk manual UI pass set.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Walk every tutorial JSON file.",
    )
    return parser.parse_args()


def _process_events(app: Any, rounds: int = 4) -> None:
    from PySide6 import QtCore

    for _ in range(max(1, int(rounds))):
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)


def _session_backup(session_path: Path) -> tuple[bool, bytes | None]:
    try:
        existed = bool(session_path.exists())
        return existed, session_path.read_bytes() if existed else None
    except OSError:
        return False, None


def _restore_session(session_path: Path, existed: bool, data: bytes | None) -> None:
    try:
        if existed and data is not None:
            session_path.write_bytes(data)
        elif not existed and session_path.exists():
            session_path.unlink()
    except OSError as exc:
        print(f"[Tutorial Walkthrough Smoke] WARNING: Could not restore session file: {exc}")


def _tutorial_ids(args: argparse.Namespace, tutorial_framework: Any) -> list[str]:
    if args.all:
        return [str(item.get("id") or "") for item in tutorial_framework.list_tutorials() if item.get("id")]
    if args.tutorial_ids:
        return [str(item).strip() for item in args.tutorial_ids if str(item).strip()]
    available = {str(item.get("id") or "") for item in tutorial_framework.list_tutorials()}
    return [item for item in sorted(DEFAULT_TUTORIAL_IDS) if item in available]


def _widget_area(widget: Any) -> int:
    try:
        size = widget.size()
        return max(0, int(size.width())) * max(0, int(size.height()))
    except Exception:
        return 0


def _step_errors(overlay: Any, tutorial_id: str, step_index: int) -> list[str]:
    from PySide6 import QtWidgets

    errors: list[str] = []
    step = dict((overlay.steps or [])[step_index] or {})
    target_name = str(step.get("target") or "").strip()
    widget = getattr(overlay, "current_target_widget", None)
    if widget is None:
        errors.append(f"{tutorial_id} step {step_index + 1} target {target_name!r}: widget not resolved")
        return errors
    if isinstance(widget, QtWidgets.QWidget) and not widget.isVisible():
        errors.append(f"{tutorial_id} step {step_index + 1} target {target_name!r}: widget is not visible")
    highlight_rect = getattr(overlay, "highlight_rect", None)
    if highlight_rect is None or highlight_rect.isNull() or highlight_rect.width() <= 0 or highlight_rect.height() <= 0:
        errors.append(f"{tutorial_id} step {step_index + 1} target {target_name!r}: highlight rect is empty")
        return errors
    try:
        panel_rect = overlay._panel_rect_in_main_window()
        main_area = _widget_area(overlay.main_window)
        target_area = max(1, highlight_rect.width() * highlight_rect.height())
        target_is_broad = bool(main_area and target_area > (main_area * 0.35))
        if not target_is_broad and not panel_rect.isNull() and panel_rect.intersects(highlight_rect.adjusted(-10, -10, 10, 10)):
            errors.append(f"{tutorial_id} step {step_index + 1} target {target_name!r}: tutorial panel overlaps target")
    except Exception as exc:
        errors.append(f"{tutorial_id} step {step_index + 1} target {target_name!r}: panel geometry check failed: {exc}")
    return errors


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.path.insert(0, str(ROOT))

    from PySide6 import QtWidgets

    import qt_app
    import tutorial_framework

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([str(ROOT / "qt_app.py")])
    session_path = Path(qt_app.SESSION_PATH)
    session_existed, session_data = _session_backup(session_path)
    bridge = None
    errors: list[str] = []
    walked = 0
    try:
        qt_app.configure_qt_app_shell_dependencies(qt_app.__dict__)
        qt_app._configure_real_ui_bridge_dependencies()
        bridge = qt_app.MainUiRealRuntimeBridge("main.ui", session_read_only=True)
        bridge.window.resize(1400, 980)
        bridge.window.show()
        _process_events(app, 12)
        ids = _tutorial_ids(_parse_args(), tutorial_framework)
        for tutorial_id in ids:
            payload = tutorial_framework.load_tutorial(tutorial_id)
            if not payload:
                errors.append(f"{tutorial_id}: could not load tutorial")
                continue
            bridge._start_tutorial_from_ui_real(tutorial_id)
            _process_events(app, 8)
            overlay = getattr(bridge, "_frontend_active_tutorial_overlay", None)
            if overlay is None:
                errors.append(f"{tutorial_id}: overlay was not created")
                continue
            step_count = len(getattr(overlay, "steps", []) or [])
            for index in range(step_count):
                try:
                    overlay.show_step(index)
                    _process_events(app, 6)
                    errors.extend(_step_errors(overlay, tutorial_id, index))
                except Exception as exc:
                    errors.append(f"{tutorial_id} step {index + 1}: raised {exc}")
            try:
                overlay.finish("smoke")
            except Exception:
                pass
            _process_events(app, 4)
            walked += 1
    finally:
        if bridge is not None:
            try:
                bridge.close()
            except Exception:
                pass
        _process_events(app, 4)
        _restore_session(session_path, session_existed, session_data)
        app.quit()

    if errors:
        print(f"Tutorial walkthrough smoke failed after {walked} tutorial(s):")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Tutorial walkthrough smoke passed for {walked} tutorial(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
