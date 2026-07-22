"""Smoke checks for buffer-aware streaming text flush timing."""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _timeout_scenario(*, lead_seconds: float) -> list[dict]:
    from core.streaming_text import StreamingChunkAssembler

    now = [0.0]
    config = {
        "stream_first_chunk_min_chars": 80,
        "stream_force_flush_seconds": 1.0,
        "stream_force_flush_later_seconds": 2.0,
        "stream_buffer_lead_seconds": lead_seconds,
        "stream_flush_relax_lead_seconds": 1.0,
        "stream_flush_disable_lead_seconds": 2.5,
    }
    assembler = StreamingChunkAssembler(
        220,
        320,
        config_getter=lambda key, default=None: config.get(key, default),
        clock=lambda: now[0],
    )
    assembler.emission_count = 1
    text = ("safe " * 20).rstrip() + " unfinishedtailwithletters"
    assert assembler.feed(text) == []
    now[0] = 3.0
    return assembler.feed("")


def _test_low_buffer_lead_keeps_timeout_flush() -> None:
    chunks = _timeout_scenario(lead_seconds=0.0)
    assert chunks, "low lead should keep timeout flush responsive"
    assert chunks[0]["reason"].startswith("timeout_"), chunks[0]


def _test_comfortable_buffer_lead_relaxes_timeout_flush() -> None:
    chunks = _timeout_scenario(lead_seconds=3.0)
    assert chunks == [], chunks


def _test_first_chunk_target_honors_fast_start_setting() -> None:
    from core.streaming_text import StreamingChunkAssembler

    config = {
        "stream_first_chunk_min_chars": 22,
        "stream_force_flush_seconds": 0.9,
        "stream_force_flush_later_seconds": 2.5,
    }
    assembler = StreamingChunkAssembler(
        85,
        170,
        config_getter=lambda key, default=None: config.get(key, default),
        clock=lambda: 0.0,
    )
    first_sentence = "Ah, come on, I was really enjoying that vibe."

    chunks = assembler.feed(first_sentence)

    assert [item["text"] for item in chunks] == [first_sentence], (
        "The configured fast-start threshold must not be raised to the steady 85-character target"
    )


def main() -> None:
    _test_low_buffer_lead_keeps_timeout_flush()
    _test_comfortable_buffer_lead_relaxes_timeout_flush()
    _test_first_chunk_target_honors_fast_start_setting()
    print("streaming text adaptive flush smoke passed")


if __name__ == "__main__":
    main()
