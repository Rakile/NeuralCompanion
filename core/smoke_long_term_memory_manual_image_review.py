from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_engine():
    addons_module = types.ModuleType("addons")
    addons_module.__path__ = [str(ROOT / "addons")]
    sys.modules["addons"] = addons_module
    import addons.vam_avatar.config  # noqa: F401
    import engine

    return engine


def _results():
    return [
        {
            "kind": "chunk",
            "id": "chunk_one",
            "source_chat_id": "review_chat",
            "source_message_start": 1,
            "source_message_end": 4,
            "content": "1. User: First image. 2. Assistant: First reply.",
            "assets": [
                {
                    "asset_id": "asset_one",
                    "kind": "image",
                    "role": "user",
                    "origin": "user_attachment",
                    "relation": "attached_to_turn",
                    "source_message_index": 1,
                    "mime_type": "image/png",
                    "blob": b"one",
                    "metadata": {"original_path": "one.png"},
                    "link_metadata": {},
                },
                {
                    "asset_id": "asset_two",
                    "kind": "image",
                    "role": "assistant",
                    "origin": "assistant_visual_reply",
                    "relation": "generated_by_reply",
                    "source_message_index": 2,
                    "mime_type": "image/jpeg",
                    "blob": b"two",
                    "metadata": {},
                    "link_metadata": {"visual_reply_prompt": "Second candidate"},
                },
            ],
        }
    ]


def test_review_callback_receives_all_candidates_and_can_override_selection():
    engine = _load_engine()
    original_config = dict(engine.RUNTIME_CONFIG)
    captured = {}

    def review(payload):
        captured.update(payload)
        return {"cancelled": False, "asset_ids": ["asset_two", "unknown"]}

    try:
        engine.RUNTIME_CONFIG["long_term_memory_image_review_enabled"] = True
        engine.register_long_term_memory_image_review_callback(review)
        decision = engine._apply_long_term_memory_image_review(
            [{"role": "user", "content": "Show me the remembered image."}],
            _results(),
            {
                "action": "memory_only",
                "request_kind": "prior_image",
                "prior_image_requested": True,
                "asset_ids": ["asset_one"],
                "reason": "The router selected the first candidate.",
            },
            has_current_image=False,
        )
    finally:
        engine.unregister_long_term_memory_image_review_callback(review)
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)

    assert [item["asset_id"] for item in captured["candidates"]] == ["asset_one", "asset_two"]
    assert captured["selected_asset_ids"] == ["asset_one"]
    assert captured["decision_reason"] == "The router selected the first candidate."
    assert captured["candidates"][1]["visualization_prompt"] == "Second candidate"
    assert captured["candidates"][0]["blob"] == b"one"
    assert decision["asset_ids"] == ["asset_two"]
    assert decision["action"] == "memory_only"
    assert decision["manual_review_applied"] is True


def test_review_cancel_raises_dedicated_cancellation():
    engine = _load_engine()
    original_config = dict(engine.RUNTIME_CONFIG)

    def review(_payload):
        return {"cancelled": True, "asset_ids": []}

    try:
        engine.RUNTIME_CONFIG["long_term_memory_image_review_enabled"] = True
        engine.register_long_term_memory_image_review_callback(review)
        try:
            engine._apply_long_term_memory_image_review(
                [{"role": "user", "content": "Recall an image."}],
                _results(),
                {"action": "no_images", "asset_ids": [], "reason": "No match."},
                has_current_image=False,
            )
        except engine.LongTermMemoryImageReviewCancelled:
            pass
        else:
            raise AssertionError("manual review cancellation did not abort the request")
    finally:
        engine.unregister_long_term_memory_image_review_callback(review)
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)


