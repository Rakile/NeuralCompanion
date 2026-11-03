"""Pure chat-session compatibility projection and import planning."""

from __future__ import annotations

from core.image_attachments import image_paths, set_image_paths

import copy
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from core import conversation_history as conversation_history_runtime
from core import continuity_memory, long_term_memory, visual_reply_history
from core.runtime.auto_reply_guidance import normalize_auto_reply_guidance


RelayMetadataSanitizer = Callable[[object], Mapping[str, object] | None]
RelayRegistrySanitizer = Callable[[object], Mapping[str, Mapping[str, object]]]
SensoryEventSanitizer = Callable[[object], Mapping[str, object] | None]


def sanitize_chat_turn(
    entry: object,
    *,
    sanitize_relay_metadata: RelayMetadataSanitizer,
    preserve_transaction_id: bool = False,
) -> dict[str, object] | None:
    """Return one stable persisted turn without mutating the source."""

    if not isinstance(entry, Mapping):
        return None
    role = str(entry.get("role", "") or "").strip().lower()
    if role not in {"user", "system", "assistant"}:
        return None
    attachments = image_paths(entry)
    attachment_path = attachments[0] if attachments else ""
    content = str(entry.get("content", "") or "").strip()
    if not content and not attachment_path:
        return None
    if not content:
        content = "Please respond to the image I just sent you."
    origin = str(entry.get("origin", "") or "").strip().lower()
    if origin not in {"input", "assistant_reply"}:
        origin = "assistant_reply" if role == "assistant" else "input"

    reserved = {
        "role",
        "content",
        "origin",
        "created_at",
        "attachment_image_path",
        "attachment_image_paths",
        "attachment_source",
        "identity_relay",
        "normal_chat_transaction_id",
        "hidden_proactive",
        "remote_capture_id",
        "auto_reply_guidance",
    }
    for field_name in visual_reply_history.VISUAL_REPLY_IMAGE_FIELDS:
        reserved.add(field_name)
        reserved.add(f"{field_name}_source")
    reserved.update(visual_reply_history.VISUAL_REPLY_METADATA_FIELDS)
    turn = {
        str(key): copy.deepcopy(value)
        for key, value in entry.items()
        if str(key) not in reserved
    }
    turn.update({"role": role, "content": content, "origin": origin})
    created_at = conversation_history_runtime.coerce_turn_created_at(
        entry.get("created_at")
    )
    if created_at is not None:
        turn["created_at"] = created_at
    if attachment_path:
        set_image_paths(turn, attachments)
        attachment_source = str(entry.get("attachment_source", "") or "").strip().lower()
        if attachment_source:
            turn["attachment_source"] = attachment_source
    relay = sanitize_relay_metadata(entry.get("identity_relay"))
    if relay is not None:
        turn["identity_relay"] = copy.deepcopy(dict(relay))
    if preserve_transaction_id:
        transaction_id = str(entry.get("normal_chat_transaction_id") or "").strip()
        if re.fullmatch(r"[0-9a-f]{32}", transaction_id):
            turn["normal_chat_transaction_id"] = transaction_id
    if bool(entry.get("hidden_proactive", False)):
        turn["hidden_proactive"] = True
    remote_capture_id = re.sub(
        r"[^A-Za-z0-9_-]+", "", str(entry.get("remote_capture_id") or "")
    )[:96]
    if remote_capture_id:
        turn["remote_capture_id"] = remote_capture_id
    direction = normalize_auto_reply_guidance(entry.get("auto_reply_guidance"))
    if role == "user" and direction is not None:
        turn["auto_reply_guidance"] = direction
    visual_reply_history.preserve_visual_reply_image_fields(turn, entry)
    return turn


def reconstruct_input_turn(
    entry: object,
    *,
    sanitize_relay_metadata: RelayMetadataSanitizer,
) -> dict[str, object] | None:
    """Reconstruct only fields accepted by the pending-input pipeline."""

    turn = sanitize_chat_turn(
        entry,
        sanitize_relay_metadata=sanitize_relay_metadata,
        preserve_transaction_id=True,
    )
    if turn is None:
        return None
    retained = (
        "role",
        "content",
        "origin",
        "created_at",
        "attachment_image_path",
        "attachment_image_paths",
        "attachment_source",
        "normal_chat_output_token_cap",
        "companion_orb_response_guidance",
        "auto_reply_guidance",
        "companion_orb_debug_trace_id",
        "identity_relay",
        "normal_chat_transaction_id",
        "remote_capture_id",
    )
    return {key: turn[key] for key in retained if key in turn}


