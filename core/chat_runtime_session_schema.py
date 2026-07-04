from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Mapping


SESSION_KEY = "chat_runtime"

LEGACY_FIELD_PATHS = OrderedDict(
    (
        ("chat_provider", ("core", "provider")),
        ("chat_provider_settings", ("provider_settings",)),
        ("chat_provider_generation_settings", ("generation_settings",)),
        ("chat_font_size", ("ui", "font_size")),
        ("chat_runtime_expanded", ("ui", "expanded")),
        ("allow_proactive_replies", ("proactive", "allow_replies")),
        ("require_first_user_before_proactive", ("proactive", "require_first_user")),
        ("listen_idle_window_seconds", ("proactive", "listen_idle_window_seconds")),
        ("proactive_delay_seconds", ("proactive", "delay_seconds")),
        ("chat_context_window_messages", ("context", "window_messages")),
        ("stored_chat_history_limit", ("context", "stored_history_limit")),
        ("chat_context_overflow_policy", ("context", "overflow_policy")),
        ("spellcheck_enabled", ("spellcheck", "enabled")),
        ("spellcheck_language", ("spellcheck", "language")),
        ("continuity_memory_id", ("memory", "id")),
        ("active_chat_context_path", ("memory", "active_chat_context_path")),
        ("active_chat_context_name", ("memory", "active_chat_context_name")),
        ("continuity_memory_enabled", ("memory", "enabled")),
        ("continuity_memory_auto_summarize", ("memory", "auto_summarize")),
        ("continuity_memory_auto_turns", ("memory", "auto_turns")),
        ("continuity_memory_inject", ("memory", "inject")),
        ("continuity_memory_max_chars", ("memory", "max_chars")),
        ("long_term_memory_retrieval_enabled", ("archive", "retrieval_enabled")),
        ("long_term_memory_retrieval_max_items", ("archive", "retrieval_max_items")),
        ("long_term_memory_recall_image_limit", ("archive", "recall_image_limit")),
        ("long_term_memory_auto_archive_enabled", ("archive", "auto_archive_enabled")),
        ("long_term_memory_archive_batch_turns", ("archive", "batch_turns")),
        ("long_term_memory_embedding_enabled", ("archive", "embedding_enabled")),
        ("long_term_memory_embedding_model", ("archive", "embedding_model")),
        ("long_term_memory_embedding_context_length", ("archive", "embedding_context_length")),
        ("long_term_memory_embedding_base_url", ("archive", "embedding_base_url")),
        ("limit_response_length", ("response", "limit_length")),
        ("max_response_tokens", ("response", "max_tokens")),
    )
)

LEGACY_ALIASES = {
    "long_term_memory_enabled": "continuity_memory_enabled",
    "long_term_memory_update_on_save": "continuity_memory_auto_summarize",
    "continuity_memory_update_on_save": "continuity_memory_auto_summarize",
    "long_term_memory_inject": "continuity_memory_inject",
    "long_term_memory_max_chars": "continuity_memory_max_chars",
}

GENERATION_DEFAULT_KEYS = ("temperature", "top_p", "top_k", "repeat_penalty", "min_p")

