"""Pure lifecycle state for a preserved Companion Orb vision model."""

from __future__ import annotations

from dataclasses import dataclass
import threading


_RESIDENCY_STATES = frozenset(
    {"disabled", "ensuring", "ready", "degraded", "releasing"}
)


@dataclass(frozen=True, slots=True)
class VisionModelSpec:
    provider_id: str
    endpoint: str
    model_id: str
    handling: str = "parallel_pinned"

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", str(self.provider_id or "").strip())
        object.__setattr__(self, "endpoint", str(self.endpoint or "").strip())
        object.__setattr__(self, "model_id", str(self.model_id or "").strip())
        object.__setattr__(self, "handling", str(self.handling or "").strip())
        if not self.provider_id or not self.endpoint or not self.model_id:
            raise ValueError("Vision model provider, endpoint, and model are required.")


@dataclass(frozen=True, slots=True)
class VisionModelLease:
    generation: int
    spec: VisionModelSpec
    resolved_model_key: str
    identifier: str
    owned: bool


@dataclass(frozen=True, slots=True)
class VisionResidencySnapshot:
    generation: int
    state: str
    spec: VisionModelSpec | None
    lease: VisionModelLease | None
    message: str = ""

    def __post_init__(self) -> None:
        if self.state not in _RESIDENCY_STATES:
            raise ValueError(f"Unknown vision residency state: {self.state}")


class VisionResidencyCoordinator:
    """Serialize settings generations without performing model I/O."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._generation = 0
        self._state = "disabled"
        self._spec: VisionModelSpec | None = None
        self._lease: VisionModelLease | None = None
        self._message = ""

    def require(self, spec: VisionModelSpec) -> int:
        if not isinstance(spec, VisionModelSpec):
            raise TypeError("Vision residency requires VisionModelSpec.")
        with self._lock:
            if self._spec == spec and self._state in {"ensuring", "ready"}:
                return self._generation
            self._generation += 1
            self._state = "ensuring"
            self._spec = spec
            self._lease = None
            self._message = ""
            return self._generation

    def ready(
        self,
        generation: int,
        spec: VisionModelSpec,
        *,
        resolved_model_key: str,
        identifier: str,
        owned: bool,
    ) -> bool:
        clean_key = str(resolved_model_key or "").strip()
        clean_identifier = str(identifier or "").strip()
        if not clean_key or not clean_identifier:
            return False
        with self._lock:
            if (
                int(generation) != self._generation
                or spec != self._spec
                or self._state not in {"ensuring", "degraded"}
            ):
                return False
            self._lease = VisionModelLease(
                generation=self._generation,
                spec=spec,
                resolved_model_key=clean_key,
                identifier=clean_identifier,
                owned=bool(owned),
            )
            self._state = "ready"
            self._message = ""
            return True

    def degraded(self, generation: int, message: str) -> bool:
        with self._lock:
            if (
                int(generation) != self._generation
                or self._state not in {"ensuring", "degraded"}
            ):
                return False
            self._state = "degraded"
            self._message = str(message or "Vision model unavailable.").strip()[:500]
            return True

    def disable(self) -> VisionResidencySnapshot:
        with self._lock:
            self._generation += 1
            self._spec = None
            self._message = ""
            self._state = "releasing" if self._lease is not None else "disabled"
            return self._snapshot_locked()

    def released(self, generation: int) -> bool:
        with self._lock:
            if int(generation) != self._generation or self._state != "releasing":
                return False
            self._lease = None
            self._state = "disabled"
            self._message = ""
            return True

    def snapshot(self) -> VisionResidencySnapshot:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> VisionResidencySnapshot:
        return VisionResidencySnapshot(
            generation=self._generation,
            state=self._state,
            spec=self._spec,
            lease=self._lease,
            message=self._message,
        )
