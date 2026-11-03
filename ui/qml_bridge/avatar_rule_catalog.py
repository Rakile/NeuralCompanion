"""Refresh lightweight pack metadata off the Qt thread for prompt defaults."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6 import QtCore


def read_pack_catalog(app_root: Path) -> dict:
    # Reuse the providers' shared manifest loader; never load models/media.
    from addons.musetalk_avatar.avatar_packs import discover_avatar_packs
    result = {}
    for provider in ('musetalk', 'ditto'):
        packs = discover_avatar_packs(
            default_avatar_id='', packs_dir=app_root / 'avatar_packs',
            avatars_dir=app_root / 'MuseTalk/results/v15/avatars', engine=provider,
            include_legacy=False, include_standalone=False)
        result[provider] = {
            identity: {'default_avatar_id': pack.default_avatar_id,
                       'emotion_avatar_map': pack.emotion_avatar_map()}
            for identity, pack in packs.items()
        }
    return result


class AvatarRuleCatalog(QtCore.QObject):
    """Publish immutable runtime-only facts; user rules are never rewritten."""

    def __init__(self, bridge, app_root: Path) -> None:
        super().__init__(bridge)
        self._bridge = bridge
        self._root = app_root
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='nc-pack-rules')
        self._future = None
        self._closed = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._timer.start(0)

    def _tick(self) -> None:
        if self._closed:
            return
        if self._future is None:
            self._future = self._executor.submit(read_pack_catalog, self._root)
        if not self._future.done():
            self._timer.start(100)
            return
        try:
            catalog = self._future.result()
        except (OSError, ValueError, RuntimeError):
            # Fail closed rather than advertise tags from an unavailable pack.
            catalog = {}
        self._future = None
        config = self._bridge._application.config
        if config.get('_avatar_rule_pack_catalog', {}) != catalog:
            result = config.update('_avatar_rule_pack_catalog', catalog)
            if result.accepted:
                self._bridge.configurationChanged.emit()
        self._timer.start(2000)

    def close(self) -> None:
        self._closed = True
        self._timer.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
