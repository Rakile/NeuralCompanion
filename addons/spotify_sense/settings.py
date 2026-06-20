from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


DEFAULT_HIDDEN_COMMENTARY_STYLE_PROMPT = (
    "Make song-change comments sound like a relaxed music-aware companion: one short natural line, "
    "specific to the track title, artist, mood, or energy. Avoid dry metadata summaries, repeated "
    "'now playing' wording, and hidden-system mechanics."
)
DEFAULT_HIDDEN_SENSORY_QUICK_IDS = [
    "builtin.natural_companion",
    "builtin.story_soundtrack",
    "builtin.focus_mode",
]

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "client_id": "",
    "redirect_uri": "http://127.0.0.1:8765/spotify/callback",
    "access_token": "",
    "refresh_token": "",
    "expires_at": 0,
    "scopes": [],
    "account_display_name": "",
    "account_id": "",
    "allow_llm_control": False,
    "require_confirmation": True,
    "autonomous_music": "off",
    "default_device_id": "",
    "default_volume": 30,
    "duck_while_speaking": False,
    "duck_volume_percent": 15,
    "duck_fade_down_ms": 650,
    "duck_fade_up_ms": 900,
    "restore_volume_after_speech": True,
    "comment_on_song_changes": False,
    "music_awareness_enabled": True,
    "album_art_thumbnail_enabled": True,
    "include_paused_track_context": False,
    "music_response_mode": "subtle",
    "music_awareness_relevance_only": True,
    "proactive_comment_cooldown_seconds": 120,
    "hidden_response_cooldown_seconds": 300,
    "user_music_change_cooldown_seconds": 120,
    "music_context_cache_seconds": 45,
    "allow_playlist_changes": False,
    "allow_queue_changes": False,
    "story_mode_background_music": False,
    "story_music_prefer_ambient": True,
    "story_music_target_volume": 30,
    "story_music_transition_floor_volume": 8,
    "story_music_fade_down_ms": 900,
    "story_music_fade_up_ms": 1400,
    "coding_mode_query": "relaxing focus music",
    "song_change_monitor_enabled": False,
    "debug_logging_enabled": False,
    "hidden_commentary_style_prompt": DEFAULT_HIDDEN_COMMENTARY_STYLE_PROMPT,
    "hidden_sensory_preset_id": "builtin.natural_companion",
    "hidden_sensory_custom_presets": [],
    "hidden_sensory_quick_ids": list(DEFAULT_HIDDEN_SENSORY_QUICK_IDS),
}

TOKEN_KEYS = {"access_token", "refresh_token"}


