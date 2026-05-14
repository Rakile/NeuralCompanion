from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Mapping

from addons.visual_reply.providers import PROVIDER_SPECS, provider_settings_from_config


SESSION_KEY = "visual_reply"

LEGACY_FIELD_PATHS = OrderedDict(
    (
        ("visual_reply_mode", ("core", "mode")),
        ("visual_replies_enabled", ("core", "enabled")),
        ("visual_reply_provider", ("core", "provider")),
        ("visual_reply_provider_settings", ("providers", "settings")),
        ("visual_reply_auto_show_dock", ("ui", "auto_show_dock")),
        ("visual_reply_visible", ("ui", "visible")),
        ("visual_reply_master_style_prompt", ("prompt", "master_style")),
        ("visual_reply_master_prompt_safe", ("prompt", "safe")),
        ("visual_reply_master_prompt_no_speech_bubbles", ("prompt", "no_speech_bubbles")),
        ("visual_reply_story_mode", ("story", "enabled")),
        ("visual_reply_story_max_images", ("story", "max_images")),
        ("visual_reply_story_continuity_strength", ("story", "continuity_strength")),
        ("visual_reply_story_theme_prompts", ("story", "theme_prompts")),
        ("visual_reply_story_theme_enabled", ("story", "theme_enabled")),
    )
)

ACTIVE_PROVIDER_LEGACY_FIELDS = {
    "visual_reply_size": "size",
    "visual_reply_model": "model",
}

PROVIDER_LEGACY_FIELD_NAMES = tuple(
    key
    for spec in PROVIDER_SPECS
    for key in (
        spec.legacy_api_key_config_key,
        spec.legacy_model_config_key,
        spec.legacy_size_config_key,
    )
    if key
)

_MISSING = object()


def _mapping(value) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _nested_get(payload: Mapping, path: tuple[str, ...]):
    current = payload
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current.get(part)
    return current


def _nested_set(payload: dict, path: tuple[str, ...], value) -> None:
    current = payload
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = copy.deepcopy(value)


def _merge_missing_provider_settings(target: dict, source: Mapping) -> dict:
    merged = copy.deepcopy(target)
    for provider, values in _mapping(source).items():
        provider_id = str(provider or "").strip().lower()
        if not provider_id:
            continue
        source_values = _mapping(values)
        if not source_values and provider_id not in merged:
            continue
        provider_values = _mapping(merged.get(provider_id))
        for key, value in source_values.items():
            if key not in provider_values:
                provider_values[key] = copy.deepcopy(value)
        merged[provider_id] = provider_values
    return merged


def normalize_visual_reply_settings(session_or_settings) -> dict:
    source = _mapping(session_or_settings)
    grouped = _mapping(source.get(SESSION_KEY))
    legacy_keys = tuple(LEGACY_FIELD_PATHS) + tuple(ACTIVE_PROVIDER_LEGACY_FIELDS) + PROVIDER_LEGACY_FIELD_NAMES
    if not grouped and any(key in source for key in legacy_keys):
        grouped = {}
    else:
        grouped = copy.deepcopy(grouped)

    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        if legacy_key in source and _nested_get(grouped, path) is _MISSING:
            _nested_set(grouped, path, source.get(legacy_key))

    provider_settings = _mapping(_nested_get(grouped, ("providers", "settings")))
    provider_source_keys = ("visual_reply_provider_settings",) + PROVIDER_LEGACY_FIELD_NAMES
    if any(key in source for key in provider_source_keys):
        provider_settings = _merge_missing_provider_settings(provider_settings, provider_settings_from_config(source))

    provider_value = _nested_get(grouped, ("core", "provider"))
    provider = str("" if provider_value is _MISSING else provider_value or source.get("visual_reply_provider", "") or "").strip().lower()
    if provider:
        provider_values = _mapping(provider_settings.get(provider))
        for legacy_key, role in ACTIVE_PROVIDER_LEGACY_FIELDS.items():
            if legacy_key in source and role not in provider_values:
                provider_values[role] = copy.deepcopy(source.get(legacy_key))
        if provider_values:
            provider_settings[provider] = provider_values

    if provider_settings:
        _nested_set(grouped, ("providers", "settings"), provider_settings)

    return grouped


def flatten_visual_reply_settings(session_or_settings) -> dict:
    grouped = normalize_visual_reply_settings(session_or_settings)
    flattened = {}
    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        value = _nested_get(grouped, path)
        if value is not _MISSING:
            flattened[legacy_key] = copy.deepcopy(value)

    mode = str(flattened.get("visual_reply_mode", "") or "").strip().lower()
    if "visual_replies_enabled" not in flattened and mode:
        flattened["visual_replies_enabled"] = mode != "off"

    provider_settings = _mapping(_nested_get(grouped, ("providers", "settings")))
    if provider_settings:
        flattened["visual_reply_provider_settings"] = copy.deepcopy(provider_settings)

    provider = str(flattened.get("visual_reply_provider", "") or "").strip().lower()
    if provider:
        provider_values = _mapping(provider_settings.get(provider))
        if "size" in provider_values:
            flattened["visual_reply_size"] = copy.deepcopy(provider_values.get("size"))
        if "model" in provider_values:
            flattened["visual_reply_model"] = copy.deepcopy(provider_values.get("model"))

    return flattened


def group_visual_reply_session(session: Mapping) -> dict:
    payload = dict(session or {})
    grouped = normalize_visual_reply_settings(payload)
    for key in LEGACY_FIELD_PATHS:
        payload.pop(key, None)
    for key in ACTIVE_PROVIDER_LEGACY_FIELDS:
        payload.pop(key, None)
    for key in PROVIDER_LEGACY_FIELD_NAMES:
        payload.pop(key, None)
    if grouped:
        payload[SESSION_KEY] = grouped
    else:
        payload.pop(SESSION_KEY, None)
    return payload


def with_flat_visual_reply_settings(session: Mapping) -> dict:
    payload = dict(session or {})
    payload.update(flatten_visual_reply_settings(payload))
    return payload
