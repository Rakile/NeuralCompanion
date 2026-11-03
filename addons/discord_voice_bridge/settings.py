from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


ADDON_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS_PATH = ADDON_DIR / "settings.example.json"
LOCAL_SETTINGS_PATH = ADDON_DIR / "settings.local.json"
SETTINGS_SCHEMA_PATH = ADDON_DIR / "settings_schema.json"
LOCAL_ROOM_DEFAULTS_PATH = ADDON_DIR / "local_room_defaults.json"
LOCAL_ROOM_SEED_STATE_KEY = "local_room_cast_seed"


# One authoritative configuration per process. Disk is persistence; callers get
# isolated copies, and successful saves publish the new state under the same lock.
_SETTINGS_LOCK = threading.RLock()
_SETTINGS_CACHE = None
_SCHEMA_CACHE = None


def _settings_state(*, reload=False):
    global _SETTINGS_CACHE
    key = (str(DEFAULT_SETTINGS_PATH), str(LOCAL_SETTINGS_PATH))
    if reload or _SETTINGS_CACHE is None or _SETTINGS_CACHE[0] != key:
        defaults = _read_json(DEFAULT_SETTINGS_PATH)
        local = _read_json(LOCAL_SETTINGS_PATH, missing_ok=True)
        effective = _deep_merge(defaults, local)
        _SETTINGS_CACHE = (key, defaults, local, effective)
    return _SETTINGS_CACHE


def load_settings() -> dict[str, Any]:
    with _SETTINGS_LOCK:
        return copy.deepcopy(_settings_state()[3])


def load_local_settings() -> dict[str, Any]:
    with _SETTINGS_LOCK:
        return copy.deepcopy(_settings_state()[2])


def reload_settings() -> dict[str, Any]:
    """Explicitly import outside edits; failed reloads retain the last good state."""
    with _SETTINGS_LOCK:
        return copy.deepcopy(_settings_state(reload=True)[3])


def ensure_local_room_bots() -> dict[str, Any]:
    """Seed the editable Local room cast once, then leave saved bots untouched."""
    defaults = _read_json(LOCAL_ROOM_DEFAULTS_PATH)
    version = int(defaults.get("version") or 1)
    local = load_local_settings()
    state = local.get(LOCAL_ROOM_SEED_STATE_KEY)
    if isinstance(state, dict) and int(state.get("version") or 0) >= version:
        return load_settings()

    loaded = load_settings()
    bots = [copy.deepcopy(item) for item in list(loaded.get("bots") or []) if isinstance(item, dict)]
    occupied_ids = {str(item.get("id") or "").strip().lower() for item in bots}
    occupied_roles = {
        str(item.get("local_room_role") or "").strip().lower()
        for item in bots
        if str(item.get("local_room_role") or "").strip()
    }
    for raw in list(defaults.get("bots") or []):
        if not isinstance(raw, dict):
            continue
        bot = copy.deepcopy(raw)
        role = str(bot.get("local_room_role") or "").strip().lower()
        if not role or role in occupied_roles:
            continue
        preferred_id = str(bot.get("id") or f"local_room_{role}").strip()
        bot["id"] = _available_bot_id(preferred_id, occupied_ids)
        bots.append(bot)
        occupied_ids.add(bot["id"].lower())
        occupied_roles.add(role)

    return save_local_settings(
        {
            "bots": bots,
            LOCAL_ROOM_SEED_STATE_KEY: {"version": version},
        },
        allow_secret_updates=True,
    )


def save_local_settings(updates: dict[str, Any], *, allow_secret_updates: bool = False) -> dict[str, Any]:
    with _SETTINGS_LOCK:
        local = load_local_settings()
        if not isinstance(local, dict):
            local = {}
        clean_updates = copy.deepcopy(updates if isinstance(updates, dict) else {})
        if allow_secret_updates:
            _drop_empty_secret_fields(clean_updates)
        else:
            _drop_secret_fields(clean_updates)
        merged = _deep_merge(local, clean_updates)
        _restore_existing_secret_fields(local, merged)
        LOCAL_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                    dir=LOCAL_SETTINGS_PATH.parent, prefix=LOCAL_SETTINGS_PATH.name + '.', suffix='.tmp', delete=False) as handle:
                temporary_path = Path(handle.name)
                json.dump(merged, handle, indent=2, ensure_ascii=True)
                handle.write("\n")
            for attempt in range(6):
                try:
                    os.replace(temporary_path, LOCAL_SETTINGS_PATH)
                    break
                except PermissionError as error:
                    # Windows readers/scanners can briefly block an atomic replace,
                    # even when the destination is writable. Keep the old file intact.
                    if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 5:
                        raise
                    time.sleep(.01 * (2 ** attempt))
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        global _SETTINGS_CACHE
        key, defaults, _, _ = _settings_state()
        effective = _deep_merge(defaults, merged)
        _SETTINGS_CACHE = (key, defaults, merged, effective)
        return copy.deepcopy(effective)


def load_settings_schema() -> dict[str, Any]:
    global _SCHEMA_CACHE
    with _SETTINGS_LOCK:
        key = str(SETTINGS_SCHEMA_PATH)
        if _SCHEMA_CACHE is None or _SCHEMA_CACHE[0] != key:
            _SCHEMA_CACHE = (key, _read_json(SETTINGS_SCHEMA_PATH))
        return copy.deepcopy(_SCHEMA_CACHE[1])


def _available_bot_id(preferred_id: str, occupied_ids: set[str]) -> str:
    candidate = preferred_id or "local_room_bot"
    if candidate.lower() not in occupied_ids:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}".lower() in occupied_ids:
        suffix += 1
    return f"{candidate}_{suffix}"


def redacted_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    result = copy.deepcopy(settings if settings is not None else load_settings())
    _redact_secrets(result)
    return result


def _redact_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"token", "discord_token", "api_key", "secret"}:
                value[key] = "<redacted>"
            else:
                _redact_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _redact_secrets(child)


def _drop_secret_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key in list(value.keys()):
            if str(key).lower() in {"token", "discord_token", "api_key", "secret"}:
                value.pop(key, None)
            else:
                _drop_secret_fields(value[key])
    elif isinstance(value, list):
        for child in value:
            _drop_secret_fields(child)


def _drop_empty_secret_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key in list(value.keys()):
            if str(key).lower() in {"token", "discord_token", "api_key", "secret"}:
                if not str(value.get(key) or "").strip():
                    value.pop(key, None)
                continue
            _drop_empty_secret_fields(value[key])
    elif isinstance(value, list):
        for child in value:
            _drop_empty_secret_fields(child)


def _restore_existing_secret_fields(source: Any, target: Any) -> None:
    if isinstance(source, dict) and isinstance(target, dict):
        for key, child in source.items():
            if str(key).lower() in {"token", "discord_token", "api_key", "secret"}:
                if key not in target:
                    target[key] = child
                continue
            if key in target:
                _restore_existing_secret_fields(child, target[key])
    elif isinstance(source, list) and isinstance(target, list):
        source_by_id = {
            str(item.get("id") or item.get("name") or ""): item
            for item in source
            if isinstance(item, dict) and (item.get("id") or item.get("name"))
        }
        for index, item in enumerate(target):
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or item.get("name") or "")
            source_item = source_by_id.get(key)
            if source_item is None and index < len(source) and isinstance(source[index], dict):
                source_item = source[index]
            if source_item is not None:
                _restore_existing_secret_fields(source_item, item)


def _read_json(path: Path, *, missing_ok: bool = False) -> dict[str, Any]:
    if missing_ok and not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged
