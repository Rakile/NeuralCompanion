"""Application-shell constants shared by the native QML entry point."""

from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
APP_TITLE = "Neural Companion"
APP_ICON_PATH = APP_ROOT / "ui_icons" / "app" / "neural_companion_app_icon.ico"
SESSION_PATH = Path("qt_session.json")


__all__ = ["APP_ICON_PATH", "APP_ROOT", "APP_TITLE", "SESSION_PATH"]
