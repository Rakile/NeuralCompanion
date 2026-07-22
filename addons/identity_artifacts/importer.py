from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


SUPPORTED_FORMAT = "NC_IDENTITY_EXPORT"
SUPPORTED_EXPORT_KIND = "reflect_and_export_identity"
SUPPORTED_FORMAT_VERSIONS = {"1.1"}

KNOWN_TOP_LEVEL_FIELDS = {
    "format",
    "format_version",
    "export_kind",
    "artifact_contract",
    "source_scope",
    "source_registry",
    "coverage_assessment",
    "exposure_model",
    "hot_identity",
    "transient_continuity",
    "identity_structure",
    "ltm_seed_records",
    "identity_projections",
    "artifact_limits",
    "import_notes",
}


SourceType = Literal["file", "pasted", "legacy"]


@dataclass
class RawIdentityArtifact:
    artifact_hash: str
    raw_bytes: bytes
    raw_text: str
    source_type: SourceType
    source_path: str = ""
    provider_label: str = ""
    imported_at: str = ""
    parsed_json: dict[str, Any] | None = None
    format: str = ""
    format_version: str = ""
    export_kind: str = ""
    source_scope_summary: str = ""
    status: str = "failed"
    mechanical_warnings: list[str] = field(default_factory=list)

    @property
    def parsed(self) -> dict[str, Any] | None:
        return self.parsed_json

    def metadata_dict(self) -> dict[str, Any]:
        return {
            "artifact_hash": self.artifact_hash,
            "artifact_ref": f"library/{self.artifact_hash}.json",
            "source_type": self.source_type,
            "source_path": self.source_path,
            "provider_label": self.provider_label,
            "imported_at": self.imported_at,
            "format": self.format,
            "format_version": self.format_version,
            "export_kind": self.export_kind,
            "source_scope_summary": self.source_scope_summary,
            "status": self.status,
            "mechanical_warnings": list(self.mechanical_warnings),
        }


@dataclass
class StructuredIdentityImport:
    source_registry: dict[str, dict[str, Any]] = field(default_factory=dict)
    hot_identity_text: str = ""
    hot_identity_claims: list[dict[str, Any]] = field(default_factory=list)
    transient_continuity: dict[str, Any] = field(default_factory=dict)
    identity_items: list[dict[str, Any]] = field(default_factory=list)
    ltm_seed_records: list[dict[str, Any]] = field(default_factory=list)
    identity_projections: list[dict[str, Any]] = field(default_factory=list)
    unresolved_references: list[dict[str, str]] = field(default_factory=list)
    skipped_sections: list[str] = field(default_factory=list)
    ignored_top_level_fields: list[str] = field(default_factory=list)
    import_warnings: list[str] = field(default_factory=list)
    runtime_use_state: str = "disabled"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_registry": dict(self.source_registry),
            "hot_identity_text": self.hot_identity_text,
            "hot_identity_claims": list(self.hot_identity_claims),
            "transient_continuity": dict(self.transient_continuity),
            "identity_items": list(self.identity_items),
            "ltm_seed_records": list(self.ltm_seed_records),
            "identity_projections": list(self.identity_projections),
            "unresolved_references": list(self.unresolved_references),
            "skipped_sections": list(self.skipped_sections),
            "ignored_top_level_fields": list(self.ignored_top_level_fields),
            "import_warnings": list(self.import_warnings),
            "runtime_use_state": self.runtime_use_state,
        }


@dataclass
class IdentityImportResult:
    raw: RawIdentityArtifact
    structured: StructuredIdentityImport | None = None


