from __future__ import annotations

import engine


def test_conversation_boundaries_release_long_term_memory_store() -> None:
    calls: list[object] = []
    original_release = engine.long_term_memory.release_store
    original_clear_memory = engine.continuity_memory.clear_memory

    def release_store(path=None):
        calls.append(path)
        return 0

    engine.long_term_memory.release_store = release_store
    engine.continuity_memory.clear_memory = lambda memory_id: engine.continuity_memory.memory_path(memory_id)
    try:
        calls.clear()
        engine.reset_chat_runtime_state()
        assert calls, "Loading another conversation must release the active Long-Term Memory store"

        calls.clear()
        engine.reset_session_state()
        assert calls, "Restarting the current conversation must release the active Long-Term Memory store"

        calls.clear()
        engine.clear_continuity_memory()
        assert calls, "Clearing conversation memory must release the active Long-Term Memory store"
    finally:
        engine.long_term_memory.release_store = original_release
        engine.continuity_memory.clear_memory = original_clear_memory


if __name__ == "__main__":
    test_conversation_boundaries_release_long_term_memory_store()
    print("Long-Term Memory conversation release smoke test passed.")
