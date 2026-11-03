"""Immutable runtime identifiers and stale-work lease checks."""

from __future__ import annotations

from dataclasses import dataclass


def _validate_generation(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True, order=True)
class RunId:
    """Monotonic identifier for one application runtime."""

    value: int

    def __post_init__(self) -> None:
        _validate_generation(self.value, "RunId")


@dataclass(frozen=True, slots=True, order=True)
class SessionGeneration:
    """Monotonic identifier for one session state generation."""

    value: int

    def __post_init__(self) -> None:
        _validate_generation(self.value, "SessionGeneration")


@dataclass(frozen=True, slots=True, order=True)
class TurnId:
    """Opaque identifier for one accepted user turn."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise ValueError("TurnId must be a string")


@dataclass(frozen=True, slots=True, order=True)
class RouteGeneration:
    """Monotonic identifier for one route selection generation."""

    value: int

    def __post_init__(self) -> None:
        _validate_generation(self.value, "RouteGeneration")


@dataclass(frozen=True, slots=True)
class RuntimePosition:
    """The currently authoritative runtime identifiers for a side effect."""

    run_id: RunId
    session_generation: SessionGeneration | None = None
    turn_id: TurnId | None = None
    route_generation: RouteGeneration | None = None


@dataclass(frozen=True, slots=True)
class WorkLease:
    """Identifiers that must still match before work may make a side effect."""

    run_id: RunId
    session_generation: SessionGeneration | None = None
    turn_id: TurnId | None = None
    route_generation: RouteGeneration | None = None

    def matches(self, position: RuntimePosition) -> bool:
        """Return whether this lease remains current at its declared scope."""

        return (
            self.run_id == position.run_id
            and (
                self.session_generation is None
                or self.session_generation == position.session_generation
            )
            and (self.turn_id is None or self.turn_id == position.turn_id)
            and (
                self.route_generation is None
                or self.route_generation == position.route_generation
            )
        )


__all__ = [
    "RouteGeneration",
    "RunId",
    "RuntimePosition",
    "SessionGeneration",
    "TurnId",
    "WorkLease",
]
