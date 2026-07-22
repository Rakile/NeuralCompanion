from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))


def _load_engine():
    addons_module = types.ModuleType("addons")
    addons_module.__path__ = [str(ROOT / "addons")]
    sys.modules["addons"] = addons_module
    import addons.vam_avatar.config  # noqa: F401
    import engine

    return engine


def _candidate_results():
    return [
        {
            "kind": "chunk",
            "id": "chunk_cornfield",
            "source_chat_id": "testing_memory",
            "source_message_start": 127,
            "source_message_end": 134,
            "snippet": "The assistant generated a cinematic cornfield scene.",
            "assets": [
                {
                    "asset_id": "asset_cornfield",
                    "kind": "image",
                    "role": "assistant",
                    "origin": "assistant_visual_reply",
                    "relation": "generated_by_reply",
                    "metadata": {
                        "visual_reply_prompt": (
                            "A man in a red jacket and a woman in a green jacket standing in a cornfield."
                        )
                    },
                    "link_metadata": {},
                }
            ],
        },
        {
            "kind": "chunk",
            "id": "chunk_challenge",
            "source_chat_id": "testing_memory",
            "source_message_start": 9,
            "source_message_end": 16,
            "snippet": "9. User: Why don't you combine a bit of both. 10. Assistant: A creative sanctuary.",
            "content": (
                "9. User: Why don't you combine a bit of both.\n"
                "10. Assistant: A creative sanctuary full of artistic tools.\n"
                "11. User: Yes, generate that image.\n"
                "12. Assistant: Here is the creative workspace.\n"
                "13. User: Here is another image from me. [Image attached: clipboard]\n"
                "14. Assistant: This is a cognitive challenge designed to check basic reading skills, "
                "complex logical reasoning, and spatial awareness.\n"
                "15. User: Tell me a short story.\n"
                "16. Assistant: Once upon a time."
            ),
            "assets": [
                {
                    "asset_id": "asset_challenge",
                    "kind": "image",
                    "role": "user",
                    "origin": "user_attachment",
                    "relation": "attached_to_turn",
                    "source_message_index": 13,
                    "metadata": {},
                    "link_metadata": {},
                }
            ],
        },
    ]


def test_router_uses_visual_prompts_and_validates_selected_assets():
    engine = _load_engine()
    original_completion = engine._chat_completion_create
    original_model = engine.RUNTIME_CONFIG.get("model_name")
    captured = {}

    def fake_completion(params, additional_params=None, *, stream=False):
        captured["params"] = params
        return json.dumps(
            {
                "action": "memory_only",
                "request_kind": "prior_image",
                "asset_ids": ["asset_cornfield", "asset_unknown"],
                "reason": "The user explicitly refers to the earlier cornfield image.",
            }
        )

    try:
        engine.RUNTIME_CONFIG["model_name"] = "test-model"
        engine._chat_completion_create = fake_completion
        decision = engine._decide_long_term_memory_image_context(
            [
                {
                    "role": "user",
                    "content": "What color was the woman's jacket in the image you generated earlier?",
                    "attachment_image_path": "runtime/current.png",
                }
            ],
            _candidate_results(),
        )
    finally:
        engine._chat_completion_create = original_completion
        engine.RUNTIME_CONFIG["model_name"] = original_model

    assert decision["action"] == "memory_only"
    assert decision["request_kind"] == "prior_image"
    assert decision["prior_image_requested"] is True
    assert decision["asset_ids"] == ["asset_cornfield"]
    request_text = json.dumps(captured["params"]["messages"], ensure_ascii=False)
    assert "current user turn includes a fresh image attachment" in request_text.lower()
    assert "woman in a green jacket" in request_text
    assert "asset_cornfield" in request_text
    assert "cognitive challenge designed to check basic reading skills" in request_text
    assert "request_kind" in request_text