def import_identity_artifact(
    raw_input: bytes | str,
    provider_label: str = "",
    *,
    source_type: SourceType | None = None,
    source_path: str = "",
) -> IdentityImportResult:
    raw_bytes, raw_text, kind = _canonical_input(raw_input, source_type)
    raw = RawIdentityArtifact(
        artifact_hash=hashlib.sha256(raw_bytes).hexdigest(),
        raw_bytes=raw_bytes,
        raw_text=raw_text,
        source_type=kind,
        source_path=str(source_path or ""),
        provider_label=str(provider_label or "").strip(),
        imported_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        parsed = json.loads(raw_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raw.status = "failed"
        raw.mechanical_warnings.append(f"Artifact could not be parsed as JSON: {getattr(exc, 'msg', str(exc))}")
        return IdentityImportResult(raw=raw, structured=None)

    if not isinstance(parsed, dict):
        raw.status = "failed"
        raw.mechanical_warnings.append("Parsed artifact is not a JSON object.")
        return IdentityImportResult(raw=raw, structured=None)

    raw.parsed_json = parsed
    raw.format = _as_string(parsed.get("format"))
    raw.format_version = _as_string(parsed.get("format_version"))
    raw.export_kind = _as_string(parsed.get("export_kind"))
    raw.source_scope_summary = _source_scope_summary(parsed.get("source_scope"))

    hard_failure = _hard_failure_warning(parsed, raw)
    if hard_failure:
        raw.status = "failed"
        raw.mechanical_warnings.append(hard_failure)
        return IdentityImportResult(raw=raw, structured=None)

    structured = _extract_structured(parsed)
    raw.status = "imported"
    return IdentityImportResult(raw=raw, structured=structured)


def _canonical_input(raw_input: bytes | str, source_type: SourceType | None) -> tuple[bytes, str, SourceType]:
    if isinstance(raw_input, bytes):
        kind = source_type or "file"
        raw_bytes = bytes(raw_input)
    elif isinstance(raw_input, str):
        kind = source_type or "pasted"
        if kind in {"file", "legacy"}:
            raise TypeError(f"{kind} imports require bytes")
        raw_bytes = raw_input.encode("utf-8")
    else:
        raise TypeError("raw_input must be bytes or str")
    if kind not in {"file", "pasted", "legacy"}:
        raise ValueError(f"Unsupported source_type: {kind}")
    encoding = json.detect_encoding(raw_bytes) if raw_bytes else "utf-8"
    raw_text = raw_bytes.decode(encoding, errors="replace")
    return raw_bytes, raw_text, kind


def _hard_failure_warning(parsed: dict[str, Any], raw: RawIdentityArtifact) -> str:
    if raw.format != SUPPORTED_FORMAT:
        return "Format missing or not NC_IDENTITY_EXPORT."
    if raw.export_kind != SUPPORTED_EXPORT_KIND:
        return "Export kind missing or not reflect_and_export_identity."
    if raw.format_version not in SUPPORTED_FORMAT_VERSIONS:
        return f"Unsupported format_version: {raw.format_version or '(missing)'}."
    contract = parsed.get("artifact_contract")
    if not isinstance(contract, dict):
        return ""
    if contract.get("raw_export_is_identity_artifact") is False:
        return "artifact_contract contradicts raw artifact preservation."
    if contract.get("preserve_raw_output") is False:
        return "artifact_contract contradicts raw output preservation."
    if contract.get("semantic_validation_allowed") is True:
        return "artifact_contract allows semantic validation; NC importer cannot honor that safely."
    return ""


def _extract_structured(parsed: dict[str, Any]) -> StructuredIdentityImport:
    structured = StructuredIdentityImport()
    structured.ignored_top_level_fields = sorted(
        str(key) for key in parsed.keys() if str(key) not in KNOWN_TOP_LEVEL_FIELDS
    )
    for field_name in structured.ignored_top_level_fields:
        structured.import_warnings.append(f"unknown top-level field ignored during structured import: {field_name}")

    structured.source_registry = _extract_source_registry(parsed.get("source_registry"), structured)
    known_sources = set(structured.source_registry.keys())

    hot_identity = parsed.get("hot_identity")
    if isinstance(hot_identity, dict):
        compressed_text = hot_identity.get("compressed_text")
        if isinstance(compressed_text, str):
            structured.hot_identity_text = compressed_text
        elif "compressed_text" in hot_identity:
            _skip_section(structured, "hot_identity.compressed_text", "wrong type")
        structured.hot_identity_claims = _extract_record_list(
            section_name="hot_identity.claims",
            value=hot_identity.get("claims"),
            structured=structured,
        )
        _collect_unresolved_sources("hot_identity.claims", structured.hot_identity_claims, known_sources, structured)
    elif hot_identity is not None:
        _skip_section(structured, "hot_identity", "wrong type")

    transient = parsed.get("transient_continuity")
    if isinstance(transient, dict):
        structured.transient_continuity = dict(transient)
        _collect_unresolved_sources("transient_continuity", [transient], known_sources, structured)
    elif transient is not None:
        _skip_section(structured, "transient_continuity", "wrong type")

    identity_structure = parsed.get("identity_structure")
    if isinstance(identity_structure, dict):
        structured.identity_items = _extract_record_list(
            section_name="identity_structure.identity_items",
            value=identity_structure.get("identity_items"),
            structured=structured,
        )
        _collect_unresolved_sources("identity_structure.identity_items", structured.identity_items, known_sources, structured)
    elif identity_structure is not None:
        _skip_section(structured, "identity_structure", "wrong type")

    structured.ltm_seed_records = _extract_record_list(
        section_name="ltm_seed_records",
        value=parsed.get("ltm_seed_records"),
        structured=structured,
    )
    _collect_unresolved_sources("ltm_seed_records", structured.ltm_seed_records, known_sources, structured)

    structured.identity_projections = _extract_record_list(
        section_name="identity_projections",
        value=parsed.get("identity_projections"),
        structured=structured,
    )
    _collect_projection_references(structured)
    return structured


def _extract_source_registry(value: Any, structured: StructuredIdentityImport) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, list):
        _skip_section(structured, "source_registry", "wrong type")
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            structured.import_warnings.append(f"source_registry[{index}] skipped because wrong type.")
            continue
        source_id = _as_string(item.get("source_id"))
        if not source_id:
            structured.import_warnings.append(f"source_registry[{index}] skipped because source_id is missing.")
            continue
        registry[source_id] = dict(item)
    return registry


def _extract_record_list(section_name: str, value: Any, structured: StructuredIdentityImport) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        _skip_section(structured, section_name, "wrong type")
        return []
    records: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            structured.import_warnings.append(f"{section_name}[{index}] skipped because wrong type.")
            continue
        records.append(dict(item))
    return records


def _collect_unresolved_sources(
    section_name: str,
    records: list[dict[str, Any]],
    known_sources: set[str],
    structured: StructuredIdentityImport,
) -> None:
    for index, record in enumerate(records):
        raw_source_ids = record.get("source_ids")
        if raw_source_ids is None:
            continue
        if not isinstance(raw_source_ids, list):
            structured.import_warnings.append(f"{section_name}[{index}] source_ids ignored because wrong type.")
            continue
        for source_id in raw_source_ids:
            source_text = _as_string(source_id)
            if not source_text or source_text in known_sources:
                continue
            structured.unresolved_references.append(
                {"section": section_name, "record_index": str(index), "source_id": source_text}
            )
            structured.import_warnings.append(
                f"source_id unresolved in {section_name}[{index}]: {source_text}"
            )


def _collect_projection_references(structured: StructuredIdentityImport) -> None:
    known_item_ids = {_as_string(item.get("id")) for item in structured.identity_items if _as_string(item.get("id"))}
    for index, projection in enumerate(structured.identity_projections):
        for field_name in ("allowed_item_ids", "redacted_item_ids"):
            raw_ids = projection.get(field_name)
            if raw_ids is None:
                continue
            if not isinstance(raw_ids, list):
                structured.import_warnings.append(f"identity_projections[{index}] {field_name} ignored because wrong type.")
                continue
            for item_id in raw_ids:
                item_text = _as_string(item_id)
                if not item_text or item_text in known_item_ids:
                    continue
                structured.unresolved_references.append(
                    {"section": "identity_projections", "record_index": str(index), "item_id": item_text}
                )
                structured.import_warnings.append(
                    f"projection references missing identity item in identity_projections[{index}]: {item_text}"
                )


def _skip_section(structured: StructuredIdentityImport, section_name: str, reason: str) -> None:
    structured.skipped_sections.append(section_name)
    structured.import_warnings.append(f"section skipped because {reason}: {section_name}")


def _source_scope_summary(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    declared = _as_string(value.get("declared_access"))
    confidence = value.get("confidence_in_scope")
    if declared and confidence is not None:
        return f"{declared} (confidence_in_scope={confidence})"
    return declared


def _as_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
