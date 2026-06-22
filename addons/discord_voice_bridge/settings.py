from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


ADDON_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS_PATH = ADDON_DIR / "settings.example.json"
LOCAL_SETTINGS_PATH = ADDON_DIR / "settings.local.json"
SETTINGS_SCHEMA_PATH = ADDON_DIR / "settings_schema.json"


def load_settings() -> dict[str, Any]:
    settings = _read_json(DEFAULT_SETTINGS_PATH)
    local = _read_json(LOCAL_SETTINGS_PATH, missing_ok=True)
    if isinstance(local, dict):
        settings = _deep_merge(settings, local)
    return settings


def load_local_settings() -> dict[str, Any]:
    return _read_json(LOCAL_SETTINGS_PATH, missing_ok=True)


def save_local_settings(updates: dict[str, Any], *, allow_secret_updates: bool = False) -> dict[str, Any]:
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
    with LOCAL_SETTINGS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    return load_settings()


def load_settings_schema() -> dict[str, Any]:
    return _read_json(SETTINGS_SCHEMA_PATH)


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