def test_image_candidates_share_one_complete_archived_chunk_context():
    engine = _load_engine()
    original_config = dict(engine.RUNTIME_CONFIG)
    try:
        engine.RUNTIME_CONFIG["long_term_memory_recall_text_budget"] = -1
        payload = engine._long_term_memory_image_context_payload(
            [
                {
                    "kind": "chunk",
                    "id": "chunk_135_138",
                    "source_chat_id": "testing_memory",
                    "source_message_start": 135,
                    "source_message_end": 138,
                    "content": (
                        "135. User: Generate the cornfield image.\n"
                        "136. Assistant: Here is the generated cornfield image.\n"
                        "137. User: What color is the jacket? [Image attached: clipboard]\n"
                        "138. Assistant: The jacket is green."
                    ),
                    "assets": [
                        {
                            "asset_id": "asset_generated",
                            "kind": "image",
                            "role": "assistant",
                            "origin": "assistant_visual_reply",
                            "relation": "generated_by_reply",
                            "source_message_index": 136,
                            "metadata": {"visual_reply_prompt": "Two people in a cornfield."},
                            "link_metadata": {},
                        },
                        {
                            "asset_id": "asset_user",
                            "kind": "image",
                            "role": "user",
                            "origin": "user_attachment",
                            "relation": "attached_to_turn",
                            "source_message_index": 137,
                            "metadata": {},
                            "link_metadata": {},
                        },
                    ],
                }
            ]
        )
    finally:
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)

    assert len(payload["recalled_image_contexts"]) == 1
    shared_context = payload["recalled_image_contexts"][0]
    assert "135. User:" in shared_context["memory_context"]
    assert "138. Assistant:" in shared_context["memory_context"]
    assert len(payload["recalled_image_candidates"]) == 2
    assert {
        candidate["memory_context_id"] for candidate in payload["recalled_image_candidates"]
    } == {shared_context["memory_context_id"]}
    assert all("memory_excerpt" not in candidate for candidate in payload["recalled_image_candidates"])


def test_router_failure_conservatively_uses_no_recalled_images():
    engine = _load_engine()
    original_completion = engine._chat_completion_create
    original_model = engine.RUNTIME_CONFIG.get("model_name")

    try:
        engine.RUNTIME_CONFIG["model_name"] = "test-model"
        engine._chat_completion_create = lambda *args, **kwargs: "not json"
        decision = engine._decide_long_term_memory_image_context(
            [{"role": "user", "content": "Generate a brand new image."}],
            _candidate_results(),
        )
    finally:
        engine._chat_completion_create = original_completion
        engine.RUNTIME_CONFIG["model_name"] = original_model

    assert decision["action"] == "no_images"
    assert decision["prior_image_requested"] is False
    assert decision["asset_ids"] == []
    assert "invalid" in decision["reason"].lower()


def test_unmatched_prior_image_request_informs_main_assistant_without_candidate_noise():
    engine = _load_engine()
    decision = {
        "action": "no_images",
        "prior_image_requested": True,
        "asset_ids": [],
        "reason": (
            "No candidate matches the magazines. Available candidates include an ethereal being and a cornfield."
        ),
    }

    context = engine._long_term_memory_image_lookup_context(decision)

    assert "no matching archived image" in context.lower()
    assert "no recalled image was attached" in context.lower()
    assert "textual conversation memory" in context.lower()
    assert "visually inspected" in context.lower()
    assert "textual memory only" in context.lower()
    assert "cannot currently inspect the image" in context.lower()
    assert "do not present inferred or remembered visual details as confirmed" in context.lower()
    assert "do not claim vivid, clear, or direct visual memory" in context.lower()
    assert "do not answer yes" in context.lower()
    assert "do not add, infer, embellish, or confirm" in context.lower()
    assert "words literally present in the user request" in context.lower()
    assert "layout, mood, aesthetic, setting, associations, or additional objects" in context.lower()
    assert "ethereal being" not in context.lower()
    assert engine._long_term_memory_image_lookup_context(
        {"action": "no_images", "prior_image_requested": False, "asset_ids": [], "reason": "ordinary text"}
    ) == ""


def test_prior_image_intent_is_independent_from_candidate_match():
    engine = _load_engine()
    decision = engine._normalize_long_term_memory_image_context_decision(
        {
            "action": "no_images",
            "request_kind": "prior_image",
            "asset_ids": [],
            "reason": (
                "The user asks whether I remember an image shown in the past, but no candidate matches it."
            ),
        },
        _candidate_results(),
        has_current_image=False,
    )

    assert decision["action"] == "no_images"
    assert decision["request_kind"] == "prior_image"
    assert decision["prior_image_requested"] is True
    assert engine._long_term_memory_image_lookup_context(decision)


