"""Pure admission policy for bounded Companion Orb vision inference."""

from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True, slots=True)
class VisionInferenceRequest:
    key: object
    endpoint: str
    generation: int
    priority: int
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", str(self.endpoint or "").strip())
        object.__setattr__(self, "generation", int(self.generation))
        object.__setattr__(self, "priority", int(self.priority))
        object.__setattr__(self, "reason", str(self.reason or "").strip()[:120])


@dataclass(frozen=True, slots=True)
class VisionInferenceAdmission:
    action: str
    request: VisionInferenceRequest
    token: threading.Event
    generation: int
    message: str = ""


@dataclass(slots=True)
class _InferenceEntry:
    request: VisionInferenceRequest
    token: threading.Event


def _endpoint_key(endpoint: str) -> str:
    return str(endpoint or "").strip().rstrip("/").lower()


class VisionInferenceCoordinator:
    """Allow one request per endpoint and coalesce the bounded pending slot."""

    def __init__(self, *, generation: int = 0) -> None:
        self._lock = threading.RLock()
        self._generation = int(generation)
        self._active: dict[str, _InferenceEntry] = {}
        self._pending: dict[str, _InferenceEntry] = {}

    def admit(self, request: VisionInferenceRequest) -> VisionInferenceAdmission:
        if not isinstance(request, VisionInferenceRequest):
            raise TypeError("Vision inference requires VisionInferenceRequest.")
        endpoint = _endpoint_key(request.endpoint)
        token = threading.Event()
        with self._lock:
            if not endpoint or request.generation != self._generation:
                token.set()
                return VisionInferenceAdmission(
                    "rejected",
                    request,
                    token,
                    self._generation,
                    "stale generation or missing endpoint",
                )
            active = self._active.get(endpoint)
            if active is None:
                entry = _InferenceEntry(request, token)
                self._active[endpoint] = entry
                return VisionInferenceAdmission(
                    "start", request, token, self._generation
                )
            if active.request.key == request.key:
                return VisionInferenceAdmission(
                    "join", active.request, active.token, self._generation
                )

            if (
                active.request.reason in {"scan", "continuous_scan"}
                and request.priority > active.request.priority
            ):
                active.token.set()

            pending = self._pending.get(endpoint)
            if pending is not None and pending.request.key == request.key:
                return VisionInferenceAdmission(
                    "join", pending.request, pending.token, self._generation
                )
            if pending is None or request.priority >= pending.request.priority:
                if pending is not None:
                    pending.token.set()
                self._pending[endpoint] = _InferenceEntry(request, token)
                return VisionInferenceAdmission(
                    "queued", request, token, self._generation
                )

            token.set()
            return VisionInferenceAdmission(
                "rejected",
                request,
                token,
                self._generation,
                "a higher-priority request is already queued",
            )

    def finish(
        self,
        request: VisionInferenceRequest,
        token: threading.Event,
    ) -> VisionInferenceAdmission | None:
        endpoint = _endpoint_key(request.endpoint)
        with self._lock:
            active = self._active.get(endpoint)
            if (
                active is None
                or active.request != request
                or active.token is not token
            ):
                return None
            self._active.pop(endpoint, None)
            pending = self._pending.pop(endpoint, None)
            if (
                pending is None
                or pending.token.is_set()
                or pending.request.generation != self._generation
            ):
                return None
            self._active[endpoint] = pending
            return VisionInferenceAdmission(
                "start",
                pending.request,
                pending.token,
                self._generation,
            )

    def invalidate(self, generation: int) -> None:
        with self._lock:
            self._generation = int(generation)
            entries = tuple(self._active.values()) + tuple(self._pending.values())
            self._active.clear()
            self._pending.clear()
            for entry in entries:
                entry.token.set()

    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def owns_start(
        self,
        request: VisionInferenceRequest,
        token: threading.Event,
    ) -> bool:
        endpoint = _endpoint_key(request.endpoint)
        with self._lock:
            active = self._active.get(endpoint)
            return bool(
                active is not None
                and active.request == request
                and active.token is token
                and not token.is_set()
            )
