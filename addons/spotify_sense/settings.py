from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


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
    "restore_volume_after_speech": True,
    "comment_on_song_changes": False,
    "music_awareness_enabled": True,
    "include_paused_track_context": False,
    "music_response_mode": "subtle",
    "music_awareness_relevance_only": True,
    "proactive_comment_cooldown_seconds": 120,
    "music_context_cache_seconds": 45,
    "allow_playlist_changes": False,
    "allow_queue_changes": False,
    "story_mode_background_music": False,
    "coding_mode_query": "relaxing focus music",
    "song_change_monitor_enabled": False,
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
        "include_paused_track_context",
        "music_awareness_relevance_only",
        "allow_playlist_changes",
        "allow_queue_changes",
        "story_mode_background_music",
        "song_change_monitor_enabled",
    ):
        data[key] = bool(data.get(key, DEFAULT_SETTINGS[key]))
    for key, default, minimum, maximum in (
        ("default_volume", 30, 0, 100),
        ("duck_volume_percent", 15, 0, 100),
        ("proactive_comment_cooldown_seconds", 120, 15, 3600),
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
    return data