def test_explicit_prior_image_request_repairs_contradictory_none_classification():
    engine = _load_engine()
    decision = engine._normalize_long_term_memory_image_context_decision(
        {
            "action": "no_images",
            "request_kind": "none",
            "asset_ids": [],
            "reason": "The user asks about a specific image shown in the past, but no candidate matches.",
        },
        _candidate_results(),
        has_current_image=False,
        latest_user_request=(
            "Do you remember the image I showed you that had magazines showing beautiful scenery?"
        ),
    )

    assert decision["action"] == "no_images"
    assert decision["request_kind"] == "prior_image"
    assert decision["prior_image_requested"] is True


def test_new_image_request_is_not_repaired_as_prior_image_intent():
    engine = _load_engine()
    decision = engine._normalize_long_term_memory_image_context_decision(
        {
            "action": "no_images",
            "request_kind": "new_generation",
            "asset_ids": [],
            "reason": "The user asks to create a new image.",
        },
        _candidate_results(),
        has_current_image=False,
        latest_user_request="Generate an image of magazines beside a vineyard.",
    )

    assert decision["request_kind"] == "new_generation"
    assert decision["prior_image_requested"] is False


def test_missing_recalled_image_guard_is_placed_immediately_after_latest_user_turn():
    engine = _load_engine()
    messages = [
        {"role": "user", "content": "Earlier question."},
        {"role": "assistant", "content": "Earlier answer."},
        {"role": "user", "content": "Do you remember the image with vineyard magazines?"},
    ]
    guard = (
        "Long-Term Memory image lookup found no matching archived image, so no recalled image was attached. "
        "Do not claim that you can currently see it."
    )

    guarded = engine._insert_long_term_memory_image_lookup_guard(messages, guard)

    assert [message["role"] for message in guarded] == ["user", "assistant", "user", "user"]
    assert guarded[-2]["content"] == "Do you remember the image with vineyard magazines?"
    assert guarded[-1]["content"] == guard


def test_missing_recalled_image_guard_strips_unrelated_historical_images():
    engine = _load_engine()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Here is a different image."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,OLD"}},
            ],
        },
        {"role": "assistant", "content": "That image shows an unrelated scene."},
        {"role": "user", "content": "Do you remember the image with vineyard magazines?"},
    ]

    filtered = engine._strip_historical_images_for_missing_memory_lookup(messages)

    assert filtered[0]["content"] == [{"type": "text", "text": "Here is a different image."}]
    assert filtered[1:] == messages[1:]
    assert "data:image" not in json.dumps(filtered)


def test_unmatched_prior_image_lookup_note_is_injected_into_recall_context():
    engine = _load_engine()
    from core import long_term_memory

    original_completion = engine._chat_completion_create
    original_retrieve = engine.retrieve_long_term_memory
    original_attach = long_term_memory.attach_assets_to_retrieval_results
    original_support = engine._current_model_supports_images
    original_config = dict(engine.RUNTIME_CONFIG)
    try:
        engine.RUNTIME_CONFIG["model_name"] = "test-model"
        engine.RUNTIME_CONFIG["long_term_memory_retrieval_enabled"] = True
        engine.RUNTIME_CONFIG["long_term_memory_retrieval_max_items"] = 6
        engine.RUNTIME_CONFIG["long_term_memory_recall_image_limit"] = 1
        engine.retrieve_long_term_memory = lambda *args, **kwargs: _candidate_results()
        long_term_memory.attach_assets_to_retrieval_results = lambda results, include_blob=False: results
        engine._current_model_supports_images = lambda: True
        engine._chat_completion_create = lambda *args, **kwargs: json.dumps(
            {
                "action": "no_images",
                "request_kind": "prior_image",
                "asset_ids": [],
                "reason": "No recalled candidate matches the magazines described by the user.",
            }
        )

        context, asset_messages, lookup_guard = engine.build_long_term_memory_recall(
            [{"role": "user", "content": "Can you recall the image with vineyard magazines?"}],
            include_lookup_context=True,
        )
    finally:
        engine._chat_completion_create = original_completion
        engine.retrieve_long_term_memory = original_retrieve
        long_term_memory.attach_assets_to_retrieval_results = original_attach
        engine._current_model_supports_images = original_support
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)

    assert "found no matching archived image" in context.lower()
    assert "visually inspected" in context.lower()
    assert "no matching archived image" in lookup_guard.lower()
    assert "ethereal" not in context.lower()
    assert "cornfield" not in context.lower()
    assert asset_messages == []


def test_disabled_retrieval_honors_lookup_context_return_shape():
    engine = _load_engine()

    original_config = dict(engine.RUNTIME_CONFIG)
    try:
        engine.RUNTIME_CONFIG["long_term_memory_retrieval_enabled"] = False
        result = engine.build_long_term_memory_recall(
            [{"role": "user", "content": "Hello"}],
            include_lookup_context=True,
        )
    finally:
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)

    assert result == ("", [], "")


