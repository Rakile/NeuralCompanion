from __future__ import annotations

import re
from typing import Any, Mapping

STRUCTURED_STORY_SCHEMA_VERSION = "mprc.story_output.v1"


def normalize_structured_output_cast(cast: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, dict[str, str]]:
    normalized: dict[str, dict[str, str]] = {
        "narrator": {"speaker_name": "Narrator"},
    }
    for raw_id, raw_item in dict(cast or {}).items():
        speaker_id = _speaker_id(raw_id)
        if not speaker_id or speaker_id in {"narrator", "unknown_speaker"}:
            continue
        item = dict(raw_item or {}) if isinstance(raw_item, Mapping) else {}
        speaker_name = re.sub(r"\s+", " ", str(item.get("speaker_name") or item.get("display_name") or speaker_id)).strip()
        if speaker_name:
            normalized[speaker_id] = {"speaker_name": speaker_name}
    normalized["unknown_speaker"] = {"speaker_name": "Unknown Speaker"}
    return normalized


def build_structured_story_output_schema(
    cast: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    require_choices: bool = True,
) -> dict[str, Any]:
    normalized_cast = normalize_structured_output_cast(cast)
    speaker_ids = list(normalized_cast.keys())
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://neuralcompanion.local/schemas/mprc-story-output-v1.json",
        "title": "NeuralCompanion MPRC Structured Story Output",
        "description": (
            "Use this schema as the provider Structured Output JSON Schema for MPRC Play. "
            "The model selects speaker_id only; NeuralCompanion maps speaker_id to the local voice route. "
            "Keep payloads compact so the app can convert them into tagged story text before TTS."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "response_type",
            "segments",
            "choices",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": STRUCTURED_STORY_SCHEMA_VERSION},
            "response_type": {"type": "string", "const": "story_turn"},
            "segments": {
                "type": "array",
                "minItems": 1,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "speaker_id",
                        "role",
                        "text",
                    ],
                    "properties": {
                        "speaker_id": {"type": "string", "enum": speaker_ids},
                        "role": {
                            "type": "string",
                            "enum": ["narrator", "character", "sfx", "music", "ambience", "fx"],
                        },
                        "text": {"type": "string", "minLength": 1, "maxLength": 1600},
                    },
                },
            },
            "choices": {
                "type": "array",
                "minItems": 2 if require_choices else 0,
                "maxItems": 4 if require_choices else 0,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["label"],
                    "properties": {
                        "label": {"type": "string", "minLength": 1, "maxLength": 220},
                    },
                },
            },
        },
    }


def _speaker_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text
