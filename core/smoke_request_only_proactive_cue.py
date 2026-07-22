from __future__ import annotations

import ast
import copy
import queue
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = str(Path(__file__).resolve().parent)
while SCRIPT_DIR in sys.path:
    sys.path.remove(SCRIPT_DIR)
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from core import conversation_history
from core.conversation_flow_v2 import (
    ConversationActionType,
    ConversationPolicy,
    ConversationStateMachine,
    ConversationEvent,
    ConversationEventType,
    ConversationState,
)


CUE = "You continue speaking."


def _roles(messages):
    return [str((item or {}).get("role", "")) for item in messages]


def test_request_copy_is_detached_and_obeys_tail_rules():
    source = [{"role": "assistant", "content": [{"type": "text", "text": "AAA"}]}]
    prepared = conversation_history.prepare_request_history_messages(source, cue_eligible=True)
    assert _roles(prepared) == ["assistant", "user"]
    assert prepared[-1] == {"role": "user", "content": CUE}
    prepared[0]["content"][0]["text"] = "changed"
    assert source[0]["content"][0]["text"] == "AAA"

    assert conversation_history.prepare_request_history_messages([], cue_eligible=True) == [
        {"role": "user", "content": CUE}
    ]
    user_ended = [{"role": "assistant", "content": "AAA"}, {"role": "user", "content": "ABABAB"}]
    assert conversation_history.prepare_request_history_messages(user_ended, cue_eligible=True) == user_ended
    system_ended = [{"role": "assistant", "content": "AAA"}, {"role": "system", "content": "guard"}]
    assert conversation_history.prepare_request_history_messages(system_ended, cue_eligible=True) == system_ended
    assistant_ended = [{"role": "assistant", "content": "AAA"}]
    assert conversation_history.prepare_request_history_messages(assistant_ended, cue_eligible=False) == assistant_ended


def test_hidden_specific_user_prompt_suppresses_generic_cue():
    messages = [
        {"role": "assistant", "content": "AAA"},
        {"role": "user", "content": "React now to this hidden sensory cue."},
    ]
    prepared = conversation_history.prepare_request_history_messages(messages, cue_eligible=True)
    assert prepared == messages
    assert sum(item.get("content") == CUE for item in prepared) == 0


def test_proactive_controller_emits_no_history_append():
    for stream_mode in (False, True):
        policy = ConversationPolicy(stream_mode=stream_mode, allow_proactive_replies=True)
        machine = ConversationStateMachine(policy)
        state = ConversationState()
        machine.dispatch(state, ConversationEvent(ConversationEventType.START), now=0.0)
        actions = machine.dispatch(
            state,
            ConversationEvent(ConversationEventType.INTERACTION_STATUS, {"status": "skip_speech"}),
            now=1.0,
        )
        assert any(action.type is ConversationActionType.GENERATE_PROACTIVE_TURN for action in actions)
        actions = machine.dispatch(state, ConversationEvent(ConversationEventType.THINKING_STARTED), now=2.0)
        assert all(action.type is not ConversationActionType.APPEND_HISTORY for action in actions)
        start_type = ConversationActionType.START_LLM_STREAM if stream_mode else ConversationActionType.START_LLM_REQUEST
        start = next(action for action in actions if action.type is start_type)
        assert start.payload.get("proactive") is True


def test_normal_user_and_skip_user_reply_contracts_remain_distinct():
    machine = ConversationStateMachine(ConversationPolicy(stream_mode=False))
    state = ConversationState()
    machine.dispatch(state, ConversationEvent(ConversationEventType.START), now=0.0)
    machine.dispatch(state, ConversationEvent(ConversationEventType.USER_TEXT_CAPTURED, {"text": CUE}), now=1.0)
    actions = machine.dispatch(state, ConversationEvent(ConversationEventType.THINKING_STARTED), now=2.0)
    appended = [action for action in actions if action.type is ConversationActionType.APPEND_HISTORY]
    assert len(appended) == 1
    assert appended[0].payload.get("placeholder") is not True

    state = ConversationState()
    machine.dispatch(state, ConversationEvent(ConversationEventType.START), now=0.0)
    machine.dispatch(
        state,
        ConversationEvent(ConversationEventType.INTERACTION_STATUS, {"status": "skip_user_reply"}),
        now=1.0,
    )
    actions = machine.dispatch(state, ConversationEvent(ConversationEventType.THINKING_STARTED), now=2.0)
    assert all(action.type is not ConversationActionType.APPEND_HISTORY for action in actions)
    request = next(action for action in actions if action.type is ConversationActionType.START_LLM_REQUEST)
    assert request.payload.get("proactive") is False


