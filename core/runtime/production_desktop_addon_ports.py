"""Process-owned addon ports used by the production desktop composition root."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping

from core import avatar_runtime


class ProductionDesktopAvatarRegistryPort:
    """Create registered avatar providers without importing their addons."""

    __slots__ = ("_addon_capability_invoker",)

    def __init__(self, addon_capability_invoker=None) -> None:
        if addon_capability_invoker is not None and not callable(addon_capability_invoker):
            raise TypeError("Avatar addon capability invoker must be callable.")
        self._addon_capability_invoker = addon_capability_invoker

    def create_avatar_adapter(
        self,
        provider_id: str,
        construction_input: object,
    ) -> object | None:
        return avatar_runtime.create_avatar_adapter(
            str(provider_id or "").strip(),
            construction_input,
        )

    def invoke_addon_capability(self, addon_id, capability, payload=None) -> object:
        if self._addon_capability_invoker is None:
            return None
        return self._addon_capability_invoker(
            str(addon_id or "").strip(),
            str(capability or "").strip(),
            dict(payload or {}),
        )


class ProductionDesktopAddonManagerPort:
    """Stable finite adapter around the Qt-owned addon manager lifecycle."""

    __slots__ = ("_getter", "_lock", "_logger")

    def __init__(self, *, logger: Callable[[str], object] = print) -> None:
        if not callable(logger):
            raise TypeError("Production desktop addon logger must be callable.")
        self._logger = logger
        self._lock = threading.RLock()
        self._getter: Callable[[], object | None] | None = None

    def bind_manager_getter(
        self,
        getter: Callable[[], object | None],
    ) -> Callable[[], None]:
        if not callable(getter):
            raise TypeError("Addon manager binding requires a callable getter.")
        with self._lock:
            if self._getter is not None:
                raise RuntimeError("Production desktop addon manager is already bound.")
            self._getter = getter

        def unbind() -> None:
            with self._lock:
                if self._getter is getter:
                    self._getter = None

        return unbind

    def invoke_capability(
        self,
        capability: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        manager = self._manager()
        callback = getattr(manager, "invoke_capability", None)
        if not callable(callback):
            return None
        return callback(str(capability or ""), dict(payload or {}))

    def invoke_all_capabilities(
        self,
        capability: str,
        payload: dict[str, object] | None = None,
    ) -> list[object]:
        manager = self._manager()
        callback = getattr(manager, "invoke_all_capabilities", None)
        if not callable(callback):
            return []
        return list(callback(str(capability or ""), dict(payload or {})) or [])

    def invoke_addon_capability(
        self,
        addon_id: str,
        capability: str,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        manager = self._manager()
        callback = getattr(manager, "invoke_addon_capability", None)
        if not callable(callback):
            return None
        return callback(
            str(addon_id or ""),
            str(capability or ""),
            dict(payload or {}),
        )

    def record_latency_event(self, event: str, **fields: object) -> None:
        manager = self._manager()
        callback = getattr(manager, "record_latency_event", None)
        if callable(callback):
            callback(str(event or ""), **dict(fields))

    def invoke_service_capability(self, service_id: str, capability: str,
                                  payload: Mapping[str, object] | None = None, **metadata_match: object) -> object:
        manager = self._manager()
        callback = getattr(manager, 'invoke_service_capability', None)
        if not callable(callback):
            return None
        return callback(str(service_id or ''), str(capability or ''), dict(payload or {}), **metadata_match)

    def publish_event(
        self,
        event: str,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        manager = self._manager()
        callback = getattr(manager, "publish_event", None)
        if callable(callback):
            callback(str(event or ""), dict(payload or {}))

    def roleplay_assistant_reply(self, text: str) -> object:
        return self.invoke_capability(
            "roleplay.assistant_reply",
            {"text": str(text or "")},
        )

    def buddy_contextual_reply(
        self,
        payload: Mapping[str, object],
    ) -> object:
        return self.invoke_capability(
            "buddy_chat.contextual_reply",
            dict(payload),
        )

    def buddy_assistant_reply(
        self,
        text: str,
        *,
        source: str = "",
    ) -> object:
        payload = {"text": str(text or "")}
        normalized_source = str(source or "").strip().lower()
        if normalized_source:
            payload["source"] = normalized_source
        return self.invoke_capability("buddy_chat.assistant_reply", payload)

    def companion_orb_assistant_focus(
        self,
        payload: Mapping[str, object],
    ) -> object:
        return self.invoke_capability(
            "companion_orb.assistant_focus",
            dict(payload),
        )

    def _manager(self) -> object | None:
        with self._lock:
            getter = self._getter
        if getter is None:
            return None
        try:
            return getter()
        except Exception as exc:
            self._logger(f"[Addons] Manager lookup failed: {exc}")
            return None


class ProductionDesktopMuseTalkRuntimePort:
    """Finite MuseTalk process operations routed through the addon boundary."""

    __slots__ = ("_addons",)

    _ADDON_ID = "nc.musetalk_avatar"

    def __init__(self, addons: ProductionDesktopAddonManagerPort) -> None:
        if not isinstance(addons, ProductionDesktopAddonManagerPort):
            raise TypeError(
                "MuseTalk runtime port requires ProductionDesktopAddonManagerPort."
            )
        self._addons = addons

    def reset_musetalk_pipeline_data(self) -> None:
        self._invoke("runtime.pipeline.reset")

    def set_current_musetalk_frame_data(
        self,
        payload: Mapping[str, object],
    ) -> None:
        self._invoke("runtime.preview.set_state", {"state": dict(payload)})

    def write_musetalk_preview_frame(
        self,
        payload: Mapping[str, object],
    ) -> None:
        self._invoke("runtime.preview.write_frame", {"frame": dict(payload)})

    def _invoke(
        self,
        capability: str,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        return self._addons.invoke_addon_capability(
            self._ADDON_ID,
            capability,
            payload,
        )


class ProductionDesktopIdentityRelaySessionPort:
    """Route persisted Relay session state through its owning addon."""

    __slots__ = ("_addons",)

    _ADDON_ID = "nc.identity_artifacts"

    def __init__(self, addons: ProductionDesktopAddonManagerPort) -> None:
        if not isinstance(addons, ProductionDesktopAddonManagerPort):
            raise TypeError(
                "Identity Relay session port requires ProductionDesktopAddonManagerPort."
            )
        self._addons = addons

    def reset_session(self) -> object:
        return self._invoke("identity_relay.chat_session.reset")

    def export_session(self) -> Mapping[str, object] | None:
        result = self._invoke("identity_relay.chat_session.export")
        return dict(result) if isinstance(result, Mapping) else None

    def import_session(self, payload: Mapping[str, object]) -> object:
        if not isinstance(payload, Mapping):
            raise TypeError("Identity Relay session import requires a mapping.")
        return self._invoke(
            "identity_relay.chat_session.import",
            payload,
        )

    def _invoke(
        self,
        capability: str,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        return self._addons.invoke_addon_capability(
            self._ADDON_ID,
            capability,
            payload,
        )


__all__ = [
    "ProductionDesktopAddonManagerPort",
    "ProductionDesktopAvatarRegistryPort",
    "ProductionDesktopIdentityRelaySessionPort",
    "ProductionDesktopMuseTalkRuntimePort",
]
