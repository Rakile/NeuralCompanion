"""Continuity memory helpers.

Continuity memory is a compact, chat-session-scoped summary that can be injected
for short-to-medium term recollection. It is intentionally separate from a
future long-term archive/RAG memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import runtime_paths


MEMORY_VERSION = 1
DEFAULT_MAX_CHARS = 3000
DEFAULT_UPDATE_BATCH_TURNS = 120
DEFAULT_TAIL_SUMMARY_TURNS = 500
MEMORY_DIR = runtime_paths.RUNTIME_DIR / "continuity_memory"
LEGACY_MEMORY_PATH = runtime_paths.RUNTIME_DIR / "long_term_memory" / "chat_memory.json"


@dataclass(frozen=True, slots=True)
class ContinuityMemoryBinding:
    memory_id: str
    path: Path


def bind_memory(memory_id: Any = "", path: Path | None = None) -> ContinuityMemoryBinding:
    resolved_id = normalize_memory_id(memory_id, fallback="default")
    target = Path(path) if path is not None else memory_path(resolved_id)
    return ContinuityMemoryBinding(
        memory_id=resolved_id,
        path=target.expanduser().resolve(strict=False),
    )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_memory_id() -> str:
    return f"chat_{uuid.uuid4().hex[:12]}"


def normalize_memory_id(value: Any, *, fallback: str = "") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return fallback
    normalized = re.sub(r"[^a-z0-9_.-]+", "_", raw).strip("._-")
    return normalized[:96] or fallback


def memory_id_from_label(label: Any) -> str:
    normalized = normalize_memory_id(label)
    if normalized:
        return normalized
    digest = hashlib.sha1(str(label or "").encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"chat_{digest}"


def memory_path(memory_id: Any = "") -> Path:
    normalized = normalize_memory_id(memory_id, fallback="default")
    return MEMORY_DIR / f"{normalized}.json"


def normalize_max_chars(value: Any, default: int = DEFAULT_MAX_CHARS) -> int:
    try:
        return max(500, min(20000, int(value)))
    except Exception:
        return default


def compact_text(value: Any, limit: int = 520) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def memory_payload(
    summary: str = "",
    *,
    memory_id: str = "",
    source_turn_count: int = 0,
    updated_at: str = "",
) -> dict[str, Any]:
    return {
        "version": MEMORY_VERSION,
        "memory_id": normalize_memory_id(memory_id, fallback="default"),
        "updated_at": updated_at or _now_iso(),
        "source_turn_count": max(0, int(source_turn_count or 0)),
        "summary": str(summary or "").strip(),
    }


class MemoryRecoveryError(RuntimeError):
    """A damaged memory must be restored or explicitly cleared before writes."""


def load_memory(memory_id: Any = "", path: Path | None = None) -> dict[str, Any]:
    resolved_id = normalize_memory_id(memory_id, fallback="default")
    target = Path(path) if path is not None else memory_path(resolved_id)
    if not target.exists() and path is None and resolved_id == "default" and LEGACY_MEMORY_PATH.exists():
        target = LEGACY_MEMORY_PATH
    payload = None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Memory document must be a JSON object.")
        version = payload.get("version", MEMORY_VERSION)
        if isinstance(version, bool) or version not in (MEMORY_VERSION, str(MEMORY_VERSION)):
            raise ValueError("Memory document has an unsupported version.")
        summary = payload.get("summary", "")
        if summary is not None and not isinstance(summary, str):
            raise ValueError("Memory summary must be text.")
        raw_count = payload.get("source_turn_count", 0)
        if raw_count is None or raw_count == "":
            raw_count = 0
        try:
            if isinstance(raw_count, bool) or not isinstance(raw_count, (int, float, str)):
                raise ValueError
            count = int(raw_count)
            if count < 0 or isinstance(raw_count, float) and raw_count != count:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Memory source_turn_count must be a non-negative integer.") from None
        return memory_payload(
            summary or "",
            memory_id=normalize_memory_id(payload.get("memory_id"), fallback=resolved_id),
            source_turn_count=count,
            updated_at=str(payload.get("updated_at", "") or ""),
        )
    except FileNotFoundError:
        return memory_payload(memory_id=resolved_id, updated_at="")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        summary = payload.get("summary", "") if isinstance(payload, dict) else ""
        recovered = memory_payload(
            summary if isinstance(summary, str) else "", memory_id=resolved_id,
        )
        recovered["recovery_error"] = (
            f"Conversation Memory needs recovery at {target}: {exc} "
            "The file was left unchanged. Updates are paused. Restore a valid file "
            "or explicitly clear Conversation Memory before updating it."
        )
        return recovered


def atomic_write_text(target: Path, text: str) -> Path:
    """Publish a complete memory document without truncating the last good file."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return target


def save_memory(payload: dict[str, Any], memory_id: Any = "", path: Path | None = None) -> Path:
    resolved_id = normalize_memory_id(memory_id or (payload or {}).get("memory_id"), fallback="default")
    target = Path(path) if path is not None else memory_path(resolved_id)
    existing = load_memory(resolved_id, path=path)
    if existing.get("recovery_error"):
        raise MemoryRecoveryError(existing["recovery_error"])
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = memory_payload(
        str((payload or {}).get("summary", "") or ""),
        memory_id=resolved_id,
        source_turn_count=int((payload or {}).get("source_turn_count", 0) or 0),
        updated_at=str((payload or {}).get("updated_at", "") or _now_iso()),
    )
    atomic_write_text(target, json.dumps(normalized, indent=2))
    return target


