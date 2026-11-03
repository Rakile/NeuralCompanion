from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any


_LOCK = threading.RLock()
_TRACE_PATHS: dict[str, Path] = {}
_TRACE_STARTS: dict[str, float] = {}
_MAX_TRACES = 24
_MAX_TEXT_CHARS = 100_000
_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
)
_DATA_URL = re.compile(
    r"^data:(?P<mime>[^;,]+)?(?:;[^,]*)?;base64,(?P<data>[A-Za-z0-9+/=\r\n]+)$",
    flags=re.IGNORECASE,
)


def start_trace(
    app_root: Path | str,
    *,
    trace_id: str = "",
    scope: str,
    image_path: Path | str,
    route: str = "lfm_observation_to_main_chat",
) -> str:
    """Start or reuse one opt-in Companion Orb vision pipeline trace."""

    normalized_id = _safe_trace_id(trace_id) or (
        f"vision-{int(time.time() * 1000)}-{threading.get_ident()}"
    )
    source = Path(image_path).expanduser()
    root = (
        Path(app_root).expanduser()
        / "runtime"
        / "companion_orb"
        / "debug"
        / "vision_pipeline"
    )
    with _LOCK:
        trace_path = _TRACE_PATHS.get(normalized_id)
        if trace_path is None:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            trace_dir = root / f"{stamp}_{normalized_id}"
            trace_dir.mkdir(parents=True, exist_ok=True)
            trace_path = trace_dir / "trace.jsonl"
            _TRACE_PATHS[normalized_id] = trace_path
            _TRACE_STARTS[normalized_id] = time.monotonic()
            snapshot_copy = ""
            if source.is_file():
                suffix = source.suffix.lower() if source.suffix else ".img"
                destination = trace_dir / f"sent_image{suffix}"
                try:
                    shutil.copy2(source, destination)
                    snapshot_copy = str(destination)
                except OSError:
                    snapshot_copy = ""
            _write_latest_pointer(root, trace_path)
            _prune_trace_directories(root, keep=trace_dir)
            _append_locked(
                normalized_id,
                "trace_started",
                {
                    "scope": str(scope or "unknown"),
                    "route": str(route or ""),
                    "source_image": _image_descriptor(source),
                    "snapshot_copy": snapshot_copy,
                },
            )
    return normalized_id


def record_event(trace_id: object, stage: str, **details: object) -> bool:
    """Append a sanitized event to an active trace without affecting runtime flow."""

    normalized_id = _safe_trace_id(trace_id)
    if not normalized_id:
        return False
    with _LOCK:
        if normalized_id not in _TRACE_PATHS:
            return False
        try:
            _append_locked(normalized_id, stage, details)
        except OSError:
            return False
    return True


def finish_trace(trace_id: object, **details: object) -> bool:
    normalized_id = _safe_trace_id(trace_id)
    if not normalized_id:
        return False
    recorded = record_event(normalized_id, "trace_finished", **details)
    if recorded:
        with _LOCK:
            _TRACE_PATHS.pop(normalized_id, None)
            _TRACE_STARTS.pop(normalized_id, None)
    return recorded


def active_trace_path(trace_id: object) -> Path | None:
    with _LOCK:
        return _TRACE_PATHS.get(_safe_trace_id(trace_id))


def clear_active_traces() -> None:
    """Forget open handles after the UI clears diagnostics on disk."""

    with _LOCK:
        _TRACE_PATHS.clear()
        _TRACE_STARTS.clear()


def serialize_provider_request(request: object) -> object:
    """Expose a frozen provider request without private bindings or credentials."""

    params_copy = getattr(request, "params_copy", None)
    additional_copy = getattr(request, "additional_params_copy", None)
    context = getattr(request, "context", None)
    if callable(params_copy) and callable(additional_copy):
        context_summary = getattr(context, "to_summary", None)
        return sanitize(
            {
                "context": (
                    context_summary()
                    if callable(context_summary)
                    else {
                        "provider_name": getattr(context, "provider_name", ""),
                        "model_name": getattr(context, "model_name", ""),
                    }
                ),
                "params": params_copy(),
                "additional_params": additional_copy(),
            }
        )
    return sanitize(request)