class SpotifySenseSettings:
    def __init__(self, storage):
        self.storage = storage
        self.path = Path(storage.resolve("config.json")) if storage is not None else None
        self.data = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> dict[str, Any]:
        if self.storage is None:
            return dict(self.data)
        try:
            payload = self.storage.read_json("config.json")
            if isinstance(payload, dict):
                merged = dict(DEFAULT_SETTINGS)
                merged.update(payload)
                self.data = _sanitize(merged)
        except Exception:
            self.data = dict(DEFAULT_SETTINGS)
        return dict(self.data)

    def save(self) -> None:
        if self.storage is None:
            return
        payload = _sanitize(dict(self.data))
        self.storage.write_json("config.json", payload)

    def update(self, **values) -> dict[str, Any]:
        self.data.update(values)
        self.data = _sanitize(self.data)
        self.save()
        return dict(self.data)

    def public_summary(self) -> dict[str, Any]:
        summary = {key: value for key, value in self.data.items() if key not in TOKEN_KEYS}
        summary["connected"] = bool(self.data.get("access_token") and self.data.get("refresh_token"))
        summary["token_expires_in_seconds"] = max(0, int(float(self.data.get("expires_at", 0) or 0) - time.time()))
        return summary


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(DEFAULT_SETTINGS)
    data.update(dict(payload or {}))
    data["enabled"] = bool(data.get("enabled", False))
    data["allow_llm_control"] = bool(data.get("allow_llm_control", False))
    data["require_confirmation"] = bool(data.get("require_confirmation", True))
    mode = str(data.get("autonomous_music", "off") or "off").strip().lower()
    data["autonomous_music"] = mode if mode in {"off", "routines", "full"} else "off"
    response_mode = str(data.get("music_response_mode", "subtle") or "subtle").strip().lower().replace(" ", "_").replace("/", "_")
    data["music_response_mode"] = response_mode if response_mode in {"off", "subtle", "companion", "dj_critic", "story_soundtrack"} else "subtle"
    for key in (
        "duck_while_speaking",
        "restore_volume_after_speech",
        "comment_on_song_changes",
        "music_awareness_enabled",
        "album_art_thumbnail_enabled",
        "include_paused_track_context",
        "music_awareness_relevance_only",
        "allow_playlist_changes",
        "allow_queue_changes",
        "story_mode_background_music",
        "story_music_prefer_ambient",
        "song_change_monitor_enabled",
        "debug_logging_enabled",
    ):
        data[key] = bool(data.get(key, DEFAULT_SETTINGS[key]))
    for key, default, minimum, maximum in (
        ("default_volume", 30, 0, 100),
        ("duck_volume_percent", 15, 0, 100),
        ("duck_fade_down_ms", 650, 0, 5000),
        ("duck_fade_up_ms", 900, 0, 5000),
        ("story_music_target_volume", 30, 0, 100),
        ("story_music_transition_floor_volume", 8, 0, 100),
        ("story_music_fade_down_ms", 900, 0, 8000),
        ("story_music_fade_up_ms", 1400, 0, 8000),
        ("proactive_comment_cooldown_seconds", 120, 15, 3600),
        ("hidden_response_cooldown_seconds", 300, 15, 7200),
        ("user_music_change_cooldown_seconds", 120, 0, 3600),
        ("music_context_cache_seconds", 45, 5, 300),
    ):
        try:
            data[key] = max(minimum, min(maximum, int(data.get(key, default))))
        except Exception:
            data[key] = default
    try:
        data["expires_at"] = int(float(data.get("expires_at", 0) or 0))
    except Exception:
        data["expires_at"] = 0
    if not isinstance(data.get("scopes"), list):
        try:
            data["scopes"] = list(json.loads(str(data.get("scopes") or "[]")))
        except Exception:
            data["scopes"] = []
    data["hidden_commentary_style_prompt"] = (
        _clean_text(data.get("hidden_commentary_style_prompt"), limit=1200)
        or DEFAULT_HIDDEN_COMMENTARY_STYLE_PROMPT
    )
    data["hidden_sensory_preset_id"] = _clean_text(data.get("hidden_sensory_preset_id"), limit=96)
    data["hidden_sensory_custom_presets"] = _sanitize_hidden_sensory_presets(
        data.get("hidden_sensory_custom_presets")
    )
    data["hidden_sensory_quick_ids"] = _sanitize_hidden_sensory_ids(
        data.get("hidden_sensory_quick_ids"),
        fallback=DEFAULT_HIDDEN_SENSORY_QUICK_IDS,
    )
    return data


def _clean_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > limit:
        text = text[:limit].strip()
    return text


def _sanitize_hidden_sensory_presets(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in list(value)[:100]:
        if not isinstance(item, dict):
            continue
        prompt = _clean_text(item.get("prompt"), limit=1200)
        if not prompt:
            continue
        preset_id = _clean_text(item.get("id"), limit=96)
        if not preset_id:
            preset_id = f"custom.hidden_sensory_{len(records) + 1}"
        if preset_id in seen:
            continue
        seen.add(preset_id)
        name = _clean_text(item.get("name"), limit=80) or "Custom Hidden Sensory"
        records.append(
            {
                "id": preset_id,
                "name": name,
                "prompt": prompt,
                "created_at": _clean_text(item.get("created_at"), limit=40),
                "updated_at": _clean_text(item.get("updated_at"), limit=40),
            }
        )
    return records


def _sanitize_hidden_sensory_ids(value: Any, *, fallback: list[str]) -> list[str]:
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = list(fallback)
    ids: list[str] = []
    for item in raw_items:
        preset_id = _clean_text(item, limit=96)
        if preset_id and preset_id not in ids:
            ids.append(preset_id)
        if len(ids) >= 6:
            break
    return ids
