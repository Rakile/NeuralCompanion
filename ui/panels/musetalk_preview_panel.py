"""Compatibility import for the addon-owned MuseTalk preview panel.

The MuseTalk avatar addon owns the preview surface implementation. This module
keeps older host imports stable while the dock/runtime shell continues moving
toward addon-owned UI.
"""

from addons.musetalk_avatar.preview_panel import (
    QT_MUSETALK_LOOP_FADE_MS,
    QT_PREVIEW_AHEAD_PRELOAD,
    QT_PREVIEW_CACHE_LIMIT,
    QT_PREVIEW_INITIAL_PRELOAD,
    QtMuseTalkPreviewPanel,
)

__all__ = [
    "QT_MUSETALK_LOOP_FADE_MS",
    "QT_PREVIEW_AHEAD_PRELOAD",
    "QT_PREVIEW_CACHE_LIMIT",
    "QT_PREVIEW_INITIAL_PRELOAD",
    "QtMuseTalkPreviewPanel",
]
