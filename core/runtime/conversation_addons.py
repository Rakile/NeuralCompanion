"""Conversation-turn addon commands owned outside the engine bootstrap."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from core import runtime_files, speech_text
from core.runtime.addon_extensions import AddonRuntimeExtensions
from core.runtime.addons import AddonGateway
from core.runtime.speech_routes import (
    VoiceSegment,
    VoiceSegmentationPolicy,
    VoiceSegmentationRequest,
)


class AddonCapabilityPort(Protocol):
    """Finite host capability surface used during a conversation turn."""

    def invoke_capability(
        self,
        capability: str,
        payload: dict[str, object] | None = None,
    ) -> object: ...

    def invoke_all_capabilities(
        self,
        capability: str,
        payload: dict[str, object] | None = None,
    ) -> list[object]: ...


class ConversationAddonBinding:
    """Own the replaceable addon capability port without locating it globally."""

    __slots__ = ("_lock", "_port")

    def __init__(self, port: AddonCapabilityPort | None = None) -> None:
        self._lock = threading.RLock()
        self._port = port

    def bind(self, port: AddonCapabilityPort | None) -> None:
        with self._lock:
            self._port = port

    def snapshot(self) -> AddonCapabilityPort | None:
        with self._lock:
            return self._port


class ConversationAddonOwner:
    """Own addon command interception and stream policy for conversation turns."""

    __slots__ = (
        "_gateway",
        "_extensions",
        "_binding",
        "_continue_assistant_sentinel",
    )

    def __init__(
        self,
        *,
        gateway: AddonGateway,
        extensions: AddonRuntimeExtensions,
        binding: ConversationAddonBinding,
        continue_assistant_sentinel: str = "__CONTINUE_ASSISTANT__",
    ) -> None:
        if not isinstance(gateway, AddonGateway):
            raise TypeError("Conversation addon ownership requires AddonGateway.")
        if not isinstance(extensions, AddonRuntimeExtensions):
            raise TypeError(
                "Conversation addon ownership requires AddonRuntimeExtensions."
            )
        if not isinstance(binding, ConversationAddonBinding):
            raise TypeError(
                "Conversation addon ownership requires ConversationAddonBinding."
            )
        self._gateway = gateway
        # Retain the same composed extension owner set used by the addon host.
        # Conversation capabilities remain manager-owned and are not re-created here.
        self._extensions = extensions
        self._binding = binding
        self._continue_assistant_sentinel = str(
            continue_assistant_sentinel or "__CONTINUE_ASSISTANT__"
        )

    def _invoke(self, capability: str, payload: Mapping[str, object]) -> object:
        if self._gateway.closed:
            return None
        port = self._binding.snapshot()
        if port is None:
            return None
        try:
            return port.invoke_capability(capability, dict(payload))
        except Exception as exc:
            print(f"⚠️ [Addons] Capability '{capability}' failed: {exc}")
            return None

    def _invoke_all(
        self,
        capability: str,
        payload: Mapping[str, object],
    ) -> list[object]:
        if self._gateway.closed:
            return []
        port = self._binding.snapshot()
        if port is None:
            return []
        try:
            return list(port.invoke_all_capabilities(capability, dict(payload)) or [])
        except Exception as exc:
            print(f"[Addons] Capability fanout '{capability}' failed: {exc}")
            return []

    def maybe_handle_addon_user_text_command(
        self,
        text: str,
        *,
        input_role: str,
        accepted_input_turn: Mapping[str, object] | None = None,
    ) -> dict[str, object] | None:
        role = str(input_role or "user").strip().lower() or "user"
        if role != "user":
            return None
        content = str(text or "").strip()
        if not content or content in {
            self._continue_assistant_sentinel,
            "You continue speaking.",
        }:
            return None
        payload: dict[str, object] = {"text": content, "role": role}
        turn_context = _awareness_turn_context(accepted_input_turn)
        if turn_context:
            payload["turn_context"] = turn_context
        result = self._invoke("chat.user_text_command", payload)
        if not isinstance(result, dict) or not bool(result.get("handled", False)):
            return None
        response_text = str(result.get("response_text") or "").strip()
        return dict(result) if response_text else None
    def maybe_handle_buddy_contextual_reply(
        self,
        payload: object,
    ) -> dict[str, object] | None:
        request = dict(payload) if isinstance(payload, Mapping) else {}
        result = self._invoke("buddy_chat.contextual_reply", request)
        if not isinstance(result, dict) or not bool(result.get("handled", False)):
            return None
        return dict(result) if str(result.get("response_text") or "").strip() else None

    def addon_voice_segments_stream_policy(
        self,
        config: Mapping[str, object],
    ) -> dict[str, object]:
        results = self._invoke_all(
            "tts.voice_segments.requires_full_text",
            config,
        )
        return dict(speech_text.resolve_addon_voice_stream_policy(results))

    def voice_stream_policy(
        self,
        request: VoiceSegmentationRequest,
    ) -> VoiceSegmentationPolicy:
        policy = self.addon_voice_segments_stream_policy(
            {
                "tts_backend": str(request.tts_backend or ""),
                "streaming": bool(request.streaming),
            }
        )
        return VoiceSegmentationPolicy(
            requires_full_text=bool(policy.get("requires_full_text", False)),
            preserve_input_chunks=bool(policy.get("preserve_voice_labels", False)),
        )

    def voice_segments(
        self,
        request: VoiceSegmentationRequest,
    ) -> tuple[VoiceSegment, ...]:
        payload: dict[str, object] = {
            "text": str(request.text or ""),
            "tts_backend": str(request.tts_backend or ""),
            "streaming": bool(request.streaming),
        }
        if request.streaming:
            payload["stream_start"] = bool(request.stream_start)
            payload["stream_source_index"] = max(
                0,
                int(request.stream_source_index),
            )
        if request.source_metadata:
            payload["source_meta"] = dict(request.source_metadata)
        result = self._invoke("tts.voice_segments", payload)
        if isinstance(result, Mapping):
            raw_segments = result.get("segments")
            suppress_original = bool(result.get("suppress_original", False))
        elif isinstance(result, (list, tuple)):
            raw_segments = result
            suppress_original = False
        else:
            raw_segments = ()
            suppress_original = False

        segments = []
        for raw in tuple(raw_segments or ()):
            if not isinstance(raw, Mapping):
                continue
            text = str(raw.get("text", "") or "").strip()
            if not text:
                continue
            metadata = dict(raw)
            metadata.pop("text", None)
            voice_path = str(metadata.pop("voice_path", "") or "").strip()
            voice_language = str(
                metadata.pop("voice_language", "") or ""
            ).strip()
            segments.append(
                VoiceSegment(
                    text=text,
                    voice_path=(
                        runtime_files.resolve_voice_reference_path(voice_path)
                        if voice_path
                        else ""
                    ),
                    voice_language=voice_language,
                    source_metadata=MappingProxyType(metadata),
                )
            )
        if segments:
            return tuple(segments)
        if suppress_original:
            # A present empty segment suppresses the coordinator's fallback
            # without introducing another public result type.
            return (VoiceSegment(""),)
        return ()


def _awareness_turn_context(
    turn: Mapping[str, object] | None,
) -> dict[str, object]:
    """Expose awareness routing without leaking local attachment paths."""

    if not isinstance(turn, Mapping):
        return {}
    has_image = bool(str(turn.get("attachment_image_path", "") or "").strip())
    has_hidden_context = isinstance(turn.get("hidden_proactive_request"), Mapping)
    has_orb_guidance = bool(
        str(turn.get("companion_orb_response_guidance", "") or "").strip()
    )
    if not (has_image or has_hidden_context or has_orb_guidance):
        return {}
    return {
        "requires_shared_awareness_pipeline": True,
        "has_image_attachment": has_image,
        "has_hidden_proactive_context": has_hidden_context,
        "has_companion_orb_guidance": has_orb_guidance,
        "source": str(turn.get("attachment_source", "") or "").strip().lower(),
    }


def build_conversation_addon_owner(
    *,
    gateway: AddonGateway,
    extensions: AddonRuntimeExtensions,
    binding: ConversationAddonBinding,
    continue_assistant_sentinel: str = "__CONTINUE_ASSISTANT__",
) -> ConversationAddonOwner:
    return ConversationAddonOwner(
        gateway=gateway,
        extensions=extensions,
        binding=binding,
        continue_assistant_sentinel=continue_assistant_sentinel,
    )


__all__ = [
    "AddonCapabilityPort",
    "ConversationAddonBinding",
    "ConversationAddonOwner",
    "build_conversation_addon_owner",
]
