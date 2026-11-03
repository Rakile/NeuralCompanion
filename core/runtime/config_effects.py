"""Runtime configuration normalization and side-effect ownership."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from core.runtime.config import (
    RuntimeConfigChanged,
    RuntimeConfigService,
    RuntimeConfigSnapshot,
)
from core.runtime.events import RuntimeSubscription


LEGACY_CONFIG_KEY_TRANSLATIONS = MappingProxyType(
    {
        "long_term_memory_enabled": "continuity_memory_enabled",
        "long_term_memory_update_on_save": "continuity_memory_auto_summarize",
        "continuity_memory_update_on_save": "continuity_memory_auto_summarize",
        "long_term_memory_inject": "continuity_memory_inject",
        "long_term_memory_max_chars": "continuity_memory_max_chars",
    }
)

_HOTKEY_KEYS = frozenset(
    {
        "hotkeys",
        "push_to_talk_hotkey",
        "manual_action_hotkeys",
        "ui_action_hotkeys",
    }
)
_HOTKEY_EFFECT_KEYS = _HOTKEY_KEYS | {"input_mode", "offline_replay_only"}
_MEMORY_EFFECT_KEYS = frozenset(
    {"continuity_memory_id", "active_chat_context_path", "active_chat_context_name"}
)
_AVATAR_EMOTION_KEYS = frozenset(
    {"musetalk_avatar_pack_id", "musetalk_enabled_pack_emotions"}
)
_VISUAL_PRESENCE_PREFIXES = ("ai_presence_", "companion_orb_")


@dataclass(frozen=True, slots=True)
class HotkeyConfigCallbacks:
    """Typed hotkey normalization and application boundary."""

    normalize_settings: Callable[
        [object, object | None, object | None, object | None], Mapping[str, object]
    ]
    normalize_binding: Callable[[object], str]
    normalize_manual_actions: Callable[[object], Mapping[str, object]]
    normalize_ui_actions: Callable[[object], Mapping[str, object]]
    bind: Callable[[RuntimeConfigSnapshot], None]
    default_push_to_talk: str


@dataclass(frozen=True, slots=True)
class ProviderConfigCallbacks:
    """Typed chat-provider normalization and settings boundary."""

    normalize_provider_id: Callable[[object, str], str]
    apply_settings: Callable[[dict[str, object]], None]
    default_provider_id: str


@dataclass(frozen=True, slots=True)
class MemoryConfigCallbacks:
    """Typed active-memory-store refresh boundary."""

    refresh_active_store: Callable[[object], None]


@dataclass(frozen=True, slots=True)
class AvatarConfigCallbacks:
    """Typed avatar config normalization and cache boundary."""

    normalize_replay_role_voices: Callable[[object], Mapping[str, object]]
    normalize_enabled_pack_emotions: Callable[[object], Mapping[str, object]]
    invalidate_emotion_names: Callable[[], None]


@dataclass(frozen=True, slots=True)
class VisualPresenceConfigCallbacks:
    """Typed visual-presence settings boundary."""

    apply: Callable[[RuntimeConfigSnapshot], None]


class RuntimeConfigEffects:
    """Own legacy config writes and their deterministic domain fan-out."""

    def __init__(
        self,
        config: RuntimeConfigService,
        *,
        hotkeys: HotkeyConfigCallbacks | None = None,
        provider: ProviderConfigCallbacks | None = None,
        memory: MemoryConfigCallbacks | None = None,
        avatar: AvatarConfigCallbacks | None = None,
        visual_presence: VisualPresenceConfigCallbacks | None = None,
    ) -> None:
        self._config = config
        self._hotkeys = hotkeys
        self._provider = provider
        self._memory = memory
        self._avatar = avatar
        self._visual_presence = visual_presence
        self._subscription: RuntimeSubscription | None = config.subscribe(
            self._apply_changed_config
        )

    def close(self) -> None:
        subscription = self._subscription
        if subscription is None:
            return
        self._subscription = None
        subscription.close()

    def translate_key(self, key: object) -> object:
        normalized = str(key or "")
        return LEGACY_CONFIG_KEY_TRANSLATIONS.get(normalized, key)

    def update(self, key: object, value: object) -> RuntimeConfigChanged | None:
        """Apply one legacy-compatible write, ignoring unknown config keys."""

        translated = self.translate_key(key)
        snapshot = self._config.snapshot()
        if translated not in snapshot.values:
            return None
        normalized_key = str(translated)
        if normalized_key in _HOTKEY_KEYS:
            return self._update_hotkeys(normalized_key, value, snapshot)
        normalized_value = self._normalize_value(normalized_key, value)
        return self._config.update(normalized_key, normalized_value)

    def _update_hotkeys(
        self,
        key: str,
        value: object,
        snapshot: RuntimeConfigSnapshot,
    ) -> RuntimeConfigChanged:
        callbacks = self._require_hotkeys()
        values = snapshot.values
        if key == "hotkeys":
            settings = dict(callbacks.normalize_settings(value, None, None, None))
        else:
            settings = dict(
                callbacks.normalize_settings(
                    values.get("hotkeys", {}),
                    values.get("push_to_talk_hotkey"),
                    values.get("manual_action_hotkeys"),
                    values.get("ui_action_hotkeys"),
                )
            )
            if key == "push_to_talk_hotkey":
                settings["push_to_talk"] = (
                    callbacks.normalize_binding(value)
                    or callbacks.default_push_to_talk
                )
            elif key == "manual_action_hotkeys":
                settings["manual_actions"] = dict(
                    callbacks.normalize_manual_actions(value)
                )
            else:
                settings["ui_actions"] = dict(callbacks.normalize_ui_actions(value))
        return self._config.update_many(self._legacy_hotkey_values(settings))

    @staticmethod
    def _legacy_hotkey_values(
        settings: Mapping[str, object],
    ) -> dict[str, object]:
        payload = dict(settings)
        return {
            "hotkeys": payload,
            "push_to_talk_hotkey": payload["push_to_talk"],
            "manual_action_hotkeys": dict(payload["manual_actions"]),
            "ui_action_hotkeys": dict(payload["ui_actions"]),
        }

    def _normalize_value(self, key: str, value: object) -> object:
        if key == "chat_provider":
            callbacks = self._require_provider()
            return callbacks.normalize_provider_id(value, callbacks.default_provider_id)
        if key in {"chat_provider_settings", "stt_backend_settings"}:
            return dict(value or {})
        if key == "chat_replay_role_voices":
            return dict(self._require_avatar().normalize_replay_role_voices(value))
        if key == "musetalk_enabled_pack_emotions":
            return dict(self._require_avatar().normalize_enabled_pack_emotions(value))
        return value

    def _apply_changed_config(self, event: RuntimeConfigChanged) -> None:
        changed = frozenset(event.changed_keys)
        if self._hotkeys is not None and changed.intersection(_HOTKEY_EFFECT_KEYS):
            self._hotkeys.bind(event.snapshot)
        if self._provider is not None and "chat_provider_settings" in changed:
            settings = _thaw(event.values.get("chat_provider_settings", {}))
            self._provider.apply_settings(dict(settings or {}))
        if self._memory is not None and changed.intersection(_MEMORY_EFFECT_KEYS):
            try:
                self._memory.refresh_active_store(
                    _thaw(event.values.get("continuity_memory_id"))
                )
            except Exception:
                pass
        if self._avatar is not None and changed.intersection(_AVATAR_EMOTION_KEYS):
            self._avatar.invalidate_emotion_names()
        if self._visual_presence is not None and any(
            key.startswith(_VISUAL_PRESENCE_PREFIXES) for key in event.changed_keys
        ):
            try:
                self._visual_presence.apply(event.snapshot)
            except Exception:
                pass

    def _require_hotkeys(self) -> HotkeyConfigCallbacks:
        if self._hotkeys is None:
            raise RuntimeError("Hotkey config callbacks are not configured")
        return self._hotkeys

    def _require_provider(self) -> ProviderConfigCallbacks:
        if self._provider is None:
            raise RuntimeError("Provider config callbacks are not configured")
        return self._provider

    def _require_avatar(self) -> AvatarConfigCallbacks:
        if self._avatar is None:
            raise RuntimeError("Avatar config callbacks are not configured")
        return self._avatar


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return {_thaw(item) for item in value}
    return value


__all__ = [
    "AvatarConfigCallbacks",
    "HotkeyConfigCallbacks",
    "LEGACY_CONFIG_KEY_TRANSLATIONS",
    "MemoryConfigCallbacks",
    "ProviderConfigCallbacks",
    "RuntimeConfigEffects",
    "VisualPresenceConfigCallbacks",
]
