from __future__ import annotations

import threading
import math
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal, Mapping

from addons.identity_artifacts.storage import ArtifactResolution


RelayState = Literal["active", "suspended", "unavailable"]
RelayAvailability = Literal["none", "available", "unavailable"]


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise TypeError("Identity Relay capture context must be JSON-like")
            return MappingProxyType({key: freeze(entry) for key, entry in item.items()})
        if isinstance(item, (list, tuple)):
            return tuple(freeze(entry) for entry in item)
        if isinstance(item, Enum):
            return freeze(item.value)
        if is_dataclass(item) and not isinstance(item, type):
            return MappingProxyType(
                {entry.name: freeze(getattr(item, entry.name)) for entry in fields(item)}
            )
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float) and math.isfinite(item):
            return item
        raise TypeError("Identity Relay capture context must be JSON-like")

    if not isinstance(value, Mapping):
        raise TypeError("Identity Relay capture context must be JSON-like")
    return freeze(value)


@dataclass(frozen=True, slots=True)
class IdentityRelayModeSnapshot:
    connected: bool
    enabled: bool
    artifact_ref: str = ""
    artifact_hash: str = ""
    connection_revision: int = 0


@dataclass(frozen=True, slots=True)
class IdentityRelayCapture:
    enabled: bool
    artifact_ref: str
    artifact_hash: str
    connection_revision: int = 0
    normalizer_revision: str = ""
    normalized_digest: str = ""
    attestation_revision: int = 0
    transient_activation: Mapping[str, Any] = field(default_factory=dict)
    runtime_use: Mapping[str, Any] = field(default_factory=dict)
    frozen_provider: Mapping[str, Any] = field(default_factory=dict)
    frozen_normalized_model: Mapping[str, Any] = field(default_factory=dict)
    frozen_model_digest: str = ""

    def __post_init__(self) -> None:
        if not self.enabled:
            object.__setattr__(self, "normalizer_revision", "")
            object.__setattr__(self, "normalized_digest", "")
            object.__setattr__(self, "attestation_revision", 0)
            object.__setattr__(self, "transient_activation", MappingProxyType({}))
            object.__setattr__(self, "runtime_use", MappingProxyType({}))
            object.__setattr__(self, "frozen_provider", MappingProxyType({}))
            object.__setattr__(self, "frozen_normalized_model", MappingProxyType({}))
            object.__setattr__(self, "frozen_model_digest", "")
            return
        object.__setattr__(self, "transient_activation", _freeze_mapping(self.transient_activation))
        object.__setattr__(self, "runtime_use", _freeze_mapping(self.runtime_use))
        object.__setattr__(self, "frozen_provider", _freeze_mapping(self.frozen_provider))
        object.__setattr__(
            self,
            "frozen_normalized_model",
            _freeze_mapping(self.frozen_normalized_model),
        )


@dataclass(frozen=True, slots=True)
class IdentityRelaySnapshot:
    state: RelayState
    artifact_ref: str
    artifact_hash: str | None
    hot_identity_text: str
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class IdentityRelayUiSnapshot:
    revision: int
    options: tuple[tuple[str, str], ...]
    connected_ref: str
    availability: RelayAvailability
    enabled: bool
    warning: str


