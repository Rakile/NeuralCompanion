from pathlib import Path


def main() -> int:
    source_path = Path(__file__).with_name("controller.py")
    source = source_path.read_text(encoding="utf-8")

    required_snippets = [
        "_REPLAY_TOOLTIP_MAX_CHARS",
        "_replay_content_signature",
        "blockSignals(True)",
        "setUpdatesEnabled(False)",
        "item.setToolTip(_bounded_text(",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    if missing:
        raise AssertionError(f"Missing defensive replay UI snippet(s): {missing}")
    if 'str(entry.get("content", "") or "")) for entry in replayable' in source:
        raise AssertionError("Replay signature still stores full message content.")
    print("chat_session_player smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