def clear_memory(memory_id: Any = "", path: Path | None = None) -> Path:
    resolved_id = normalize_memory_id(memory_id, fallback="default")
    target = Path(path) if path is not None else memory_path(resolved_id)
    # This is the explicit reset command; ordinary updates cannot bypass recovery.
    return atomic_write_text(target, json.dumps(memory_payload(memory_id=resolved_id), indent=2))


def sanitize_history_turns(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for turn in list(history or []):
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "") or "").strip().lower()
        if role not in {"user", "assistant", "system"}:
            continue
        content = compact_text(turn.get("content", ""))
        if not content:
            continue
        label = "User" if role == "user" else ("Assistant" if role == "assistant" else "System")
        sanitized.append({"role": role, "label": label, "content": content})
    return sanitized


def unsummarized_turns(history: list[dict[str, Any]], existing: dict[str, Any]) -> list[dict[str, str]]:
    turns = sanitize_history_turns(history)
    previous_count = max(0, int((existing or {}).get("source_turn_count", 0) or 0))
    if previous_count >= len(turns):
        return []
    return turns[previous_count:]


def update_batch_turns(turns: list[dict[str, str]], *, max_turns: int = DEFAULT_UPDATE_BATCH_TURNS) -> list[dict[str, str]]:
    try:
        limit = max(1, int(max_turns))
    except Exception:
        limit = DEFAULT_UPDATE_BATCH_TURNS
    return list(turns or [])[:limit]


def tail_summary_turns(turns: list[dict[str, str]], requested_turns: Any) -> list[dict[str, str]]:
    try:
        limit = int(requested_turns)
    except Exception:
        limit = DEFAULT_TAIL_SUMMARY_TURNS
    limit = max(1, limit)
    return list(turns or [])[-limit:]


def format_turn_segment(turns: list[dict[str, str]]) -> str:
    lines = []
    for turn in list(turns or []):
        lines.append(f"{turn['label']}: {turn['content']}")
    return "\n".join(lines).strip()


def trim_to_budget(text: str, max_chars: int) -> str:
    clean = str(text or "").strip()
    max_chars = normalize_max_chars(max_chars)
    if len(clean) <= max_chars:
        return clean
    marker = "\n...\n"
    keep = max(0, max_chars - len(marker))
    return marker + clean[-keep:].lstrip()


def build_summary_update_messages(existing_summary: str, new_segment: str, *, max_chars: int) -> list[dict[str, str]]:
    budget = normalize_max_chars(max_chars)
    return [
        {
            "role": "system",
            "content": (
                "You update a Continuity Memory summary for a local desktop AI companion. "
                "This is short-to-medium term continuity, not a permanent archive. "
                "Preserve durable facts, user preferences, names, current projects, decisions, "
                "unresolved follow-ups, and important emotional/contextual state. "
                "Remove filler, greetings, applause, transient wording, and duplicate phrasing. "
                "Do not invent facts. If the new segment contradicts old memory, keep the newer "
                "clear fact and remove or qualify the outdated one. "
                f"Return only the updated continuity summary, under {budget} characters."
            ),
        },
        {
            "role": "user",
            "content": (
                "Existing Continuity Memory summary:\n"
                "<<<BEGIN EXISTING SUMMARY>>>\n"
                f"{str(existing_summary or '').strip() or '(empty)'}\n"
                "<<<END EXISTING SUMMARY>>>\n\n"
                "New unsummarized chat segment:\n"
                "<<<BEGIN NEW SEGMENT>>>\n"
                f"{str(new_segment or '').strip() or '(empty)'}\n"
                "<<<END NEW SEGMENT>>>\n\n"
                "Rewrite the Continuity Memory summary now."
            ),
        },
    ]


def build_context(runtime_config: dict[str, Any], *, memory_id: Any = "", path: Path | None = None) -> str:
    enabled = bool((runtime_config or {}).get("continuity_memory_enabled", (runtime_config or {}).get("long_term_memory_enabled", False)))
    if not enabled:
        return ""
    inject = bool((runtime_config or {}).get("continuity_memory_inject", (runtime_config or {}).get("long_term_memory_inject", False)))
    if not inject:
        return ""
    resolved_id = normalize_memory_id(memory_id or (runtime_config or {}).get("continuity_memory_id"), fallback="default")
    payload = load_memory(resolved_id, path=path)
    summary = str(payload.get("summary", "") or "").strip()
    if not summary:
        return ""
    max_chars = normalize_max_chars((runtime_config or {}).get("continuity_memory_max_chars", (runtime_config or {}).get("long_term_memory_max_chars", DEFAULT_MAX_CHARS)))
    summary = trim_to_budget(summary, max_chars)
    return (
        "Continuity Memory summary for this chat session. Treat this as user-approved background "
        "continuity; use it only when relevant and do not quote it verbatim unless asked.\n\n"
        f"{summary}"
    )
