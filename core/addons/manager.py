from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .context import AddonContext, AddonEventBus, AddonServiceRegistry
from .manifest import AddonManifest


@dataclass
class LoadedAddon:
    manifest: AddonManifest
    root_dir: Path
    module: ModuleType | None = None
    instance: Any = None
    context: AddonContext | None = None
    state: str = "discovered"
    error: str = ""


class AddonManager:
    def __init__(
        self,
        *,
        app_root: str | Path,
        llm_snapshot_getter,
        tts_snapshot_getter,
        avatar_snapshot_getter,
        host_services: dict[str, Any] | None = None,
    ):
        self.app_root = Path(app_root)
        self.addons_dir = self.app_root / "addons"
        self.storage_root = self.app_root / "runtime" / "addons"
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("nc.addons")
        self.event_bus = AddonEventBus()
        self.service_registry = AddonServiceRegistry()
        self._llm_snapshot_getter = llm_snapshot_getter
        self._tts_snapshot_getter = tts_snapshot_getter
        self._avatar_snapshot_getter = avatar_snapshot_getter
        self._host_services = dict(host_services or {})
        self._records: list[LoadedAddon] = []

    def discover(self) -> list[LoadedAddon]:
        self._records = []
        seen_ids: set[str] = set()
        if not self.addons_dir.exists():
            return []
        for child in sorted(self.addons_dir.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / "addon.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = AddonManifest.from_file(manifest_path)
                if not manifest.enabled:
                    self.logger.info("Skipping disabled addon: %s", manifest.id)
                    continue
                if manifest.id in seen_ids:
                    raise ValueError(f"Duplicate addon id '{manifest.id}'")
                seen_ids.add(manifest.id)
                self._records.append(LoadedAddon(manifest=manifest, root_dir=child))
            except Exception as exc:
                self.logger.warning("Failed to discover addon in %s: %s", child, exc)
        return list(self._records)

    def _load_module(self, manifest: AddonManifest) -> ModuleType:
        entry_path = (manifest.root_dir / manifest.entry_point).resolve()
        if not entry_path.exists():
            raise FileNotFoundError(f"Addon entry point not found: {entry_path}")
        module_name = f"nc_addon_{manifest.id.replace('.', '_').replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module spec for addon '{manifest.id}'")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _instantiate_addon(self, module: ModuleType, manifest: AddonManifest):
        if hasattr(module, "create_addon") and callable(module.create_addon):
            return module.create_addon()
        if hasattr(module, "Addon") and callable(module.Addon):
            return module.Addon()
        raise ValueError(
            f"Addon '{manifest.id}' must expose create_addon() or an Addon class in {manifest.entry_point}"
        )

    def load_all(self) -> list[LoadedAddon]:
        for record in self._records:
            try:
                record.module = self._load_module(record.manifest)
                record.instance = self._instantiate_addon(record.module, record.manifest)
                record.state = "loaded"
            except Exception as exc:
                record.state = "error"
                record.error = str(exc)
                self.logger.warning("Failed to load addon '%s': %s", record.manifest.id, exc)
        return list(self._records)

    def initialize_all(self) -> list[LoadedAddon]:
        if not self._records:
            self.discover()
        if not any(record.state in {"loaded", "initialized", "error"} for record in self._records):
            self.load_all()
        for record in self._records:
            if record.state != "loaded":
                continue
            try:
                record.context = AddonContext(
                    manifest=record.manifest,
                    app_root=self.app_root,
                    event_bus=self.event_bus,
                    service_registry=self.service_registry,
                    storage_root=self.storage_root,
                    llm_snapshot_getter=self._llm_snapshot_getter,
                    tts_snapshot_getter=self._tts_snapshot_getter,
                    avatar_snapshot_getter=self._avatar_snapshot_getter,
                    host_services=self._host_services,
                )
                if hasattr(record.instance, "initialize"):
                    record.instance.initialize(record.context)
                record.state = "initialized"
                self.logger.info("Initialized addon '%s' v%s", record.manifest.id, record.manifest.version)
            except Exception as exc:
                record.state = "error"
                record.error = str(exc)
                self.logger.warning("Failed to initialize addon '%s': %s", record.manifest.id, exc)
        return list(self._records)

    def unload_all(self) -> None:
        for record in reversed(self._records):
            try:
                if record.instance is not None and hasattr(record.instance, "shutdown"):
                    record.instance.shutdown()
            except Exception:
                self.logger.exception("Addon shutdown failed for '%s'", record.manifest.id)
            finally:
                if record.context is not None:
                    try:
                        record.context.close()
                    except Exception:
                        self.logger.exception("Addon context cleanup failed for '%s'", record.manifest.id)
                if record.state != "error":
                    record.state = "unloaded"

    def get_tab_contributions(self, area: str = "top_level"):
        contributions = []
        for record in self._records:
            if record.state != "initialized" or record.context is None:
                continue
            for contribution in record.context.ui.get_tab_contributions():
                if contribution.area == area:
                    contributions.append(contribution)
        return sorted(contributions, key=lambda item: (item.order, item.title.lower()))

    def publish_event(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        self.event_bus.publish(event_name, payload)

    def list_registered_services(self) -> list[dict[str, Any]]:
        return list(self.service_registry.list_entries())

    def get_registered_service(self, service_name: str, default: Any = None) -> Any:
        return self.service_registry.get(service_name, default)

    def invoke_capability(self, capability: str, payload: dict[str, Any] | None = None) -> Any:
        capability = str(capability or "").strip()
        request = dict(payload or {})
        for record in self._records:
            if record.state != "initialized" or record.instance is None:
                continue
            try:
                if hasattr(record.instance, "invoke_capability"):
                    result = record.instance.invoke_capability(capability, request)
                    if result is not None:
                        return result
            except Exception:
                self.logger.exception("Addon capability invoke failed for '%s' on '%s'", capability, record.manifest.id)
        return None

    def export_session_state(self) -> dict[str, Any]:
        session: dict[str, Any] = {}
        for record in self._records:
            if record.state != "initialized" or record.instance is None:
                continue
            try:
                if hasattr(record.instance, "export_session_state"):
                    payload = record.instance.export_session_state() or {}
                    if isinstance(payload, dict):
                        session.update(payload)
            except Exception:
                self.logger.exception("Addon session export failed for '%s'", record.manifest.id)
        return session

    def import_session_state(self, session: dict[str, Any] | None) -> None:
        payload = dict(session or {})
        for record in self._records:
            if record.state != "initialized" or record.instance is None:
                continue
            try:
                if hasattr(record.instance, "import_session_state"):
                    record.instance.import_session_state(payload)
            except Exception:
                self.logger.exception("Addon session import failed for '%s'", record.manifest.id)

    def get_loaded_addons(self) -> list[LoadedAddon]:
        return list(self._records)

    def get_addon_record(self, addon_id: str) -> LoadedAddon | None:
        addon_id = str(addon_id or "").strip()
        if not addon_id:
            return None
        return next((record for record in self._records if record.manifest.id == addon_id), None)

    def get_addon_instance(self, addon_id: str):
        record = self.get_addon_record(addon_id)
        return None if record is None else record.instance

