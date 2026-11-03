"""Lease-bound conversation presence publication."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from core.runtime.avatar import AvatarService, AvatarSnapshot
from core.runtime.config import RuntimeConfigService
from core.runtime.conversation import ConversationService
from core.runtime.identifiers import WorkLease


class PresenceVisualAuthority(Protocol):
    """Finite AI Presence and Companion Orb publication surface."""

    def set_ai_state(self, state: str) -> object: ...

    def set_audio_level(self, level: float) -> object: ...

    def set_user_voice_analysis(self, frame: object, active: bool) -> object: ...

    def set_companion_orb_audio_level(self, level: float) -> object: ...


class AvatarPresenceOwner:
    """Publish one session's conversation phases through visual presence.

    ``AvatarService`` remains the sole owner of provider/avatar speaking state.
    This owner only publishes the corresponding AI Presence and Companion Orb
    view, under the conversation service's session-effect admission.
    """

    def __init__(
        self,
        *,
        avatar: AvatarService,
        config: RuntimeConfigService,
        conversation: ConversationService,
        lease: WorkLease,
        visual: PresenceVisualAuthority | None,
    ) -> None:
        self._avatar = avatar
        self._config = config
        self._conversation = conversation
        self._lease = lease
        self._visual = visual

    @property
    def lease(self) -> WorkLease:
        return self._lease

    def for_lease(self, lease: WorkLease) -> "AvatarPresenceOwner":
        """Return a new immutable binding for a successor session."""

        return AvatarPresenceOwner(
            avatar=self._avatar,
            config=self._config,
            conversation=self._conversation,
            lease=lease,
            visual=self._visual,
        )

    def avatar_snapshot(self) -> AvatarSnapshot:
        """Expose the canonical avatar state without duplicating ownership."""

        return self._avatar.snapshot()

    def set_state(self, state: str) -> None:
        visual = self._visual
        if visual is None:
            return
        admission = self._conversation.admit_session_effect(self._lease)
        if admission is None:
            return
        try:
            try:
                visual.set_ai_state(state)
            except BaseException:
                pass
        finally:
            self._conversation.release_session_effect(admission)

    def set_audio_level(self, level: float) -> None:
        visual = self._visual
        if visual is None:
            return
        try:
            numeric = float(level or 0.0)
        except (TypeError, ValueError):
            numeric = 0.0

        admission = self._conversation.admit_session_effect(self._lease)
        if admission is None:
            return
        try:
            config = self._config.snapshot().values
            ai_enabled = _ai_audio_sync_enabled(config)
            orb_enabled = _orb_audio_sync_enabled(config)
            try:
                if ai_enabled or numeric <= 0.0:
                    visual.set_audio_level(numeric if ai_enabled else 0.0)
                if orb_enabled or numeric <= 0.0:
                    visual.set_companion_orb_audio_level(
                        numeric if orb_enabled else 0.0
                    )
            except BaseException:
                # Presence publication is visual-only and must never abort chat.
                pass
        finally:
            self._conversation.release_session_effect(admission)


def _ai_audio_sync_enabled(config: Mapping[str, object]) -> bool:
    if not bool(config.get("ai_presence_enabled", False)):
        return False
    mode = str(
        config.get("ai_presence_display_mode", "fullscreen") or "fullscreen"
    ).strip().lower()
    return mode != "off"


def _orb_audio_sync_enabled(config: Mapping[str, object]) -> bool:
    if not bool(config.get("companion_orb_voice_sync_enabled", True)):
        return False
    if not bool(config.get("companion_orb_enabled", False)):
        return False
    mode = str(
        config.get("companion_orb_display_mode", "off") or "off"
    ).strip().lower()
    return mode != "off"


__all__ = ["AvatarPresenceOwner", "PresenceVisualAuthority"]
