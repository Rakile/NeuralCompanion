"""MuseTalk text and hearing policy helpers."""

from __future__ import annotations


_VRAM_MODE_ALIASES = {
    "quality": "quality",
    "balanced": "balanced",
    "low": "low",
    "low_vram": "low",
    "very_low": "very_low",
    "very_low_vram": "very_low",
}


def normalize_vram_mode(value: str, default: str = "quality") -> str:
    fallback = _VRAM_MODE_ALIASES.get(str(default or "quality").strip().lower(), "quality")
    return _VRAM_MODE_ALIASES.get(str(value or "").strip().lower(), fallback)


def vram_mode(runtime_config: dict, default: str = "quality") -> str:
    return normalize_vram_mode((runtime_config or {}).get("musetalk_vram_mode", default), default=default)


def chunk_limits_for_index(chunk_index: int, runtime_config: dict, defaults: dict) -> tuple[int, int]:
    config = runtime_config or {}
    chunk_index = max(0, int(chunk_index))
    quickstart = list(defaults.get("quickstart") or [(90, 130), (130, 180)])
    quickstart_limits = [
        (
            int(config.get("musetalk_quickstart_1_target_chars", quickstart[0][0]) or quickstart[0][0]),
            int(config.get("musetalk_quickstart_1_max_chars", quickstart[0][1]) or quickstart[0][1]),
        ),
        (
            int(config.get("musetalk_quickstart_2_target_chars", quickstart[1][0]) or quickstart[1][0]),
            int(config.get("musetalk_quickstart_2_max_chars", quickstart[1][1]) or quickstart[1][1]),
        ),
    ]
    if chunk_index < len(quickstart_limits):
        return quickstart_limits[chunk_index]
    target_default = int(defaults.get("target", defaults.get("musetalk_target", 110)) or 110)
    max_default = int(defaults.get("max", defaults.get("musetalk_max", 220)) or 220)
    return (
        int(config.get("musetalk_chunk_target_chars", target_default) or target_default),
        int(config.get("musetalk_chunk_max_chars", max_default) or max_default),
    )
