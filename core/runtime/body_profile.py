"""Owned avatar body-profile state and immutable projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import threading
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class BodyProfileSnapshot:
    """A deeply immutable projection of editable avatar body state."""

    profile: Mapping[str, object]
    state: Mapping[str, object]
    hand_calibration: Mapping[str, object]
    edit_emotion: str
    force_edit_mode: bool

    @property
    def live_sync(self) -> bool:
        return not self.force_edit_mode

    def to_mapping(self) -> Mapping[str, object]:
        """Project the legacy body snapshot schema without exposing mutable state."""

        return MappingProxyType(
            {
                "profile": self.profile,
                "state": self.state,
                "hand_calibration": self.hand_calibration,
                "edit_emotion": self.edit_emotion,
                "force_edit_mode": self.force_edit_mode,
            }
        )


class BodyProfileService:
    """Own body pose, emotion profile, and hand-calibration mutations."""

    def __init__(
        self,
        *,
        profile: Mapping[str, object],
        state: Mapping[str, object],
        hand_calibration: Mapping[str, object],
        edit_emotion: object = "neutral",
        force_edit_mode: bool = True,
    ) -> None:
        self._lock = threading.Lock()
        self._profile = _mutable_mapping(profile)
        self._state = _mutable_mapping(state)
        self._hand_calibration = _mutable_mapping(hand_calibration)
        self._edit_emotion = str(edit_emotion or "").lower()
        self._force_edit_mode = bool(force_edit_mode)

    def snapshot(self) -> BodyProfileSnapshot:
        with self._lock:
            return BodyProfileSnapshot(
                profile=_freeze_mapping(self._profile),
                state=_freeze_mapping(self._state),
                hand_calibration=_freeze_mapping(self._hand_calibration),
                edit_emotion=self._edit_emotion,
                force_edit_mode=self._force_edit_mode,
            )

    def set_live_sync(self, enabled: object) -> BodyProfileSnapshot:
        with self._lock:
            self._force_edit_mode = not bool(enabled)
            return self._snapshot_locked()

    def select_emotion(self, emotion: object) -> BodyProfileSnapshot:
        with self._lock:
            self._edit_emotion = str(emotion or "").lower()
            return self._snapshot_locked()

    def update_pose(self, key: object, value: object) -> BodyProfileSnapshot:
        pose_key = str(key)
        owned_value = _mutable_copy(value)
        with self._lock:
            target = self._edit_emotion if self._force_edit_mode else "neutral"
            if target in self._profile:
                target_profile = self._profile[target]
                if not isinstance(target_profile, dict):
                    raise TypeError(f"Body profile {target!r} is not mutable")
                target_profile[pose_key] = owned_value
            self._state[pose_key] = _mutable_copy(value)
            return self._snapshot_locked()

    def update_profile(self, profile: object) -> BodyProfileSnapshot:
        updates = dict(profile or {})
        with self._lock:
            self._profile.update(_mutable_mapping(updates))
            return self._snapshot_locked()

    def update_hand_calibration(self, values: object) -> BodyProfileSnapshot:
        updates = dict(values or {})
        with self._lock:
            self._hand_calibration.update(_mutable_mapping(updates))
            return self._snapshot_locked()

    def _snapshot_locked(self) -> BodyProfileSnapshot:
        return BodyProfileSnapshot(
            profile=_freeze_mapping(self._profile),
            state=_freeze_mapping(self._state),
            hand_calibration=_freeze_mapping(self._hand_calibration),
            edit_emotion=self._edit_emotion,
            force_edit_mode=self._force_edit_mode,
        )


def _mutable_mapping(values: Mapping[object, object]) -> dict[str, object]:
    if not isinstance(values, Mapping):
        raise TypeError("Body profile state must be a mapping")
    return {str(key): _mutable_copy(value) for key, value in values.items()}


def _mutable_copy(value: object) -> object:
    if isinstance(value, Mapping):
        return _mutable_mapping(value)
    if isinstance(value, list):
        return [_mutable_copy(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_mutable_copy(item) for item in value)
    if isinstance(value, set):
        return {_mutable_copy(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_mutable_copy(item) for item in value)
    return value


def _freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): _freeze(value) for key, value in values.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


__all__ = ["BodyProfileService", "BodyProfileSnapshot"]