MODEL_STATE_KEYS = (
    "model_name",
    "model_requires_vision",
    "model_supports_images",
    "model_supports_reasoning",
    "model_supports_reasoning_toggle",
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


def normalize_chat_runtime_settings(session_or_settings) -> dict:
    source = _mapping(session_or_settings)
    grouped = _mapping(source.get(SESSION_KEY))
    if not grouped and any(key in source for key in LEGACY_FIELD_PATHS):
        grouped = {}
    else:
        grouped = copy.deepcopy(grouped)

    for old_key, new_key in LEGACY_ALIASES.items():
        if old_key in source and new_key not in source:
            source[new_key] = source.get(old_key)

    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        if legacy_key in source and _nested_get(grouped, path) is _MISSING:
            _nested_set(grouped, path, source.get(legacy_key))

    provider_value = _nested_get(grouped, ("core", "provider"))
    provider = str("" if provider_value is _MISSING else provider_value or "").strip().lower()
    if provider:
        provider_settings = _mapping(grouped.get("provider_settings"))
        provider_values = _mapping(provider_settings.get(provider))
        for key in MODEL_STATE_KEYS:
            legacy_value = source.get(key, _MISSING)
            old_grouped_value = _nested_get(grouped, ("core", key))
            if key not in provider_values:
                if legacy_value is not _MISSING:
                    provider_values[key] = copy.deepcopy(legacy_value)
                elif old_grouped_value is not _MISSING:
                    provider_values[key] = copy.deepcopy(old_grouped_value)
        if provider_values:
            provider_settings[provider] = provider_values
            grouped["provider_settings"] = provider_settings
        core = _mapping(grouped.get("core"))
        for key in MODEL_STATE_KEYS:
            core.pop(key, None)
        if core:
            grouped["core"] = core
        else:
            grouped.pop("core", None)

        generation_settings = _mapping(grouped.get("generation_settings"))
        generation_values = _mapping(generation_settings.get(provider))
        old_generation_defaults = _mapping(grouped.get("generation_defaults"))
        for key in GENERATION_DEFAULT_KEYS:
            if key in generation_values:
                continue
            if key in source:
                generation_values[key] = copy.deepcopy(source.get(key))
            elif key in old_generation_defaults:
                generation_values[key] = copy.deepcopy(old_generation_defaults.get(key))
        if generation_values:
            generation_settings[provider] = generation_values
            grouped["generation_settings"] = generation_settings
        grouped.pop("generation_defaults", None)

    return grouped


def flatten_chat_runtime_settings(session_or_settings) -> dict:
    grouped = normalize_chat_runtime_settings(session_or_settings)
    flattened = {}
    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        value = _nested_get(grouped, path)
        if value is not _MISSING:
            flattened[legacy_key] = copy.deepcopy(value)
    grouped_provider_value = _nested_get(grouped, ("core", "provider"))
    provider = str(
        flattened.get("chat_provider")
        or ("" if grouped_provider_value is _MISSING else grouped_provider_value)
        or ""
    ).strip().lower()
    if provider:
        provider_values = _mapping(_mapping(grouped.get("provider_settings")).get(provider))
        for key in MODEL_STATE_KEYS:
            if key in provider_values:
                flattened[key] = copy.deepcopy(provider_values.get(key))
        generation_values = _mapping(_mapping(grouped.get("generation_settings")).get(provider))
        for key in GENERATION_DEFAULT_KEYS:
            if key in generation_values:
                flattened[key] = copy.deepcopy(generation_values.get(key))
    return flattened


def chat_runtime_session_value(session_or_settings, legacy_key: str, default=None):
    key = str(legacy_key or "")
    if key in MODEL_STATE_KEYS or key in GENERATION_DEFAULT_KEYS:
        return flatten_chat_runtime_settings(session_or_settings).get(key, default)
    path = LEGACY_FIELD_PATHS.get(key)
    if path is None:
        return default
    grouped = normalize_chat_runtime_settings(session_or_settings)
    value = _nested_get(grouped, path)
    if value is _MISSING:
        return default
    return value


def group_chat_runtime_session(session: Mapping) -> dict:
    payload = dict(session or {})
    grouped = normalize_chat_runtime_settings(payload)
    for key in LEGACY_FIELD_PATHS:
        payload.pop(key, None)
    for key in LEGACY_ALIASES:
        payload.pop(key, None)
    for key in GENERATION_DEFAULT_KEYS:
        payload.pop(key, None)
    for key in MODEL_STATE_KEYS:
        payload.pop(key, None)
    if grouped:
        payload[SESSION_KEY] = grouped
    else:
        payload.pop(SESSION_KEY, None)
    return payload


def with_flat_chat_runtime_settings(session: Mapping) -> dict:
    payload = dict(session or {})
    payload.update(flatten_chat_runtime_settings(payload))
    return payload
