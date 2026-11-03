"""Shared, installation-relative Stockfish paths; no imports of the app or Qt."""
from __future__ import annotations

from pathlib import Path

BUNDLED_ENGINE = 'bundled'
_LEGACY_SHORTCUT = 'i:/chess/engines/stockfish.exe'


def bundled_stockfish_path(app_root: Path | None = None) -> Path:
    root = Path(app_root) if app_root is not None else Path(__file__).resolve().parents[2]
    return root / 'tools' / 'stockfish' / 'stockfish.exe'


def normalize_engine_selection(value: str) -> str:
    selection = value.strip()
    if selection.replace('\\', '/').casefold() == _LEGACY_SHORTCUT and not Path(selection).is_file():
        return BUNDLED_ENGINE
    return selection


def resolve_engine_path(value: str, app_root: Path | None = None) -> str:
    selection = normalize_engine_selection(value)
    if not selection:
        return ''  # Explicitly retain the basic engine option.
    if selection == BUNDLED_ENGINE:
        bundled = bundled_stockfish_path(app_root)
        return str(bundled) if bundled.is_file() else ''
    custom = Path(selection)
    if not custom.is_absolute():
        root = Path(app_root) if app_root is not None else Path(__file__).resolve().parents[2]
        custom = root / custom
    return str(custom)
