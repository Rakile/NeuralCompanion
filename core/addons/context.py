from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from .contributions import TabContribution
from .manifest import AddonManifest


class AddonPermissionError(PermissionError):
    pass


class AddonEventBus:
    def __init__(self):
        self._subscriptions: dict[str, list[tuple[int, Callable[[dict[str, Any]], None]]]] = {}
        self._next_token = 1

    def subscribe(self, event_name: str, handler: Callable[[dict[str, Any]], None]) -> int:
        token = self._next_token
        self._next_token += 1
        self._subscriptions.setdefault(str(event_name), []).append((token, handler))
        return token

    def unsubscribe(self, token: int) -> None:
        for event_name, handlers in list(self._subscriptions.items()):
            next_handlers = [(existing_token, handler) for existing_token, handler in handlers if existing_token != token]
            if next_handlers:
                self._subscriptions[event_name] = next_handlers
            else:
                self._subscriptions.pop(event_name, None)

    def publish(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        handlers = list(self._subscriptions.get(str(event_name), []))
        for _token, handler in handlers:
            try:
                handler(dict(payload or {}))
            except Exception:
                logging.getLogger("nc.addons.events").exception("Addon event handler failed for '%s'", event_name)


class AddonServiceRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._services: dict[str, dict[str, Any]] = {}

    def register(self, *, owner_addon_id: str, service_name: str, service: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = str(owner_addon_id or "").strip()
        name = str(service_name or "").strip()
        if not owner:
            raise ValueError("Service owner addon id is required.")
        if not name:
            raise ValueError("Service name is required.")
        entry = {
            "name": name,
            "owner_addon_id": owner,
            "service": service,
            "metadata": dict(metadata or {}),
        }
        with self._lock:
            self._services[name] = entry
        return dict(entry)

    def unregister(self, service_name: str) -> bool:
        name = str(service_name or "").strip()
        if not name:
            return False
        with self._lock:
            return self._services.pop(name, None) is not None

    def unregister_owner(self, owner_addon_id: str) -> int:
        owner = str(owner_addon_id or "").strip()
        if not owner:
            return 0
        removed = 0
        with self._lock:
            for name, entry in list(self._services.items()):
                if str(entry.get("owner_addon_id") or "") != owner:
                    continue
                self._services.pop(name, None)
                removed += 1
        return removed

    def get(self, service_name: str, default: Any = None) -> Any:
        name = str(service_name or "").strip()
        if not name:
            return default
        with self._lock:
            entry = self._services.get(name)
        if not entry:
            return default
        return entry.get("service", default)

    def list_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            entries = list(self._services.values())
        summaries = []
        for entry in entries:
            summaries.append(
                {
                    "name": str(entry.get("name") or "").strip(),
                    "owner_addon_id": str(entry.get("owner_addon_id") or "").strip(),
                    "metadata": dict(entry.get("metadata") or {}),
                }
            )
        return sorted(summaries, key=lambda item: (item.get("owner_addon_id", ""), item.get("name", "")))


class AddonServiceBase:
    def __init__(self, context: "AddonContext"):
        self._context = context

    def _require(self, permission: str) -> None:
        self._context.require_permission(permission)


class AddonEventService(AddonServiceBase):
    def __init__(self, context: "AddonContext", event_bus: AddonEventBus):
        super().__init__(context)
        self._event_bus = event_bus
        self._tokens: list[int] = []

    def subscribe(self, event_name: str, handler: Callable[[dict[str, Any]], None]) -> int:
        self._require("events.subscribe")
        token = self._event_bus.subscribe(event_name, handler)
        self._tokens.append(token)
        return token

    def publish(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        self._require("events.publish")
        self._event_bus.publish(event_name, payload)

    def cleanup(self) -> None:
        for token in self._tokens:
            self._event_bus.unsubscribe(token)
        self._tokens.clear()


class AddonPeerService(AddonServiceBase):
    def __init__(self, context: "AddonContext", registry: AddonServiceRegistry):
        super().__init__(context)
        self._registry = registry

    def register(self, service_name: str, service: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require("services.register")
        entry = self._registry.register(
            owner_addon_id=self._context.manifest.id,
            service_name=service_name,
            service=service,
            metadata=metadata,
        )
        return {
            "name": str(entry.get("name") or "").strip(),
            "owner_addon_id": str(entry.get("owner_addon_id") or "").strip(),
            "metadata": dict(entry.get("metadata") or {}),
        }

    def unregister(self, service_name: str) -> bool:
        self._require("services.register")
        name = str(service_name or "").strip()
        if not name:
            return False
        current = next((item for item in self._registry.list_entries() if str(item.get("name") or "") == name), None)
        if current is not None and str(current.get("owner_addon_id") or "") != self._context.manifest.id:
            raise AddonPermissionError(
                f"Addon '{self._context.manifest.id}' may not unregister peer service '{name}' owned by '{current.get('owner_addon_id')}'."
            )
        return self._registry.unregister(name)

    def get(self, service_name: str, default: Any = None) -> Any:
        self._require("services.consume")
        return self._registry.get(service_name, default)

    def list(self) -> list[dict[str, Any]]:
        self._require("services.consume")
        return list(self._registry.list_entries())

    def cleanup(self) -> None:
        self._registry.unregister_owner(self._context.manifest.id)


class AddonUIService(AddonServiceBase):
    def __init__(self, context: "AddonContext"):
        super().__init__(context)
        self._tab_contributions: list[TabContribution] = []

    def register_tab(
        self,
        *,
        id: str,
        title: str,
        factory: Callable[["AddonContext"], Any],
        area: str = "top_level",
        order: int = 1000,
        tooltip: str = "",
        parent_tab_id: str = "",
        icon_path: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TabContribution:
        self._require("ui.tabs")
        contribution_metadata = dict(metadata or {})
        if str(icon_path or "").strip():
            contribution_metadata["icon_path"] = str(icon_path or "").strip()
        contribution = TabContribution(
            id=str(id or "").strip(),
            title=str(title or "").strip(),
            factory=factory,
            addon_id=self._context.manifest.id,
            area=str(area or "top_level").strip() or "top_level",
            order=int(order),
            tooltip=str(tooltip or ""),
            parent_tab_id=str(parent_tab_id or "").strip(),
            metadata=contribution_metadata,
        )
        self._tab_contributions.append(contribution)
        return contribution

    def register_designer_tab(
        self,
        *,
        id: str,
        title: str,
        ui_path: str,
        binder: Callable[[Any, "AddonContext"], None] | None = None,
        fallback_factory: Callable[["AddonContext"], Any] | None = None,
        area: str = "top_level",
        order: int = 1000,
        tooltip: str = "",
        parent_tab_id: str = "",
        icon_path: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TabContribution:
        self._require("ui.tabs")
        relative_ui_path = str(ui_path or "").strip()
        if not relative_ui_path:
            raise ValueError("Designer tab ui_path is required.")

        def _factory(addon_context: "AddonContext"):
            try:
                addon_context = addon_context or self._context
                from PySide6 import QtCore, QtUiTools

                raw_path = Path(relative_ui_path)
                resolved_path = raw_path if raw_path.is_absolute() else self._context.manifest.root_dir / raw_path
                ui_file = QtCore.QFile(str(resolved_path))
                if not ui_file.open(QtCore.QIODevice.ReadOnly):
                    raise RuntimeError(f"Could not open addon UI file: {resolved_path}")
                try:
                    widget = QtUiTools.QUiLoader().load(ui_file)
                finally:
                    ui_file.close()
                if widget is None:
                    raise RuntimeError(f"Addon UI file did not produce a widget: {resolved_path}")
                host_binder = addon_context.get_service("qt.bind_designer_widgets")
                if callable(host_binder):
                    host_binder(widget)
                if binder is not None:
                    binder(widget, addon_context)
                return widget
            except Exception as exc:
                if fallback_factory is None:
                    raise
                try:
                    addon_context.logger.warning(
                        "Designer UI tab '%s' failed to load from '%s'; using fallback factory. Error: %s",
                        str(id or "").strip(),
                        relative_ui_path,
                        exc,
                    )
                except Exception:
                    pass
                return fallback_factory(addon_context)

        contribution_metadata = {**dict(metadata or {}), "ui_path": relative_ui_path, "ui_kind": "designer"}
        if str(icon_path or "").strip():
            contribution_metadata["icon_path"] = str(icon_path or "").strip()

        contribution = TabContribution(
            id=str(id or "").strip(),
            title=str(title or "").strip(),
            factory=_factory,
            addon_id=self._context.manifest.id,
            area=str(area or "top_level").strip() or "top_level",
            order=int(order),
            tooltip=str(tooltip or ""),
            parent_tab_id=str(parent_tab_id or "").strip(),
            metadata=contribution_metadata,
        )
        self._tab_contributions.append(contribution)
        return contribution

    def get_tab_contributions(self) -> list[TabContribution]:
        return list(self._tab_contributions)

    def cleanup(self) -> None:
        self._tab_contributions.clear()


class AddonStorageService(AddonServiceBase):
    def __init__(self, context: "AddonContext", storage_root: Path):
        super().__init__(context)
        self._storage_root = Path(storage_root)

    @property
    def addon_dir(self) -> Path:
        path = self._storage_root / self._context.manifest.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve(self, relative_path: str = "") -> Path:
        relative = Path(str(relative_path or "").strip())
        return (self.addon_dir / relative).resolve()

    def read_text(self, relative_path: str, encoding: str = "utf-8") -> str:
        self._require("storage.read")
        return self.resolve(relative_path).read_text(encoding=encoding)

    def write_text(self, relative_path: str, content: str, encoding: str = "utf-8") -> Path:
        self._require("storage.write")
        target = self.resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding=encoding)
        return target

    def read_json(self, relative_path: str) -> Any:
        self._require("storage.read")
        return json.loads(self.read_text(relative_path))

    def write_json(self, relative_path: str, payload: Any) -> Path:
        self._require("storage.write")
        return self.write_text(relative_path, json.dumps(payload, indent=2))


class AddonSnapshotService(AddonServiceBase):
    def __init__(self, context: "AddonContext", permission: str, getter: Callable[[], dict[str, Any]]):
        super().__init__(context)
        self._permission = permission
        self._getter = getter

    def snapshot(self) -> dict[str, Any]:
        self._require(self._permission)
        return dict(self._getter() or {})


class AddonContext:
    def __init__(
        self,
        *,
        manifest: AddonManifest,
        app_root: Path,
        event_bus: AddonEventBus,
        service_registry: AddonServiceRegistry,
        storage_root: Path,
        llm_snapshot_getter: Callable[[], dict[str, Any]],
        tts_snapshot_getter: Callable[[], dict[str, Any]],
        avatar_snapshot_getter: Callable[[], dict[str, Any]],
        host_services: dict[str, Any] | None = None,
    ):
        self.manifest = manifest
        self.app_root = Path(app_root)
        self.logger = logging.getLogger(f"nc.addon.{manifest.id}")
        self._permissions = set(manifest.permissions)
        self._host_services = dict(host_services or {})
        self.events = AddonEventService(self, event_bus)
        self.services = AddonPeerService(self, service_registry)
        self.ui = AddonUIService(self)
        self.storage = AddonStorageService(self, storage_root)
        self.llm = AddonSnapshotService(self, "llm.read", llm_snapshot_getter)
        self.tts = AddonSnapshotService(self, "tts.read", tts_snapshot_getter)
        self.avatar = AddonSnapshotService(self, "avatar.read", avatar_snapshot_getter)

    def has_permission(self, permission: str) -> bool:
        return permission in self._permissions

    def require_permission(self, permission: str) -> None:
        if permission not in self._permissions:
            raise AddonPermissionError(
                f"Addon '{self.manifest.id}' requested '{permission}' without declaring that permission."
            )

    def get_service(self, name: str, default: Any = None) -> Any:
        return self._host_services.get(str(name), default)

    def close(self) -> None:
        self.events.cleanup()
        self.services.cleanup()
        self.ui.cleanup()