def test_proactive_barge_in_becomes_a_normal_user_turn():
    for stream_mode in (False, True):
        policy = ConversationPolicy(stream_mode=stream_mode, allow_proactive_replies=True)
        machine = ConversationStateMachine(policy)
        state = ConversationState()
        machine.dispatch(state, ConversationEvent(ConversationEventType.START), now=0.0)
        machine.dispatch(
            state,
            ConversationEvent(ConversationEventType.INTERACTION_STATUS, {"status": "skip_speech"}),
            now=1.0,
        )
        machine.dispatch(state, ConversationEvent(ConversationEventType.THINKING_STARTED), now=2.0)
        machine.dispatch(
            state,
            ConversationEvent(ConversationEventType.ASSISTANT_REPLY_READY, {"text": "proactive reply"}),
            now=3.0,
        )
        machine.dispatch(
            state,
            ConversationEvent(ConversationEventType.BARGE_IN_CAPTURED, {"text": "real user turn"}),
            now=4.0,
        )
        actions = machine.dispatch(state, ConversationEvent(ConversationEventType.THINKING_STARTED), now=5.0)
        appended = [action for action in actions if action.type is ConversationActionType.APPEND_HISTORY]
        assert len(appended) == 1
        assert appended[0].payload == {"role": policy.input_message_role, "content": "real user turn"}
        start_type = ConversationActionType.START_LLM_STREAM if stream_mode else ConversationActionType.START_LLM_REQUEST
        start = next(action for action in actions if action.type is start_type)
        assert start.payload.get("proactive") is False
        assert state.is_proactive_turn is False
        assert state.proactive_placeholder_role is None
        assert state.preserve_proactive_placeholder is False


def test_regeneration_contracts_and_legacy_rows():
    history = [
        {"role": "assistant", "content": "AAA", "origin": "assistant_reply"},
        {"role": "assistant", "content": "BBB", "origin": "assistant_reply"},
    ]
    resumed, removed = conversation_history.prepare_regeneration_turn(
        history, target_in_history=True, input_roles={"user", "system"}
    )
    assert removed is True
    assert resumed is None
    assert history == [{"role": "assistant", "content": "AAA", "origin": "assistant_reply"}]
    outbound = conversation_history.prepare_request_history_messages(history, cue_eligible=True)
    assert outbound[-1] == {"role": "user", "content": CUE}

    history = [
        {"role": "assistant", "content": "AAA", "origin": "assistant_reply"},
        {
            "role": "user",
            "content": "ABABAB",
            "origin": "input",
            "created_at": 123.5,
            "attachment_image_path": "x.png",
            "attachment_source": "clipboard",
            "identity_relay": {
                "state": "active",
                "artifact_ref": "library/example.json",
                "snapshot_hash": "frozen-snapshot",
            },
        },
        {"role": "assistant", "content": "BBB", "origin": "assistant_reply"},
    ]
    resumed, removed = conversation_history.prepare_regeneration_turn(
        history, target_in_history=True, input_roles={"user", "system"}
    )
    assert removed is True
    assert resumed["content"] == "ABABAB"
    assert resumed["attachment_image_path"] == "x.png"
    assert resumed["created_at"] == 123.5
    assert resumed["attachment_source"] == "clipboard"
    assert resumed["identity_relay"]["snapshot_hash"] == "frozen-snapshot"
    resumed["identity_relay"]["state"] = "mutated"
    assert history[-1]["identity_relay"]["state"] == "active"
    assert conversation_history.prepare_request_history_messages(history, cue_eligible=True) == history

    prior = [{"role": "assistant", "content": "AAA", "origin": "assistant_reply"}]
    resumed, removed = conversation_history.prepare_regeneration_turn(
        prior, target_in_history=False, input_roles={"user", "system"}
    )
    assert removed is False
    assert resumed is None
    assert prior[0]["content"] == "AAA"

    legacy = [{"role": "user", "content": CUE, "origin": "input"}]
    resumed, removed = conversation_history.prepare_regeneration_turn(
        legacy, target_in_history=False, input_roles={"user", "system"}
    )
    assert removed is False
    assert resumed["content"] == CUE
    assert legacy == [{"role": "user", "content": CUE, "origin": "input"}]
    assert conversation_history.prepare_request_history_messages(legacy, cue_eligible=True) == legacy

    repeated = [{"role": "assistant", "content": "AAA", "origin": "assistant_reply"}]
    initial_user_count = sum(item.get("role") == "user" for item in repeated)
    for replacement in ("BBB", "CCC", "DDD"):
        outbound = conversation_history.prepare_request_history_messages(repeated, cue_eligible=True)
        assert outbound[-1] == {"role": "user", "content": CUE}
        assert sum(item.get("role") == "user" for item in repeated) == initial_user_count
        repeated.append({"role": "assistant", "content": replacement, "origin": "assistant_reply"})
        resumed, removed = conversation_history.prepare_regeneration_turn(
            repeated, target_in_history=True, input_roles={"user", "system"}
        )
        assert removed is True
        assert resumed is None
        assert sum(item.get("role") == "user" for item in repeated) == initial_user_count


