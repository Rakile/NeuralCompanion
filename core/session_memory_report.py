"""Pure rendering for readable Conversation and Long-Term Memory exports."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


TurnTimestampFormatter = Callable[[Mapping[str, object]], str]


@dataclass(frozen=True, slots=True)
class SessionMemoryReportData:
    """Frozen inputs required to render one memory export."""

    exported_at: str
    chat_context_name: str
    chat_context_path: str
    memory_id: str
    store_path: str
    continuity: Mapping[str, object]
    history: Sequence[Mapping[str, object]]
    records: Sequence[Mapping[str, object]]
    chunks: Sequence[Mapping[str, object]]
    assets_by_target: Mapping[tuple[str, str], Sequence[Mapping[str, object]]]


def default_export_path(
    runtime_dir: str | Path,
    *,
    active_name: str,
    memory_id: str,
    normalized_name: str,
    timestamp: str,
) -> Path:
    """Return the conventional export path from already-resolved values."""

    del active_name, memory_id
    return Path(runtime_dir) / "memory_exports" / (
        f"{normalized_name}_memory_export_{timestamp}.md"
    )


def _asset_lines(assets: Sequence[Mapping[str, object]]) -> list[str]:
    lines: list[str] = []
    for asset_index, asset in enumerate(assets, start=1):
        metadata = dict(asset.get("metadata") or {})
        link_metadata = dict(asset.get("link_metadata") or {})
        lines.extend(
            [
                f"    Asset {asset_index}: {asset.get('asset_id') or asset.get('id') or ''}",
                f"      Role: {asset.get('role', '')}",
                f"      Relation: {asset.get('relation', '')}",
                f"      Source message: {asset.get('source_message_index', '')}",
                f"      Origin: {asset.get('origin', '')}",
                f"      Source: {asset.get('source', '')}",
                f"      MIME: {asset.get('mime_type', '')}",
                f"      SHA256: {asset.get('sha256', '')}",
            ]
        )
        original_path = str(
            metadata.get("original_path") or link_metadata.get("original_path") or ""
        ).strip()
        if original_path:
            lines.append(f"      Original path: {original_path}")
        prompt = str(
            link_metadata.get("visual_reply_prompt")
            or metadata.get("visual_reply_prompt")
            or ""
        ).strip()
        if prompt:
            lines.append(f"      Visualization prompt: {prompt}")
    return lines


def render_session_memory_report(
    data: SessionMemoryReportData,
    *,
    format_turn_timestamp: TurnTimestampFormatter,
) -> str:
    """Render one report without reading globals, databases, or files."""

    continuity = dict(data.continuity or {})
    history = list(data.history or ())
    records = list(data.records or ())
    chunks = list(data.chunks or ())
    lines = [
        "# Session Memory Export",
        "",
        f"Exported: {data.exported_at}",
        f"Chat context: {data.chat_context_name or '(unsaved chat)'}",
        f"Chat context path: {data.chat_context_path or '(none)'}",
        f"Continuity memory id: {data.memory_id}",
        f"Long-Term Memory store: {data.store_path}",
        "",
        "## Conversation Memory",
        "",
        f"Summary characters: {len(str(continuity.get('summary', '') or ''))}",
        f"Summarized messages: {int(continuity.get('source_turn_count', 0) or 0)}",
        "",
        str(continuity.get("summary", "") or "").strip() or "(empty)",
        "",
        "## Long-Term Memory Archive",
        "",
        f"Raw archived chunks: {len(chunks)}",
        f"Extracted records: {len(records)}",
        "",
    ]

    if chunks:
        lines.extend(["### Raw Archived Chat Chunks", ""])
        for index, chunk in enumerate(chunks, start=1):
            chunk_id = str(chunk.get("id", "") or "")
            tags = ", ".join(list(chunk.get("tags") or ()))
            lines.extend(
                [
                    f"#### Chunk {index}: {chunk_id}",
                    "",
                    f"Source: {chunk.get('source_chat_id', '')} messages {chunk.get('source_message_start', '')}-{chunk.get('source_message_end', '')}",
                    f"Status: {chunk.get('status', '')}",
                    f"Created: {chunk.get('created_at', '')}",
                    f"Updated: {chunk.get('updated_at', '')}",
                    f"Tags: {tags or '(none)'}",
                    "",
                    "```text",
                    str(chunk.get("text", "") or "").strip(),
                    "```",
                ]
            )
            asset_lines = _asset_lines(
                data.assets_by_target.get(("chunk", chunk_id), ())
            )
            if asset_lines:
                lines.extend(["", "Linked image assets:", *asset_lines])
            lines.append("")
    else:
        lines.extend(["No raw archived chat chunks.", ""])

    if records:
        lines.extend(["### Extracted Memory Records", ""])
        for index, record in enumerate(records, start=1):
            record_id = str(record.get("id", "") or "")
            tags = ", ".join(list(record.get("tags") or ()))
            lines.extend(
                [
                    f"#### Record {index}: {record.get('title', '') or record_id}",
                    "",
                    f"ID: {record_id}",
                    f"Type: {record.get('type', '')}",
                    f"Status: {record.get('status', '')}",
                    f"Importance: {float(record.get('importance', 0.0) or 0.0):.2f}",
                    f"Confidence: {float(record.get('confidence', 0.0) or 0.0):.2f}",
                    f"Source: {record.get('source_chat_id', '')} messages {record.get('source_message_start', '')}-{record.get('source_message_end', '')}",
                    f"Created: {record.get('created_at', '')}",
                    f"Updated: {record.get('updated_at', '')}",
                    f"Tags: {tags or '(none)'}",
                    "",
                    "Summary:",
                    str(record.get("summary", "") or "").strip() or "(empty)",
                    "",
                    "Content:",
                    str(record.get("content", "") or "").strip() or "(empty)",
                ]
            )
            asset_lines = _asset_lines(
                data.assets_by_target.get(("record", record_id), ())
            )
            if asset_lines:
                lines.extend(["", "Linked image assets:", *asset_lines])
            lines.append("")
    else:
        lines.extend(["No extracted memory records.", ""])

    lines.extend(
        [
            "## Recent Chat Messages",
            "",
            f"Messages currently loaded: {len(history)}",
            "",
        ]
    )
    if history:
        for index, turn in enumerate(history, start=1):
            role = str(turn.get("role", "") or "unknown").strip() or "unknown"
            content = str(turn.get("content", "") or "").strip()
            created_at = format_turn_timestamp(turn)
            lines.extend(
                [
                    f"### Message {index}: {role}",
                    "",
                    f"Created: {created_at or 'unknown'}",
                    "",
                    content or "(empty)",
                    "",
                ]
            )
            asset_markers: list[str] = []
            for field_name in (
                "attachment_image_path",
                "generated_image_path",
                "visual_reply_image_path",
                "assistant_visual_reply_image_path",
            ):
                value = str(turn.get(field_name, "") or "").strip()
                if value:
                    asset_markers.append(f"- {field_name}: {value}")
            for field_name in (
                "generated_image_paths",
                "visual_reply_image_paths",
                "assistant_visual_reply_image_paths",
            ):
                values = turn.get(field_name)
                if isinstance(values, (list, tuple)):
                    asset_markers.extend(
                        f"- {field_name}: {str(value).strip()}"
                        for value in values
                        if str(value or "").strip()
                    )
            if asset_markers:
                lines.extend(["Image references:", *asset_markers, ""])
            prompt = str(turn.get("visual_reply_prompt", "") or "").strip()
            if prompt:
                lines.extend([f"Visualization prompt: {prompt}", ""])
    else:
        lines.append("No chat messages are currently loaded.")

    return "\n".join(lines).rstrip() + "\n"


def write_session_memory_report(
    path: str | Path,
    data: SessionMemoryReportData,
    *,
    format_turn_timestamp: TurnTimestampFormatter,
) -> Mapping[str, object]:
    """Write a rendered report and return the stable public summary."""

    output_path = Path(path)
    if not output_path.suffix:
        output_path = output_path.with_suffix(".md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_session_memory_report(data, format_turn_timestamp=format_turn_timestamp),
        encoding="utf-8",
    )
    summary = str(data.continuity.get("summary", "") or "")
    return {
        "path": str(output_path),
        "memory_id": data.memory_id,
        "summary_chars": len(summary),
        "records": len(data.records),
        "chunks": len(data.chunks),
        "messages": len(data.history),
    }


__all__ = [
    "SessionMemoryReportData",
    "default_export_path",
    "render_session_memory_report",
    "write_session_memory_report",
]
