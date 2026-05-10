"""Compatibility access for the addon-owned MuseTalk preview panel."""

from core.addons import bootstrap_runtime


_exports = bootstrap_runtime.invoke_addon_capability(
    "nc.musetalk_avatar",
    "ui.preview_panel_exports",
    default={},
)
if not _exports:
    raise ImportError("MuseTalk addon did not provide ui.preview_panel_exports.")

QT_MUSETALK_LOOP_FADE_MS = _exports["QT_MUSETALK_LOOP_FADE_MS"]
QT_PREVIEW_AHEAD_PRELOAD = _exports["QT_PREVIEW_AHEAD_PRELOAD"]
QT_PREVIEW_CACHE_LIMIT = _exports["QT_PREVIEW_CACHE_LIMIT"]
QT_PREVIEW_INITIAL_PRELOAD = _exports["QT_PREVIEW_INITIAL_PRELOAD"]
QtMuseTalkPreviewPanel = _exports["QtMuseTalkPreviewPanel"]

__all__ = [
    "QT_MUSETALK_LOOP_FADE_MS",
    "QT_PREVIEW_AHEAD_PRELOAD",
    "QT_PREVIEW_CACHE_LIMIT",
    "QT_PREVIEW_INITIAL_PRELOAD",
    "QtMuseTalkPreviewPanel",
]