class IdentityRelayModel:
    def __init__(self):
        self._lock = threading.RLock()
        self._resolution: ArtifactResolution | None = None
        self._enabled = True
        self._options: tuple[tuple[str, str], ...] = ()
        self._revision = 0
        self._connection_revision = 0
        self._normalizer_revision = ""
        self._normalized_digest = ""
        self._attestation_revision = 0
        self._transient_activation: Mapping[str, Any] = MappingProxyType({})
        self._runtime_use: Mapping[str, Any] = MappingProxyType({})
        self._frozen_provider: Mapping[str, Any] = MappingProxyType({})
        self._frozen_normalized_model: Mapping[str, Any] = MappingProxyType({})
        self._frozen_model_digest = ""

    def set_connection(self, resolution: ArtifactResolution | None) -> None:
        with self._lock:
            previous_ref = self._resolution.artifact_ref if self._resolution else ""
            next_ref = resolution.artifact_ref if resolution else ""
            self._resolution = resolution
            if next_ref != previous_ref:
                self._enabled = True
                self._clear_capture_context_locked()
            self._connection_revision += 1
            self._revision += 1

    def set_connection_with_context(
        self,
        resolution: ArtifactResolution | None,
        *,
        normalizer_revision: str = "",
        normalized_digest: str = "",
        attestation_revision: int = 0,
        transient_activation: Mapping[str, Any] | None = None,
        runtime_use: Mapping[str, Any] | None = None,
        frozen_normalized_model: Mapping[str, Any] | None = None,
        frozen_model_digest: str = "",
    ) -> None:
        with self._lock:
            previous_ref = self._resolution.artifact_ref if self._resolution else ""
            next_ref = resolution.artifact_ref if resolution else ""
            self._resolution = resolution
            if next_ref != previous_ref:
                self._enabled = True
            self._set_capture_context_locked(
                normalizer_revision=normalizer_revision,
                normalized_digest=normalized_digest,
                attestation_revision=attestation_revision,
                transient_activation=transient_activation or {},
                runtime_use=runtime_use or {},
                frozen_provider={},
                frozen_normalized_model=frozen_normalized_model or {},
                frozen_model_digest=frozen_model_digest,
            )
            self._connection_revision += 1
            self._revision += 1

    def clear_capture_context(self) -> None:
        with self._lock:
            self._clear_capture_context_locked()
            self._connection_revision += 1
            self._revision += 1

    def set_capture_context(
        self,
        *,
        normalizer_revision: str,
        normalized_digest: str = "",
        attestation_revision: int,
        transient_activation: Mapping[str, Any],
        runtime_use: Mapping[str, Any],
        frozen_provider: Mapping[str, Any],
        frozen_normalized_model: Mapping[str, Any] | None = None,
        frozen_model_digest: str = "",
    ) -> None:
        with self._lock:
            self._set_capture_context_locked(
                normalizer_revision=normalizer_revision,
                normalized_digest=normalized_digest,
                attestation_revision=attestation_revision,
                transient_activation=transient_activation,
                runtime_use=runtime_use,
                frozen_provider=frozen_provider,
                frozen_normalized_model=frozen_normalized_model or {},
                frozen_model_digest=frozen_model_digest,
            )
            self._connection_revision += 1
            self._revision += 1

    def capture_turn_with_context(
        self,
        *,
        normalizer_revision: str,
        normalized_digest: str = "",
        attestation_revision: int,
        transient_activation: Mapping[str, Any],
        runtime_use: Mapping[str, Any],
        frozen_provider: Mapping[str, Any],
        frozen_normalized_model: Mapping[str, Any] | None = None,
        frozen_model_digest: str = "",
    ) -> IdentityRelayCapture | None:
        with self._lock:
            if self._resolution is None or not self._enabled:
                return self._capture_turn_locked()
            self._set_capture_context_locked(
                normalizer_revision=normalizer_revision,
                normalized_digest=normalized_digest,
                attestation_revision=attestation_revision,
                transient_activation=transient_activation,
                runtime_use=runtime_use,
                frozen_provider=frozen_provider,
                frozen_normalized_model=frozen_normalized_model or {},
                frozen_model_digest=frozen_model_digest,
            )
            self._connection_revision += 1
            self._revision += 1
            return self._capture_turn_locked()

    def connection_marker(self) -> tuple[str, int]:
        with self._lock:
            connected_ref = self._resolution.artifact_ref if self._resolution else ""
            return connected_ref, self._connection_revision

    def set_enabled(self, enabled: bool) -> bool:
        with self._lock:
            if not self._is_available(self._resolution):
                return False
            self._enabled = bool(enabled)
            self._revision += 1
            return True

    def restore_enabled(self, artifact_ref: str, enabled: bool) -> bool:
        with self._lock:
            connected_ref = self._resolution.artifact_ref if self._resolution else ""
            if not connected_ref or str(artifact_ref or "") != connected_ref:
                return False
            self._enabled = bool(enabled)
            self._revision += 1
            return True

    def set_options(self, options: tuple[tuple[str, str], ...]) -> None:
        copied = tuple((str(label), str(artifact_ref)) for label, artifact_ref in options)
        with self._lock:
            if copied == self._options:
                return
            self._options = copied
            self._revision += 1

    def snapshot_for_turn(self) -> IdentityRelaySnapshot | None:
        with self._lock:
            resolution = self._resolution
            if resolution is None:
                return None
            failure_code = self._failure_code(resolution)
            if failure_code:
                return IdentityRelaySnapshot(
                    "unavailable",
                    resolution.artifact_ref,
                    resolution.artifact_hash,
                    "",
                    failure_code,
                )
            state: RelayState = "active" if self._enabled else "suspended"
            text = resolution.hot_identity_text if state == "active" else ""
            return IdentityRelaySnapshot(
                state,
                resolution.artifact_ref,
                resolution.artifact_hash,
                text,
                None,
            )

    def capture_mode(self) -> IdentityRelayModeSnapshot:
        with self._lock:
            resolution = self._resolution
            return IdentityRelayModeSnapshot(
                connected=resolution is not None,
                enabled=bool(resolution is not None and self._enabled),
                artifact_ref=resolution.artifact_ref if resolution is not None else "",
                artifact_hash=(
                    str(resolution.artifact_hash or "")
                    if resolution is not None
                    else ""
                ),
                connection_revision=self._connection_revision,
            )

    def capture_turn(
        self,
        *,
        frozen_provider: Mapping[str, Any] | None = None,
        mode_snapshot: IdentityRelayModeSnapshot | None = None,
    ) -> IdentityRelayCapture | None:
        with self._lock:
            if mode_snapshot is not None:
                if not isinstance(mode_snapshot, IdentityRelayModeSnapshot):
                    raise TypeError("mode_snapshot must be an IdentityRelayModeSnapshot")
                if not mode_snapshot.connected:
                    return None
                if not mode_snapshot.enabled:
                    return IdentityRelayCapture(
                        enabled=False,
                        artifact_ref=mode_snapshot.artifact_ref,
                        artifact_hash=mode_snapshot.artifact_hash,
                        connection_revision=mode_snapshot.connection_revision,
                    )
                resolution = self._resolution
                if (
                    resolution is None
                    or not self._enabled
                    or mode_snapshot.connection_revision != self._connection_revision
                    or mode_snapshot.artifact_ref != resolution.artifact_ref
                    or mode_snapshot.artifact_hash
                    != str(resolution.artifact_hash or "")
                ):
                    raise RuntimeError(
                        "Identity Relay mode changed after turn acceptance."
                    )
            if self._resolution is None or not self._enabled:
                return self._capture_turn_locked()
            copied_frozen_provider = (
                self._frozen_provider
                if frozen_provider is None
                else _freeze_mapping(frozen_provider)
            )
            turn_runtime_use = (
                None
                if frozen_provider is None
                else self._turn_runtime_use(copied_frozen_provider)
            )
            return self._capture_turn_locked(copied_frozen_provider, turn_runtime_use)

    @classmethod
    def enrich_capture(
        cls,
        capture: IdentityRelayCapture,
        *,
        frozen_provider: Mapping[str, Any],
        owner_override: bool = False,
    ) -> IdentityRelayCapture:
        if not isinstance(capture, IdentityRelayCapture):
            raise TypeError("capture must be an IdentityRelayCapture")
        if not capture.enabled:
            return capture
        copied_provider = _freeze_mapping(frozen_provider)
        runtime_use = dict(capture.runtime_use)
        runtime_use.update(cls._turn_runtime_use(copied_provider))
        runtime_use["owner_override"] = owner_override is True
        return replace(
            capture,
            runtime_use=runtime_use,
            frozen_provider=copied_provider,
        )

    def _clear_capture_context_locked(self) -> None:
        self._normalizer_revision = ""
        self._normalized_digest = ""
        self._attestation_revision = 0
        self._transient_activation = MappingProxyType({})
        self._runtime_use = MappingProxyType({})
        self._frozen_provider = MappingProxyType({})
        self._frozen_normalized_model = MappingProxyType({})
        self._frozen_model_digest = ""

    def _set_capture_context_locked(
        self,
        *,
        normalizer_revision: str,
        normalized_digest: str,
        attestation_revision: int,
        transient_activation: Mapping[str, Any],
        runtime_use: Mapping[str, Any],
        frozen_provider: Mapping[str, Any],
        frozen_normalized_model: Mapping[str, Any],
        frozen_model_digest: str,
    ) -> None:
        copied_normalizer_revision = str(normalizer_revision or "")
        copied_normalized_digest = str(normalized_digest or "")
        copied_attestation_revision = max(int(attestation_revision), 0)
        copied_transient_activation = _freeze_mapping(transient_activation)
        copied_runtime_use = _freeze_mapping(runtime_use)
        copied_frozen_provider = _freeze_mapping(frozen_provider)
        copied_frozen_normalized_model = _freeze_mapping(frozen_normalized_model)
        copied_frozen_model_digest = str(frozen_model_digest or "")
        self._normalizer_revision = copied_normalizer_revision
        self._normalized_digest = copied_normalized_digest
        self._attestation_revision = copied_attestation_revision
        self._transient_activation = copied_transient_activation
        self._runtime_use = copied_runtime_use
        self._frozen_provider = copied_frozen_provider
        self._frozen_normalized_model = copied_frozen_normalized_model
        self._frozen_model_digest = copied_frozen_model_digest

    def _capture_turn_locked(
        self,
        frozen_provider: Mapping[str, Any] | None = None,
        turn_runtime_use: Mapping[str, Any] | None = None,
    ) -> IdentityRelayCapture | None:
        resolution = self._resolution
        if resolution is None:
            return None
        if not self._enabled:
            return IdentityRelayCapture(
                enabled=False,
                artifact_ref=resolution.artifact_ref,
                artifact_hash=str(resolution.artifact_hash or ""),
                connection_revision=self._connection_revision,
            )
        provider = self._frozen_provider if frozen_provider is None else frozen_provider
        runtime_use = dict(self._runtime_use)
        if turn_runtime_use is not None:
            runtime_use.update(turn_runtime_use)
        return IdentityRelayCapture(
            enabled=self._enabled,
            artifact_ref=resolution.artifact_ref,
            artifact_hash=str(resolution.artifact_hash or ""),
            connection_revision=self._connection_revision,
            normalizer_revision=self._normalizer_revision,
            normalized_digest=self._normalized_digest,
            attestation_revision=self._attestation_revision,
            transient_activation=self._transient_activation,
            runtime_use=runtime_use,
            frozen_provider=provider,
            frozen_normalized_model=self._frozen_normalized_model,
            frozen_model_digest=self._frozen_model_digest,
        )

    @staticmethod
    def _turn_runtime_use(frozen_provider: Mapping[str, Any]) -> Mapping[str, Any]:
        provider_config = frozen_provider.get("provider_config")
        locality = (
            provider_config.get("provider_is_remote")
            if isinstance(provider_config, Mapping)
            else frozen_provider.get("provider_is_remote")
        )
        return {
            "surface": "local_private_chat",
            "provider_is_remote": locality if type(locality) is bool else None,
            "requested_use": str(frozen_provider.get("requested_use") or ""),
            "transient": bool(frozen_provider.get("transient", False)),
        }

    def ui_snapshot(self) -> IdentityRelayUiSnapshot:
        with self._lock:
            resolution = self._resolution
            connected_ref = resolution.artifact_ref if resolution else ""
            failure_code = self._failure_code(resolution)
            if resolution is None:
                availability: RelayAvailability = "none"
            elif failure_code:
                availability = "unavailable"
            else:
                availability = "available"
            options = self._options
            if connected_ref and not any(ref == connected_ref for _label, ref in options):
                options = options + (("Unavailable Identity", connected_ref),)
            return IdentityRelayUiSnapshot(
                revision=self._revision,
                options=tuple(options),
                connected_ref=connected_ref,
                availability=availability,
                enabled=self._enabled,
                warning=self._warning_for(failure_code),
            )

    @staticmethod
    def _failure_code(resolution: ArtifactResolution | None) -> str | None:
        if resolution is None:
            return None
        if resolution.failure_code:
            return resolution.failure_code
        return None

    @classmethod
    def _is_available(cls, resolution: ArtifactResolution | None) -> bool:
        return resolution is not None and cls._failure_code(resolution) is None

    @staticmethod
    def _warning_for(failure_code: str | None) -> str:
        warnings = {
            "missing": "Identity file is missing.",
            "unreadable": "Identity file could not be read.",
            "corrupt": "Identity file failed its integrity check.",
            "invalid": "Identity reference is invalid.",
            "empty_normalized_identity": "Identity artifact has no usable normalized continuity.",
        }
        return warnings.get(str(failure_code or ""), "")
