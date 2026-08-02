from __future__ import annotations

import inspect
import json
import sys
import tempfile
import tracemalloc
from pathlib import Path


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _sources():
    from addons.audio_story_mode import chatlog_source, markdown_source, novel_models

    return chatlog_source, markdown_source, novel_models


def test_jsonl_adapter_detects_fields_and_emits_bounded_stable_records(
    tmp_path: Path,
) -> None:
    chatlog_source, _markdown_source, _novel_models = _sources()
    path = tmp_path / "chat.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {"author": "Ada", "content": "x" * 80, "timestamp": index}
            )
            for index in range(12)
        ),
        encoding="utf-8",
    )
    adapter = chatlog_source.ChatlogSourceAdapter()

    preview = adapter.inspect(path)
    batches = list(
        adapter.iter_batches(
            path,
            preview,
            max_records=5,
            max_serialized_chars=1_800,
        )
    )
    records = [record for batch in batches for record in batch]

    assert preview.parser_id == "json_lines"
    assert preview.record_count == 12
    assert preview.participants == ("Ada",)
    assert preview.date_start == "0"
    assert preview.date_end == "11"
    assert [len(batch) for batch in batches] == [5, 5, 2]
    assert records[0].speaker == "Ada"
    assert len({record.source_record_id for record in records}) == 12
    assert all(
        len(json.dumps([item.to_dict() for item in batch], ensure_ascii=False))
        <= 1_800
        for batch in batches
    )


def test_top_level_array_and_nested_messages_are_detected(tmp_path: Path) -> None:
    chatlog_source, _markdown_source, _novel_models = _sources()
    array_path = tmp_path / "array.json"
    nested_path = tmp_path / "nested.json"
    messages = [
        {"speaker": "Lin", "text": "Hello", "created_at": "2026-01-01"},
        {"speaker": "Mira", "text": "Hi", "created_at": "2026-01-02"},
    ]
    array_path.write_text(json.dumps(messages), encoding="utf-8")
    nested_path.write_text(json.dumps({"data": {"messages": messages}}), encoding="utf-8")
    adapter = chatlog_source.ChatlogSourceAdapter()

    array_preview = adapter.inspect(array_path)
    nested_preview = adapter.inspect(nested_path)

    assert array_preview.parser_id == "json_array"
    assert array_preview.field_map.collection_path == ()
    assert nested_preview.parser_id == "json_object_array"
    assert nested_preview.field_map.collection_path == ("data", "messages")
    assert nested_preview.record_count == 2


def test_explicit_field_map_supports_custom_layout(tmp_path: Path) -> None:
    chatlog_source, _markdown_source, novel_models = _sources()
    path = tmp_path / "custom.json"
    path.write_text(
        json.dumps(
            {
                "archive": {
                    "entries": [
                        {"sender": "Nova", "body": "First"},
                        {"sender": "Nova", "body": "Second"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    field_map = novel_models.ChatlogFieldMap(
        collection_path=("archive", "entries"),
        speaker_field="sender",
        text_field="body",
    )
    adapter = chatlog_source.ChatlogSourceAdapter()

    preview = adapter.inspect(path, field_map=field_map)
    records = [item for batch in adapter.iter_batches(path, preview) for item in batch]

    assert preview.record_count == 2
    assert [record.text for record in records] == ["First", "Second"]


def test_ambiguous_text_fields_require_explicit_mapping(tmp_path: Path) -> None:
    chatlog_source, _markdown_source, _novel_models = _sources()
    path = tmp_path / "ambiguous.json"
    path.write_text(
        json.dumps([{"author": "Ada", "text": "One", "content": "Two"}]),
        encoding="utf-8",
    )
    adapter = chatlog_source.ChatlogSourceAdapter()

    preview = adapter.inspect(path)

    assert preview.ambiguities
    try:
        list(adapter.iter_batches(path, preview))
    except chatlog_source.AmbiguousChatlogMapping:
        pass
    else:
        raise AssertionError("Ambiguous mappings must not import without confirmation")


def test_ambiguous_preview_samples_are_bounded_and_redacted(tmp_path: Path) -> None:
    chatlog_source, _markdown_source, _novel_models = _sources()
    path = tmp_path / "ambiguous-sensitive.json"
    path.write_text(
        json.dumps(
            [
                {
                    "author": "Ada",
                    "text": "One",
                    "content": "Two",
                    "access_token": "secret-value",
                    "unrelated": "x" * 10_000,
                }
            ]
        ),
        encoding="utf-8",
    )

    preview = chatlog_source.ChatlogSourceAdapter().inspect(path)

    assert preview.ambiguities
    encoded = json.dumps(preview.samples, ensure_ascii=False)
    assert "secret-value" not in encoded
    assert len(encoded) < 2_000


def test_json_lines_count_malformed_and_non_text_records_as_skipped(
    tmp_path: Path,
) -> None:
    chatlog_source, _markdown_source, _novel_models = _sources()
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"author": "Ada", "content": "Valid"}),
                "{broken",
                json.dumps({"author": "Ada", "content": ""}),
                json.dumps({"author": "Ada", "content": "Also valid"}),
            ]
        ),
        encoding="utf-8",
    )

    preview = chatlog_source.ChatlogSourceAdapter().inspect(path)

    assert preview.record_count == 2
    assert preview.skipped_count == 2


def test_adapter_cancellation_stops_inspection(tmp_path: Path) -> None:
    chatlog_source, _markdown_source, _novel_models = _sources()
    path = tmp_path / "chat.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"author": "Ada", "content": str(index)})
            for index in range(100)
        ),
        encoding="utf-8",
    )
    calls = 0

    def cancel_check() -> bool:
        nonlocal calls
        calls += 1
        return calls > 3

    try:
        chatlog_source.ChatlogSourceAdapter().inspect(path, cancel_check=cancel_check)
    except chatlog_source.SourceImportCancelled:
        pass
    else:
        raise AssertionError("Inspection should honor cancellation")


