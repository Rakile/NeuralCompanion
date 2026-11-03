from __future__ import annotations

import copy
import importlib.util
import logging
import json
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .context import AddonContext, AddonEventBus, AddonServiceRegistry
from .manifest import AddonManifest
from core.runtime.addons import (
    AddonCapabilities,
    AddonGateway,
    AddonHostContext,
    AddonPaths,
)
from core.session_document import AddonSessionContribution, canonicalize_session
from core.session_persistence_contract import (
    normalize_addon_session_payload,
    policy_for_key,
)
from core.tts_latency_diagnostics import TtsLatencyDiagnostics


def _copy_session_export_value(value: Any) -> Any:
    """Detach addon-owned session data while thawing read-only mappings."""
    if isinstance(value, Mapping):
        return {
            copy.deepcopy(key): _copy_session_export_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_copy_session_export_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_session_export_value(item) for item in value)
    if isinstance(value, set):
        return {_copy_session_export_value(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_copy_session_export_value(item) for item in value)
    return copy.deepcopy(value)


@dataclass
class LoadedAddon:
    manifest: AddonManifest
    root_dir: Path
    module: ModuleType | None = None
    instance: Any = None
    context: AddonContext | None = None
    host_context: AddonHostContext | None = None
    state: str = "discovered"
    error: str = ""
    shutdown_called: bool = False


class AddonRegistryRecoveryError(RuntimeError):
    """Registry preferences require explicit external recovery before updates."""


class AddonManager:
    # Required Runtime infrastructure is loaded independently of optional addon
    # switches. Access to MCP tools is controlled inside the MCP Runtime page.
    _CORE_RUNTIME_ADDON_IDS = frozenset({"nc.mcp_core"})

    CATEGORY_LABELS = {
        "vision": "Vision",
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
        addon_gateway: AddonGateway | None = None,
    ):
        self.app_root = Path(app_root)
        self.addons_dir = self.app_root / "addons"
        self.storage_root = self.app_root / "runtime" / "addons"
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.storage_root / "addon_registry.json"
        self.logger = logging.getLogger("nc.addons")
        shared_gateway = addon_gateway
        if shared_gateway is None:
            self.event_bus = AddonEventBus()
            self.service_registry = AddonServiceRegistry()
            self.addon_gateway = AddonGateway(
                event_bus=self.event_bus,
                service_registry=self.service_registry,
            )
            self._owns_addon_gateway = True
        else:
            self.addon_gateway = shared_gateway
            self.event_bus = shared_gateway.event_bus
            self.service_registry = shared_gateway.service_registry
            self._owns_addon_gateway = False
        self._llm_snapshot_getter = llm_snapshot_getter
        self._tts_snapshot_getter = tts_snapshot_getter
        self._avatar_snapshot_getter = avatar_snapshot_getter
        self._host_services = dict(host_services or {})
        self._records: list[LoadedAddon] = []
        self._registry_recovery_error = ""
        self._registry_state_known_good = False
        self._registry_file_seen = False
        self._registry_state = self._load_registry_state()
        self._latency_diagnostics: TtsLatencyDiagnostics | None = None
        self._last_session_export_mismatches: tuple[Any, ...] = ()
        self._host_services.setdefault("diagnostics.tts_latency", self.record_latency_event)

    def install_addon_gateway(self, gateway: AddonGateway) -> None:
        if any(record.context is not None for record in self._records):
            raise RuntimeError("Addon gateway must be installed before addon initialization.")
        if gateway is self.addon_gateway:
            self._owns_addon_gateway = False
            return
        previous = self.addon_gateway
        previous_owned = self._owns_addon_gateway
        self.addon_gateway = gateway
        self.event_bus = gateway.event_bus
        self.service_registry = gateway.service_registry
        self._owns_addon_gateway = False
        if previous_owned:
            previous.close()

    def set_identity_relay_runtime_service(self, service: object | None) -> None:
        if any(record.context is not None for record in self._records):
            raise RuntimeError(
                "Identity Relay runtime service must be installed before addon initialization."
            )
        if service is None:
            self._host_services.pop("identity_relay.runtime", None)
        else:
            self._host_services["identity_relay.runtime"] = service

    def _load_registry_state(self) -> dict[str, Any]:
        try:
            try:
                text = self.registry_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                if self._registry_file_seen or self._registry_recovery_error:
                    raise
                payload = {"version": 1, "categories": {}, "addons": {}}
            else:
                self._registry_file_seen = True
                payload = json.loads(text)
            self._validate_registry_state(payload)
        except Exception as exc:
            self._registry_recovery_error = (
                f"Addon registry recovery required for '{self.registry_path}': {exc}. "
                "Registry updates are paused. Restore this file from a known-good copy, "
                'or explicitly reset it to {"version": 1, "categories": {}, "addons": {}}; '
                "then reload addons or restart NeuralCompanion."
            )
            self.logger.error("%s", self._registry_recovery_error)
            return getattr(self, "_registry_state", {"version": 1, "categories": {}, "addons": {}})
        self._registry_recovery_error = ""
        self._registry_state_known_good = True
        return payload

    @staticmethod
    def _validate_registry_state(payload: Any) -> None:
        if not isinstance(payload, dict):
            raise ValueError("registry must be a JSON object")
        version = payload.get("version", 1)
        if type(version) is not int or version != 1:
            raise ValueError("registry version must be the integer 1")
        for field in ("categories", "addons"):
            values = payload.get(field, {})
            if not isinstance(values, dict):
                raise ValueError(f"registry '{field}' must be an object")
            for key, value in values.items():
                if not isinstance(key, str) or type(value) is not bool:
                    raise ValueError(f"registry '{field}.{key}' must have a boolean value")

    def get_addon_registry_recovery_error(self) -> str:
        return self._registry_recovery_error

    def _save_registry_state(self, state: dict[str, Any] | None = None) -> None:
        if self._registry_recovery_error:
            raise AddonRegistryRecoveryError(self._registry_recovery_error)
        # Detect externally damaged/unreadable state before replacing any file.
        self._load_registry_state()
        if self._registry_recovery_error:
            raise AddonRegistryRecoveryError(self._registry_recovery_error)
        state = self._registry_state if state is None else state
        self._validate_registry_state(state)
        payload = {
            "version": 1,
            "categories": dict(state.get("categories", {}) or {}),
            "addons": dict(state.get("addons", {}) or {}),
        }
        serialized = json.dumps(payload, indent=2, ensure_ascii=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.registry_path.parent,
                prefix=f".{self.registry_path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.registry_path)
            self._registry_file_seen = True
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError as exc:
                    self.logger.warning("Failed to remove addon registry temporary file: %s", exc)

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
        if manifest.id in self._CORE_RUNTIME_ADDON_IDS:
            return True
        if self._registry_recovery_error and not self._registry_state_known_good:
            return False
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
                and record.manifest.id not in self._CORE_RUNTIME_ADDON_IDS
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
            if record.manifest.id in self._CORE_RUNTIME_ADDON_IDS:
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
                record.host_context = self.addon_gateway.create_context(
                    addon_id=record.manifest.id,
                    logger=logging.getLogger(f"nc.addon.{record.manifest.id}"),
                    paths=AddonPaths(
                        app_root=self.app_root,
                        addon_root=record.root_dir,
                        storage_root=self.storage_root / record.manifest.id,
                    ),
                    capabilities_factory=lambda owner, manifest=record.manifest: AddonCapabilities.from_host_services(
                        self._host_services,
                        execution_lanes=manifest.execution_lanes,
                        owner_binding=owner,
                    ),
                )
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
                    host=record.host_context,
                )
                if hasattr(record.instance, "initialize"):
                    record.instance.initialize(record.context)
                record.state = "initialized"
                self.logger.info("Initialized addon '%s' v%s", record.manifest.id, record.manifest.version)
            except Exception as exc:
                if record.context is not None:
                    try:
                        record.context.close()
                    except Exception:
                        self.logger.exception(
                            "Addon context cleanup failed after initialization error for '%s'",
                            record.manifest.id,
                        )
                elif record.host_context is not None:
                    try:
                        record.host_context.close()
                    except Exception:
                        self.logger.exception(
                            "Addon host cleanup failed after initialization error for '%s'",
                            record.manifest.id,
                        )
                record.state = "error"
                record.error = str(exc)
                self.logger.warning("Failed to initialize addon '%s': %s", record.manifest.id, exc)
        return list(self._records)

    def unload_all(self) -> None:
        for record in reversed(self._records):
            self._begin_shutdown_record(record)
        for record in reversed(self._records):
            self._shutdown_record(record)
        self.close_latency_diagnostics()

    def shutdown_addon(self, addon_id: str) -> bool:
        record = self.get_addon_record(addon_id)
        if record is None:
            return False
        self._begin_shutdown_record(record)
        self._shutdown_record(record)
        return True

    def _begin_shutdown_record(self, record: LoadedAddon) -> None:
        if record.state == "unloaded" or record.instance is None:
            return
        begin_shutdown = getattr(record.instance, "begin_shutdown", None)
        if not callable(begin_shutdown):
            return
        try:
            begin_shutdown()
        except Exception:
            self.logger.exception(
                "Addon shutdown admission failed for '%s'",
                record.manifest.id,
            )

    def _shutdown_record(self, record: LoadedAddon) -> None:
        if record.state == "unloaded" and record.shutdown_called:
            return
        try:
            if (
                not record.shutdown_called
                and record.instance is not None
                and hasattr(record.instance, "shutdown")
            ):
                record.shutdown_called = True
                record.instance.shutdown()
        except Exception:
            self.logger.exception("Addon shutdown failed for '%s'", record.manifest.id)
        finally:
            if record.context is not None:
                try:
                    record.context.close()
                except Exception:
                    self.logger.exception("Addon context cleanup failed for '%s'", record.manifest.id)
            elif record.host_context is not None:
                try:
                    record.host_context.close()
                except Exception:
                    self.logger.exception("Addon host cleanup failed for '%s'", record.manifest.id)
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
            started_at = time.perf_counter()
            result = None
            error_type = ""
            try:
                if hasattr(record.instance, "invoke_capability"):
                    result = record.instance.invoke_capability(capability, self._capability_payload(request))
                    if result is not None:
                        return result
            except Exception as exc:
                error_type = type(exc).__name__
                self.logger.exception("Addon capability invoke failed for '%s' on '%s'", capability, record.manifest.id)
            finally:
                self._trace_addon_capability(
                    record,
                    capability,
                    started_at=started_at,
                    handled=result is not None,
                    error_type=error_type,
                )
        return None

    def invoke_all_capabilities(self, capability: str, payload: dict[str, Any] | None = None) -> list[Any]:
        """Invoke a capability on every initialized addon and collect results.

        This is useful for addon-owned UI binding phases where there is no
        single selected addon. Addons that do not implement the capability simply
        return ``None`` and are ignored.
        """

        capability = str(capability or "").strip()
        if not capability:
            return []
        request = dict(payload or {})
        results: list[Any] = []
        for record in self._records:
            if record.state != "initialized" or record.instance is None:
                continue
            started_at = time.perf_counter()
            result = None
            error_type = ""
            try:
                if not hasattr(record.instance, "invoke_capability"):
                    continue
                result = record.instance.invoke_capability(capability, self._capability_payload(request))
                if result is not None:
                    results.append(result)
            except Exception as exc:
                error_type = type(exc).__name__
                self.logger.exception("Addon capability invoke failed for '%s' on '%s'", capability, record.manifest.id)
            finally:
                self._trace_addon_capability(
                    record,
                    capability,
                    started_at=started_at,
                    handled=result is not None,
                    error_type=error_type,
                )
        return results

    def _trace_addon_capability(
        self,
        record: LoadedAddon,
        capability: str,
        *,
        started_at: float,
        handled: bool,
        error_type: str = "",
    ) -> None:
        diagnostics = getattr(self, "_latency_diagnostics", None)
        if diagnostics is None:
            return
        diagnostics.record_addon_capability(
            addon_id=str(record.manifest.id or ""),
            capability=str(capability or ""),
            duration_ms=(time.perf_counter() - float(started_at)) * 1000.0,
            handled=bool(handled),
            error_type=str(error_type or ""),
        )

    def flush_latency_diagnostics(self, timeout: float = 1.0) -> bool:
        diagnostics = getattr(self, "_latency_diagnostics", None)
        return True if diagnostics is None else bool(diagnostics.flush(timeout=timeout))

    def latency_diagnostics_enabled(self) -> bool:
        return getattr(self, "_latency_diagnostics", None) is not None

    def set_latency_diagnostics_enabled(self, enabled: bool, timeout: float = 1.0) -> None:
        should_enable = bool(enabled)
        diagnostics = getattr(self, "_latency_diagnostics", None)
        if should_enable:
            if diagnostics is None:
                self._latency_diagnostics = TtsLatencyDiagnostics(self.app_root)
            return
        if diagnostics is not None:
            self._latency_diagnostics = None
            diagnostics.close(timeout=timeout)

    def record_latency_event(self, event: str, **fields: Any) -> None:
        diagnostics = getattr(self, "_latency_diagnostics", None)
        if diagnostics is not None:
            diagnostics.record_event(event, **fields)

    def close_latency_diagnostics(self, timeout: float = 1.0) -> None:
        diagnostics = getattr(self, "_latency_diagnostics", None)
        if diagnostics is not None:
            self._latency_diagnostics = None
            diagnostics.close(timeout=timeout)

    @staticmethod
    def _capability_payload(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return copy.deepcopy(dict(payload or {}))
        except Exception:
            return dict(payload or {})

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
        started_at = time.perf_counter()
        result = None
        error_type = ""
        try:
            result = record.instance.invoke_capability(capability, dict(payload or {}))
            return result
        except Exception as exc:
            error_type = type(exc).__name__
            self.logger.exception("Addon capability invoke failed for '%s' on '%s'", capability, record.manifest.id)
            return None
        finally:
            self._trace_addon_capability(
                record,
                capability,
                started_at=started_at,
                handled=result is not None,
                error_type=error_type,
            )

    def invoke_addon_capability_strict(
        self,
        addon_id: str,
        capability: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Invoke one initialized addon while propagating capability failures."""
        record = self.get_addon_record(addon_id)
        if record is None or record.state != "initialized" or record.instance is None:
            return None
        capability = str(capability or "").strip()
        if not capability or not hasattr(record.instance, "invoke_capability"):
            return None
        return record.instance.invoke_capability(capability, dict(payload or {}))

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
        contributions = self.export_session_contributions()
        policies = self._contribution_policies(contributions)
        result = canonicalize_session({}, {}, contributions, policies)
        for mismatch in self._last_session_export_mismatches:
            self.logger.warning(
                "Addon session namespace mismatch for '%s' at '%s': %s",
                mismatch.addon_id,
                ".".join(mismatch.path),
                mismatch.reason,
            )
        for collision in result.collisions:
            self.logger.warning(
                "Addon session collision at '%s': accepted_owner=%s rejected_owner=%s reason=%s",
                ".".join(collision.path),
                collision.accepted_owner or "",
                collision.rejected_owner,
                collision.reason,
            )
        return result.payload

    def export_session_contributions(self) -> tuple[AddonSessionContribution, ...]:
        manager_payload = {
            "tts_runtime": {
                "diagnostics": {
                    "latency_enabled": self.latency_diagnostics_enabled(),
                }
            },
        }
        # Unknown recovery defaults must never become saved session preferences.
        if self._registry_state_known_good:
            manager_payload["addon_registry_state"] = {
                "version": 1,
                "categories": dict(self._registry_state.get("categories", {}) or {}),
                "addons": dict(self._registry_state.get("addons", {}) or {}),
            }
        core_payload = normalize_addon_session_payload(
            "core.addons.manager",
            manager_payload,
        )
        contributions: list[AddonSessionContribution] = [
            AddonSessionContribution(
                addon_id="core.addons.manager",
                payload=core_payload.payload,
            )
        ]
        mismatches: list[Any] = list(core_payload.mismatches)
        for record in self._records:
            if record.state != "initialized" or record.instance is None:
                continue
            try:
                addon_id = str(record.manifest.id or "").strip()
                payload = self._collect_addon_session_payload(record)
                normalized = normalize_addon_session_payload(addon_id, payload)
                mismatches.extend(normalized.mismatches)
                if isinstance(normalized.payload, Mapping) and normalized.payload:
                    contributions.append(
                        AddonSessionContribution(
                            addon_id=addon_id,
                            payload=copy.deepcopy(dict(normalized.payload)),
                        )
                    )
            except Exception:
                self.logger.exception("Addon session export failed for '%s'", record.manifest.id)
        self._last_session_export_mismatches = tuple(mismatches)
        return tuple(contributions)

    def _collect_addon_session_payload(self, record: LoadedAddon) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        exported = self._call_addon_session_export(record)
        if isinstance(exported, Mapping):
            payload.update(_copy_session_export_value(exported))
        capability_export = self._invoke_session_capability(record, "runtime.session.export")
        if isinstance(capability_export, Mapping):
            payload.update(_copy_session_export_value(capability_export))
        runtime_snapshot = self._runtime_config_snapshot(record)
        collected = self._invoke_session_capability(
            record,
            "runtime.collect_config",
            {"runtime_config": runtime_snapshot},
        )
        if isinstance(collected, Mapping):
            payload.update(_copy_session_export_value(collected))
        manifest_payload = self._manifest_runtime_payload(record, runtime_snapshot)
        if manifest_payload:
            payload.update(manifest_payload)
        return payload

    @staticmethod
    def _call_addon_session_export(record: LoadedAddon) -> Mapping[str, Any] | None:
        exporter = getattr(record.instance, "export_session_state", None)
        if not callable(exporter):
            return None
        payload = exporter() or {}
        return payload if isinstance(payload, Mapping) else None

    @staticmethod
    def _invoke_session_capability(
        record: LoadedAddon,
        capability: str,
        payload: dict[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        callback = getattr(record.instance, "invoke_capability", None)
        if not callable(callback):
            return None
        result = callback(str(capability), dict(payload or {}))
        return result if isinstance(result, Mapping) else None

    @staticmethod
    def _runtime_config_snapshot(record: LoadedAddon) -> dict[str, Any]:
        context = getattr(record, "context", None)
        capabilities = getattr(context, "capabilities", None)
        runtime_config = getattr(capabilities, "runtime_config", None)
        snapshot = getattr(runtime_config, "snapshot", None)
        if callable(snapshot):
            result = snapshot() or {}
            if isinstance(result, Mapping):
                return _copy_session_export_value(result)
        return {}

    def _manifest_runtime_payload(
        self,
        record: LoadedAddon,
        runtime_snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        defaults = self._manifest_runtime_defaults(record)
        if not defaults:
            return {}
        return {
            key: _copy_session_export_value(runtime_snapshot[key])
            for key in defaults
            if key in runtime_snapshot
        }

    def import_session_state(self, session: dict[str, Any] | None) -> None:
        payload = dict(session or {})
        self.set_latency_diagnostics_enabled(bool(payload.get("tts_latency_diagnostics_enabled", False)))
        registry_payload = payload.get("addon_registry_state")
        if isinstance(registry_payload, dict):
            categories = registry_payload.get("categories", {})
            addons = registry_payload.get("addons", {})
            if isinstance(categories, dict) or isinstance(addons, dict):
                registry_state = {
                    "version": int(registry_payload.get("version", 1) or 1),
                    "categories": dict(categories or {}),
                    "addons": dict(addons or {}),
                }
                try:
                    self._save_registry_state(registry_state)
                except Exception:
                    self.logger.exception("Addon registry state save failed during session import")
                else:
                    self._registry_state = registry_state
        for record in self._records:
            if record.state != "initialized" or record.instance is None:
                continue
            try:
                if hasattr(record.instance, "import_session_state"):
                    record.instance.import_session_state(payload)
            except Exception:
                self.logger.exception("Addon session import failed for '%s'", record.manifest.id)

    def _contribution_policies(
        self,
        contributions: tuple[AddonSessionContribution, ...],
    ) -> dict[str, Any]:
        policies: dict[str, Any] = {}
        for contribution in sorted(contributions, key=lambda item: str(item.addon_id or "").strip()):
            for path in self._leaf_paths(contribution.payload):
                for key in self._candidate_policy_keys(path):
                    policy = policy_for_key(key)
                    canonical_path = getattr(policy, "canonical_path", None)
                    if policy is None or canonical_path is None:
                        continue
                    if not self._path_matches(canonical_path, path):
                        continue
                    policies.setdefault(key, policy)
        return policies

    @staticmethod
    def _leaf_paths(
        payload: Mapping[str, Any],
        prefix: tuple[str, ...] = (),
    ) -> tuple[tuple[str, ...], ...]:
        paths: list[tuple[str, ...]] = []
        for key, value in payload.items():
            path = (*prefix, str(key))
            if isinstance(value, Mapping) and value:
                paths.extend(AddonManager._leaf_paths(value, path))
                continue
            paths.append(path)
        return tuple(paths)

    @staticmethod
    def _candidate_policy_keys(path: tuple[str, ...]) -> tuple[str, ...]:
        candidates: set[str] = set()
        if not path:
            return ()
        for index in range(len(path)):
            candidates.add("_".join(path[index:]))
        if len(path) >= 2:
            candidates.add(f"{path[0]}_{path[-1]}")
        return tuple(sorted(candidate for candidate in candidates if candidate))

    @staticmethod
    def _path_matches(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
        if len(pattern) != len(path):
            return False
        for expected, actual in zip(pattern, path):
            if expected.startswith("{") and expected.endswith("}"):
                continue
            if expected != actual:
                return False
        return True

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
        try:
            from core.dependency_repair import addon_requirements_status
        except Exception:
            addon_requirements_status = None
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
            core_runtime = record.manifest.id in self._CORE_RUNTIME_ADDON_IDS
            if core_runtime:
                addon_enabled = True
            requirements_path = record.root_dir / "requirements.txt"
            dependency_status = None
            if requirements_path.exists() and callable(addon_requirements_status):
                try:
                    dependency_status = addon_requirements_status(
                        addon_id=record.manifest.id,
                        label=record.manifest.name,
                        requirements_path=requirements_path,
                    )
                except Exception as exc:
                    dependency_status = {
                        "id": record.manifest.id,
                        "kind": "addon",
                        "label": record.manifest.name,
                        "requirements_path": str(requirements_path),
                        "status": "error",
                        "needs_install": False,
                        "installable": False,
                        "message": f"Could not inspect addon requirements: {exc}",
                    }
            group["addons"].append(
                {
                    "id": record.manifest.id,
                    "name": record.manifest.name,
                    "description": record.manifest.description,
                    "category": category,
                    "manifest_enabled": bool(record.manifest.enabled),
                    "enabled": bool(addon_enabled),
                    "core_runtime": core_runtime,
                    "effective_enabled": bool(self._manifest_effectively_enabled(record.manifest)),
                    "state": str(record.state or ""),
                    "permissions": list(record.manifest.permissions or []),
                    "services": [dict(item) for item in list(getattr(record.manifest, "services", []) or []) if isinstance(item, dict)],
                    "ui": [dict(item) for item in list(getattr(record.manifest, "ui", []) or []) if isinstance(item, dict)],
                    "version": str(record.manifest.version or ""),
                    "root_dir": str(record.root_dir),
                    "runtime_defaults": self._manifest_runtime_defaults(record),
                    "dependency_status": dependency_status,
                }
            )
        ordered = sorted(categories.values(), key=lambda item: item["label"].lower())
        for item in ordered:
            item["addons"] = sorted(item["addons"], key=lambda addon: addon["name"].lower())
        return ordered

    @staticmethod
    def _manifest_runtime_defaults(record: LoadedAddon) -> dict[str, Any]:
        manifest_path = getattr(record.manifest, "manifest_path", None)
        if manifest_path is None:
            return {}
        try:
            payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        defaults = payload.get("runtime_defaults", {})
        return dict(defaults) if isinstance(defaults, dict) else {}

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

    def get_ui_disabled_surface_specs(self) -> list[dict[str, str]]:
        specs: list[dict[str, str]] = []
        for record in self._records:
            addon_id = str(record.manifest.id or "").strip()
            for entry in list(getattr(record.manifest, "ui", []) or []):
                if not isinstance(entry, dict):
                    continue
                metadata = dict(entry.get("metadata") or {})
                raw_surfaces = metadata.get("disabled_surfaces") or entry.get("disabled_surfaces") or []
                if isinstance(raw_surfaces, dict):
                    raw_surfaces = [raw_surfaces]
                for surface in list(raw_surfaces or []):
                    if not isinstance(surface, dict):
                        continue
                    dock_name = str(surface.get("dock_name") or surface.get("dock") or "").strip()
                    button_name = str(surface.get("button_name") or surface.get("button") or "").strip()
                    action_name = str(surface.get("action_name") or surface.get("action") or "").strip()
                    if not dock_name and not button_name and not action_name:
                        continue
                    specs.append(
                        {
                            "addon_id": addon_id,
                            "dock_name": dock_name,
                            "button_name": button_name,
                            "action_name": action_name,
                            "session_visible_key": str(surface.get("session_visible_key") or "").strip(),
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
        registry_state = dict(self._registry_state)
        registry_state["categories"] = dict(registry_state.get("categories", {}) or {})
        registry_state["categories"][category] = bool(enabled)
        self._save_registry_state(registry_state)
        self._registry_state = registry_state
        return bool(enabled)

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> bool:
        addon_id = str(addon_id or "").strip()
        if not addon_id:
            return False
        if addon_id in self._CORE_RUNTIME_ADDON_IDS:
            if not enabled:
                raise ValueError("This core runtime addon is always loaded; use its Runtime access switch.")
            return True
        registry_state = dict(self._registry_state)
        registry_state["addons"] = dict(registry_state.get("addons", {}) or {})
        registry_state["addons"][addon_id] = bool(enabled)
        self._save_registry_state(registry_state)
        self._registry_state = registry_state
        return bool(enabled)

    def has_pending_restart_changes(self) -> bool:
        summary = self._addon_change_summary()
        return bool(summary.get("total_changes", 0))

    def get_pending_restart_changes_summary(self) -> dict[str, int]:
        return self._addon_change_summary()
