from __future__ import annotations

import importlib.util
import logging
import json
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
    CATEGORY_LABELS = {
        "vision": "Vision",
        "musetalk": "MuseTalk",
        "visuals": "Visuals",
        "chat": "Chat",
        "avatar": "Avatar",
        "global": "Global",
        "other": "Other",
    }

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
        self.registry_path = self.storage_root / "addon_registry.json"
        self.logger = logging.getLogger("nc.addons")
        self.event_bus = AddonEventBus()
        self.service_registry = AddonServiceRegistry()
        self._llm_snapshot_getter = llm_snapshot_getter
        self._tts_snapshot_getter = tts_snapshot_getter
        self._avatar_snapshot_getter = avatar_snapshot_getter
        self._host_services = dict(host_services or {})
        self._records: list[LoadedAddon] = []
        self._registry_state = self._load_registry_state()

    def _load_registry_state(self) -> dict[str, Any]:
        try:
            if self.registry_path.exists():
                payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
        except Exception as exc:
            self.logger.warning("Failed to read addon registry state: %s", exc)
        return {"version": 1, "categories": {}, "addons": {}}

    def _save_registry_state(self) -> None:
        payload = {
            "version": 1,
            "categories": dict(self._registry_state.get("categories", {}) or {}),
            "addons": dict(self._registry_state.get("addons", {}) or {}),
        }
        self.registry_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    def _normalize_category(self, value: str | None) -> str:
        category = str(value or "").strip().lower()
        if category:
            return category
        return "other"

    def _category_for_manifest(self, manifest: AddonManifest) -> str:
        return self._normalize_category(getattr(manifest, "category", "") or "")

    def _category_enabled(self, category: str) -> bool:
        normalized = self._normalize_category(category)
        override = dict(self._registry_state.get("categories", {}) or {}).get(normalized)
        if override is None:
            return True
        return bool(override)

    def _addon_enabled_override(self, addon_id: str) -> bool | None:
        addon_id = str(addon_id or "").strip()
        if not addon_id:
            return None
        raw = dict(self._registry_state.get("addons", {}) or {}).get(addon_id)
        if raw is None:
            return None
        return bool(raw)

    def _manifest_effectively_enabled(self, manifest: AddonManifest) -> bool:
        category = self._category_for_manifest(manifest)
        category_enabled = self._category_enabled(category)
        addon_override = self._addon_enabled_override(manifest.id)
        addon_enabled = manifest.enabled if addon_override is None else bool(addon_override)
        return bool(category_enabled and addon_enabled)

    def is_addon_effectively_enabled(self, addon_id: str) -> bool:
        target = str(addon_id or "").strip()
        if not target:
            return True
        for record in self._records:
            if str(record.manifest.id or "").strip() == target:
                return bool(self._manifest_effectively_enabled(record.manifest))
        return False

    def _addon_change_summary(self) -> dict[str, int]:
        category_changes = 0
        addon_changes = 0
        category_pending: set[str] = set()
        for category, value in dict(self._registry_state.get("categories", {}) or {}).items():
            category = self._normalize_category(category)
            if not category or bool(value) is not False:
                continue
            active_in_category = any(
                self._category_for_manifest(record.manifest) == category
                and record.state in {"loaded", "initialized"}
                for record in self._records
            )
            if active_in_category:
                category_pending.add(category)
                category_changes += 1
        for addon_id, value in dict(self._registry_state.get("addons", {}) or {}).items():
            addon_id = str(addon_id or "").strip()
            if not addon_id:
                continue
            record = None
            for record in self._records:
                if record.manifest.id == addon_id:
                    break
            else:
                record = None
            if record is None:
                continue
            if self._category_for_manifest(record.manifest) in category_pending:
                continue
            desired_enabled = self._manifest_effectively_enabled(record.manifest)
            currently_active = record.state in {"loaded", "initialized"}
            if bool(desired_enabled) != bool(currently_active):
                addon_changes += 1
        return {
            "category_changes": int(category_changes),
            "addon_changes": int(addon_changes),
            "total_changes": int(category_changes + addon_changes),
        }

    def discover(self) -> list[LoadedAddon]:
        self._records = []
        self._registry_state = self._load_registry_state()
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
                if manifest.id in seen_ids:
                    raise ValueError(f"Duplicate addon id '{manifest.id}'")
                seen_ids.add(manifest.id)
                record = LoadedAddon(manifest=manifest, root_dir=child)
                if self._manifest_effectively_enabled(manifest):
                    record.state = "discovered"
                else:
                    record.state = "disabled"
                    record.error = "Disabled in addon registry"
                    self.logger.info("Skipping disabled addon: %s", manifest.id)
                self._records.append(record)
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
            if record.state == "disabled":
                continue
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
        from .contributions import normalize_ui_area

        target_area = normalize_ui_area(area)
        contributions = []
        for record in self._records:
            if record.state != "initialized" or record.context is None:
                continue
            for contribution in record.context.ui.get_tab_contributions():
                if normalize_ui_area(contribution.area) == target_area:
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

    def invoke_addon_capability(self, addon_id: str, capability: str, payload: dict[str, Any] | None = None) -> Any:
        """Invoke a capability on one initialized addon.

        This is the host-side escape hatch that keeps backend code from importing
        addon modules just to ask addon-owned questions such as runtime budget or
        config collection.
        """
        record = self.get_addon_record(addon_id)
        if record is None or record.state != "initialized" or record.instance is None:
            return None
        capability = str(capability or "").strip()
        if not capability or not hasattr(record.instance, "invoke_capability"):
            return None
        try:
            return record.instance.invoke_capability(capability, dict(payload or {}))
        except Exception:
            self.logger.exception("Addon capability invoke failed for '%s' on '%s'", capability, record.manifest.id)
            return None

    def get_addon_id_for_service(self, service_id: str, **metadata_match: Any) -> str:
        """Return the addon that declares a manifest service matching metadata.

        Example: service_id='avatar_provider_registry', provider_id='musetalk'.
        """
        wanted_service = str(service_id or "").strip()
        if not wanted_service:
            return ""
        normalized_match = {
            str(key): str(value or "").strip().lower()
            for key, value in dict(metadata_match or {}).items()
            if str(key).strip()
        }
        for record in self._records:
            if record.state != "initialized":
                continue
            for service in list(getattr(record.manifest, "services", []) or []):
                if not isinstance(service, dict):
                    continue
                if str(service.get("id") or "").strip() != wanted_service:
                    continue
                matched = True
                for key, value in normalized_match.items():
                    if str(service.get(key) or "").strip().lower() != value:
                        matched = False
                        break
                if matched:
                    return str(record.manifest.id or "").strip()
        return ""

    def invoke_service_capability(
        self,
        service_id: str,
        capability: str,
        payload: dict[str, Any] | None = None,
        **metadata_match: Any,
    ) -> Any:
        addon_id = self.get_addon_id_for_service(service_id, **metadata_match)
        if not addon_id:
            return None
        return self.invoke_addon_capability(addon_id, capability, payload)

    def export_session_state(self) -> dict[str, Any]:
        session: dict[str, Any] = {}
        session["addon_registry_state"] = {
            "version": 1,
            "categories": dict(self._registry_state.get("categories", {}) or {}),
            "addons": dict(self._registry_state.get("addons", {}) or {}),
        }
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
        registry_payload = payload.get("addon_registry_state")
        if isinstance(registry_payload, dict):
            categories = registry_payload.get("categories", {})
            addons = registry_payload.get("addons", {})
            if isinstance(categories, dict) or isinstance(addons, dict):
                self._registry_state = {
                    "version": int(registry_payload.get("version", 1) or 1),
                    "categories": dict(categories or {}),
                    "addons": dict(addons or {}),
                }
                try:
                    self._save_registry_state()
                except Exception:
                    self.logger.exception("Addon registry state save failed during session import")
        for record in self._records:
            if record.state != "initialized" or record.instance is None:
                continue
            try:
                if hasattr(record.instance, "import_session_state"):
                    record.instance.import_session_state(payload)
            except Exception:
                self.logger.exception("Addon session import failed for '%s'", record.manifest.id)

    def export_preset_state(self) -> dict[str, Any]:
        preset: dict[str, Any] = {}
        for record in self._records:
            if record.state != "initialized" or record.instance is None:
                continue
            try:
                if hasattr(record.instance, "export_preset_state"):
                    payload = record.instance.export_preset_state() or {}
                    if isinstance(payload, dict):
                        preset.update(payload)
            except Exception:
                self.logger.exception("Addon preset export failed for '%s'", record.manifest.id)
        return preset

    def import_preset_state(self, preset: dict[str, Any] | None) -> None:
        payload = dict(preset or {})
        for record in self._records:
            if record.state != "initialized" or record.instance is None:
                continue
            try:
                if hasattr(record.instance, "import_preset_state"):
                    record.instance.import_preset_state(payload)
            except Exception:
                self.logger.exception("Addon preset import failed for '%s'", record.manifest.id)
        return None

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

    def get_addon_registry_snapshot(self) -> list[dict[str, Any]]:
        categories: dict[str, dict[str, Any]] = {}
        for record in self._records:
            category = self._category_for_manifest(record.manifest)
            group = categories.setdefault(
                category,
                {
                    "id": category,
                    "label": self.CATEGORY_LABELS.get(category, category.replace("_", " ").title()),
                    "enabled": self._category_enabled(category),
                    "addons": [],
                },
            )
            addon_override = self._addon_enabled_override(record.manifest.id)
            addon_enabled = record.manifest.enabled if addon_override is None else bool(addon_override)
            group["addons"].append(
                {
                    "id": record.manifest.id,
                    "name": record.manifest.name,
                    "description": record.manifest.description,
                    "category": category,
                    "manifest_enabled": bool(record.manifest.enabled),
                    "enabled": bool(addon_enabled),
                    "effective_enabled": bool(self._manifest_effectively_enabled(record.manifest)),
                    "state": str(record.state or ""),
                    "permissions": list(record.manifest.permissions or []),
                    "services": [dict(item) for item in list(getattr(record.manifest, "services", []) or []) if isinstance(item, dict)],
                    "ui": [dict(item) for item in list(getattr(record.manifest, "ui", []) or []) if isinstance(item, dict)],
                    "version": str(record.manifest.version or ""),
                }
            )
        ordered = sorted(categories.values(), key=lambda item: item["label"].lower())
        for item in ordered:
            item["addons"] = sorted(item["addons"], key=lambda addon: addon["name"].lower())
        return ordered

    def get_ui_placeholder_specs(self) -> list[dict[str, str]]:
        from .contributions import ui_target_for_area

        specs: list[dict[str, str]] = []
        for record in self._records:
            addon_id = str(record.manifest.id or "").strip()
            for entry in list(getattr(record.manifest, "ui", []) or []):
                if not isinstance(entry, dict):
                    continue
                placeholder = str(entry.get("placeholder") or "").strip()
                if not placeholder:
                    continue
                target = str(entry.get("target") or entry.get("mount_target") or "").strip()
                if not target:
                    target = ui_target_for_area(entry.get("area"))
                if not target:
                    continue
                specs.append(
                    {
                        "addon_id": addon_id,
                        "target": target,
                        "placeholder": placeholder,
                        "title": str(entry.get("title") or record.manifest.name or addon_id).strip(),
                    }
                )
        return specs

    def get_addon_id_for_ui_role(self, role: str) -> str:
        wanted = str(role or "").strip().lower()
        if not wanted:
            return ""
        for record in self._records:
            for entry in list(getattr(record.manifest, "ui", []) or []):
                if not isinstance(entry, dict):
                    continue
                metadata = dict(entry.get("metadata") or {})
                if str(metadata.get("runtime_role") or "").strip().lower() == wanted:
                    return str(record.manifest.id or "").strip()
        return ""

    def set_category_enabled(self, category: str, enabled: bool) -> bool:
        category = self._normalize_category(category)
        self._registry_state.setdefault("categories", {})[category] = bool(enabled)
        self._save_registry_state()
        return bool(enabled)

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> bool:
        addon_id = str(addon_id or "").strip()
        if not addon_id:
            return False
        self._registry_state.setdefault("addons", {})[addon_id] = bool(enabled)
        self._save_registry_state()
        return bool(enabled)

    def has_pending_restart_changes(self) -> bool:
        summary = self._addon_change_summary()
        return bool(summary.get("total_changes", 0))

    def get_pending_restart_changes_summary(self) -> dict[str, int]:
        return self._addon_change_summary()
