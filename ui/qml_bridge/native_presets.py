"""Preset persistence for the native QML shell."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.persona_prompt_builder import normalize_type


_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_PRESET_CONFIG_KEYS = (
    "sensory_feedback_source",
    "sensory_feedback_interval_seconds",
    "sensory_pingpong_enabled",
    "sensory_allow_hidden_proactive_speech",
    "sensory_allow_hidden_visual_generation",
    "sensory_pingpong_history_depth",
    "sensory_pingpong_prompt",
    "sensory_pingpong_source_prompts",
    "sensory_provider_metadata_overrides",
    "sensory_context_templates",
    "allow_proactive_replies",
    "require_first_user_before_proactive",
    "listen_idle_window_seconds",
    "proactive_delay_seconds",
    "chat_context_window_messages",
    "stored_chat_history_limit",
    "chat_context_overflow_policy",
    "emotional_instructions",
    "system_prompt",
    "persona_prompt_type",
    "temperature",
    "top_p",
    "top_k",
    "repeat_penalty",
    "min_p",
    "limit_response_length",
    "max_response_tokens",
)


def _plain(value: Any) -> Any:
    """Convert immutable facade snapshots into JSON-compatible values."""

    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class NativePresetStore:
    """Read and write the established flat preset format without widgets."""

    def __init__(self, root: Path, application_facade: Any) -> None:
        self._root = Path(root).resolve()
        self._directory = self._root / "presets"
        self._application = application_facade

    def names(self) -> list[str]:
        if not self._directory.is_dir():
            return []
        return sorted(
            path.stem
            for path in self._directory.glob("*.json")
            if path.is_file()
        )

    def load(self, name: str) -> dict[str, Any]:
        path = self._path(name)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise TypeError("Preset root must be an object.")
        data = dict(payload)
        if "system_prompt" in data:
            data["persona_prompt_type"] = normalize_type(data.get("persona_prompt_type"))
        for key in _PRESET_CONFIG_KEYS:
            if key not in data:
                continue
            result = self._application.config.update(key, data[key])
            if not result.accepted:
                message = getattr(result.failure, "message", "Setting was rejected.")
                raise RuntimeError(f"Preset setting '{key}' was rejected: {message}")
        addon_result = self._application.addons.import_preset_state(data)
        if not addon_result.accepted:
            message = getattr(
                addon_result.failure,
                "message",
                "Addon preset settings were rejected.",
            )
            raise RuntimeError(str(message))
        self._application.config.update("active_preset_name", self._safe_name(name))
        return data

    def save(self, name: str) -> Path:
        clean_name = self._safe_name(name)
        config = dict(self._application.config.snapshot().values)
        payload = {
            key: config[key]
            for key in _PRESET_CONFIG_KEYS
            if key in config
        }
        addon_result = self._application.addons.export_preset_state()
        if not addon_result.accepted:
            message = getattr(
                addon_result.failure,
                "message",
                "Addon preset settings could not be exported.",
            )
            raise RuntimeError(str(message))
        payload.update(dict(addon_result.value or {}))
        self._directory.mkdir(parents=True, exist_ok=True)
        destination = self._path(clean_name, require_exists=False)
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(_plain(payload), indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        self._application.config.update("active_preset_name", clean_name)
        return destination

    def delete(self, name: str) -> bool:
        path = self._path(name)
        path.unlink()
        return True

    def _path(self, name: str, *, require_exists: bool = True) -> Path:
        clean_name = self._safe_name(name)
        path = (self._directory / f"{clean_name}.json").resolve()
        if path.parent != self._directory.resolve():
            raise ValueError("Preset path escaped the preset directory.")
        if require_exists and not path.is_file():
            raise FileNotFoundError(path)
        return path

    @staticmethod
    def _safe_name(name: str) -> str:
        clean_name = str(name or "").strip().rstrip(". ")
        if (
            not clean_name
            or clean_name in {".", ".."}
            or _INVALID_NAME.search(clean_name)
        ):
            raise ValueError("Enter a valid preset name.")
        return clean_name