@dataclass(frozen=True, slots=True)
class ChatSessionExportData:
    saved_at: float
    passthrough: Mapping[str, object]
    config: Mapping[str, object]
    history: Sequence[Mapping[str, object]]
    assistant_memory: Mapping[str, object]
    sensory_hidden_history: Sequence[Mapping[str, object]]
    relay_session: Mapping[str, object]
    relay_snapshots: Mapping[str, Mapping[str, object]]


def build_chat_session_payload(data: ChatSessionExportData) -> dict[str, object]:
    """Build the version-1 session payload from one frozen snapshot."""

    config = dict(data.config or {})
    from core.runtime.embedding_provider import baseline_model, provider_id
    embedding_provider = provider_id(config.get('long_term_memory_embedding_provider'))
    embedding_model = str(
        config.get("long_term_memory_embedding_model", "text-embedding-bge-m3")
        or "text-embedding-bge-m3"
    )
    embedding_context = int(
        config.get("long_term_memory_embedding_context_length", 8192) or 8192
    )
    session_model = str(
        config.get("long_term_memory_embedding_session_model", "") or ""
    ).strip() or baseline_model(embedding_provider, embedding_model)
    session_context = int(
        config.get("long_term_memory_embedding_session_context_length", 0) or 0
    ) or embedding_context
    payload = copy.deepcopy(dict(data.passthrough or {}))
    payload.update(
        {
            "version": 1,
            "conversation_format_version": conversation_history_runtime.CONVERSATION_FORMAT_VERSION,
            "saved_at": float(data.saved_at),
            "chat_character_conversation_id": str(config.get("chat_character_conversation_id", "") or ""),
            "continuity_memory_id": str(config.get("continuity_memory_id", "") or ""),
            "continuity_memory_enabled": bool(config.get("continuity_memory_enabled", False)),
            "continuity_memory_auto_summarize": bool(
                config.get(
                    "continuity_memory_auto_summarize",
                    config.get("continuity_memory_update_on_save", False),
                )
            ),
            "continuity_memory_auto_turns": int(
                config.get(
                    "continuity_memory_auto_turns",
                    continuity_memory.DEFAULT_UPDATE_BATCH_TURNS,
                )
                or continuity_memory.DEFAULT_UPDATE_BATCH_TURNS
            ),
            "continuity_memory_inject": bool(config.get("continuity_memory_inject", False)),
            "continuity_memory_max_chars": int(
                config.get("continuity_memory_max_chars", continuity_memory.DEFAULT_MAX_CHARS)
                or continuity_memory.DEFAULT_MAX_CHARS
            ),
            "long_term_memory_retrieval_enabled": bool(
                config.get("long_term_memory_retrieval_enabled", False)
            ),
            "long_term_memory_retrieval_max_items": int(
                config.get("long_term_memory_retrieval_max_items", 6) or 6
            ),
            "long_term_memory_recall_text_budget": long_term_memory.normalize_recall_text_budget(
                config.get("long_term_memory_recall_text_budget", -1), default=-1
            ),
            "long_term_memory_recall_image_limit": long_term_memory.normalize_image_recall_limit(
                config.get("long_term_memory_recall_image_limit", 1), default=1
            ),
            "long_term_memory_image_context_max_output_tokens": long_term_memory.normalize_image_context_max_output_tokens(
                config.get(
                    "long_term_memory_image_context_max_output_tokens",
                    long_term_memory.DEFAULT_IMAGE_CONTEXT_MAX_OUTPUT_TOKENS,
                )
            ),
            "long_term_memory_auto_archive_enabled": bool(
                config.get("long_term_memory_auto_archive_enabled", False)
            ),
            "long_term_memory_archive_batch_turns": int(
                config.get(
                    "long_term_memory_archive_batch_turns",
                    long_term_memory.DEFAULT_EXTRACTION_TURNS,
                )
                or long_term_memory.DEFAULT_EXTRACTION_TURNS
            ),
            "long_term_memory_embedding_enabled": bool(
                config.get("long_term_memory_embedding_enabled", False)
            ),
            "long_term_memory_embedding_model": embedding_model,
            "long_term_memory_embedding_provider": embedding_provider,
            "long_term_memory_embedding_context_length": embedding_context,
            "long_term_memory_embedding_base_url": str(
                config.get(
                    "long_term_memory_embedding_base_url",
                    "http://127.0.0.1:1234/v1",
                )
                or "http://127.0.0.1:1234/v1"
            ),
            "long_term_memory_embedding_session_model": session_model,
            "long_term_memory_embedding_session_context_length": session_context,
            "identity_relay_session": copy.deepcopy(dict(data.relay_session or {})),
            "identity_relay_snapshots": copy.deepcopy(dict(data.relay_snapshots or {})),
            "conversation_history": copy.deepcopy(list(data.history or ())),
            "assistant_memory": json.loads(
                json.dumps(dict(data.assistant_memory or {}))
            ),
            "sensory_hidden_history": copy.deepcopy(
                list(data.sensory_hidden_history or ())
            ),
        }
    )
    return payload


