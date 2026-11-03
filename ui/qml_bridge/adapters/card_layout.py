"""Presentation-only card grouping for native addon controls.

The native adapters own control identity and runtime bindings.  This module only
adds QML layout metadata so dense addon tabs render as small, semantic cards.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import re
from typing import Iterable, Mapping

from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind


CardPlacement = tuple[str, str, int]


_CATEGORY_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "filters",
        "Filters and matching",
        ("filter", "ignore", "transcript", "phrase", "keyword", "exclude"),
    ),
    (
        "presets",
        "Presets and profiles",
        ("preset", "profile", "library", "template", "quick slot"),
    ),
    (
        "voice_audio",
        "Voice and audio",
        (
            "voice",
            "audio",
            "speech",
            "tts",
            "sound",
            "volume",
            "music",
            "wav",
            "channel",
            "channels",
        ),
    ),
    (
        "visual_media",
        "Visuals and media",
        (
            "visual",
            "image",
            "avatar",
            "portrait",
            "camera",
            "frame",
            "mask",
            "thumbnail",
            "video",
        ),
    ),
    (
        "prompts",
        "Prompts and guidance",
        ("prompt", "instruction", "guidance", "persona", "response style"),
    ),
    (
        "connection",
        "Connection and runtime",
        (
            "provider",
            "model",
            "llm",
            "endpoint",
            "api",
            "token",
            "port",
            "host",
            "server",
            "url",
            "connection",
            "connect",
            "network",
            "internet",
            " lan ",
        ),
    ),
    (
        "playback",
        "Playback and devices",
        ("playback", "play", "pause", "queue", "device", "track", "speaker"),
    ),
    (
        "behavior",
        "Behavior and automation",
        (
            "permission",
            "confirm",
            "allow",
            "enabled",
            "enable",
            "mode",
            "behavior",
            "monitor",
            "awareness",
            "cooldown",
            "interval",
            "frequency",
            "timing",
            "automatic",
            "autonomous",
            "safety",
            "privacy",
        ),
    ),
    (
        "performance",
        "Performance and timing",
        (
            "fps",
            "latency",
            "duration",
            "timeout",
            "delay",
            "cutoff",
            "length",
            "thread",
            "threads",
            "batch",
            "rate",
            "refresh",
            "hz",
            "ttl",
        ),
    ),
    (
        "appearance",
        "Appearance and motion",
        (
            "color",
            "opacity",
            "brightness",
            "animation",
            "effect",
            "theme",
            "glow",
            "position",
            "geometry",
        ),
    ),
    (
        "content",
        "Files and content",
        (
            "path",
            "folder",
            "file",
            "directory",
            "source",
            "destination",
            "cache",
            "storage",
            "project",
            "chapter",
            "story",
        ),
    ),
)

_ID_NAMESPACE_TOKENS = {
    "ai",
    "audio",
    "buddy",
    "chat",
    "companion",
    "context",
    "corsair",
    "discord",
    "hotkeys",
    "identity",
    "main",
    "mode",
    "mprc",
    "musetalk",
    "orb",
    "presence",
    "rag",
    "relay",
    "remote",
    "replay",
    "reply",
    "sense",
    "spotify",
    "story",
    "supervisor",
    "visual",
}


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return normalized or "overview"


def _semantic_placement(control: NativeControl) -> CardPlacement:
    section_key = _slug(control.section)
    metadata = dict(control.metadata)
    id_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", control.id.lower())
        if token not in _ID_NAMESPACE_TOKENS
    }
    label_tokens = set(re.findall(r"[a-z0-9]+", control.label.lower()))
    tokens = id_tokens | label_tokens
    searchable = f" {' '.join(sorted(tokens))} {control.label.lower()} "

    if control.kind is NativeControlKind.ACTION:
        return f"{section_key}_actions", "Actions", 1

    read_only = bool(metadata.get("readOnly")) or not control.enabled
    if read_only and control.kind in {
        NativeControlKind.IMAGE,
        NativeControlKind.LIST,
        NativeControlKind.MULTILINE,
    }:
        # Keep large previews, transcripts, and read-only editors out of the
        # compact status card.  Mixing one multiline preview into that group
        # otherwise promotes every short status row to a full-width card.
        return f"{section_key}_details", "Details and preview", 2
    if control.kind in {
        NativeControlKind.DISPLAY,
        NativeControlKind.IMAGE,
        NativeControlKind.LIST,
        NativeControlKind.PROGRESS,
    } or read_only:
        span = 2 if control.kind in {
            NativeControlKind.IMAGE,
            NativeControlKind.LIST,
        } else 1
        return f"{section_key}_information", "Status and information", span

    def matches(term: str) -> bool:
        normalized = str(term or "").strip().lower()
        return normalized in tokens if " " not in normalized else f" {normalized} " in searchable

    for key, title, terms in _CATEGORY_RULES:
        if any(matches(term) for term in terms):
            span = 2 if control.kind is NativeControlKind.MULTILINE else 1
            return f"{section_key}_{key}", title, span

    span = 2 if control.kind is NativeControlKind.MULTILINE else 1
    return f"{section_key}_settings", "Settings", span


def apply_card_layout(
    controls: Iterable[NativeControl],
    *,
    overrides: Mapping[str, CardPlacement] | None = None,
) -> tuple[NativeControl, ...]:
    """Return controls with semantic card metadata and no runtime changes.

    Existing explicit group metadata wins.  ``overrides`` is reserved for
    addon-specific placements where a generic semantic category is not enough.
    Card span is normalized to one or two columns; groups containing a large
    multiline/list/image control are promoted to full width.
    """

    explicit = dict(overrides or {})
    prepared: list[tuple[NativeControl, CardPlacement]] = []
    group_needs_width: dict[str, bool] = defaultdict(bool)

    for control in controls:
        metadata = dict(control.metadata)
        if control.id in explicit:
            placement = explicit[control.id]
        elif metadata.get("groupKey") and metadata.get("groupTitle"):
            placement = (
                str(metadata["groupKey"]),
                str(metadata["groupTitle"]),
                int(metadata.get("groupColumnSpan", 1)),
            )
        else:
            placement = _semantic_placement(control)
        key, title, span = placement
        normalized = (str(key), str(title), max(1, min(2, int(span))))
        prepared.append((control, normalized))
        if control.kind in {
            NativeControlKind.IMAGE,
            NativeControlKind.LIST,
            NativeControlKind.MULTILINE,
        }:
            group_needs_width[normalized[0]] = True

    rendered: list[NativeControl] = []
    for control, (key, title, span) in prepared:
        metadata = dict(control.metadata)
        metadata.update(
            groupKey=key,
            groupTitle=title,
            groupColumnSpan=2 if group_needs_width[key] else span,
        )
        rendered.append(replace(control, metadata=metadata))
    return tuple(rendered)


__all__ = ["CardPlacement", "apply_card_layout"]
