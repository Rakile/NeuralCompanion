from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path


def _iter_events(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                yield payload


def _fmt_bounds(bounds) -> str:
    try:
        values = [int(value) for value in list(bounds or [])[:4]]
    except Exception:
        values = []
    return "[" + ", ".join(str(value) for value in values) + "]" if len(values) == 4 else "[]"


def summarize(path: Path) -> str:
    events = list(_iter_events(path) or [])
    counts = Counter(str(item.get("event") or "event") for item in events)
    movement_distances = []
    clipped_captures = []
    focus_sources = Counter()
    ocr_backends = Counter()
    ping_attempts = Counter()
    latest_virtual_desktop = []
    latest_screen_bounds = []

    for item in events:
        name = str(item.get("event") or "")
        if name == "movement_step":
            try:
                movement_distances.append(float(item.get("distance_to_target", 0.0) or 0.0))
            except Exception:
                pass
        if name in {"snapshot_target_saved", "snapshot_full_screen_saved"}:
            if item.get("bounds_were_clipped"):
                clipped_captures.append(item)
            if item.get("virtual_desktop"):
                latest_virtual_desktop = item.get("virtual_desktop")
            if item.get("screen_bounds"):
                latest_screen_bounds = item.get("screen_bounds")
            backend = str(item.get("ocr_backend") or "")
            if backend:
                ocr_backends[backend] += 1
        if name in {"focus_set", "focus_extended"}:
            focus_sources[str(item.get("source") or "unknown")] += 1
        if name == "hidden_ping_attempt":
            ping_attempts["accepted" if item.get("accepted") else "rejected"] += 1

    lines = [
        f"Companion Orb debug summary for {path}",
        f"Events: {len(events)}",
        f"Latest virtual desktop: {_fmt_bounds(latest_virtual_desktop)}",
        f"Latest capture bounds: {_fmt_bounds(latest_screen_bounds)}",
        f"Clipped captures: {len(clipped_captures)}",
    ]
    if clipped_captures:
        recent = clipped_captures[-1]
        lines.append(
            "Latest clipped capture: "
            f"requested={_fmt_bounds(recent.get('requested_screen_bounds'))} "
            f"captured={_fmt_bounds(recent.get('screen_bounds'))}"
        )
    if movement_distances:
        lines.append(
            "Movement distance to target: "
            f"avg={statistics.mean(movement_distances):.2f}px "
            f"max={max(movement_distances):.2f}px "
            f"samples={len(movement_distances)}"
        )
    if focus_sources:
        lines.append("Focus sources: " + ", ".join(f"{key}={value}" for key, value in focus_sources.most_common()))
    if ocr_backends:
        lines.append("OCR backends: " + ", ".join(f"{key}={value}" for key, value in ocr_backends.most_common()))
    if ping_attempts:
        lines.append("Hidden PING attempts: " + ", ".join(f"{key}={value}" for key, value in ping_attempts.most_common()))
    if counts:
        common = ", ".join(f"{key}={value}" for key, value in counts.most_common(12))
        lines.append(f"Top events: {common}")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = Path.cwd() / "runtime" / "companion_orb" / "debug" / "companion_orb_debug.log"
    print(summarize(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
