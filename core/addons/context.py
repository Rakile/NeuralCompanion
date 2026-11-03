from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from core.runtime.addons import (
    AddonCapabilities,
    AddonEventBus,
    AddonGateway,
    AddonHostContext,
    AddonPaths,
    AddonServiceRegistry,
)

from .contributions import TabContribution, normalize_ui_area
from .manifest import AddonManifest


class AddonPermissionError(PermissionError):
    pass


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
        token = self._context.host.events.subscribe(event_name, handler)
        self._tokens.append(token)
        return token

    def publish(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        self._require("events.publish")
        self._context.host.events.publish(event_name, payload)

    def cleanup(self) -> None:
        if not self._context.host.closed:
            for token in self._tokens:
                self._context.host.events.unsubscribe(token)
        self._tokens.clear()


class AddonPeerService(AddonServiceBase):
    def __init__(self, context: "AddonContext", registry: AddonServiceRegistry):
        super().__init__(context)
        self._registry = registry

    def register(self, service_name: str, service: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require("services.register")
        entry = self._context.host.services.register(
            service_name,
            service,
            metadata,
        )
        return {
            "name": str(entry.name or "").strip(),
            "owner_addon_id": str(entry.owner_addon_id or "").strip(),
            "metadata": dict(entry.metadata or {}),
        }

    def unregister(self, service_name: str) -> bool:
        self._require("services.register")
        name = str(service_name or "").strip()
        if not name:
            return False
        return self._context.host.services.unregister(name)

    def register_consumer_factory(self, service_name: str, factory, metadata=None) -> dict[str, Any]:
        """Register an opt-in factory receiving a host-verified consumer binding."""
        self._require("services.register")
        entry = self._context.host.services.register_consumer_factory(service_name, factory, metadata)
        return {"name": entry.name, "owner_addon_id": entry.owner_addon_id,
                "metadata": dict(entry.metadata)}

    def get(self, service_name: str, default: Any = None) -> Any:
        self._require("services.consume")
        return self._context.host.services.get(service_name, default)

    def list(self) -> list[dict[str, Any]]:
        self._require("services.consume")
        return list(self._registry.list_entries())

    def cleanup(self) -> None:
        return None


class AddonUIService(AddonServiceBase):
    def __init__(self, context: "AddonContext"):
        super().__init__(context)
        self._tab_contributions: list[TabContribution] = []

    def _manifest_ui_entry(self, id: str) -> dict[str, Any]:
        target = str(id or "").strip()
        if not target:
            return {}
        for entry in list(getattr(self._context.manifest, "ui", []) or []):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("id") or "").strip() == target:
                return dict(entry)
        return {}

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
            area=normalize_ui_area(area),
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
        del (
            id,
            title,
            ui_path,
            binder,
            fallback_factory,
            area,
            order,
            tooltip,
            parent_tab_id,
            icon_path,
            metadata,
        )
        self._require("ui.tabs")
        raise RuntimeError(
            "Designer addon tabs were removed from NeuralCompanion. "
            "Declare metadata.native_qml and register a typed native adapter instead."
        )

    def register_manifest_tab(
        self,
        *,
        id: str,
        factory: Callable[["AddonContext"], Any],
        title: str | None = None,
        area: str | None = None,
        order: int | None = None,
        tooltip: str | None = None,
        parent_tab_id: str | None = None,
        icon_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TabContribution:
        entry = self._manifest_ui_entry(id)
        entry_metadata = dict(entry.get("metadata") or {})
        entry_metadata.update(dict(metadata or {}))
        return self.register_tab(
            id=id,
            title=str(title if title is not None else entry.get("title", "")).strip(),
            factory=factory,
            area=str(area if area is not None else entry.get("area", "top_level")).strip() or "top_level",
            order=int(order if order is not None else entry.get("order", 1000)),
            tooltip=str(tooltip if tooltip is not None else entry.get("tooltip", "")).strip(),
            parent_tab_id=str(parent_tab_id if parent_tab_id is not None else entry.get("parent_tab_id", "")).strip(),
            icon_path=str(icon_path if icon_path is not None else entry.get("icon_path", "")).strip(),
            metadata=entry_metadata,
        )

    def register_manifest_designer_tab(
        self,
        *,
        id: str,
        binder: Callable[[Any, "AddonContext"], None] | None = None,
        fallback_factory: Callable[["AddonContext"], Any] | None = None,
        title: str | None = None,
        ui_path: str | None = None,
        area: str | None = None,
        order: int | None = None,
        tooltip: str | None = None,
        parent_tab_id: str | None = None,
        icon_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TabContribution:
        entry = self._manifest_ui_entry(id)
        entry_metadata = dict(entry.get("metadata") or {})
        entry_metadata.update(dict(metadata or {}))
        if bool(
            entry_metadata.get("native_qml")
            or getattr(self._context.manifest, "native_qml", False)
        ):
            # Native surfaces are registered with the QML adapter registry.
            # Keep the contribution identity visible to addon discovery while
            # refusing to construct or require a Designer file.
            return self.register_tab(
                id=id,
                title=str(
                    title if title is not None else entry.get("title", "")
                ).strip(),
                factory=lambda _context: None,
                area=str(
                    area if area is not None else entry.get("area", "top_level")
                ).strip()
                or "top_level",
                order=int(order if order is not None else entry.get("order", 1000)),
                tooltip=str(
                    tooltip if tooltip is not None else entry.get("tooltip", "")
                ).strip(),
                parent_tab_id=str(
                    parent_tab_id
                    if parent_tab_id is not None
                    else entry.get("parent_tab_id", "")
                ).strip(),
                icon_path=str(
                    icon_path if icon_path is not None else entry.get("icon_path", "")
                ).strip(),
                metadata={
                    **entry_metadata,
                    "native_qml": True,
                    "ui_kind": "native_qml",
                },
            )
        return self.register_designer_tab(
            id=id,
            title=str(title if title is not None else entry.get("title", "")).strip(),
            ui_path=str(ui_path if ui_path is not None else entry.get("ui_path", "")).strip(),
            binder=binder,
            fallback_factory=fallback_factory,
            area=str(area if area is not None else entry.get("area", "top_level")).strip() or "top_level",
            order=int(order if order is not None else entry.get("order", 1000)),
            tooltip=str(tooltip if tooltip is not None else entry.get("tooltip", "")).strip(),
            parent_tab_id=str(parent_tab_id if parent_tab_id is not None else entry.get("parent_tab_id", "")).strip(),
            icon_path=str(icon_path if icon_path is not None else entry.get("icon_path", "")).strip(),
            metadata=entry_metadata,
        )

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
        self._context.ensure_open()
        path = self._storage_root / self._context.manifest.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve(self, relative_path: str = "") -> Path:
        self._context.ensure_open()
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
        host: AddonHostContext | None = None,
    ):
        self.manifest = manifest
        self.app_root = Path(app_root)
        self.logger = logging.getLogger(f"nc.addon.{manifest.id}")
        self._close_lock = threading.Lock()
        self._closed = False
        self._permissions = set(manifest.permissions)
        self._host_services = dict(host_services or {})
        if host is None:
            gateway = AddonGateway(
                event_bus=event_bus,
                service_registry=service_registry,
            )
            host = gateway.create_context(
                addon_id=manifest.id,
                logger=self.logger,
                paths=AddonPaths(
                    app_root=self.app_root,
                    addon_root=manifest.root_dir,
                    storage_root=Path(storage_root) / manifest.id,
                ),
                capabilities_factory=lambda owner: AddonCapabilities.from_host_services(
                    self._host_services,
                    execution_lanes=manifest.execution_lanes,
                    owner_binding=owner,
                ),
            )
            self._owned_gateway = gateway
        else:
            self._owned_gateway = None
        self.host = host
        self.owner = host.owner
        self.paths = host.paths
        self.tasks = host.tasks
        self.ui_dispatcher = host.ui
        self.capabilities = host.capabilities
        self.events = AddonEventService(self, event_bus)
        self.services = AddonPeerService(self, service_registry)
        self.ui = AddonUIService(self)
        self.storage = AddonStorageService(self, storage_root)
        self.llm = AddonSnapshotService(self, "llm.read", llm_snapshot_getter)
        self.tts = AddonSnapshotService(self, "tts.read", tts_snapshot_getter)
        self.avatar = AddonSnapshotService(self, "avatar.read", avatar_snapshot_getter)

    @property
    def closed(self) -> bool:
        with self._close_lock:
            return self._closed

    def ensure_open(self) -> None:
        if self.closed:
            raise RuntimeError(
                f"Addon context '{self.manifest.id}' is closed."
            )

    def has_permission(self, permission: str) -> bool:
        self.ensure_open()
        return permission in self._permissions

    def require_permission(self, permission: str) -> None:
        self.ensure_open()
        if permission not in self._permissions:
            raise AddonPermissionError(
                f"Addon '{self.manifest.id}' requested '{permission}' without declaring that permission."
            )

    def get_service(self, name: str, default: Any = None) -> Any:
        self.ensure_open()
        return self._host_services.get(str(name), default)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self.events.cleanup()
        self.services.cleanup()
        self.ui.cleanup()
        self.host.close()
