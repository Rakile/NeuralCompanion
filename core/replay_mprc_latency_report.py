"""Summarize the latest Conversation Replay/MPRC latency trace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


DEFAULT_TRACE_PATH = Path("runtime") / "logs" / "tts_addon_latency.jsonl"
LONG_DELAY_MS = 500.0
SLOW_GENERATION_MS = 2_000.0
_RUNTIME_FIELDS = (
    "python_threads",
    "torch_loaded",
    "torch_threads",
    "torch_interop_threads",
    "cuda_available",
    "cuda_device",
    "cuda_allocated_mb",
    "cuda_reserved_mb",
)


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _maximum(rows: Iterable[dict[str, Any]], event: str, field: str = "duration_ms") -> float:
    return max(
        (_number(row.get(field)) for row in rows if row.get("event") == event),
        default=0.0,
    )


def _runtime_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row[field] for field in _RUNTIME_FIELDS if field in row}


def load_trace_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def summarize_latest_replay(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = list(rows or [])
    replay_positions = [
        index
        for index, row in enumerate(ordered)
        if row.get("event") == "replay_source_start" and str(row.get("trace_id") or "").strip()
    ]
    if not replay_positions:
        return {
            "classification": "no_replay_trace",
            "message": "No instrumented Conversation Replay trace was found.",
        }

    start_position = replay_positions[-1]
    start_row = ordered[start_position]
    trace_id = str(start_row.get("trace_id") or "").strip()
    start_clock = _number(start_row.get("monotonic_ms"))
    end_clock = float("inf")
    for row in ordered[start_position + 1 :]:
        if row.get("event") == "tts_pipeline_start" and str(row.get("trace_id") or "") != trace_id:
            end_clock = _number(row.get("monotonic_ms")) or float("inf")
            break

    trace_rows = [
        row
        for row in ordered[start_position:]
        if start_clock <= _number(row.get("monotonic_ms")) < end_clock
    ]
    prior_rows = ordered[: start_position + 1]
    mprc_end_position = next(
        (index for index in range(len(prior_rows) - 1, -1, -1) if prior_rows[index].get("event") == "mprc_initialize_end"),
        -1,
    )
    mprc_init = prior_rows[mprc_end_position] if mprc_end_position >= 0 else {}
    mprc_start = next(
        (
            row
            for row in reversed(prior_rows[: max(0, mprc_end_position)])
            if row.get("event") == "mprc_initialize_start"
        ),
        {},
    )

    lock_rows = [row for row in trace_rows if row.get("event") == "chatterbox_lock_acquired"]
    slowest_lock = max(lock_rows, key=lambda row: _number(row.get("lock_wait_ms")), default={})
    max_lock_wait_ms = _number(slowest_lock.get("lock_wait_ms"))
    lock_owner = str(slowest_lock.get("observed_owner_thread") or "").strip()
    max_setup_ms = _maximum(trace_rows, "chatterbox_model_start", "setup_ms")
    max_conditioning_ms = _maximum(trace_rows, "chatterbox_voice_conditioning")
    max_t3_ms = _maximum(trace_rows, "chatterbox_t3_inference")
    max_s3_ms = _maximum(trace_rows, "chatterbox_s3_inference")
    max_model_ms = _maximum(trace_rows, "chatterbox_model_end", "model_ms")
    max_generation_ms = _maximum(
        (
            row
            for row in trace_rows
            if row.get("event") == "tts_generation" and str(row.get("trace_id") or "") == trace_id
        ),
        "tts_generation",
    )
    max_lookahead_ms = _maximum(trace_rows, "replay_lookahead_wait")
    max_notify_ms = _maximum(trace_rows, "tts_addon_chunk_notify")
    max_preprocess_ms = _maximum(trace_rows, "tts_preprocess")
    max_queue_ms = max(
        _maximum(trace_rows, "tts_generator_queue_put"),
        _maximum(trace_rows, "tts_preprocess", "queue_wait_ms"),
    )
    mprc_hook_ms = max(
        (
            _number(row.get("duration_ms"))
            for row in trace_rows
            if row.get("event") == "addon_capability"
            and row.get("addon_id") == "nc.multi_persona_roleplay"
        ),
        default=0.0,
    )

    if max_lock_wait_ms >= LONG_DELAY_MS:
        classification = "chatterbox_lock_contention"
        message = "Replay waited on the shared Chatterbox lock before model inference."
    elif max_setup_ms >= LONG_DELAY_MS:
        classification = "chatterbox_setup"
        message = "Delay occurred while preparing Chatterbox model or voice conditionals."
    elif max_conditioning_ms >= LONG_DELAY_MS:
        classification = "chatterbox_voice_conditioning"
        message = "Delay occurred while Chatterbox prepared or cloned the reference voice."
    elif max_t3_ms >= SLOW_GENERATION_MS:
        classification = "chatterbox_t3_inference"
        message = "Delay occurred in Chatterbox T3 speech-token inference before the S3 console marker."
    elif max_s3_ms >= SLOW_GENERATION_MS:
        classification = "chatterbox_s3_inference"
        message = "Delay occurred in Chatterbox S3 mel/audio inference after speech tokens were ready."
    elif max_model_ms >= SLOW_GENERATION_MS:
        classification = "chatterbox_model_inference"
        message = "Delay occurred inside Chatterbox model inference, not in addon hooks or queues."
    elif max_lookahead_ms >= LONG_DELAY_MS:
        classification = "replay_lookahead"
        message = "Conversation Replay scheduling held generation at its lookahead gate."
    elif max_notify_ms >= LONG_DELAY_MS:
        classification = "addon_notification"
        message = "An addon audio-chunk notification delayed the replay pipeline."
    elif max_preprocess_ms >= LONG_DELAY_MS:
        classification = "playback_preprocess"
        message = "Audio/avatar preprocessing delayed playback after TTS generation."
    elif max_queue_ms >= LONG_DELAY_MS:
        classification = "queue_backpressure"
        message = "A bounded replay queue blocked the producer or preprocessor."
    elif max_generation_ms >= SLOW_GENERATION_MS:
        classification = "unclassified_tts_generation"
        message = "TTS generation was slow, but no instrumented Chatterbox stage explains it."
    else:
        classification = "no_long_delay"
        message = "No stage in the latest replay exceeded the diagnostic delay thresholds."

    return {
        "classification": classification,
        "message": message,
        "trace_id": trace_id,
        "item_count": int(start_row.get("item_count", 0) or 0),
        "mprc_roleplay_enabled": mprc_init.get("roleplay_enabled"),
        "mprc_initialize_ms": _number(mprc_init.get("duration_ms")),
        "mprc_runtime_before": _runtime_snapshot(mprc_start),
        "mprc_runtime_after": _runtime_snapshot(mprc_init),
        "max_generation_ms": round(max_generation_ms, 3),
        "max_lock_wait_ms": round(max_lock_wait_ms, 3),
        "lock_owner": lock_owner,
        "max_setup_ms": round(max_setup_ms, 3),
        "max_conditioning_ms": round(max_conditioning_ms, 3),
        "max_t3_ms": round(max_t3_ms, 3),
        "max_s3_ms": round(max_s3_ms, 3),
        "max_model_ms": round(max_model_ms, 3),
        "max_lookahead_ms": round(max_lookahead_ms, 3),
        "max_addon_notify_ms": round(max_notify_ms, 3),
        "max_preprocess_ms": round(max_preprocess_ms, 3),
        "max_queue_wait_ms": round(max_queue_ms, 3),
        "max_mprc_hook_ms": round(mprc_hook_ms, 3),
    }


def format_summary(summary: dict[str, Any]) -> str:
    if summary.get("classification") == "no_replay_trace":
        return str(summary.get("message") or "No replay trace found.")
    owner = str(summary.get("lock_owner") or "none observed")
    roleplay_state = summary.get("mprc_roleplay_enabled")
    roleplay_label = "unknown" if roleplay_state is None else ("enabled" if roleplay_state else "disabled")
    runtime_before = dict(summary.get("mprc_runtime_before") or {})
    runtime_after = dict(summary.get("mprc_runtime_after") or {})

    def transition(field: str) -> str:
        return f"{runtime_before.get(field, '?')} -> {runtime_after.get(field, '?')}"

    return "\n".join(
        (
            f"Replay trace: {summary.get('trace_id')} ({summary.get('item_count', 0)} item(s))",
            f"Classification: {summary.get('classification')}",
            f"Conclusion: {summary.get('message')}",
            f"MPRC roleplay state: {roleplay_label}; slowest MPRC hook: {summary.get('max_mprc_hook_ms', 0.0):.3f} ms",
            f"MPRC init runtime: Python threads {transition('python_threads')}; Torch threads {transition('torch_threads')}; "
            f"CUDA reserved MB {transition('cuda_reserved_mb')}",
            f"TTS generation max: {summary.get('max_generation_ms', 0.0):.3f} ms",
            f"Chatterbox lock/setup/model: {summary.get('max_lock_wait_ms', 0.0):.3f} / "
            f"{summary.get('max_setup_ms', 0.0):.3f} / {summary.get('max_model_ms', 0.0):.3f} ms",
            f"Chatterbox conditioning/T3/S3: {summary.get('max_conditioning_ms', 0.0):.3f} / "
            f"{summary.get('max_t3_ms', 0.0):.3f} / {summary.get('max_s3_ms', 0.0):.3f} ms",
            f"Observed lock owner: {owner}",
            f"Replay lookahead/addon notify/preprocess/queue: {summary.get('max_lookahead_ms', 0.0):.3f} / "
            f"{summary.get('max_addon_notify_ms', 0.0):.3f} / {summary.get('max_preprocess_ms', 0.0):.3f} / "
            f"{summary.get('max_queue_wait_ms', 0.0):.3f} ms",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", nargs="?", default=str(DEFAULT_TRACE_PATH), help="Path to tts_addon_latency.jsonl")
    parser.add_argument("--json", action="store_true", help="Print the machine-readable summary")
    args = parser.parse_args()

    path = Path(args.trace)
    if not path.is_file():
        print(f"Trace file not found: {path}")
        return 2
    summary = summarize_latest_replay(load_trace_rows(path))
    print(json.dumps(summary, indent=2, ensure_ascii=True) if args.json else format_summary(summary))
    return 0 if summary.get("classification") != "no_replay_trace" else 1


if __name__ == "__main__":
    raise SystemExit(main())