@dataclass(frozen=True, slots=True)
class ChatSessionImportPlan:
    passthrough: Mapping[str, object]
    relay_snapshots: Mapping[str, Mapping[str, object]]
    relay_session: Mapping[str, object]
    embedding_model: str
    embedding_context_length: int
    continuity_memory_id: str
    history: Sequence[Mapping[str, object]]
    conversation_migration: Mapping[str, object]
    assistant_memory: Mapping[str, object]
    sensory_hidden_history: Sequence[Mapping[str, object]]


def plan_chat_session_import(
    payload: object,
    *,
    sanitize_relay_registry: RelayRegistrySanitizer,
    sanitize_sensory_event: SensoryEventSanitizer,
    default_assistant_memory: Callable[[], Mapping[str, object]],
    fallback_embedding_model: str,
    fallback_embedding_context_length: int,
) -> ChatSessionImportPlan:
    """Validate and freeze all data before a mutating session transition begins."""

    if not isinstance(payload, Mapping):
        raise ValueError("Chat session payload must be a JSON object")
    raw_history, migration = conversation_history_runtime.migrate_conversation_history_content(
        payload.get("conversation_history", []),
        source_version=payload.get("conversation_format_version", 0),
    )
    raw_memory = payload.get("assistant_memory")
    memory = (
        json.loads(json.dumps(dict(raw_memory)))
        if isinstance(raw_memory, Mapping)
        else copy.deepcopy(dict(default_assistant_memory()))
    )
    memory.setdefault("preferences", {})
    memory.setdefault("recent_context", [])
    sensory_history = tuple(
        item
        for item in (
            sanitize_sensory_event(entry)
            for entry in list(payload.get("sensory_hidden_history", []) or [])
        )
        if item is not None
    )
    model = str(
        payload.get(
            "long_term_memory_embedding_session_model",
            payload.get("long_term_memory_embedding_model", fallback_embedding_model),
        )
        or fallback_embedding_model
    ).strip()
    context_length = int(
        payload.get(
            "long_term_memory_embedding_session_context_length",
            payload.get(
                "long_term_memory_embedding_context_length",
                fallback_embedding_context_length,
            ),
        )
        or fallback_embedding_context_length
    )
    memory_id = continuity_memory.normalize_memory_id(
        payload.get("continuity_memory_id")
    )
    relay_session = payload.get("identity_relay_session")
    return ChatSessionImportPlan(
        passthrough=copy.deepcopy(dict(payload)),
        relay_snapshots=copy.deepcopy(
            dict(sanitize_relay_registry(payload.get("identity_relay_snapshots")))
        ),
        relay_session=copy.deepcopy(
            dict(relay_session) if isinstance(relay_session, Mapping) else {}
        ),
        embedding_model=model,
        embedding_context_length=context_length,
        continuity_memory_id=memory_id,
        history=tuple(copy.deepcopy(list(raw_history or ()))),
        conversation_migration=copy.deepcopy(dict(migration or {})),
        assistant_memory=memory,
        sensory_hidden_history=sensory_history,
    )


__all__ = [
    "ChatSessionExportData",
    "ChatSessionImportPlan",
    "build_chat_session_payload",
    "plan_chat_session_import",
    "reconstruct_input_turn",
    "sanitize_chat_turn",
]