def test_markdown_adapter_preserves_text_and_splits_on_headings(tmp_path: Path) -> None:
    _chatlog_source, markdown_source, _novel_models = _sources()
    text = "# One\n\nFirst paragraph.\n\n# Two\n\nSecond paragraph.\n"
    path = tmp_path / "novel.md"
    path.write_text(text, encoding="utf-8")
    adapter = markdown_source.MarkdownSourceAdapter()

    preview = adapter.inspect(path)
    chapters = list(adapter.iter_narration_chapters(path))

    assert preview.record_count == 2
    assert [title for title, _chunks in chapters] == ["One", "Two"]
    assert [chunks[0].text for _title, chunks in chapters] == [
        "First paragraph.",
        "Second paragraph.",
    ]
    assert path.read_text(encoding="utf-8") == text


def test_large_chatlog_iteration_keeps_only_bounded_batches(tmp_path: Path) -> None:
    chatlog_source, _markdown_source, _novel_models = _sources()
    path = tmp_path / "large.jsonl"
    record_count = 8_000
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "author": "Ada" if index % 2 == 0 else "Nova",
                    "content": f"Message {index}: " + ("x" * 400),
                }
            )
            for index in range(record_count)
        ),
        encoding="utf-8",
    )
    adapter = chatlog_source.ChatlogSourceAdapter()

    tracemalloc.start()
    try:
        preview = adapter.inspect(path)
        observed = 0
        largest_batch = 0
        for batch in adapter.iter_batches(path, preview):
            observed += len(batch)
            largest_batch = max(largest_batch, len(batch))
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert observed == record_count
    assert largest_batch <= 250
    assert peak < 20 * 1024 * 1024, peak


def test_high_cardinality_metadata_is_bounded_and_batches_honor_exact_limit(
    tmp_path: Path,
) -> None:
    chatlog_source, _markdown_source, novel_models = _sources()
    path = tmp_path / "high-cardinality.jsonl"
    record_count = 10_000
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "author": f"speaker-{index}-" + ("s" * 2_000),
                    "content": "body-" + ("x" * 3_000),
                    "timestamp": f"{index}-" + ("t" * 2_000),
                    "thread_id": f"thread-{index}-" + ("q" * 2_000),
                }
            )
            for index in range(record_count)
        ),
        encoding="utf-8",
    )
    mapping = novel_models.ChatlogFieldMap(
        speaker_field="author",
        text_field="content",
        timestamp_field="timestamp",
        thread_field="thread_id",
    )
    adapter = chatlog_source.ChatlogSourceAdapter()

    tracemalloc.start()
    try:
        preview = adapter.inspect(path, field_map=mapping)
        batches = adapter.iter_batches(
            path,
            preview,
            max_records=250,
            max_serialized_chars=1_200,
        )
        observed = 0
        for batch in batches:
            encoded = json.dumps(
                [item.to_dict() for item in batch], ensure_ascii=False
            )
            assert len(encoded) <= 1_200
            observed += len(batch)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert observed >= record_count
    assert len(preview.participants) <= 256
    assert peak < 28 * 1024 * 1024, peak


def main() -> int:
    tests = [
        test
        for name, test in sorted(globals().items())
        if name.startswith("test_") and callable(test)
    ]
    failures = 0
    for test in tests:
        try:
            parameters = tuple(inspect.signature(test).parameters)
            if parameters == ("tmp_path",):
                with tempfile.TemporaryDirectory() as directory:
                    test(Path(directory))
            elif not parameters:
                test()
            else:
                raise AssertionError(
                    f"Unsupported smoke fixture(s): {', '.join(parameters)}"
                )
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