def test_active_vocalization_skip_branch_stays_provider_free():
    source = (ROOT / "engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    flow = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_conversation_flow")
    active_skip = ""
    for node in ast.walk(flow):
        if not isinstance(node, ast.If):
            continue
        segment = ast.get_source_segment(source, node.test) or ""
        if 'status == "skip_speech"' not in segment:
            continue
        replay_split = next(
            (
                statement
                for statement in node.body
                if isinstance(statement, ast.If)
                and "response_text_is_replay" in (ast.get_source_segment(source, statement.test) or "")
            ),
            None,
        )
        if replay_split is not None and replay_split.orelse:
            active_skip = "\n".join(
                ast.get_source_segment(source, statement) or ""
                for statement in replay_split.orelse
            )
            break
    assert active_skip
    assert "stop_playback.set()" in active_skip
    assert "chat_with_llm(" not in active_skip
    assert "start_streamed_llm_reply(" not in active_skip
    assert "regenerating = True" not in active_skip
    assert "discard_assistant_history = True" not in active_skip
    assert "stream_state.cancel_requested.set()" not in active_skip


def test_stream_generation_is_not_cancelled_by_playback_stop():
    source = (ROOT / "engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    stream_fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "start_streamed_llm_reply"
    )
    segment = ast.get_source_segment(source, stream_fn) or ""
    assert "stop_playback.is_set()" not in segment


def test_stream_collects_complete_reply_after_playback_stop():
    import engine

    original_build = engine.build_llm_request
    original_completion = engine._chat_completion_create
    original_runtime = engine._chat_runtime
    stop_playback_was_set = engine.stop_playback.is_set()
    stop_flag_was_set = engine.stop_flag.is_set()

    class FrozenRuntime:
        def __init__(self):
            self.context = object()
            self.prepared = object()
            self.prepared_calls = []
            self.stream_calls = []

        def capture_frozen_context(self):
            return self.context

        def frozen_execution_available(self, context, *, stream=False):
            assert context is self.context
            return True

        def prepare_frozen_request(self, context, params, additional_params):
            assert context is self.context
            self.prepared_calls.append((params, additional_params))
            return self.prepared

        def stream_frozen(self, request, *, cancel_token=None):
            assert request is self.prepared
            self.stream_calls.append((request, cancel_token))
            return iter(["complete ", "assistant reply"])

    runtime = FrozenRuntime()
    try:
        engine.build_llm_request = lambda request_context=None: (
            {"model": "test", "messages": []},
            {},
        )
        engine._chat_completion_create = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("normal chat must not use the live completion path")
            )
        )
        engine._chat_runtime = runtime
        engine.stop_flag.clear()
        engine.stop_playback.set()
        accepted_turn = engine._begin_normal_chat_transaction(
            {"role": "user", "content": "stream fixture"}
        )
        request_context = engine._freeze_normal_chat_request(accepted_turn)
        text_queue = queue.Queue()
        state = engine.start_streamed_llm_reply(
            text_queue,
            request_context=request_context,
        )
        assert state.done.wait(timeout=3.0)
        assert state.full_text == "complete assistant reply"
        assert len(runtime.prepared_calls) == 1
        assert len(runtime.stream_calls) == 1
    finally:
        engine.build_llm_request = original_build
        engine._chat_completion_create = original_completion
        engine._chat_runtime = original_runtime
        if stop_playback_was_set:
            engine.stop_playback.set()
        else:
            engine.stop_playback.clear()
        if stop_flag_was_set:
            engine.stop_flag.set()
        else:
            engine.stop_flag.clear()


