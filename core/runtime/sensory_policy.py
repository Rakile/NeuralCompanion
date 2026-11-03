"""Typed sensory source, prompt, message, and admission policy."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path
import re
import time

from core.runtime.config import RuntimeConfigSnapshot
from core.runtime.prompt_assembly import PromptMessage
from core.runtime.sensory_context_templates import context_text
from core.runtime.prompt_tasks import (
    companion_orb_drop_guidance_from_snapshots,
    compact_companion_orb_drop_guidance,
)
from core.sensory import DEFAULT_SENSORY_PINGPONG_PROMPT, SensoryRegistry, resolve_pingpong_prompt
from core.sensory_source_selection import enabled_source_ids


ConfigInput = RuntimeConfigSnapshot | Mapping[str, object]

_IMAGE_MODEL_POSITIVE_FRAGMENTS = (
    "vision",
    "image",
    "multimodal",
    "vl",
    "llava",
    "bakllava",
    "moondream",
    "pixtral",
    "minicpm-v",
    "internvl",
    "phi-3.5-vision",
    "phi-4-multimodal",
    "gemma-3",
    "gpt-4o",
    "gpt-4.1",
    "omni",
    "qwen/qwen3.5",
    "qwen3.5",
    "qwen2-vl",
    "qwen2.5-vl",
    "qvq",
)
_IMAGE_MODEL_NEGATIVE_FRAGMENTS = (
    "embedding",
    "rerank",
    "whisper",
    "tts",
    "audio",
    "transcribe",
    "grok-imagine",
)


@dataclass(frozen=True, slots=True)
class SensoryRuntimeActivity:
    """Request-local runtime activity used to admit a sensory cycle."""

    microphone_active: bool = False
    audio_playing: bool = False
    llm_request_active: bool = False
    manual_pause_active: bool = False
    pause_after_chunk: bool = False
    playback_paused: bool = False


@dataclass(frozen=True, slots=True)
class SensoryPromptInputs:
    """Detached inputs for one hidden sensory prompt."""

    snapshots: tuple[Mapping[str, object], ...]
    config: ConfigInput
    retained_history: tuple[Mapping[str, object], ...] = ()
    visible_history: tuple[Mapping[str, object], ...] = ()
    available_emotions: tuple[str, ...] = ()
    priority: bool = False
    allow_images: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshots", tuple(self.snapshots))
        object.__setattr__(self, "retained_history", tuple(self.retained_history))
        object.__setattr__(self, "visible_history", tuple(self.visible_history))
        object.__setattr__(
            self,
            "available_emotions",
            tuple(str(item or "").strip() for item in self.available_emotions),
        )
        object.__setattr__(self, "priority", bool(self.priority))


class SensoryPolicy:
    """Own deterministic sensory selection, prompt shaping, and admission rules."""

    def __init__(self, registry: SensoryRegistry) -> None:
        if not isinstance(registry, SensoryRegistry):
            raise TypeError("Sensory policy requires a SensoryRegistry.")
        self._registry = registry

    @property
    def registry(self) -> SensoryRegistry:
        return self._registry

    def selected_sources(
        self,
        config: ConfigInput,
        selected_sources: Sequence[str] | None = None,
    ) -> tuple[str, ...]:
        values = _config_values(config)
        configured: object = (
            tuple(selected_sources)
            if selected_sources is not None
            else values.get("sensory_feedback_source", "off")
        )
        return enabled_source_ids(
            configured,
            (provider.id for provider in self._registry.list_providers()),
        )

    def source_instruction(
        self,
        config: ConfigInput,
        selected_sources: Sequence[str] | None = None,
    ) -> str:
        sources = (
            tuple(selected_sources)
            if selected_sources is not None
            else self.selected_sources(config)
        )
        instructions: list[str] = []
        seen: set[str] = set()
        for source in sources:
            effective = self._effective_provider(source, config)
            instruction = str(effective.get("instruction") or "").strip()
            if not instruction or instruction in seen:
                continue
            instructions.append(instruction)
            seen.add(instruction)
        if instructions:
            return "\n\n".join(instructions)
        if not sources:
            return ""
        return context_text(_config_values(config), "fallback_source_instruction")

    def model_supports_images(self, config: ConfigInput) -> bool:
        values = _config_values(config)
        explicit = values.get("model_supports_images")
        if explicit is not None:
            return bool(explicit)
        model_name = str(values.get("model_name", "") or "").strip().lower()
        if not model_name or any(
            fragment in model_name for fragment in _IMAGE_MODEL_NEGATIVE_FRAGMENTS
        ):
            return False
        return any(
            fragment in model_name for fragment in _IMAGE_MODEL_POSITIVE_FRAGMENTS
        )

    def blocked_reasons(
        self,
        activity: SensoryRuntimeActivity,
        config: ConfigInput,
        *,
        allow_audio_playback: bool = False,
    ) -> tuple[str, ...]:
        if not isinstance(activity, SensoryRuntimeActivity):
            raise TypeError("Sensory admission requires SensoryRuntimeActivity.")
        reasons: list[str] = []
        if activity.microphone_active:
            reasons.append("microphone_active")
        if activity.audio_playing and not allow_audio_playback:
            reasons.append("audio_playing")
        if activity.llm_request_active:
            reasons.append("llm_request_active")
        if activity.manual_pause_active:
            reasons.append("manual_pause_active")
        if activity.pause_after_chunk:
            reasons.append("pause_after_chunk")
        if activity.playback_paused:
            reasons.append("playback_paused")
        if bool(_config_values(config).get("offline_replay_only", False)):
            reasons.append("offline_replay_only")
        return tuple(reasons)

    def visual_allowed(
        self,
        config: ConfigInput,
        *,
        visual_service_enabled: bool,
    ) -> bool:
        return bool(
            _config_values(config).get(
                "sensory_allow_hidden_visual_generation",
                False,
            )
            and visual_service_enabled
        )

    def proactive_allowed(
        self,
        config: ConfigInput,
        *,
        speech_service_ready: bool,
        snapshots: Sequence[Mapping[str, object]] = (),
    ) -> bool:
        return bool(
            _config_values(config).get(
                "sensory_allow_hidden_proactive_speech",
                False,
            )
            and speech_service_ready
            and not _orb_suppresses_proactive(snapshots)
        )

    def retained_context(
        self,
        entries: Sequence[Mapping[str, object]],
        config: ConfigInput,
    ) -> str:
        values = _config_values(config)
        depth = max(
            0,
            int(values.get("sensory_pingpong_history_depth", 3) or 3),
        )
        history = list(entries)[-depth:] if depth > 0 else []
        lines: list[str] = []
        for entry in history:
            created_at = float(entry.get("created_at", 0.0) or 0.0)
            stamp = (
                time.strftime("%H:%M:%S", time.localtime(created_at))
                if created_at > 0
                else "unknown"
            )
            parts = [f"[{stamp}] {str(entry.get('source', 'sensory') or 'sensory')}"]
            summary = str(entry.get("summary", "") or "").strip()
            emotion = str(entry.get("emotion", "") or "").strip()
            attention = str(entry.get("attention", "") or "").strip()
            if summary:
                parts.append(summary)
            if emotion:
                parts.append(f"emotion={emotion}")
            if attention:
                parts.append(f"attention={attention}")
            tags = list(entry.get("tags", ()) or ())
            if tags:
                parts.append(f"tags={', '.join(str(tag) for tag in tags[:6])}")
            lines.append(" | ".join(parts))
        if not lines:
            return ""
        return (
            context_text(values, "retained_history_framing")
            + "\n".join(f"- {line}" for line in lines)
        )

    def snapshot_message(
        self,
        snapshot: Mapping[str, object],
        config: ConfigInput,
        *,
        allow_images: bool,
    ) -> PromptMessage | None:
        if not isinstance(snapshot, Mapping):
            return None
        source = str(snapshot.get("source", "sensory") or "sensory")
        captured_at = float(snapshot.get("captured_at", 0.0) or 0.0)
        timestamp = _timestamp(captured_at)
        role = str(snapshot.get("role", "user") or "user")
        message = snapshot.get("message")
        if isinstance(message, Mapping):
            if allow_images:
                return PromptMessage.from_mapping(message)
            content = self._compact_text_payload(snapshot, config)
            return (
                PromptMessage(
                    role=str(message.get("role", role) or "user"),
                    content=content,
                )
                if content
                else None
            )
        content = snapshot.get("content")
        if isinstance(content, Sequence) and not isinstance(
            content,
            (str, bytes, bytearray),
        ):
            if allow_images:
                return PromptMessage(role=role, content=list(content))
            text = self._compact_text_payload(snapshot, config)
            return PromptMessage(role=role, content=text) if text else None
        if isinstance(content, str) and content.strip():
            metadata = snapshot.get("metadata")
            if isinstance(metadata, Mapping) and metadata:
                payload = {
                    "source": source,
                    "captured_at": captured_at,
                    "content": content,
                    "metadata": dict(metadata),
                }
                return PromptMessage(
                    role=role,
                    content=json.dumps(payload, ensure_ascii=True),
                )
            return PromptMessage(role=role, content=content)
        if not allow_images:
            text = self._compact_text_payload(snapshot, config)
            return PromptMessage(role=role, content=text) if text else None
        overview_url = _data_url_for_local_image(snapshot.get("image_path", ""))
        raw_tiles = snapshot.get("image_tiles", ())
        tile_specs = tuple(
            dict(item)
            for item in raw_tiles
            if isinstance(item, Mapping)
            and _data_url_for_local_image(item.get("path", ""))
        ) if isinstance(raw_tiles, Sequence) and not isinstance(
            raw_tiles,
            (str, bytes, bytearray),
        ) else ()
        if not overview_url and not tile_specs:
            return None
        text_prefix = self._snapshot_prefix(snapshot, config, "snapshot_prefix")
        metadata_payload = self._compact_text_payload(
            snapshot,
            config,
            image_omitted=False,
        )
        if metadata_payload:
            text_prefix = f"{text_prefix}\n\nContext metadata: {metadata_payload}"
        content_parts: list[dict[str, object]] = [
            {"type": "text", "text": text_prefix}
        ]
        if overview_url:
            if tile_specs:
                content_parts.append(
                    {
                        "type": "text",
                        "text": context_text(_config_values(config), "desktop_overview_instruction"),
                    }
                )
            content_parts.append(
                {"type": "image_url", "image_url": {"url": overview_url}}
            )
        for index, tile in enumerate(tile_specs):
            tile_url = _data_url_for_local_image(tile.get("path", ""))
            if not tile_url:
                continue
            label = str(tile.get("label") or f"Desktop detail tile {index + 1}")
            bounds = _focus_bounds(tile.get("screen_bounds"))
            content_parts.extend(
                (
                    {
                        "type": "text",
                        "text": context_text(
                            _config_values(config), "desktop_tile_instruction",
                            LABEL=label, BOUNDS=list(bounds),
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": tile_url}},
                )
            )
        return PromptMessage(
            role=role,
            content=tuple(content_parts),
        )

    def build_messages(self, inputs: SensoryPromptInputs) -> tuple[PromptMessage, ...]:
        if not isinstance(inputs, SensoryPromptInputs):
            raise TypeError("Sensory prompt assembly requires SensoryPromptInputs.")
        snapshots = _manual_priority_snapshots(inputs.snapshots)
        manual_priority = bool(inputs.priority) and any(
            _manual_orb_snapshot(item) for item in snapshots
        )
        suppress_proactive = _orb_suppresses_proactive(snapshots)
        allow_images = (
            self.model_supports_images(inputs.config)
            if inputs.allow_images is None
            else bool(inputs.allow_images)
        )
        from core.screen_review import screen_review_contributor, screen_images, clipboard_image_is_new
        compact = screen_review_contributor(self._registry,
            tuple(str(item.get('source', '')) for item in snapshots), _config_values(inputs.config))
        if compact is not None:
            if compact.source_id == 'clipboard' and not clipboard_image_is_new(snapshots):
                return ()
            images = screen_images(snapshots) if allow_images else []
            content = ([{'type': 'text', 'text': 'New clipboard image.'}, *images]
                       if compact.source_id == 'clipboard' else images)
            return (PromptMessage('system', compact.prompt),
                    PromptMessage('user', content)) if images else ()
        ping_messages = tuple(
            message
            for message in (
                self.snapshot_message(
                    snapshot,
                    inputs.config,
                    allow_images=allow_images,
                )
                for snapshot in snapshots
            )
            if message is not None
        )
        if not ping_messages:
            return ()
        emotions = sorted(
            {item for item in inputs.available_emotions if item}
        )
        emotion_text = ", ".join(emotions[:48]) if emotions else "neutral"
        source_ids = tuple(
            str(item.get("source", "") or "").strip().lower()
            for item in snapshots
        )
        messages: list[PromptMessage] = [
            PromptMessage(
                role="system",
                content=self._pingpong_prompt(
                    source_ids,
                    emotion_text,
                    inputs.config,
                ),
            )
        ]
        instruction = self.source_instruction(inputs.config, source_ids)
        if instruction:
            messages.append(PromptMessage(role="system", content=instruction))
        if manual_priority:
            focus_only = (
                context_text(_config_values(inputs.config), "manual_orb_focus_only")
                if suppress_proactive
                else ""
            )
            messages.append(
                PromptMessage(
                    role="system",
                    content=(
                        context_text(_config_values(inputs.config), "manual_orb_priority")
                        + focus_only
                    ),
                )
            )
            guidance = companion_orb_drop_guidance_from_snapshots(snapshots)
            if guidance:
                messages.append(
                    PromptMessage(
                        role="system",
                        content=(
                            guidance
                            + context_text(_config_values(inputs.config), "manual_orb_guidance_scope")
                        ),
                    )
                )
        # Detection uses current captures only. History remains owned by the
        # runtime for retention and action cadence, not evidence for this review.
        messages.extend(ping_messages)
        return tuple(messages)

    def build_message_mappings(
        self,
        inputs: SensoryPromptInputs,
    ) -> tuple[dict[str, object], ...]:
        """Return detached mappings for the existing provider request surface."""

        return tuple(message.to_mapping() for message in self.build_messages(inputs))

    def effective_provider(
        self,
        provider_id: str,
        config: ConfigInput,
    ) -> dict[str, object]:
        """Return the same effective source fields used by message assembly."""
        return self._effective_provider(provider_id, config)

    def _effective_provider(
        self,
        provider_id: str,
        config: ConfigInput,
    ) -> dict[str, object]:
        provider_key = str(provider_id or "").strip().lower()
        provider = self._registry.get_provider(provider_key)
        base_metadata = dict(getattr(provider, "metadata", {}) or {})
        payload: dict[str, object] = {
            "label": str(getattr(provider, "label", provider_key) or provider_key),
            "instruction": str(getattr(provider, "instruction", "") or ""),
            "description": str(getattr(provider, "description", "") or ""),
            "metadata": base_metadata,
        }
        values = _config_values(config)
        overrides = values.get("sensory_provider_metadata_overrides", {})
        source_override = (
            overrides.get(provider_key, {}) if isinstance(overrides, Mapping) else {}
        )
        if isinstance(source_override, Mapping):
            for key in ("label", "instruction", "description"):
                if key in source_override:
                    payload[key] = str(source_override.get(key) or "")
            metadata_override = source_override.get("metadata", {})
            if isinstance(metadata_override, Mapping):
                merged = dict(base_metadata)
                merged.update(dict(metadata_override))
                payload["metadata"] = merged
        source_prompts = values.get("sensory_pingpong_source_prompts", {})
        if isinstance(source_prompts, Mapping) and provider_key in source_prompts:
            metadata = dict(payload.get("metadata") or {})
            metadata["pingpong_prompt"] = str(
                source_prompts.get(provider_key) or ""
            )
            payload["metadata"] = metadata
        # Upgrade only recognized shipped guidance, including legacy metadata overrides.
        # Explicit empty source guidance and user-authored text remain untouched.
        from core.sensory_prompt_defaults import SOURCE_LEGACY_HASHES, resolve_prompt
        metadata = dict(payload.get('metadata') or {})
        guidance = metadata.get('pingpong_prompt')
        recommended = base_metadata.get('pingpong_prompt')
        if guidance and recommended:
            metadata['pingpong_prompt'] = resolve_prompt(
                guidance, recommended, legacy_hashes=SOURCE_LEGACY_HASHES.get(provider_key, ()))
            payload['metadata'] = metadata
        return payload

    def _source_prompt_text(
        self,
        source_ids: Sequence[str],
        config: ConfigInput,
    ) -> str:
        normalized = tuple(
            str(item or "").strip().lower()
            for item in source_ids
            if str(item or "").strip()
        )
        fragments: list[str] = []
        seen: set[str] = set()
        for source_id in normalized:
            effective = self._effective_provider(source_id, config)
            metadata = dict(effective.get("metadata") or {})
            if metadata.get("prompt_fragment_enabled", True) is not False:
                fragment = str(metadata.get("pingpong_prompt") or "").strip()
                sections: list[str] = []
                ping_payload = _metadata_lines(metadata.get("ping_payload", ()))
                influences = _metadata_lines(
                    metadata.get("pong_influences", metadata.get("pong_outputs", ()))
                )
                subscriptions = _metadata_lines(
                    metadata.get("tag_subscriptions", ()),
                    name_key="tag",
                    description_key="action",
                )
                if ping_payload:
                    sections.append(
                        "Declared PING payload:\n"
                        + "\n".join(f"- {line}" for line in ping_payload)
                    )
                if influences:
                    sections.append(
                        "May influence PONG:\n"
                        + "\n".join(f"- {line}" for line in influences)
                    )
                if subscriptions:
                    sections.append(
                        "Declared tag subscriptions:\n"
                        + "\n".join(f"- {line}" for line in subscriptions)
                    )
                full_fragment = "\n\n".join(
                    item for item in (fragment, *sections) if item
                )
                if full_fragment and full_fragment not in seen:
                    seen.add(full_fragment)
                    label = str(effective.get("label") or source_id)
                    fragments.append(f"Source prompt for {label}:\n{full_fragment}")
        for contributor in self._registry.list_prompt_contributors():
            if not _source_matches(contributor.source_id, normalized):
                continue
            fragment = str(contributor.metadata.get('legacy_prompt', contributor.prompt) or "").strip()
            if not fragment or fragment in seen:
                continue
            seen.add(fragment)
            label = str(contributor.label or contributor.source_id)
            fragments.append(f"Behavior prompt for {label}:\n{fragment}")
        return "\n\n".join(fragments)

    def _pingpong_prompt(
        self,
        source_ids: Sequence[str],
        emotion_text: str,
        config: ConfigInput,
    ) -> str:
        configured = resolve_pingpong_prompt(
            _config_values(config).get(
                "sensory_pingpong_prompt",
                DEFAULT_SENSORY_PINGPONG_PROMPT,
            )
            or DEFAULT_SENSORY_PINGPONG_PROMPT
        ).strip()
        prompt = (configured or DEFAULT_SENSORY_PINGPONG_PROMPT).replace(
            "__EMOTION_LIST__",
            emotion_text,
        )
        source_prompt = self._source_prompt_text(source_ids, config)
        if source_prompt:
            return prompt + "\n\nEnabled source-specific guidance:\n" + source_prompt
        return prompt

    def _snapshot_prefix(
        self,
        snapshot: Mapping[str, object],
        config: ConfigInput,
        fallback_key: str,
    ) -> str:
        source = str(snapshot.get("source", "sensory") or "sensory")
        timestamp = _timestamp(float(snapshot.get("captured_at", 0.0) or 0.0))
        values = _config_values(config)
        overrides = values.get("sensory_provider_metadata_overrides", {})
        source_override = overrides.get(source.strip().lower(), {}) if isinstance(overrides, Mapping) else {}
        metadata = source_override.get("metadata", {}) if isinstance(source_override, Mapping) else {}
        if isinstance(metadata, Mapping) and "snapshot_prompt" in metadata:
            return str(metadata.get("snapshot_prompt") or "").replace(
                "__SOURCE__", source,
            ).replace("__CAPTURED_AT__", timestamp)
        content_text = str(snapshot.get("content_text") or "").strip()
        return content_text or context_text(
            values, fallback_key, SOURCE=source, CAPTURED_AT=timestamp,
        )

    def _compact_text_payload(
        self,
        snapshot: Mapping[str, object],
        config: ConfigInput,
        *,
        image_omitted: bool = True,
    ) -> str:
        source = str(snapshot.get("source", "sensory") or "sensory")
        captured_at = float(snapshot.get("captured_at", 0.0) or 0.0)
        timestamp = _timestamp(captured_at)
        raw_metadata = snapshot.get("metadata")
        metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
        raw_target = metadata.get("target")
        target = dict(raw_target) if isinstance(raw_target, Mapping) else {}
        if source == "companion_orb_target" and not bool(
            _config_values(config).get("companion_orb_include_process_name", True)
        ):
            target["process_name"] = ""
        compact: dict[str, object] = {
            "source": source,
            "captured_at": timestamp,
            "image_omitted": bool(image_omitted),
        }
        for key in (
            "target_available",
            "reason",
            "capture_mode",
            "full_screen_context",
            "screen_bounds",
            "requested_screen_bounds",
            "manual_inspection_primary",
            "drop_focus_bounds",
            "ocr_backend",
            "ocr_text_recognized",
            "ocr_region_detection_only",
            "ocr_text_recognition_available",
            "vision_tile_count",
            "vision_tile_bounds",
        ):
            if key in metadata:
                compact[key] = metadata.get(key)
        manual = metadata.get("manual_inspection")
        if isinstance(manual, Mapping) and manual:
            compact["manual_inspection"] = {
                "reason": str(manual.get("reason") or "")[:80],
                "primary": bool(manual.get("primary", False)),
                "focus_bounds": manual.get("focus_bounds") or [],
                "required_response_focus": str(
                    manual.get("required_response_focus") or ""
                )[:120],
                "instruction": str(manual.get("instruction") or "")[:360],
            }
        if target:
            compact["target"] = {
                "type": str(target.get("target_type") or ""),
                "title": str(target.get("title") or "")[:160],
                "process_name": str(target.get("process_name") or "")[:120],
                "bounds": target.get("bounds") or target.get("screen_bounds") or [],
            }
        ocr_text = str(metadata.get("ocr_text") or "").strip()
        if ocr_text:
            compact["ocr_text"] = ocr_text[:1800]
        regions = _compact_ocr_regions(metadata.get("ocr_regions", ()))
        if regions:
            compact["ocr_regions"] = regions
        lfm_visual_context = _compact_lfm_visual_context(
            metadata.get("lfm_visual_context")
        )
        if lfm_visual_context:
            compact["lfm_visual_context"] = lfm_visual_context
        guidance = compact_companion_orb_drop_guidance(metadata)
        if guidance:
            compact["smart_drop_guidance"] = guidance
            guidance_text = str(
                metadata.get("smart_drop_guidance_text") or ""
            ).strip()
            if guidance_text:
                compact["smart_drop_guidance_text"] = guidance_text[:1200]
        content_text = self._snapshot_prefix(snapshot, config, "compact_text_prefix")
        return json.dumps(
            {
                "instruction": context_text(_config_values(config), "compact_instruction"),
                "content_text": content_text,
                "metadata": compact,
            },
            ensure_ascii=True,
        )


def _config_values(config: ConfigInput) -> Mapping[str, object]:
    if isinstance(config, RuntimeConfigSnapshot):
        return config.values
    if not isinstance(config, Mapping):
        raise TypeError("Sensory policy requires a config mapping or snapshot.")
    return config


def _timestamp(captured_at: float) -> str:
    return (
        time.strftime("%H:%M:%S", time.localtime(captured_at))
        if captured_at > 0
        else "unknown"
    )


def _data_url_for_local_image(image_path: object) -> str:
    path = Path(str(image_path or "").strip())
    if not str(image_path or "").strip() or not path.is_file():
        return ""
    mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def _manual_orb_snapshot(snapshot: Mapping[str, object]) -> bool:
    if (
        str(snapshot.get("source", "") or "").strip().lower()
        != "companion_orb_target"
    ):
        return False
    raw_metadata = snapshot.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
    raw_manual = metadata.get("manual_inspection")
    manual = raw_manual if isinstance(raw_manual, Mapping) else {}
    return bool(
        metadata.get("manual_inspection_primary")
        or _focus_bounds(metadata.get("drop_focus_bounds"))
        or _focus_bounds(manual.get("focus_bounds"))
    )


def _manual_priority_snapshots(
    snapshots: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    normalized = tuple(item for item in snapshots if isinstance(item, Mapping))
    manual = tuple(item for item in normalized if _manual_orb_snapshot(item))
    return manual or normalized


def _focus_bounds(value: object) -> tuple[int, int, int, int] | tuple[()]:
    try:
        values = tuple(int(item) for item in list(value or ())[:4])
    except (TypeError, ValueError):
        return ()
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        return ()
    return values


def _orb_suppresses_proactive(
    snapshots: Sequence[Mapping[str, object]],
) -> bool:
    for snapshot in snapshots:
        if (
            str(snapshot.get("source", "") or "").strip().lower()
            != "companion_orb_target"
        ):
            continue
        raw_metadata = snapshot.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
        if metadata.get("suppress_hidden_proactive") or metadata.get(
            "immediate_image_delivery"
        ):
            return True
    return False


def _visible_history_summary(
    history: Sequence[Mapping[str, object]],
    *,
    limit: int = 6,
) -> str:
    visible_turns: list[tuple[str, str]] = []
    for turn in history:
        if not isinstance(turn, Mapping):
            continue
        role = str(turn.get("role", "") or "").strip().lower()
        if role not in {"user", "system", "assistant"}:
            continue
        content = str(turn.get("content", "") or "").strip()
        if not content and str(turn.get("attachment_image_path", "") or "").strip():
            content = "Please respond to the image I just sent you."
        if content:
            visible_turns.append((role, content))
    lines: list[str] = []
    for role, raw_content in visible_turns[-limit:]:
        content = re.sub(r"\s+", " ", raw_content).strip()
        if len(content) > 240:
            content = content[:237] + "..."
        label = (
            "Assistant"
            if role == "assistant"
            else "System"
            if role == "system"
            else "User"
        )
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _source_matches(contributor_source: object, source_ids: Sequence[str]) -> bool:
    source = str(contributor_source or "").strip().lower()
    keys = {
        str(item or "").strip().lower()
        for item in source_ids
        if str(item or "").strip()
    }
    if not keys:
        return True
    return source in keys or (
        source == "screen" and any("screen" in key for key in keys)
    )


def _metadata_lines(
    raw: object,
    *,
    name_key: str = "field",
    description_key: str = "description",
) -> tuple[str, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return ()
    lines: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            name = str(
                item.get(name_key) or item.get("field") or item.get("tag") or ""
            ).strip()
            description = str(
                item.get(description_key)
                or item.get("description")
                or item.get("action")
                or ""
            ).strip()
            text = (
                f"{name}: {description}"
                if name and description
                else name or description
            )
        else:
            text = str(item or "").strip()
        if text and text not in lines:
            lines.append(text)
    return tuple(lines)


def _compact_ocr_regions(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    result: list[dict[str, object]] = []
    for region in list(raw)[:24]:
        if not isinstance(region, Mapping):
            continue
        bounds = _focus_bounds(region.get("screen_bounds"))
        if not bounds:
            continue
        item: dict[str, object] = {
            "screen_bounds": list(bounds),
            "kind": str(region.get("kind") or "")[:40],
        }
        text = str(region.get("text") or "").strip()
        if text:
            item["text"] = text[:140]
        confidence = region.get("confidence")
        if confidence is not None:
            try:
                item["confidence"] = round(float(confidence), 3)
            except (TypeError, ValueError):
                pass
        result.append(item)
    return result


def _compact_lfm_visual_context(raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        return {}
    compact: dict[str, object] = {}
    for key, limit in (
        ("scene_summary", 320),
        ("user_focus", 180),
        ("limitations", 180),
    ):
        value = str(raw.get(key) or "").strip()
        if value:
            compact[key] = value[:limit]
    for key, count, limit in (
        ("visible_evidence", 3, 180),
        ("suggested_topics", 2, 120),
    ):
        value = raw.get(key)
        if not isinstance(value, Sequence) or isinstance(
            value, (str, bytes, bytearray)
        ):
            continue
        items = [str(item or "").strip()[:limit] for item in list(value)[:count]]
        items = [item for item in items if item]
        if items:
            compact[key] = items
    regions = _compact_ocr_regions(raw.get("regions", ()))
    if regions:
        compact["regions"] = regions
    return compact


__all__ = [
    "SensoryPolicy",
    "SensoryPromptInputs",
    "SensoryRuntimeActivity",
]