def test_empty_query_honors_lookup_context_return_shape():
    engine = _load_engine()

    original_config = dict(engine.RUNTIME_CONFIG)
    try:
        engine.RUNTIME_CONFIG["long_term_memory_retrieval_enabled"] = True
        result = engine.build_long_term_memory_recall(
            [],
            include_lookup_context=True,
        )
    finally:
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)

    assert result == ("", [], "")


def test_long_term_memory_recall_text_defaults_to_uncapped_full_content():
    engine = _load_engine()
    from core import long_term_memory

    original_retrieve = engine.retrieve_long_term_memory
    original_attach = long_term_memory.attach_assets_to_retrieval_results
    original_config = dict(engine.RUNTIME_CONFIG)
    full_content = "1. User: " + ("A" * 900) + " FULL_CHUNK_END"
    try:
        engine.RUNTIME_CONFIG["long_term_memory_retrieval_enabled"] = True
        engine.RUNTIME_CONFIG["long_term_memory_retrieval_max_items"] = 1
        engine.RUNTIME_CONFIG["long_term_memory_recall_text_budget"] = -1
        engine.retrieve_long_term_memory = lambda *args, **kwargs: [
            {
                "kind": "chunk",
                "id": "chunk_full",
                "title": "Raw chat chunk",
                "content": full_content,
                "snippet": long_term_memory.compact_text(full_content, 720),
                "source_chat_id": "testing_memory",
                "source_message_start": 1,
                "source_message_end": 8,
                "assets": [],
            }
        ]
        long_term_memory.attach_assets_to_retrieval_results = lambda results, include_blob=False: results

        context, asset_messages = engine.build_long_term_memory_recall(
            [{"role": "user", "content": "Recall the full archived discussion."}]
        )
    finally:
        engine.retrieve_long_term_memory = original_retrieve
        long_term_memory.attach_assets_to_retrieval_results = original_attach
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)

    assert engine.RUNTIME_CONFIG.get("long_term_memory_recall_text_budget", -1) == -1
    assert full_content in context
    assert "FULL_CHUNK_END" in context
    assert asset_messages == []


def test_positive_long_term_memory_recall_text_budget_caps_total_recall_body():
    engine = _load_engine()
    from core import long_term_memory

    original_retrieve = engine.retrieve_long_term_memory
    original_attach = long_term_memory.attach_assets_to_retrieval_results
    original_config = dict(engine.RUNTIME_CONFIG)
    full_content = "1. User: " + ("B" * 200) + " FULL_CHUNK_END"
    try:
        engine.RUNTIME_CONFIG["long_term_memory_retrieval_enabled"] = True
        engine.RUNTIME_CONFIG["long_term_memory_retrieval_max_items"] = 1
        engine.RUNTIME_CONFIG["long_term_memory_recall_text_budget"] = 80
        engine.retrieve_long_term_memory = lambda *args, **kwargs: [
            {
                "kind": "chunk",
                "id": "chunk_limited",
                "title": "Raw chat chunk",
                "content": full_content,
                "snippet": long_term_memory.compact_text(full_content, 720),
                "source_chat_id": "testing_memory",
                "source_message_start": 1,
                "source_message_end": 8,
                "assets": [],
            }
        ]
        long_term_memory.attach_assets_to_retrieval_results = lambda results, include_blob=False: results

        context, asset_messages = engine.build_long_term_memory_recall(
            [{"role": "user", "content": "Recall the archived discussion."}]
        )
    finally:
        engine.retrieve_long_term_memory = original_retrieve
        long_term_memory.attach_assets_to_retrieval_results = original_attach
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)

    recall_line = next(line for line in context.splitlines() if line.startswith("   Recall: "))
    recall_body = recall_line.removeprefix("   Recall: ")
    assert len(recall_body) <= 80
    assert recall_body.endswith("...")
    assert "FULL_CHUNK_END" not in context
    assert asset_messages == []


def test_current_only_removes_old_visual_memory_but_keeps_text_memory():
    engine = _load_engine()
    results = _candidate_results() + [
        {
            "kind": "chunk",
            "id": "chunk_text_only",
            "snippet": "The user prefers concise answers.",
            "assets": [],
        }
    ]

    filtered = engine._filter_long_term_memory_results_for_image_decision(
        results,
        {"action": "current_only", "asset_ids": [], "reason": "Use the current attachment."},
    )

    assert [item["id"] for item in filtered] == ["chunk_text_only"]


