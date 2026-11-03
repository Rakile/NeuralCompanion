"""Saved Persona overrides resolved into request-local config, never global settings."""
from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from core.provider_prompt_rules import normalize_rules


def normalize_persona_overrides(value) -> dict:
    source = value if isinstance(value, Mapping) else {}
    count = source.get("context_messages", 20)
    try:
        if isinstance(count, bool) or (isinstance(count, float) and not count.is_integer()):
            raise ValueError
        count = int(count)
        if count < 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        if source.get("context_enabled") is True:
            raise ValueError("Persona context messages must be a whole number of zero or more.") from None
        count = 20
    mode = str(source.get("document_memory") or "inherit").strip().lower()
    if mode not in {"inherit", "enabled", "disabled"}:
        raise ValueError("Choose Use defaults, Enabled, or Disabled for Document Memory.")
    package_id = source.get("document_package_id", "")
    if package_id is None:
        package_id = ""
    if not isinstance(package_id, str):
        raise ValueError("Choose one existing document package or use the configured default.")
    package_id = package_id.strip()
    if len(package_id) > 128 or any(ord(char) < 32 for char in package_id):
        raise ValueError("The Persona document package reference is invalid.")
    result = {
        "llm_enabled": source.get("llm_enabled") is True,
        "llm_provider": str(source.get("llm_provider") or "").strip().lower(),
        "llm_model": str(source.get("llm_model") or "").strip(),
        "context_enabled": source.get("context_enabled") is True,
        "context_messages": count,
        "document_memory": mode,
        "document_package_id": package_id,
        "document_package_name": str(source.get("document_package_name") or "").strip()[:160] if package_id else "",
    }
    if "technical_rules" in source:
        result["technical_rules"] = normalize_rules(source["technical_rules"])
    # Missing/empty values inherit the provider settings in legacy records.
    for key in ("liquidai_tts_voice", "liquidai_tts_language"):
        selection = source.get(key)
        if selection is None:
            continue
        if not isinstance(selection, str) or any(ord(char) < 32 for char in selection):
            raise ValueError("The Persona LiquidAI voice or language selection is invalid.")
        selection = selection.strip()
        if selection:
            result[key] = selection
    return result


def apply_persona_overrides(config, overrides) -> dict:
    result = dict(config or {})
    value = normalize_persona_overrides(overrides)
    if str(result.get("tts_backend") or "").strip().lower() == "liquidai":
        for key in ("liquidai_tts_voice", "liquidai_tts_language"):
            if key in value:
                result[key] = value[key]
    # Replace, never inherit another persona's request-local rules.
    result.pop('_persona_technical_rules', None)
    if 'technical_rules' in value:
        result['_persona_technical_rules'] = value['technical_rules']
    if value["llm_enabled"]:
        if not value["llm_provider"] or not value["llm_model"]:
            raise ValueError("Choose both a provider and model for this Persona's language model override.")
        result["_persona_llm_provider"] = value["llm_provider"]
        result["chat_provider"] = value["llm_provider"]
        result["model_name"] = value["llm_model"]
    if value["context_enabled"]:
        result["_persona_context_messages"] = value["context_messages"]
        result["chat_context_window_messages"] = value["context_messages"]
    if value["document_memory"] != "inherit":
        result["_persona_document_memory"] = value["document_memory"] == "enabled"
    if value["document_package_id"]:
        result["_persona_document_package_id"] = value["document_package_id"]
    return result


def resolve_persona_reply_settings(runtime_config, chat=None, overrides=None, *, local_room=False):
    """Describe the same request policy without changing defaults or activating providers."""
    config = dict(runtime_config or {})
    chat = chat if isinstance(chat, Mapping) else {}
    value = normalize_persona_overrides(overrides)

    def setting_bool(key, default=True):
        setting = chat.get(key)
        if setting is None:
            return default
        if isinstance(setting, str):
            return setting.strip().lower() not in {"", "0", "false", "no", "off"}
        return bool(setting)

    provider_source = model_source = "global"
    if not setting_bool("use_global_model"):
        provider = str(chat.get("provider") or "").strip().lower()
        model = str(chat.get("model_name") or "").strip()
        if provider:
            config["chat_provider"] = provider
            provider_source = "participant"
        if model:
            config["model_name"] = model
            model_source = "participant"
    if local_room:
        try:
            config["chat_context_window_messages"] = max(0, int(chat.get("context_entries", 20)))
        except (TypeError, ValueError, OverflowError):
            config["chat_context_window_messages"] = 20
    elif not value["context_enabled"]:
        from core.conversation_history import chat_context_window_messages
        config["chat_context_window_messages"] = chat_context_window_messages(config)
    config = apply_persona_overrides(config, value)
    if value["llm_enabled"]:
        provider_source = model_source = "persona"
    enabled = None
    memory_source = "document_default"
    if not setting_bool("use_selected_rag_context"):
        enabled, memory_source = False, "participant"
    if value["document_memory"] != "inherit":
        enabled = value["document_memory"] == "enabled"
        memory_source = "persona"
    return {
        "provider": str(config.get("chat_provider") or ""),
        "model": str(config.get("model_name") or ""),
        "provider_source": provider_source,
        "model_source": model_source,
        "context_messages": config.get("chat_context_window_messages", 20),
        "context_source": "persona" if value["context_enabled"] else "room" if local_room else "global",
        "document_memory_enabled": enabled,
        "document_memory_source": memory_source,
        "document_package_id": value["document_package_id"],
        "document_package_name": value["document_package_name"],
        "document_package_source": "persona" if value["document_package_id"] else "document_default",
    }


@lru_cache(maxsize=8)
def _read_library(path: str, modified: int, size: int):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("personas", {}), dict):
        raise ValueError("The saved Persona library is invalid.")
    return data


def read_persona_overrides(app_root, persona_id="", *, active=False) -> dict:
    path = Path(app_root) / "runtime" / "quick_personas.json"
    identity = str(persona_id or "").strip()
    try:
        stat = path.stat()
    except FileNotFoundError:
        if identity:
            raise ValueError(f"Persona {identity!r} is unavailable.") from None
        return normalize_persona_overrides({})
    data = _read_library(str(path), stat.st_mtime_ns, stat.st_size)
    records = data.get("personas", {})
    if identity:
        record = next((item for item in records.values() if isinstance(item, Mapping) and item.get("id") == identity), None)
        if record is None:
            raise ValueError(f"Persona {identity!r} is unavailable.")
    elif active:
        record = records.get(str(data.get("active_slot")))
    else:
        record = None
    return normalize_persona_overrides(record.get("overrides") if isinstance(record, Mapping) else {})