def test_stream_startup_fallback_reuses_the_same_frozen_request():
    import engine

    original_build = engine.build_llm_request
    original_runtime = engine._chat_runtime

    class FrozenRuntime:
        def __init__(self):
            self.context = object()
            self.prepared = object()
            self.stream_requests = []
            self.complete_requests = []

        def capture_frozen_context(self):
            return self.context

        def frozen_execution_available(self, context, *, stream=False):
            return context is self.context

        def prepare_frozen_request(self, context, params, additional_params):
            assert context is self.context
            return self.prepared

        def stream_frozen(self, request, *, cancel_token=None):
            self.stream_requests.append(request)
            raise RuntimeError("startup failure")

        def complete_frozen(self, request, *, timeout=None, cancel_token=None):
            del timeout, cancel_token
            self.complete_requests.append(request)
            return "frozen fallback"

    runtime = FrozenRuntime()
    try:
        engine.build_llm_request = lambda request_context=None: (
            {"model": "test", "messages": []},
            {},
        )
        engine._chat_runtime = runtime
        accepted_turn = engine._begin_normal_chat_transaction(
            {"role": "user", "content": "fallback fixture"}
        )
        request_context = engine._freeze_normal_chat_request(accepted_turn)
        state = engine.start_streamed_llm_reply(queue.Queue(), request_context=request_context)
        assert state.done.wait(timeout=3.0)
        assert state.full_text == "frozen fallback"
        assert runtime.stream_requests == [runtime.prepared]
        assert runtime.complete_requests == [runtime.prepared]
    finally:
        engine.build_llm_request = original_build
        engine._chat_runtime = original_runtime


def test_build_request_injects_only_after_request_local_user_messages():
    import engine

    original_build_hidden_context = engine._build_active_hidden_proactive_context_text
    original_build_hidden_prompt = engine._build_active_hidden_proactive_prompt_message
    original_collect = engine._collect_addon_chat_contexts
    original_memory = engine.continuity_memory.build_context
    original_ltm = engine.build_long_term_memory_recall
    original_sensory = engine._build_sensory_feedback_messages
    runtime_snapshot = dict(engine.RUNTIME_CONFIG)
    try:
        engine.RUNTIME_CONFIG.update({
            "emotional_instructions": "emotion",
            "system_prompt": "persona",
            "model_name": "test-model",
            "active_preset_name": "",
        })
        engine._collect_addon_chat_contexts = lambda history, **kwargs: []
        engine.continuity_memory.build_context = lambda *args, **kwargs: ""
        engine.build_long_term_memory_recall = lambda *args, **kwargs: ("", [], "")
        engine._build_sensory_feedback_messages = lambda: []
        engine._build_active_hidden_proactive_context_text = lambda: ""
        engine._build_active_hidden_proactive_prompt_message = lambda: None
        request = {
            "kind": "normal_chat",
            "history": [{"role": "assistant", "content": "AAA"}],
            "request_only_continue_cue": True,
        }
        params, _ = engine.build_llm_request(request)
        assert params["messages"][-1] == {"role": "user", "content": CUE}
        assert request["history"] == [{"role": "assistant", "content": "AAA"}]

        engine._build_active_hidden_proactive_context_text = lambda: "hidden"
        engine._build_active_hidden_proactive_prompt_message = lambda: {
            "role": "user",
            "content": "specific hidden prompt",
        }
        params, _ = engine.build_llm_request(request)
        assert params["messages"][-1]["content"] == "specific hidden prompt"
        assert sum(item.get("content") == CUE for item in params["messages"] if isinstance(item, dict)) == 0
    finally:
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(runtime_snapshot)
        engine._build_active_hidden_proactive_context_text = original_build_hidden_context
        engine._build_active_hidden_proactive_prompt_message = original_build_hidden_prompt
        engine._collect_addon_chat_contexts = original_collect
        engine.continuity_memory.build_context = original_memory
        engine.build_long_term_memory_recall = original_ltm
        engine._build_sensory_feedback_messages = original_sensory


def test_stream_and_fallback_share_frozen_prepared_request_structure():
    source = (ROOT / "engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    stream_fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "start_streamed_llm_reply"
    )
    segment = ast.get_source_segment(source, stream_fn) or ""
    assert "request_context = request_context or _freeze_normal_chat_request(" in segment
    assert "prepared_request = _prepared_normal_chat_provider_request(request_context)" in segment
    assert "fallback_text = chat_with_llm(" in segment
    assert "request_context," in segment
    assert "prepared_request=prepared_request," in segment
    assert "discard_empty_transaction=False," in segment


def main():
    test_request_copy_is_detached_and_obeys_tail_rules()
    test_hidden_specific_user_prompt_suppresses_generic_cue()
    test_proactive_controller_emits_no_history_append()
    test_normal_user_and_skip_user_reply_contracts_remain_distinct()
    test_proactive_barge_in_becomes_a_normal_user_turn()
    test_regeneration_contracts_and_legacy_rows()
    test_active_vocalization_skip_branch_stays_provider_free()
    test_stream_generation_is_not_cancelled_by_playback_stop()
    test_stream_collects_complete_reply_after_playback_stop()
    test_stream_startup_fallback_reuses_the_same_frozen_request()
    test_build_request_injects_only_after_request_local_user_messages()
    test_stream_and_fallback_share_frozen_prepared_request_structure()
    print("smoke_request_only_proactive_cue: ok")


if __name__ == "__main__":
    main()
