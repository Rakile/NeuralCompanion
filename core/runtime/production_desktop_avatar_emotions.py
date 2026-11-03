"""Owned avatar-emotion catalog for the production desktop graph."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from pathlib import Path

from core.addons import bootstrap_runtime
from core.text_tags import persona_mood_names
from core.runtime.body_profile import BodyProfileService
from core.runtime.config import RuntimeConfigService
from core.runtime.production_desktop_addon_ports import (
    ProductionDesktopAddonManagerPort,
)


DEFAULT_EMOTION_NAMES = frozenset(
    {"neutral", "happy", "sad", "angry", "shy", "surprised"}
)
_LEGACY_AVATAR_MAP = {"angry": "angry_avatar"}
_LEGACY_TRANSITIONS = {
    ("angry_avatar", "default_avatar"): {"start_frame": 80, "end_frame": 7}
}


class ProductionDesktopAvatarEmotionCatalog:
    """Cache the selected avatar's declared emotion names for two seconds."""

    __slots__ = (
        "_addons",
        "_app_root",
        "_body",
        "_config",
        "_loaded_at",
        "_lock",
        "_names",
    )

    def __init__(
        self,
        *,
        app_root: str | Path,
        config: RuntimeConfigService,
        body: BodyProfileService,
        addons: ProductionDesktopAddonManagerPort,
    ) -> None:
        if not isinstance(config, RuntimeConfigService):
            raise TypeError("Avatar emotion catalog requires RuntimeConfigService.")
        if not isinstance(body, BodyProfileService):
            raise TypeError("Avatar emotion catalog requires BodyProfileService.")
        if not isinstance(addons, ProductionDesktopAddonManagerPort):
            raise TypeError(
                "Avatar emotion catalog requires ProductionDesktopAddonManagerPort."
            )
        self._app_root = Path(app_root).resolve()
        self._config = config
        self._body = body
        self._addons = addons
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self._names = set(DEFAULT_EMOTION_NAMES)

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0
            self._names = set(DEFAULT_EMOTION_NAMES)

    def available_names(self) -> set[str]:
        return self._load(force=False) | persona_mood_names(self._config.snapshot().values)

    def refresh_emotions(self) -> set[str]:
        return self._load(force=True)

    def _load(self, *, force: bool) -> set[str]:
        now = time.time()
        with self._lock:
            if not force and self._names and now - self._loaded_at < 2.0:
                return set(self._names)
        values = self._config.snapshot().values
        profile = self._body.snapshot().profile
        payload = {
            "runtime_config": values,
            "default_names": sorted(DEFAULT_EMOTION_NAMES),
            "avatar_profile": profile,
            "legacy_map": dict(_LEGACY_AVATAR_MAP),
            "legacy_transitions": dict(_LEGACY_TRANSITIONS),
            "avatars_dir": (
                self._app_root / "MuseTalk" / "results" / "v15" / "avatars"
            ),
        }
        avatar_mode = str(values.get("avatar_mode", "") or "").strip().lower()
        names = (
            self._addons.invoke_service_capability(
                'avatar_provider_registry',
                "runtime.available_pack_emotion_names",
                payload,
                provider_id=avatar_mode,
            )
            if avatar_mode
            else None
        )
        if names is None:
            names = bootstrap_runtime.invoke_addon_capability(
                "nc.musetalk_avatar",
                "runtime.available_pack_emotion_names",
                payload,
                app_root=self._app_root,
                default=None,
            )
        normalized = _normalize_names(names, profile)
        with self._lock:
            self._loaded_at = now
            self._names = normalized
            return set(normalized)


def _normalize_names(
    names: object,
    profile: Mapping[str, object],
) -> set[str]:
    source = names if isinstance(names, (list, tuple, set, frozenset)) else ()
    normalized = {
        str(item or "").strip().lower()
        for item in source
        if str(item or "").strip()
    }
    if normalized:
        return normalized
    return set(DEFAULT_EMOTION_NAMES).union(
        str(key or "").strip().lower()
        for key in profile
        if str(key or "").strip()
    )


__all__ = [
    "DEFAULT_EMOTION_NAMES",
    "ProductionDesktopAvatarEmotionCatalog",
]