def test_disabled_review_preserves_automatic_decision_without_callback():
    engine = _load_engine()
    original_config = dict(engine.RUNTIME_CONFIG)
    called = []

    def review(_payload):
        called.append(True)
        return {"cancelled": False, "asset_ids": []}

    automatic = {"action": "memory_only", "asset_ids": ["asset_one"], "reason": "Automatic."}
    try:
        engine.RUNTIME_CONFIG["long_term_memory_image_review_enabled"] = False
        engine.register_long_term_memory_image_review_callback(review)
        decision = engine._apply_long_term_memory_image_review(
            [], _results(), automatic, has_current_image=False
        )
    finally:
        engine.unregister_long_term_memory_image_review_callback(review)
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)

    assert decision == automatic
    assert called == []


def test_bound_review_callback_can_be_unregistered_by_equivalent_method():
    engine = _load_engine()

    class Reviewer:
        def review(self, _payload):
            return {"cancelled": False, "asset_ids": []}

    reviewer = Reviewer()
    engine.register_long_term_memory_image_review_callback(reviewer.review)
    engine.unregister_long_term_memory_image_review_callback(reviewer.review)
    assert engine._long_term_memory_image_review_callback_snapshot() is None


def test_manual_empty_selection_uses_truthful_lookup_guard():
    engine = _load_engine()
    guard = engine._long_term_memory_image_lookup_context(
        {
            "action": "no_images",
            "request_kind": "prior_image",
            "prior_image_requested": True,
            "asset_ids": [],
            "manual_review_applied": True,
        }
    )
    assert "manual review" in guard.lower()
    assert "no recalled image was selected" in guard.lower()
    assert "no matching archived image" not in guard.lower()


def test_explicit_manual_selection_overrides_automatic_image_limit():
    engine = _load_engine()
    from core import long_term_memory

    original_config = dict(engine.RUNTIME_CONFIG)
    original_retrieve = engine.retrieve_long_term_memory
    original_attach = long_term_memory.attach_assets_to_retrieval_results
    original_decide = engine._decide_long_term_memory_image_context
    original_support = engine._current_model_supports_images
    hydrated = _results()

    def attach(_results_value, include_blob=False):
        copied = _results()
        if not include_blob:
            for item in copied:
                for asset in item["assets"]:
                    asset.pop("blob", None)
        return copied

    def review(_payload):
        return {"cancelled": False, "asset_ids": ["asset_one", "asset_two"]}

    try:
        engine.RUNTIME_CONFIG.update(
            {
                "long_term_memory_retrieval_enabled": True,
                "long_term_memory_retrieval_max_items": 2,
                "long_term_memory_recall_image_limit": 0,
                "long_term_memory_image_review_enabled": True,
            }
        )
        engine.retrieve_long_term_memory = lambda *args, **kwargs: hydrated
        long_term_memory.attach_assets_to_retrieval_results = attach
        engine._decide_long_term_memory_image_context = lambda *_args, **_kwargs: {
            "action": "no_images",
            "request_kind": "prior_image",
            "prior_image_requested": True,
            "asset_ids": [],
            "reason": "Automatic selection found no match.",
        }
        engine._current_model_supports_images = lambda: True
        engine.register_long_term_memory_image_review_callback(review)

        _context, messages = engine.build_long_term_memory_recall(
            [{"role": "user", "content": "Let me choose the images."}]
        )
    finally:
        engine.unregister_long_term_memory_image_review_callback(review)
        engine.retrieve_long_term_memory = original_retrieve
        long_term_memory.attach_assets_to_retrieval_results = original_attach
        engine._decide_long_term_memory_image_context = original_decide
        engine._current_model_supports_images = original_support
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(original_config)

    assert len(messages) == 2


def main() -> int:
    test_review_callback_receives_all_candidates_and_can_override_selection()
    test_review_cancel_raises_dedicated_cancellation()
    test_disabled_review_preserves_automatic_decision_without_callback()
    test_bound_review_callback_can_be_unregistered_by_equivalent_method()
    test_manual_empty_selection_uses_truthful_lookup_guard()
    test_explicit_manual_selection_overrides_automatic_image_limit()
    print("long term memory manual image review engine smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
