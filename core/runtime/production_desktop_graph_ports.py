"""Finite process adapters for production desktop graph leaves."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import dry_run
from core import text_tags, tts_runtime
from core.runtime.loop_control import DryRunReplyOwner
from visual_presence import runtime as visual_presence_runtime


class DesktopAvatarAddonPort(Protocol):
    def create_avatar_adapter(
        self,
        provider_id: str,
        construction_input: object,
    ) -> object | None: ...

    def invoke_addon_capability(
        self,
        addon_id: str,
        capability: str,
        payload: Mapping[str, object] | None = None,
    ) -> object: ...


class DesktopConversationAddonPort(Protocol):
    def record_latency_event(self, event: str, **fields: object) -> object: ...

    def roleplay_assistant_reply(self, text: str) -> object: ...

    def buddy_contextual_reply(
        self,
        payload: Mapping[str, object],
    ) -> object: ...

    def buddy_assistant_reply(
        self,
        text: str,
        *,
        source: str = "",
    ) -> object: ...

    def companion_orb_assistant_focus(
        self,
        payload: Mapping[str, object],
    ) -> object: ...


class DesktopSpeechBackendPort(Protocol):
    def current_tts_adapter(self, config: object = None) -> object | None: ...

    def sample_rate(self, default: int = 24000) -> int: ...


class DesktopEventState(Protocol):
    def clear(self) -> None: ...

    def is_set(self) -> bool: ...

    def set(self) -> None: ...


class DesktopAvatarPreviewState(Protocol):
    def reset_musetalk_pipeline_data(self) -> None: ...

    def set_current_musetalk_frame_data(
        self,
        payload: Mapping[str, object],
    ) -> None: ...

    def write_musetalk_preview_frame(
        self,
        payload: Mapping[str, object],
    ) -> None: ...


def _require_methods(name: str, value: object, methods: tuple[str, ...]) -> None:
    missing = tuple(method for method in methods if not callable(getattr(value, method, None)))
    if missing:
        raise TypeError(f"{name} is missing required methods: {', '.join(missing)}")


@dataclass(frozen=True, slots=True)
class ProductionDesktopGraphPortBindings:
    """Required live process bindings used to construct the finite adapters."""

    avatar_addons: DesktopAvatarAddonPort
    conversation_addons: DesktopConversationAddonPort
    avatar_preview_state: DesktopAvatarPreviewState
    push_to_talk_held: DesktopEventState
    log_musetalk_memory_checkpoint: Callable[..., object]
    logger: Callable[[str], object] = print

    def __post_init__(self) -> None:
        _require_methods(
            "avatar_addons",
            self.avatar_addons,
            ("create_avatar_adapter",),
        )
        _require_methods(
            "conversation_addons",
            self.conversation_addons,
            (
                "roleplay_assistant_reply",
                "buddy_contextual_reply",
                "buddy_assistant_reply",
                "companion_orb_assistant_focus",
                "record_latency_event",
            ),
        )
        _require_methods(
            "avatar_preview_state",
            self.avatar_preview_state,
            (
                "reset_musetalk_pipeline_data",
                "set_current_musetalk_frame_data",
                "write_musetalk_preview_frame",
            ),
        )
        _require_methods(
            "push_to_talk_held",
            self.push_to_talk_held,
            ("clear", "is_set", "set"),
        )
        callbacks = (
            "log_musetalk_memory_checkpoint",
            "logger",
        )
        invalid = tuple(name for name in callbacks if not callable(getattr(self, name)))
        if invalid:
            raise TypeError("Invalid production desktop bindings: " + ", ".join(invalid))


class ProductionDryRunRuntime:
    def auto_replies_enabled(self) -> bool:
        return bool(dry_run.auto_replies_enabled())

    def next_auto_reply(self) -> str | None:
        return dry_run.next_auto_reply()

    def begin_reply(
        self,
        runtime_config: Mapping[str, object],
        streamed: bool = False,
        proactive: bool = False,
    ) -> str | None:
        return dry_run.begin_reply(
            runtime_config,
            streamed=bool(streamed),
            proactive=bool(proactive),
        )

    def finalize_reply(self, reply_id: str | None) -> object:
        return dry_run.finalize_reply(reply_id)


class ProductionDesktopAvatarEmotionBinding:
    """Publish the graph-owned emotion catalog to pre-graph adapters."""

    __slots__ = ("_lock", "_owner")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: object | None = None

    def bind(self, owner: object) -> None:
        _require_methods(
            "avatar_emotions",
            owner,
            ("invalidate", "available_names", "refresh_emotions"),
        )
        with self._lock:
            if self._owner is not None:
                raise RuntimeError("Production avatar emotion catalog is already bound.")
            self._owner = owner

    def invalidate(self) -> object:
        return self._required().invalidate()

    def available_names(self) -> object:
        return self._required().available_names()

    def refresh_emotions(self) -> object:
        return self._required().refresh_emotions()

    def _required(self) -> object:
        with self._lock:
            owner = self._owner
        if owner is None:
            raise RuntimeError("Production avatar emotions were used before binding.")
        return owner


class ProductionDesktopAvatarRuntimeActions:
    def __init__(
        self,
        emotions: ProductionDesktopAvatarEmotionBinding,
        log_memory_checkpoint: Callable[..., object],
    ) -> None:
        self._emotions = emotions
        self._log_memory_checkpoint = log_memory_checkpoint

    def invalidate_available_emotion_names(self) -> None:
        self._emotions.invalidate()

    def log_memory_checkpoint(self, *args: object, **kwargs: object) -> None:
        self._log_memory_checkpoint(*args, **kwargs)

    def record_reply_metric(self, *args: object, **kwargs: object) -> None:
        dry_run.record_reply_metric(*args, **kwargs)


class ProductionDesktopAvatarPreviewState:
    def __init__(self, state: DesktopAvatarPreviewState) -> None:
        self._state = state

    def set_current_musetalk_frame_data(self, payload: dict[str, object]) -> None:
        self._state.set_current_musetalk_frame_data(dict(payload))

    def write_musetalk_preview_frame(self, payload: dict[str, object]) -> None:
        self._state.write_musetalk_preview_frame(dict(payload))


class ProductionAvatarAddonCapabilityGateway:
    def __init__(self, port: DesktopAvatarAddonPort) -> None:
        _require_methods("avatar_addons", port, ("create_avatar_adapter",))
        self._port = port

    def invoke_addon_capability(
        self,
        addon_id: str,
        capability: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        normalized_addon = str(addon_id or "").strip()
        normalized_capability = str(capability or "").strip()
        if normalized_capability == "runtime.create_adapter":
            request = dict(payload or {})
            return self._port.create_avatar_adapter(
                normalized_addon,
                request.get("construction_input"),
            )
        if (
            normalized_addon == "nc.main_chat_remote"
            and normalized_capability == "runtime.main_chat_remote.presentation"
        ):
            invoke = getattr(self._port, "invoke_addon_capability", None)
            if not callable(invoke):
                return None
            return invoke(
                normalized_addon,
                normalized_capability,
                dict(payload or {}),
            )
        else:
            raise ValueError(f"Unsupported avatar capability: {capability}")


class ProductionPresenceVisualAuthority:
    def set_ai_state(self, state: str) -> object:
        return visual_presence_runtime.set_ai_state(str(state))

    def set_audio_level(self, level: float) -> object:
        return visual_presence_runtime.set_audio_level(float(level))

    def set_voice_analysis(self, frame: object) -> object:
        return visual_presence_runtime.set_voice_analysis(frame)

    def set_user_voice_analysis(self, frame: object, active: bool) -> object:
        return visual_presence_runtime.set_user_voice_analysis(frame, bool(active))

    def set_companion_orb_audio_level(self, level: float) -> object:
        return visual_presence_runtime.set_companion_orb_audio_level(float(level))

    def set_presence_mood(self, mood: str) -> object:
        return visual_presence_runtime.set_presence_mood(str(mood or "").strip().lower())

    def set_companion_orb_comment_focus(
        self,
        payload: Mapping[str, object],
    ) -> object:
        return visual_presence_runtime.set_companion_orb_comment_focus(dict(payload))


class ProductionAssistantReplyNotifier:
    def __init__(
        self,
        port: DesktopConversationAddonPort,
        *,
        logger: Callable[[str], object],
    ) -> None:
        self._port = port
        self._logger = logger

    def notify_assistant_reply(self, text: str) -> None:
        content = str(text or "").strip()
        if not content:
            return
        for label, callback in (
            ("roleplay", self._port.roleplay_assistant_reply),
            ("buddy chat", self._port.buddy_assistant_reply),
        ):
            try:
                callback(content)
            except Exception as exc:
                self._logger(f"[Addons] {label} assistant reply failed: {exc}")

    def notify_companion_orb_focus(self, directive: object) -> None:
        payload = {
            "region_id": str(getattr(directive, "region_id", "") or "").strip(),
            "target": str(getattr(directive, "target", "") or "").strip(),
            "action": str(getattr(directive, "action", "") or "").strip().lower(),
        }
        if not payload["region_id"] or not payload["target"]:
            return
        try:
            self._port.companion_orb_assistant_focus(payload)
        except Exception as exc:
            self._logger(f"[Addons] Companion Orb assistant focus failed: {exc}")


class ProductionSpeechLatencyRecorder:
    def __init__(self, record: Callable[..., object]) -> None:
        self._record = record

    def record_assistant_finalize(
        self,
        *,
        duration_ms: float,
        reply_chars: int,
    ) -> None:
        self._record(
            "assistant_finalize",
            duration_ms=float(duration_ms),
            reply_chars=int(reply_chars),
        )


class ProductionSensoryHistorySanitizer:
    def __init__(self, available_emotion_names: Callable[[], object]) -> None:
        self._available_emotion_names = available_emotion_names

    def sanitize(self, entry: object) -> Mapping[str, object] | None:
        if not isinstance(entry, Mapping):
            return None
        summary = _clean(entry.get("summary"))
        emotion = _clean(entry.get("emotion"), lower=True)
        attention = _clean(entry.get("attention"), lower=True)
        proactive = _clean(entry.get("proactive_candidate"))
        visual = _clean(entry.get("visual_candidate"))
        tags: list[str] = []
        raw_tags = entry.get("tags", ())
        if isinstance(raw_tags, (list, tuple, set)):
            for item in raw_tags:
                tag = _clean(item)[:80]
                if tag and tag not in tags:
                    tags.append(tag)
        should_speak = _boolish(entry.get("should_speak", False))
        should_generate = _boolish(entry.get("should_generate_image", False))
        if emotion and not text_tags.is_emotion_tag(
            emotion,
            self._available_emotion_names(),
        ):
            emotion = ""
        if not (
            summary
            or emotion
            or attention
            or proactive
            or visual
            or should_speak
            or should_generate
            or tags
        ):
            return None
        return {
            "type": "sensory_pong",
            "hidden": True,
            "source": _clean(entry.get("source", "sensory"), lower=True) or "sensory",
            "summary": summary[:220],
            "emotion": emotion,
            "attention": attention[:80],
            "proactive_candidate": proactive[:220],
            "visual_candidate": visual[:220],
            "should_speak": should_speak,
            "should_generate_image": should_generate,
            "tags": tags[:12],
            "created_at": float(entry.get("created_at", time.time()) or time.time()),
        }


class ProductionPushToTalkHoldOwner:
    def __init__(self, state: DesktopEventState) -> None:
        self._state = state

    def set_hold(self, active: bool) -> bool:
        (self._state.set if bool(active) else self._state.clear)()
        return True


class ProductionCompanionOrbContextualReplyOwner:
    def __init__(self, port: DesktopConversationAddonPort) -> None:
        self._port = port

    def maybe_reply(
        self,
        payload: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        result = self._port.buddy_contextual_reply(dict(payload))
        if not isinstance(result, Mapping) or not bool(result.get("handled", False)):
            return None
        return dict(result) if str(result.get("response_text") or "").strip() else None

    def record_reply(self, text: str, *, source: str) -> None:
        content = str(text or "").strip()
        if content:
            self._port.buddy_assistant_reply(
                content,
                source=str(source or "").strip().lower(),
            )


class ProductionAudioStoryTtsResourceOwner:
    def __init__(self, *, seed: object, speech: DesktopSpeechBackendPort) -> None:
        _require_methods("audio_story_seed", seed, ("set_seed",))
        _require_methods(
            "audio_story_speech",
            speech,
            ("current_tts_adapter", "sample_rate"),
        )
        self._seed = seed
        self._speech = speech

    def set_seed(self, seed: int) -> object:
        return self._seed.set_seed(int(seed))

    def generate(self, text: str, **settings: object) -> object:
        model = self._speech.current_tts_adapter()
        generate = getattr(model, "generate", None)
        if not callable(generate):
            raise RuntimeError("Audio Story TTS model is not initialized.")
        return generate(str(text), **dict(settings))

    def save_wav(self, path: str, wav: object, sample_rate: int) -> object:
        return tts_runtime.save_audio_file(str(path), wav, int(sample_rate))

    def sample_rate(self, default: int) -> int:
        return int(self._speech.sample_rate(int(default)))


class ProductionAvatarEmotionResourceOwner:
    def __init__(
        self,
        refresh_emotions: Callable[[], object],
        speech: object,
    ) -> None:
        if not callable(refresh_emotions):
            raise TypeError("Avatar emotion refresh must be callable.")
        _require_methods("avatar_resource_speech", speech, ("tts_device",))
        self._refresh_emotions = refresh_emotions
        self._speech = speech

    def refresh_emotions(self) -> object:
        return self._refresh_emotions()

    def tts_device(self) -> str:
        return str(self._speech.tts_device() or "cpu")


@dataclass(frozen=True, slots=True)
class ProductionDesktopGraphPorts:
    """Compatibility-independent values consumed by the desktop graph inputs."""

    dry_run: DryRunReplyOwner
    avatar_runtime_actions: ProductionDesktopAvatarRuntimeActions
    avatar_preview_state: ProductionDesktopAvatarPreviewState
    avatar_addon_gateway: ProductionAvatarAddonCapabilityGateway
    presence_visual: ProductionPresenceVisualAuthority
    reply_notifier: ProductionAssistantReplyNotifier
    speech_latency: ProductionSpeechLatencyRecorder
    sensory_history: ProductionSensoryHistorySanitizer
    push_to_talk_hold: ProductionPushToTalkHoldOwner
    push_to_talk_held: DesktopEventState
    contextual_replies: ProductionCompanionOrbContextualReplyOwner
    avatar_emotions: ProductionDesktopAvatarEmotionBinding


def build_production_desktop_graph_ports(
    bindings: ProductionDesktopGraphPortBindings,
) -> ProductionDesktopGraphPorts:
    if not isinstance(bindings, ProductionDesktopGraphPortBindings):
        raise TypeError("bindings must be ProductionDesktopGraphPortBindings.")
    avatar_emotions = ProductionDesktopAvatarEmotionBinding()
    return ProductionDesktopGraphPorts(
        dry_run=DryRunReplyOwner(ProductionDryRunRuntime()),
        avatar_runtime_actions=ProductionDesktopAvatarRuntimeActions(
            avatar_emotions,
            bindings.log_musetalk_memory_checkpoint,
        ),
        avatar_preview_state=ProductionDesktopAvatarPreviewState(
            bindings.avatar_preview_state
        ),
        avatar_addon_gateway=ProductionAvatarAddonCapabilityGateway(bindings.avatar_addons),
        presence_visual=ProductionPresenceVisualAuthority(),
        reply_notifier=ProductionAssistantReplyNotifier(
            bindings.conversation_addons,
            logger=bindings.logger,
        ),
        speech_latency=ProductionSpeechLatencyRecorder(
            bindings.conversation_addons.record_latency_event
        ),
        sensory_history=ProductionSensoryHistorySanitizer(
            avatar_emotions.available_names
        ),
        push_to_talk_hold=ProductionPushToTalkHoldOwner(bindings.push_to_talk_held),
        push_to_talk_held=bindings.push_to_talk_held,
        contextual_replies=ProductionCompanionOrbContextualReplyOwner(
            bindings.conversation_addons
        ),
        avatar_emotions=avatar_emotions,
    )


def _clean(value: object, *, lower: bool = False) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.lower() if lower else text


def _boolish(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


__all__ = [
    "DesktopAvatarAddonPort",
    "DesktopConversationAddonPort",
    "DesktopEventState",
    "DesktopSpeechBackendPort",
    "ProductionDesktopGraphPortBindings",
    "ProductionDesktopGraphPorts",
    "ProductionDesktopAvatarEmotionBinding",
    "ProductionAudioStoryTtsResourceOwner",
    "ProductionAvatarEmotionResourceOwner",
    "build_production_desktop_graph_ports",
]
