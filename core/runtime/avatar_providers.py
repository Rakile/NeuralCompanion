"""Named avatar-provider policy and MuseTalk pack operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.identifiers import WorkLease


EffectCommit = Callable[[WorkLease, Callable[[], object]], CommandResult[object]]


class MuseTalkPackAdapter(Protocol):
    avatar_provider_id: str
    default_avatar_id: str

    def select_avatar_pack(self, pack_id: str) -> object: ...


@dataclass(frozen=True, slots=True)
class AvatarProviderCapabilities:
    """Finite addon boundary for provider policy and MuseTalk packs."""

    resolve_vram_mode: Callable[[str, Mapping[str, object], str], str] | None = None
    chunk_limits_for_index: Callable[
        [str, int, Mapping[str, object], Mapping[str, object]],
        Sequence[int] | None,
    ] | None = None
    normalize_pack_emotions: Callable[[object], Mapping[str, object]] | None = None
    enabled_pack_emotions: Callable[
        [Mapping[str, object], str],
        Sequence[str] | None,
    ] | None = None
    musetalk_pack_catalog: Callable[
        [Mapping[str, object]],
        Sequence[Mapping[str, object]],
    ] | None = None
    select_musetalk_pack: Callable[[Mapping[str, object], str], str | None] | None = None
    update_config: Callable[[str, object], object] | None = None
    invalidate_emotions: Callable[[], object] | None = None
    restore_musetalk_idle: Callable[[str, WorkLease], object] | None = None
    audio_active: Callable[[], bool] | None = None
    shutdown_requested: Callable[[], bool] | None = None


class AvatarProviderOperations:
    """Own provider policy decisions without exposing addon dispatch primitives."""

    def __init__(
        self,
        *,
        adapter: Callable[[], MuseTalkPackAdapter | None],
        capabilities: AvatarProviderCapabilities | None = None,
        commit_effect: EffectCommit | None = None,
        lease_is_current: Callable[[WorkLease], bool] | None = None,
    ) -> None:
        self._adapter = adapter
        self._capabilities = capabilities or AvatarProviderCapabilities()
        self._lease_is_current = lease_is_current or (lambda _lease: True)
        self._commit_effect = commit_effect or self._commit_if_current

    def active_vram_mode(
        self,
        runtime_config: Mapping[str, object],
        default: str = "quality",
    ) -> str:
        config = _freeze_mapping(runtime_config)
        fallback = str(default or "quality").strip().lower() or "quality"
        provider_id = str(config.get("avatar_mode") or "").strip().lower()
        resolver = self._capabilities.resolve_vram_mode
        if provider_id and resolver is not None:
            value = str(resolver(provider_id, config, fallback) or "").strip().lower()
            if value:
                return value
        return str(
            config.get("avatar_vram_mode", config.get("vram_mode", fallback))
            or fallback
        ).strip().lower()

    def chunk_limits_for_index(
        self,
        chunk_index: int,
        runtime_config: Mapping[str, object],
        *,
        quickstart: Sequence[Sequence[int]],
        target: int,
        maximum: int,
    ) -> tuple[int, int]:
        fallback = (max(1, int(target)), max(1, int(maximum)))
        config = _freeze_mapping(runtime_config)
        provider_id = str(config.get("avatar_mode") or "").strip().lower()
        resolver = self._capabilities.chunk_limits_for_index
        if not provider_id or provider_id == "vseeface" or resolver is None:
            return fallback
        defaults = _freeze_mapping(
            {
                "quickstart": tuple(
                    (int(values[0]), int(values[1]))
                    for values in quickstart
                    if len(values) >= 2
                ),
                "target": fallback[0],
                "max": fallback[1],
            }
        )
        try:
            values = resolver(provider_id, max(0, int(chunk_index)), config, defaults)
            if values is None or len(values) < 2:
                return fallback
            resolved = (int(values[0]), int(values[1]))
        except Exception:
            return fallback
        return resolved if resolved[0] > 0 and resolved[1] > 0 else fallback

    def normalize_musetalk_enabled_emotions(
        self,
        value: object,
    ) -> Mapping[str, object]:
        normalizer = self._capabilities.normalize_pack_emotions
        normalized = normalizer(value) if normalizer is not None else {}
        return _freeze_mapping(normalized)

    def musetalk_enabled_emotions(
        self,
        runtime_config: Mapping[str, object],
        pack_id: str,
    ) -> tuple[str, ...] | None:
        resolver = self._capabilities.enabled_pack_emotions
        if resolver is None:
            return None
        values = resolver(_freeze_mapping(runtime_config), str(pack_id or "").strip())
        if values is None:
            return None
        return tuple(str(value).strip().lower() for value in values if str(value).strip())

    def musetalk_pack_catalog(
        self,
        runtime_config: Mapping[str, object],
    ) -> tuple[Mapping[str, object], ...]:
        catalog = self._capabilities.musetalk_pack_catalog
        values = catalog(_freeze_mapping(runtime_config)) if catalog is not None else ()
        return tuple(_freeze_mapping(value) for value in values or ())

    def select_musetalk_pack(
        self,
        runtime_config: Mapping[str, object],
        pack_id: str,
        lease: WorkLease,
    ) -> CommandResult[str]:
        config = _freeze_mapping(runtime_config)
        current = str(config.get("musetalk_avatar_pack_id") or "").strip()
        requested = str(pack_id or "").strip()
        if not requested:
            return CommandResult(True, current)
        selector = self._capabilities.select_musetalk_pack
        if selector is None:
            return _failure(
                "avatar_pack_selection_unavailable",
                "MuseTalk pack selection is unavailable",
            )

        def apply_selection() -> str:
            selected = str(selector(config, requested) or "").strip()
            if not selected:
                return current
            update = self._capabilities.update_config
            if update is not None:
                update("musetalk_avatar_pack_id", selected)
            invalidate = self._capabilities.invalidate_emotions
            if invalidate is not None:
                invalidate()
            adapter = self._adapter()
            if _matches_provider(adapter, "musetalk"):
                adapter.select_avatar_pack(selected)
                audio_active = self._capabilities.audio_active
                shutdown = self._capabilities.shutdown_requested
                can_restore_idle = not bool(audio_active is not None and audio_active())
                can_restore_idle = can_restore_idle and not bool(
                    shutdown is not None and shutdown()
                )
                restore = self._capabilities.restore_musetalk_idle
                if can_restore_idle and restore is not None:
                    restore(str(adapter.default_avatar_id or ""), lease)
            return selected

        try:
            committed = self._commit_effect(lease, apply_selection)
        except BaseException as exc:
            return _failure(
                "avatar_pack_selection_failed",
                f"Could not select MuseTalk avatar pack: {exc}",
                exc,
            )
        if not committed.accepted:
            return CommandResult(False, failure=committed.failure)
        return CommandResult(True, str(committed.value or current))

    def _commit_if_current(
        self,
        lease: WorkLease,
        effect: Callable[[], object],
    ) -> CommandResult[object]:
        if not self._lease_is_current(lease):
            return _failure(
                "avatar_provider_stale_lease",
                "Avatar provider operation lease is stale",
            )
        return CommandResult(True, effect())


def _matches_provider(adapter: object, provider_id: str) -> bool:
    actual = str(getattr(adapter, "avatar_provider_id", "") or "").strip().lower()
    return bool(actual and actual == str(provider_id or "").strip().lower())


def _freeze_mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return MappingProxyType(deepcopy(dict(value or {})))


def _failure(
    category: str,
    message: str,
    cause: BaseException | None = None,
) -> CommandResult:
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


__all__ = [
    "AvatarProviderCapabilities",
    "AvatarProviderOperations",
    "MuseTalkPackAdapter",
]