def sanitize(value: object, *, _depth: int = 0) -> object:
    if _depth > 10:
        return "<maximum depth reached>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {
            "kind": "bytes",
            "size": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, str):
        match = _DATA_URL.match(value)
        if match is not None:
            encoded = re.sub(r"\s+", "", match.group("data") or "")
            return {
                "kind": "image_data_url",
                "mime_type": str(match.group("mime") or "application/octet-stream"),
                "encoded_chars": len(encoded),
                "sha256_encoded": hashlib.sha256(encoded.encode("ascii")).hexdigest(),
            }
        if len(value) > _MAX_TEXT_CHARS:
            return value[:_MAX_TEXT_CHARS] + "\n<debug text truncated>"
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= 200:
                result["<truncated>"] = f"{len(value) - index} more fields"
                break
            key = str(raw_key)
            folded = key.casefold()
            if _secret_key(folded):
                result[key] = "<redacted>"
            else:
                result[key] = sanitize(item, _depth=_depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)
        sanitized = [sanitize(item, _depth=_depth + 1) for item in items[:500]]
        if len(items) > 500:
            sanitized.append(f"<{len(items) - 500} more items>")
        return sanitized
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: sanitize(getattr(value, field.name), _depth=_depth + 1)
            for field in fields(value)
            if not field.name.startswith("_")
        }
    summary = getattr(value, "to_summary", None)
    if callable(summary):
        try:
            return sanitize(summary(), _depth=_depth + 1)
        except Exception:
            pass
    return str(value)


def looks_degenerate(value: object) -> bool:
    compact = re.sub(r"\s+", "", str(value or ""))
    if len(compact) < 32:
        return False
    if len(set(compact)) <= 2:
        return True
    return bool(re.fullmatch(r"(.{1,12})\1{7,}", compact, flags=re.DOTALL))


def _safe_trace_id(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())[:120]


def _secret_key(folded_key: str) -> bool:
    if any(part in folded_key for part in _SECRET_KEY_PARTS):
        return True
    return folded_key in {"token", "access_token", "refresh_token", "id_token"} or (
        folded_key.endswith("_token")
        and folded_key not in {"input_token", "output_token"}
    )


def _image_descriptor(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return result
    try:
        payload = path.read_bytes()
        result.update(size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    except OSError as exc:
        result["read_error"] = str(exc)
    try:
        from PIL import Image

        with Image.open(path) as image:
            result.update(width=int(image.width), height=int(image.height), format=image.format)
    except Exception:
        pass
    return result


def _append_locked(trace_id: str, stage: str, details: Mapping[str, object]) -> None:
    path = _TRACE_PATHS[trace_id]
    started = _TRACE_STARTS.get(trace_id, time.monotonic())
    payload = {
        "schema_version": 1,
        "trace_id": trace_id,
        "stage": str(stage or "event"),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
        "details": sanitize(details),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        handle.write("\n")


def _write_latest_pointer(root: Path, trace_path: Path) -> None:
    try:
        (root / "latest_trace.txt").write_text(str(trace_path), encoding="utf-8")
    except OSError:
        pass


def _prune_trace_directories(root: Path, *, keep: Path) -> None:
    try:
        directories = sorted(
            (item for item in root.iterdir() if item.is_dir()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for directory in directories[_MAX_TRACES:]:
        if directory == keep:
            continue
        try:
            shutil.rmtree(directory)
        except OSError:
            pass


__all__ = [
    "active_trace_path",
    "clear_active_traces",
    "finish_trace",
    "looks_degenerate",
    "record_event",
    "sanitize",
    "serialize_provider_request",
    "start_trace",
]