def test_recalled_asset_message_includes_saved_visualization_prompt():
    engine = _load_engine()
    original_support = engine._current_model_supports_images
    results = _candidate_results()
    results[0]["assets"][0]["blob"] = b"remembered-image"
    results[0]["assets"][0]["mime_type"] = "image/png"

    try:
        engine._current_model_supports_images = lambda: True
        messages = engine._build_long_term_memory_asset_messages([results[0]], max_assets=1)
    finally:
        engine._current_model_supports_images = original_support

    assert len(messages) == 1
    assert "Visualization prompt: A man in a red jacket and a woman in a green jacket standing in a cornfield." in messages[0]["content"][0]["text"]


def test_prompt_backfill_uses_stored_partial_chunk_message_range():
    engine = _load_engine()
    from core import long_term_memory

    original_db = long_term_memory.default_db_path()
    original_history = list(engine.conversation_history)
    original_config = dict(engine.RUNTIME_CONFIG)
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            db_path = root / "memory.sqlite3"
            image_path = root / "cornfield.png"
            image_path.write_bytes(b"\x89PNG\r\ncornfield")
            partial_turns = [
                {
                    "index": 3,
                    "role": "assistant",
                    "label": "Assistant",
                    "content": "Here is the generated scene.",
                    "assets": [
                        {
                            "kind": "image",
                            "path": str(image_path),
                            "origin": "assistant_visual_reply",
                            "source": "generated_image",
                            "relation": "generated_by_reply",
                            "metadata": {"field": "visual_reply_image_path"},
                        }
                    ],
                },
                {"index": 4, "role": "user", "label": "User", "content": "It looks good."},
            ]
            chunk = long_term_memory.archive_history_chunk(
                partial_turns,
                source_chat_id="partial-backfill",
                path=db_path,
            )
            assert chunk is not None

            long_term_memory.set_default_db_path(db_path)
            engine.conversation_history[:] = [
                {"role": "user", "content": "First message."},
                {"role": "assistant", "content": "Second message."},
                {
                    "role": "assistant",
                    "content": "Here is the generated scene.",
                    "visual_reply_image_path": str(image_path),
                    "visual_reply_prompt": "A woman in a green jacket standing in a cornfield.",
                },
                {"role": "user", "content": "It looks good."},
            ]
            engine.RUNTIME_CONFIG["long_term_memory_auto_archive_enabled"] = True
            engine.RUNTIME_CONFIG["active_chat_context_name"] = "partial-backfill"
            engine.RUNTIME_CONFIG["long_term_memory_archive_batch_turns"] = 14

            refreshed = engine._refresh_long_term_memory_assets_for_current_chat()
            embedding_text = long_term_memory.embedding_text_for_chunk(chunk, path=db_path)

            assert refreshed >= 1
            assert "A woman in a green jacket standing in a cornfield." in embedding_text
    finally:
        long_term_memory.set_default_db_path(original_db)
        engine.conversation_history[:] = original_history
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)


def main() -> int:
    test_router_uses_visual_prompts_and_validates_selected_assets()
    test_image_candidates_share_one_complete_archived_chunk_context()
    test_router_failure_conservatively_uses_no_recalled_images()
    test_unmatched_prior_image_request_informs_main_assistant_without_candidate_noise()
    test_prior_image_intent_is_independent_from_candidate_match()
    test_explicit_prior_image_request_repairs_contradictory_none_classification()
    test_new_image_request_is_not_repaired_as_prior_image_intent()
    test_missing_recalled_image_guard_is_placed_immediately_after_latest_user_turn()
    test_missing_recalled_image_guard_strips_unrelated_historical_images()
    test_unmatched_prior_image_lookup_note_is_injected_into_recall_context()
    test_disabled_retrieval_honors_lookup_context_return_shape()
    test_empty_query_honors_lookup_context_return_shape()
    test_long_term_memory_recall_text_defaults_to_uncapped_full_content()
    test_positive_long_term_memory_recall_text_budget_caps_total_recall_body()
    test_current_only_removes_old_visual_memory_but_keeps_text_memory()
    test_recalled_asset_message_includes_saved_visualization_prompt()
    test_prompt_backfill_uses_stored_partial_chunk_message_range()
    print("long term memory image context router smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
