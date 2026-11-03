"""Typed sensory effect and prompt policy owner for the production desktop."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from core import text_tags
from core.runtime.config import RuntimeConfigService, RuntimeConfigSnapshot
from core.runtime.sensory_policy import (
    SensoryPolicy,
    SensoryPromptInputs,
    SensoryRuntimeActivity,
)


class ProductionDesktopSensoryOwner:
    """Own every late-bound capability consumed by ``SensoryService``."""

    __slots__ = (
        "_addons",
        "_avatar",
        "_available_emotions",
        "_config",
        "_control",
        "_conversation",
        "_debug_path",
        "_image_debug_path",
        "_debug_lock",
        "_logger",
        "_policy",
        "_presence",
        "_proactive",
        "_provider_activity",
        "_session",
        "_speech_ready",
        "_visual",
    )

    def __init__(
        self,
        *,
        app_root: str | Path,
        policy: SensoryPolicy,
        config: RuntimeConfigService,
        control: object,
        conversation: object,
        session: object,
        avatar: object,
        presence: object,
        proactive: object,
        visual: object,
        addons: object,
        provider_activity: object,
        available_emotions: Callable[[], object],
        speech_ready: Callable[[], bool],
        logger: Callable[[str], object] = print,
    ) -> None:
        if not isinstance(policy, SensoryPolicy):
            raise TypeError("Desktop sensory owner requires SensoryPolicy.")
        if not isinstance(config, RuntimeConfigService):
            raise TypeError("Desktop sensory owner requires RuntimeConfigService.")
        callbacks = {
            "available_emotions": available_emotions,
            "speech_ready": speech_ready,
            "logger": logger,
        }
        invalid = tuple(name for name, value in callbacks.items() if not callable(value))
        if invalid:
            raise TypeError("Desktop sensory callbacks must be callable: " + ", ".join(invalid))
        required = {
            "control": (control, ("snapshot",)),
            "conversation": (conversation, ("message_mappings", "session_lease_is_current")),
            "session": (session, ("request_chat_view_rebuild",)),
            "avatar": (avatar, ("set_expression",)),
            "presence": (presence, ("set_presence_mood", "set_companion_orb_comment_focus")),
            "proactive": (proactive, ("schedule",)),
            "visual": (visual, ("enabled", "request_generation")),
            "addons": (addons, ("publish_event",)),
            "provider_activity": (provider_activity, ("active",)),
        }
        for label, (owner, methods) in required.items():
            missing = tuple(method for method in methods if not callable(getattr(owner, method, None)))
            if missing:
                raise TypeError(f"Desktop sensory {label} is missing: {', '.join(missing)}")
        self._policy = policy
        self._config = config
        self._control = control
        self._conversation = conversation
        self._session = session
        self._avatar = avatar
        self._presence = presence
        self._proactive = proactive
        self._visual = visual
        self._addons = addons
        self._provider_activity = provider_activity
        self._available_emotions = available_emotions
        self._speech_ready = speech_ready
        self._logger = logger
        self._image_debug_path = Path(app_root).resolve() / "runtime" / "sensory_feedback" / "image_fallback.jsonl"
        self._debug_lock = threading.Lock()
        self._debug_path = (
            Path(app_root).resolve()
            / "runtime"
            / "companion_orb"
            / "debug"
            / "companion_orb_debug.log"
        )

    def orb_focus(self, payload: Mapping[str, object], lease: object) -> object:
        if not self._conversation.session_lease_is_current(lease):
            return None
        values = dict(payload or {})
        bounds = tuple(values.get("focus_bounds") or ())
        text = str(
            values.get("focus_text")
            or values.get("candidate")
            or values.get("summary")
            or values.get("attention")
            or ""
        ).strip()[:180]
        if not bounds and not text:
            return None
        focus = {
            "label": str(values.get("focus_label") or values.get("attention") or "comment focus"),
            "text": text,
            "attention": str(values.get("attention") or ""),
            "duration_seconds": float(values.get("focus_duration_seconds", 14.0) or 14.0),
        }
        if bounds:
            focus["bounds"] = bounds
        return self._presence.set_companion_orb_comment_focus(focus)

    def avatar_emotion(self, emotion: str, lease: object) -> object:
        value = str(emotion or "").strip().lower()
        result = self._avatar.set_expression(value, lease)
        if value:
            self._presence.set_presence_mood(value)
        return result

    def proactive(self, payload: Mapping[str, object], lease: object) -> object:
        trace_id = str(payload.get("trace_id", "") or "")
        if not trace_id:
            return None
        return self._proactive.schedule(
            lease,
            silence_seconds=0.0,
            metadata={
                "reason": "manual_companion_orb_drop",
                "trace_id": trace_id,
                "hidden_proactive": True,
            },
            action="hidden_proactive_reply",
        )

    def visual(self, payload: Mapping[str, object], lease: object, config: object) -> bool:
        values = _config_values(config)
        result = self._visual.request_generation(
            lease,
            prompt=str(payload.get("visual_candidate", "") or ""),
            source_text=str(
                payload.get("summary") or payload.get("proactive_candidate") or ""
            ),
            runtime_config=values,
        )
        return bool(result.accepted)

    def publish_event(self, name: str, payload: Mapping[str, object], _lease: object) -> None:
        self._addons.publish_event(str(name or ""), dict(payload or {}))

    def request_chat_rebuild(self, lease: object) -> object:
        if self._conversation.session_lease_is_current(lease):
            return self._session.request_chat_view_rebuild()
        return None

    def debug(self, event: str, fields: Mapping[str, object]) -> None:
        values = self._config.snapshot().values
        image_event = event == "sensory_image_fallback"
        if not image_event and not (
            bool(values.get("companion_orb_enabled", False))
            and bool(values.get("companion_orb_debug_enabled", False))
        ):
            return
        try:
            payload = {
                "event": str(event or "sensory_event"),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "monotonic": round(float(time.monotonic()), 3),
                "source": "sensory",
                **dict(fields or {}),
            }
            path = self._image_debug_path if image_event else self._debug_path
            with self._debug_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and path.stat().st_size > 2_000_000:
                    backup = path.with_name(path.stem + ".1" + path.suffix)
                    if backup.exists():
                        backup.unlink()
                    path.replace(backup)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str) + "\n")
        except Exception as exc:
            self._logger(f"[Sensory] Debug event write failed: {exc}")

    def loop_ready(self) -> bool:
        state = self._control.snapshot()
        return bool(
            not state.stop_requested
            and state.listening
            and not self._config.snapshot().values.get("offline_replay_only", False)
        )

    def blocked_reasons(self, allow_audio_playback: bool) -> tuple[str, ...]:
        state = self._control.snapshot()
        return self._policy.blocked_reasons(
            SensoryRuntimeActivity(
                microphone_active=state.microphone_active,
                audio_playing=state.audio_playing,
                llm_request_active=bool(self._provider_activity.active()),
                manual_pause_active=state.manual_pause,
                pause_after_chunk=state.pause_after_chunk,
                playback_paused=state.playback_paused,
            ),
            self._config.snapshot(),
            allow_audio_playback=bool(allow_audio_playback),
        )

    def build_messages(
        self,
        snapshots: object,
        allow_images: object,
        priority: object,
        config: object,
        retained: object,
    ) -> tuple[dict[str, object], ...]:
        emotions = self._available_emotions() or ()
        return self._policy.build_message_mappings(
            SensoryPromptInputs(
                snapshots=tuple(
                    dict(item) for item in (snapshots or ()) if isinstance(item, Mapping)
                ),
                config=config,
                retained_history=tuple(
                    dict(item) for item in (retained or ()) if isinstance(item, Mapping)
                ),
                visible_history=tuple(self._conversation.message_mappings()),
                available_emotions=tuple(str(item) for item in emotions),
                priority=bool(priority),
                allow_images=None if allow_images is None else bool(allow_images),
            )
        )

    def model_supports_images(self, config: object) -> bool:
        return self._policy.model_supports_images(config)

    def emotion_allowed(self, emotion: str) -> bool:
        return text_tags.is_emotion_tag(emotion, self._available_emotions())

    def visual_allowed(self, config: object) -> bool:
        values = _config_values(config)
        return self._policy.visual_allowed(
            config,
            visual_service_enabled=bool(self._visual.enabled(values)),
        )

    def proactive_ready(self) -> bool:
        return bool(self._speech_ready())


def _config_values(config: object) -> Mapping[str, object]:
    if isinstance(config, RuntimeConfigSnapshot):
        return config.values
    if isinstance(config, Mapping):
        return config
    values = getattr(config, "values", None)
    return values if isinstance(values, Mapping) else {}


__all__ = ["ProductionDesktopSensoryOwner"]
