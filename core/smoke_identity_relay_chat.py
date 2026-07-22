from __future__ import annotations

import copy
import importlib
import io
import json
import sys
import threading
import types
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))


def _load_test_module(*parts: str):
    return importlib.import_module(".".join(parts))


addons_module = types.ModuleType("addons")
addons_module.__path__ = [str(ROOT / "addons")]
sys.modules["addons"] = addons_module
_load_test_module("addons", "vam_avatar", "config")

engine = _load_test_module("engine")


ACTIVE = {
    "state": "active",
    "artifact_ref": "library/" + "a" * 64 + ".json",
    "artifact_hash": "a" * 64,
    "hot_identity_text": "Frozen continuity",
    "failure_code": None,
}


def _install_capture_result(snapshot):
    original = engine._invoke_targeted_addon_capability
    engine._invoke_targeted_addon_capability = (
        lambda addon_id, capability, payload=None: dict(snapshot)
        if capability == "identity_relay.capture_turn"
        else None
    )
    return original


def _clear_relay_runtime() -> None:
    engine.replace_chat_conversation_history([])
    with engine.identity_relay_snapshot_lock:
        engine.identity_relay_snapshot_registry.clear()


def test_targeted_capability_uses_exact_addon_route() -> None:
    calls = []

    class FakeManager:
        def invoke_addon_capability(self, addon_id, capability, payload):
            calls.append((addon_id, capability, payload))
            return {"ok": True}

    original_getter = engine._get_addon_manager
    engine._get_addon_manager = lambda: FakeManager()
    try:
        assert engine._invoke_targeted_addon_capability("nc.identity_artifacts", "capture", {"x": 1}) == {
            "ok": True
        }
        assert calls == [("nc.identity_artifacts", "capture", {"x": 1})]
    finally:
        engine._get_addon_manager = original_getter


def test_targeted_projection_preserves_exact_context_text() -> None:
    exact_context = "Identity Relay layer\n\n  Frozen continuity with exact whitespace.  \n"

    class FakeManager:
        def invoke_addon_capability(self, addon_id, capability, payload):
            assert addon_id == engine.IDENTITY_RELAY_ADDON_ID
            assert capability == "chat_context.collect"
            return {"context": exact_context, "debug": {"source": "identity_relay"}}

    original_getter = engine._get_addon_manager
    engine._get_addon_manager = lambda: FakeManager()
    try:
        contexts = engine._collect_targeted_identity_relay_chat_contexts([], ACTIVE)
    finally:
        engine._get_addon_manager = original_getter

    assert contexts == [
        {"context": exact_context, "debug": {"source": "identity_relay"}}
    ]


def test_typed_acceptance_captures_before_append() -> None:
    artifact_ref = ACTIVE["artifact_ref"]
    artifact_hash = ACTIVE["artifact_hash"]

    class FrozenContext:
        provider_name = "typed-provider"
        model_name = "typed-model"
        provider_config = {"provider_is_remote": False}
        generation_fields = {"max_tokens": 32}
        capabilities = types.SimpleNamespace(context_limit=512)

        def to_summary(self):
            return {
                "provider_name": self.provider_name,
                "model_name": self.model_name,
                "strict_relay_available": False,
            }

    class FrozenRequest:
        def __init__(self, context, params, additional):
            self.context = context
            self.params = copy.deepcopy(params)
            self.additional = copy.deepcopy(additional)

        def params_copy(self):
            return copy.deepcopy(self.params)

        def additional_params_copy(self):
            return copy.deepcopy(self.additional)

    class FrozenRuntime:
        def __init__(self):
            self.context = FrozenContext()
            self.prepare_calls = []

        def capture_frozen_context(self):
            return self.context

        def upgrade_frozen_context_for_relay(self, context):
            assert context is self.context
            return context

        def strict_relay_capability_available(self, context):
            return context is self.context

        def frozen_execution_available(self, context, *, stream=False):
            del stream
            return context is self.context

        def prepare_frozen_request(self, context, params, additional_params=None):
            prepared_params = dict(params or {})
            prepared_params["model"] = context.model_name
            prepared_params.setdefault("max_tokens", context.generation_fields["max_tokens"])
            request = FrozenRequest(context, prepared_params, additional_params or {})
            self.prepare_calls.append(request)
            return request

    runtime = FrozenRuntime()
    original_runtime = engine._chat_runtime
    original_invoke = engine._invoke_targeted_addon_capability
    original_count = engine.chat_providers.count_frozen_chat_tokens
    calls = []

    def invoke(_addon_id, capability, payload=None):
        calls.append(capability)
        if capability == "identity_relay.capture_turn":
            assert dict(payload or {}).get("schema_version") == 2
            return types.SimpleNamespace(
                enabled=True,
                artifact_ref=artifact_ref,
                artifact_hash=artifact_hash,
            )
        if capability == "identity_relay.prepare_turn":
            return types.SimpleNamespace(status="ready_without_judge", failure_code="")
        if capability == "identity_relay.finalize_turn":
            return types.SimpleNamespace(
                schema_version=2,
                projection_kind="normalized_projection",
                status="ready",
                artifact_ref=artifact_ref,
                artifact_hash=artifact_hash,
                normalizer_revision="normalizer-v2",
                attestation_revision=1,
                transient_state={},
                effective_use_decisions={},
                kernel_record_ids=("kernel",),
                prompt_text="Typed v2 continuity",
                selected_record_ids=(),
                selection_reasons={},
                signals_considered={},
                unresolved_record_ids=(),
                trace={},
                snapshot_hash="b" * 64,
                persistence_mode="persistent",
                failure_code="",
            )
        raise AssertionError(f"unexpected capability: {capability}")

    try:
        _clear_relay_runtime()
        engine._chat_runtime = runtime
        engine._invoke_targeted_addon_capability = invoke
        engine.chat_providers.count_frozen_chat_tokens = lambda _context, _messages: 64
        result = engine.queue_typed_chat_message("hello")
        assert engine.conversation_history == []
        pending = engine._consume_pending_loaded_input_turn()
        assert pending["normal_chat_transaction_id"]
        request = engine._freeze_normal_chat_request(
            pending,
            require_existing_transaction=True,
        )
        engine._ensure_normal_chat_transaction_ready(request)
        turn = engine.conversation_history[-1]
        assert result["queued"] is True
        assert len(engine.conversation_history) == 1
        assert turn["identity_relay"]["schema_version"] == 2
        assert turn["identity_relay"]["status"] == "ready"
        assert len(turn["identity_relay"]["snapshot_hash"]) == 64
        assert calls == [
            "identity_relay.capture_turn",
            "identity_relay.prepare_turn",
            "identity_relay.finalize_turn",
        ]
        assert len(runtime.prepare_calls) == 1
    finally:
        engine._chat_runtime = original_runtime
        engine._invoke_targeted_addon_capability = original_invoke
        engine.chat_providers.count_frozen_chat_tokens = original_count
        engine.reset_session_state()


def test_relay_off_typed_turn_freezes_provider_without_identity_work() -> None:
    class FrozenContext:
        provider_name = "relay-off-provider"
        model_name = "relay-off-model"
        provider_config = {"provider_is_remote": False}
        generation_fields = {"max_tokens": 32}

        def to_summary(self):
            return {
                "provider_name": self.provider_name,
                "model_name": self.model_name,
                "strict_relay_available": False,
            }

    class FrozenRuntime:
        def __init__(self):
            self.captures = []
            self.prepared = []

        def capture_frozen_context(self):
            context = FrozenContext()
            self.captures.append(context)
            return context

        def frozen_execution_available(self, context, *, stream=False):
            del stream
            return context is self.captures[0]

        def prepare_frozen_request(self, context, params, additional_params=None):
            request = types.SimpleNamespace(
                context=context,
                params_copy=lambda: copy.deepcopy(dict(params or {})),
                additional_params_copy=lambda: copy.deepcopy(dict(additional_params or {})),
            )
            self.prepared.append(request)
            return request

    runtime = FrozenRuntime()
    original_runtime = engine._chat_runtime
    original_invoke = engine._invoke_targeted_addon_capability
    relay_calls = []
    try:
        _clear_relay_runtime()
        engine._chat_runtime = runtime
        engine._invoke_targeted_addon_capability = lambda _addon_id, capability, _payload=None: (
            relay_calls.append(capability)
            or types.SimpleNamespace(
                enabled=False,
                artifact_ref=ACTIVE["artifact_ref"],
                artifact_hash=ACTIVE["artifact_hash"],
            )
            if capability == "identity_relay.capture_turn"
            else (_ for _ in ()).throw(
                AssertionError("Relay OFF must not invoke Identity Relay processing")
            )
        )

        result = engine.queue_typed_chat_message("Relay-free turn")
        assert engine.conversation_history == []
        pending = engine._consume_pending_loaded_input_turn()
        request = engine._freeze_normal_chat_request(
            pending,
            require_existing_transaction=True,
        )
        engine._ensure_normal_chat_transaction_ready(request)

        assert result["queued"] is True
        assert len(runtime.captures) == 1
        transaction_id = engine.conversation_history[-1]["normal_chat_transaction_id"]
        assert engine.normal_chat_transaction_registry[transaction_id]["provider_context"] is runtime.captures[0]
        assert relay_calls == ["identity_relay.capture_turn"]
        assert engine.conversation_history[-1]["identity_relay"]["status"] == "suspended"
        assert len(runtime.prepared) == 1
    finally:
        engine._chat_runtime = original_runtime
        engine._invoke_targeted_addon_capability = original_invoke
        engine.reset_session_state()


def test_suspended_and_proactive_turns_do_not_store_active_text() -> None:
    suspended = {**ACTIVE, "state": "suspended", "hot_identity_text": ""}
    original = _install_capture_result(suspended)
    try:
        _clear_relay_runtime()
        turn = engine._finalize_identity_relay_for_user_turn({"role": "user", "content": "roleplay"})
        assert turn["identity_relay"]["state"] == "suspended"
        assert "hot_identity_text" not in turn["identity_relay"]
        assert engine._finalize_identity_relay_for_user_turn(
            {"role": "user", "content": "You continue speaking."}, is_placeholder=True
        ).get("identity_relay") is None
    finally:
        engine._invoke_targeted_addon_capability = original


def test_saved_session_keeps_one_snapshot_copy_and_round_trips_metadata() -> None:
    original = _install_capture_result(ACTIVE)
    try:
        _clear_relay_runtime()
        first = engine._finalize_identity_relay_for_user_turn({"role": "user", "content": "one"})
        second = engine._finalize_identity_relay_for_user_turn({"role": "user", "content": "two"})
        assert first["identity_relay"]["snapshot_hash"] == second["identity_relay"]["snapshot_hash"]
        engine.replace_chat_conversation_history([first, second])
        payload = engine.export_chat_session_state()
        assert len(payload["identity_relay_snapshots"]) == 1
        engine.import_chat_session_state(payload)
        assert engine.conversation_history[0]["identity_relay"] == first["identity_relay"]
    finally:
        engine._invoke_targeted_addon_capability = original


def test_active_persistence_preserves_history_when_snapshot_is_missing() -> None:
    _clear_relay_runtime()
    metadata, _registry_entry = engine._freeze_identity_relay_snapshot(ACTIVE)
    engine.replace_chat_conversation_history(
        [{"role": "user", "content": "missing snapshot", "identity_relay": metadata}]
    )

    first_save = engine.export_chat_session_state()
    first_metadata = first_save["conversation_history"][0]["identity_relay"]
    assert first_metadata == metadata
    assert first_save["identity_relay_snapshots"] == {}

    engine.import_chat_session_state(first_save)
    assert engine.conversation_history[0]["identity_relay"] == metadata
    expanded = engine._expand_identity_relay_for_request(engine.conversation_history[0])
    assert expanded == {
        "state": "unavailable",
        "artifact_ref": ACTIVE["artifact_ref"],
        "failure_code": "missing",
        "hot_identity_text": "",
    }
    try:
        engine._freeze_normal_chat_request(
            engine.conversation_history[0],
            require_existing_transaction=True,
        )
    except engine.NormalChatTurnBlocked as exc:
        assert "persisted relay projection" in str(exc).lower()
    else:
        raise AssertionError("loaded legacy turn silently recaptured the live provider")


def test_stream_request_and_fallback_reuse_frozen_history_and_relay() -> None:
    original_collect = engine._collect_addon_chat_contexts
    try:
        _clear_relay_runtime()
        engine._collect_addon_chat_contexts = lambda history, **payload: []
        request = {
            "kind": "normal_chat",
            "history": [{"role": "user", "content": "first", "origin": "input"}],
            "identity_relay_snapshot": {
                "schema_version": 2,
                "projection_kind": "normalized_projection",
                "status": "ready",
                "artifact_ref": ACTIVE["artifact_ref"],
                "artifact_hash": ACTIVE["artifact_hash"],
                "snapshot_hash": "b" * 64,
                "prompt_text": "Frozen v2 continuity",
            },
            "request_only_continue_cue": False,
        }
        engine.conversation_history.append({"role": "user", "content": "later"})
        stream_params, _ = engine.build_llm_request(request)
        fallback_params, _ = engine.build_llm_request(request)
        for params in (stream_params, fallback_params):
            serialized = json.dumps(params["messages"])
            assert "later" not in serialized
            assert serialized.count("Frozen v2 continuity") == 1
    finally:
        engine._collect_addon_chat_contexts = original_collect


def test_relay_snapshot_is_targeted_and_generic_collectors_see_no_relay() -> None:
    _clear_relay_runtime()
    generic_payloads = []
    invoked_addons = []
    snapshot = {
        "schema_version": 2,
        "projection_kind": "normalized_projection",
        "status": "ready",
        "artifact_ref": ACTIVE["artifact_ref"],
        "artifact_hash": ACTIVE["artifact_hash"],
        "snapshot_hash": "c" * 64,
        "prompt_text": "Private v2 projection",
    }

    class FakeManager:
        def get_loaded_addons(self):
            return [
                types.SimpleNamespace(manifest=types.SimpleNamespace(id="nc.generic")),
                types.SimpleNamespace(
                    manifest=types.SimpleNamespace(id=engine.IDENTITY_RELAY_ADDON_ID)
                ),
            ]

        def invoke_addon_capability(self, addon_id, capability, payload):
            invoked_addons.append(addon_id)
            assert addon_id != engine.IDENTITY_RELAY_ADDON_ID
            generic_payloads.append((capability, copy.deepcopy(payload)))
            return {"context": "generic context", "debug": {}}

    original_getter = engine._get_addon_manager
    engine._get_addon_manager = lambda: FakeManager()
    try:
        request = {
            "kind": "normal_chat",
            "history": [{"role": "user", "content": "private relay"}],
            "identity_relay_snapshot": snapshot,
        }
        params, _ = engine.build_llm_request(request)
    finally:
        engine._get_addon_manager = original_getter

    assert len(generic_payloads) == 1
    assert generic_payloads[0][0] == "chat_context.collect"
    generic_serialized = json.dumps(generic_payloads[0][1], sort_keys=True)
    for forbidden in (
        "identity_relay",
        "snapshot_hash",
        "artifact_ref",
        "artifact_hash",
        ACTIVE["artifact_ref"],
        ACTIVE["artifact_hash"],
        ACTIVE["hot_identity_text"],
        snapshot["snapshot_hash"],
    ):
        assert forbidden not in generic_serialized

    assert invoked_addons == ["nc.generic"]
    assert json.dumps(params["messages"]).count(snapshot["prompt_text"]) == 1


def test_failed_active_projection_blocks_turn_without_assistant_provenance() -> None:
    class FrozenContext:
        provider_name = "blocked-provider"
        model_name = "blocked-model"
        provider_config = {"provider_is_remote": False}
        generation_fields = {"max_tokens": 32}

        def to_summary(self):
            return {
                "provider_name": self.provider_name,
                "model_name": self.model_name,
                "strict_relay_available": False,
            }

    class FrozenRuntime:
        def __init__(self):
            self.context = FrozenContext()
            self.reply_calls = []

        def capture_frozen_context(self):
            return self.context

        def upgrade_frozen_context_for_relay(self, context):
            assert context is self.context
            return context

        def strict_relay_capability_available(self, context):
            assert context is self.context
            return False

        def complete_frozen(self, request, **_kwargs):
            self.reply_calls.append(request)
            return "must not dispatch"

        def stream_frozen(self, request, **_kwargs):
            self.reply_calls.append(request)
            return iter(())

    runtime = FrozenRuntime()
    original_runtime = engine._chat_runtime
    original_invoke = engine._invoke_targeted_addon_capability

    def invoke(_addon_id, capability, payload=None):
        if capability == "identity_relay.capture_turn":
            assert dict(payload or {}).get("schema_version") == 2
            return types.SimpleNamespace(
                enabled=True,
                artifact_ref=ACTIVE["artifact_ref"],
                artifact_hash=ACTIVE["artifact_hash"],
            )
        raise AssertionError(f"blocked active turn reached {capability}")

    try:
        _clear_relay_runtime()
        engine._chat_runtime = runtime
        engine._invoke_targeted_addon_capability = invoke
        assert engine.queue_typed_chat_message("projection failure")["queued"] is True
        pending = engine._consume_pending_loaded_input_turn()
        request = engine._freeze_normal_chat_request(
            pending,
            require_existing_transaction=True,
        )
        try:
            engine._ensure_normal_chat_transaction_ready(request)
        except engine.NormalChatTurnBlocked as exc:
            assert "strict" in str(exc).lower()
        else:
            raise AssertionError("Relay ON failure did not block the turn")
        assert runtime.reply_calls == []
        assert engine.conversation_history == []
    finally:
        engine._chat_runtime = original_runtime
        engine._invoke_targeted_addon_capability = original_invoke
        engine.reset_session_state()


def test_malformed_v2_projection_fails_closed_before_provider_dispatch() -> None:
    class FrozenContext:
        provider_name = "malformed-provider"
        model_name = "malformed-model"
        provider_config = {"provider_is_remote": False}
        generation_fields = {"max_tokens": 32}

        def to_summary(self):
            return {
                "provider_name": self.provider_name,
                "model_name": self.model_name,
                "strict_relay_available": True,
            }

    class FrozenRuntime:
        def __init__(self):
            self.context = FrozenContext()
            self.reply_calls = []

        def capture_frozen_context(self):
            return self.context

        def upgrade_frozen_context_for_relay(self, context):
            assert context is self.context
            return context

        def strict_relay_capability_available(self, context):
            return context is self.context

        def complete_frozen(self, request, **_kwargs):
            self.reply_calls.append(request)
            return "must not dispatch"

        def stream_frozen(self, request, **_kwargs):
            self.reply_calls.append(request)
            return iter(())

    runtime = FrozenRuntime()
    calls = []
    original_runtime = engine._chat_runtime
    original_invoke = engine._invoke_targeted_addon_capability

    def invoke(_addon_id, capability, payload=None):
        calls.append((capability, dict(payload or {}), threading.current_thread().name))
        if capability == "identity_relay.capture_turn":
            return types.SimpleNamespace(
                enabled=True,
                artifact_ref=ACTIVE["artifact_ref"],
                artifact_hash=ACTIVE["artifact_hash"],
            )
        if capability == "identity_relay.prepare_turn":
            return types.SimpleNamespace(status="ready_without_judge")
        if capability == "identity_relay.finalize_turn":
            return {
                "schema_version": 2,
                "projection_kind": "normalized_projection",
                "status": "ready",
                "artifact_ref": ACTIVE["artifact_ref"],
                "artifact_hash": ACTIVE["artifact_hash"],
                "snapshot_hash": "invalid",
                "prompt_text": "must not be injected",
            }
        raise AssertionError(f"unexpected capability {capability}")

    try:
        _clear_relay_runtime()
        engine._chat_runtime = runtime
        engine._invoke_targeted_addon_capability = invoke
        assert engine.queue_typed_chat_message("malformed projection")['queued'] is True
        pending = engine._consume_pending_loaded_input_turn()
        request = engine._freeze_normal_chat_request(
            pending,
            require_existing_transaction=True,
        )
        try:
            engine._ensure_normal_chat_transaction_ready(request)
        except engine.NormalChatTurnBlocked as exc:
            assert "invalid v2 snapshot metadata" in str(exc)
        else:
            raise AssertionError("malformed v2 projection did not block the turn")

        assert [item[0] for item in calls] == [
            "identity_relay.capture_turn",
            "identity_relay.prepare_turn",
            "identity_relay.finalize_turn",
        ]
        assert all(item[2] == "nc-identity-relay-turn" for item in calls[1:])
        assert runtime.reply_calls == []
        assert engine.conversation_history == []
        assert engine.identity_relay_snapshot_registry == {}
    finally:
        engine._chat_runtime = original_runtime
        engine._invoke_targeted_addon_capability = original_invoke
        engine.reset_session_state()


def test_export_freezes_history_and_registry_without_orphan_split() -> None:
    _clear_relay_runtime()
    initial_snapshot = {
        "schema_version": 2,
        "projection_kind": "normalized_projection",
        "status": "ready",
        "artifact_ref": ACTIVE["artifact_ref"],
        "artifact_hash": ACTIVE["artifact_hash"],
        "prompt_text": "Initial v2 continuity",
        "persistence_mode": "persistent",
    }
    concurrent_snapshot = {
        "schema_version": 2,
        "projection_kind": "normalized_projection",
        "status": "ready",
        "artifact_ref": "library/" + "b" * 64 + ".json",
        "artifact_hash": "b" * 64,
        "prompt_text": "Concurrent v2 continuity",
        "persistence_mode": "persistent",
    }
    initial_snapshot = engine._identity_relay_v2_snapshot_payload(initial_snapshot)
    concurrent_snapshot = engine._identity_relay_v2_snapshot_payload(concurrent_snapshot)
    assert initial_snapshot is not None
    assert concurrent_snapshot is not None
    initial_snapshot["snapshot_hash"] = engine._identity_relay_v2_snapshot_hash(
        initial_snapshot
    )
    concurrent_snapshot["snapshot_hash"] = engine._identity_relay_v2_snapshot_hash(
        concurrent_snapshot
    )
    initial_metadata = engine._identity_relay_v2_metadata(initial_snapshot)
    concurrent_metadata = engine._identity_relay_v2_metadata(concurrent_snapshot)
    assert initial_metadata is not None
    assert concurrent_metadata is not None
    with engine.identity_relay_snapshot_lock:
        engine.identity_relay_snapshot_registry[initial_metadata["snapshot_hash"]] = initial_snapshot
    engine.replace_chat_conversation_history(
        [{"role": "user", "content": "already accepted", "origin": "input", "identity_relay": initial_metadata}]
    )

    class FrozenContext:
        provider_name = "atomic-provider"
        model_name = "atomic-model"
        provider_config = {"provider_is_remote": False}
        generation_fields = {"max_tokens": 32}
        capabilities = types.SimpleNamespace(context_limit=256)

        def to_summary(self):
            return {"provider_name": self.provider_name, "model_name": self.model_name}

    class FrozenRequest:
        def __init__(self, context, params):
            self.context = context
            self._params = copy.deepcopy(params)
            self._params.setdefault("max_tokens", 32)

        def params_copy(self):
            return copy.deepcopy(self._params)

        def additional_params_copy(self):
            return {}

    class FrozenRuntime:
        def __init__(self):
            self.context = FrozenContext()

        def capture_frozen_context(self):
            return self.context

        def upgrade_frozen_context_for_relay(self, context):
            assert context is self.context
            return context

        def strict_relay_capability_available(self, context):
            return context is self.context

        def frozen_execution_available(self, context, *, stream=False):
            return context is self.context

        def prepare_frozen_request(self, context, params, additional_params=None):
            assert context is self.context
            return FrozenRequest(context, params)

        def complete_frozen(self, request, **_kwargs):
            raise AssertionError(f"unexpected provider dispatch {request!r}")

        def stream_frozen(self, request, **_kwargs):
            raise AssertionError(f"unexpected provider dispatch {request!r}")

    original_registry_export = engine._export_identity_relay_snapshot_registry
    original_invoke = engine._invoke_targeted_addon_capability
    original_runtime = engine._chat_runtime
    original_token_count = engine.chat_providers.count_frozen_chat_tokens
    registry_copied = threading.Event()
    continue_export = threading.Event()
    freeze_attempted = threading.Event()
    exported_payloads = []
    thread_errors = []

    def blocked_registry_export():
        snapshot = original_registry_export()
        registry_copied.set()
        if not continue_export.wait(timeout=10.0):
            raise AssertionError("timed out waiting to continue chat export")
        return snapshot

    def invoke(_addon_id, capability, payload=None):
        if capability == "identity_relay.chat_session.export":
            return {}
        if capability == "identity_relay.capture_turn":
            assert dict(payload or {}).get("schema_version") == 2
            return types.SimpleNamespace(
                enabled=True,
                artifact_ref=concurrent_snapshot["artifact_ref"],
                artifact_hash=concurrent_snapshot["artifact_hash"],
            )
        if capability == "identity_relay.prepare_turn":
            return types.SimpleNamespace(status="ready_without_judge")
        if capability == "identity_relay.finalize_turn":
            return types.SimpleNamespace(**concurrent_snapshot)
        raise AssertionError(f"unexpected capability {capability}")

    def export_worker():
        try:
            exported_payloads.append(engine.export_chat_session_state())
        except Exception as exc:
            thread_errors.append(exc)

    def accept_worker():
        try:
            assert engine.queue_typed_chat_message("accepted during export")["queued"] is True
            pending = engine._consume_pending_loaded_input_turn()
            freeze_attempted.set()
            request = engine._freeze_normal_chat_request(
                pending,
                require_existing_transaction=True,
            )
            engine._ensure_normal_chat_transaction_ready(request)
        except Exception as exc:
            thread_errors.append(exc)

    engine._chat_runtime = FrozenRuntime()
    engine._invoke_targeted_addon_capability = invoke
    engine.chat_providers.count_frozen_chat_tokens = lambda context, messages: 10
    engine._export_identity_relay_snapshot_registry = blocked_registry_export
    export_thread = threading.Thread(target=export_worker, daemon=True)
    accept_thread = threading.Thread(target=accept_worker, daemon=True)
    export_started = False
    accept_started = False
    try:
        export_thread.start()
        export_started = True
        assert registry_copied.wait(timeout=5.0), thread_errors
        history_lock_available = engine.conversation_history_lock.acquire(blocking=False)
        if history_lock_available:
            engine.conversation_history_lock.release()
        assert not history_lock_available, "export released history before freezing the Relay registry"
        accept_thread.start()
        accept_started = True
        assert freeze_attempted.wait(timeout=5.0), thread_errors
        with engine.identity_relay_snapshot_lock:
            assert concurrent_metadata["snapshot_hash"] not in engine.identity_relay_snapshot_registry
        assert all(
            turn.get("content") != "accepted during export"
            for turn in engine.conversation_history
        )
    finally:
        continue_export.set()
        if export_started:
            export_thread.join(timeout=5.0)
        if accept_started:
            accept_thread.join(timeout=5.0)
        engine._export_identity_relay_snapshot_registry = original_registry_export
        engine._invoke_targeted_addon_capability = original_invoke
        engine._chat_runtime = original_runtime
        engine.chat_providers.count_frozen_chat_tokens = original_token_count

    assert not export_thread.is_alive()
    assert not accept_thread.is_alive()
    assert thread_errors == []
    assert len(exported_payloads) == 1
    exported = exported_payloads[0]
    active_snapshot_hashes = {
        turn["identity_relay"]["snapshot_hash"]
        for turn in exported["conversation_history"]
        if (turn.get("identity_relay") or {}).get("status") == "ready"
    }
    assert active_snapshot_hashes == {initial_metadata["snapshot_hash"]}
    assert set(exported["identity_relay_snapshots"]) == active_snapshot_hashes
    for snapshot_hash in active_snapshot_hashes:
        assert snapshot_hash in exported["identity_relay_snapshots"]
    committed = [
        turn
        for turn in engine.conversation_history
        if turn.get("content") == "accepted during export"
    ]
    assert len(committed) == 1
    assert committed[0]["identity_relay"] == concurrent_metadata
    assert concurrent_metadata["snapshot_hash"] in engine.identity_relay_snapshot_registry
    engine.reset_session_state()


def test_missing_or_mismatched_snapshot_fails_closed() -> None:
    original = _install_capture_result(ACTIVE)
    try:
        _clear_relay_runtime()
        turn = engine._finalize_identity_relay_for_user_turn({"role": "user", "content": "one"})
        metadata = turn["identity_relay"]
        with engine.identity_relay_snapshot_lock:
            engine.identity_relay_snapshot_registry.clear()
        expanded = engine._expand_identity_relay_for_request(turn)
        assert expanded["state"] == "unavailable"
        assert expanded.get("hot_identity_text", "") == ""
        assert "artifact_hash" not in expanded

        bad_registry = {
            metadata["snapshot_hash"]: {
                "artifact_ref": ACTIVE["artifact_ref"],
                "artifact_hash": "b" * 64,
                "hot_identity_text": ACTIVE["hot_identity_text"],
            }
        }
        assert engine._sanitize_identity_relay_snapshot_registry(bad_registry) == {}
    finally:
        engine._invoke_targeted_addon_capability = original


def test_loaded_chat_blocks_projection_purge_and_unrelated_snapshots_survive() -> None:
    assert hasattr(engine, "_identity_relay_loaded_reference_reasons")
    assert hasattr(engine, "_purge_identity_relay_runtime_derivatives")
    _clear_relay_runtime()
    target = {
        "schema_version": 2,
        "projection_kind": "normalized_projection",
        "status": "ready",
        "artifact_ref": ACTIVE["artifact_ref"],
        "artifact_hash": ACTIVE["artifact_hash"],
        "snapshot_hash": "e" * 64,
        "prompt_text": "Target persisted projection",
        "persistence_mode": "persistent",
    }
    unrelated = {
        "schema_version": 2,
        "projection_kind": "normalized_projection",
        "status": "ready",
        "artifact_ref": "library/" + "b" * 64 + ".json",
        "artifact_hash": "b" * 64,
        "snapshot_hash": "f" * 64,
        "prompt_text": "Unrelated persisted projection",
        "persistence_mode": "persistent",
    }
    metadata = engine._identity_relay_v2_metadata(target)
    with engine.identity_relay_snapshot_lock:
        engine.identity_relay_snapshot_registry.update(
            {
                target["snapshot_hash"]: target,
                unrelated["snapshot_hash"]: unrelated,
            }
        )
    engine.replace_chat_conversation_history(
        [
            {
                "role": "user",
                "content": "loaded target turn",
                "origin": "input",
                "identity_relay": metadata,
            }
        ]
    )

    assert engine._identity_relay_loaded_reference_reasons(
        target["artifact_ref"]
    ) == ("loaded_chat:conversation_history",)
    blocked = engine._purge_identity_relay_runtime_derivatives(
        target["artifact_ref"]
    )
    assert blocked["purged"] is False
    assert blocked["blocked_by"] == ("loaded_chat:conversation_history",)

    engine.replace_chat_conversation_history([])
    purged = engine._purge_identity_relay_runtime_derivatives(
        target["artifact_ref"]
    )
    assert purged == {
        "purged": True,
        "blocked_by": (),
        "removed_snapshot_count": 1,
    }
    with engine.identity_relay_snapshot_lock:
        assert target["snapshot_hash"] not in engine.identity_relay_snapshot_registry
        assert unrelated["snapshot_hash"] in engine.identity_relay_snapshot_registry


def test_phase2_queued_turn_anchors_stream_and_request_relay() -> None:
    class NoopSensoryThread:
        def __init__(self, *_args, **kwargs):
            assert kwargs.get("name") == "nc-sensory-loop"

        def start(self):
            return None

    class FrozenContext:
        def __init__(self, name):
            self.provider_name = name
            self.model_name = f"{name}-model"
            self.provider_config = {"provider_is_remote": False}
            self.generation_fields = {"max_tokens": 32}

        def to_summary(self):
            return {
                "provider_name": self.provider_name,
                "model_name": self.model_name,
                "strict_relay_available": False,
            }

    class FrozenRequest:
        def __init__(self, context, params, additional):
            self.context = context
            self._params = copy.deepcopy(params)
            self._additional = copy.deepcopy(additional)

        def params_copy(self):
            return copy.deepcopy(self._params)

        def additional_params_copy(self):
            return copy.deepcopy(self._additional)

    class FrozenRuntime:
        def __init__(self):
            self.accepted_context = FrozenContext("queued-original")
            self.live_context = self.accepted_context
            self.capture_calls = []
            self.prepared = []
            self.completed = []

        def capture_frozen_context(self):
            self.capture_calls.append(self.live_context)
            return self.live_context

        def frozen_execution_available(self, context, *, stream=False):
            del stream
            return context is self.accepted_context

        def prepare_frozen_request(self, context, params, additional_params=None):
            prepared_params = dict(params or {})
            prepared_params["model"] = context.model_name
            prepared_params.setdefault("max_tokens", context.generation_fields["max_tokens"])
            request = FrozenRequest(context, prepared_params, additional_params or {})
            self.prepared.append(request)
            return request

        def complete_frozen(self, request, *, timeout=None, cancel_token=None):
            del timeout
            assert cancel_token is not None
            self.completed.append(request)
            engine.stop_flag.set()
            return "queued frozen reply"

    class FakeTTSController:
        def __init__(self):
            self.done = threading.Event()
            self.done.set()

        def get_spoken_text(self):
            return "queued frozen reply"

    original_history = copy.deepcopy(engine.conversation_history)
    original_pending_turn = copy.deepcopy(engine.pending_loaded_input_turn)
    original_thread = engine.threading.Thread
    original_runtime = engine._chat_runtime
    original_invoke = engine._invoke_targeted_addon_capability
    original_speak = engine.speak_async
    original_addon_command = engine._maybe_handle_addon_user_text_command
    original_begin_reply = engine.dry_run.begin_reply
    original_finalize_reply = engine.dry_run.finalize_reply
    original_auto_replies_enabled = engine.dry_run.auto_replies_enabled
    original_presence_state = engine._presence_set_state
    original_presence_audio = engine._presence_set_audio_level
    original_stream_mode = engine.RUNTIME_CONFIG.get("stream_mode")
    original_input_role = engine.RUNTIME_CONFIG.get("input_message_role")
    original_offline_replay = engine.RUNTIME_CONFIG.get("offline_replay_only")
    stop_was_set = engine.stop_flag.is_set()
    with engine.identity_relay_snapshot_lock:
        original_registry = copy.deepcopy(engine.identity_relay_snapshot_registry)

    runtime = FrozenRuntime()
    relay_calls = []

    def invoke(_addon_id, capability, payload=None):
        if capability == "identity_relay.capture_turn":
            relay_calls.append(capability)
            assert dict(payload or {}).get("schema_version") == 2
            return types.SimpleNamespace(
                enabled=False,
                artifact_ref=ACTIVE["artifact_ref"],
                artifact_hash=ACTIVE["artifact_hash"],
            )
        return None

    engine.threading.Thread = lambda *args, **kwargs: (
        NoopSensoryThread(*args, **kwargs)
        if kwargs.get("name") == "nc-sensory-loop"
        else original_thread(*args, **kwargs)
    )
    engine._chat_runtime = runtime
    engine._invoke_targeted_addon_capability = invoke
    engine.speak_async = lambda *_args, **_kwargs: FakeTTSController()
    engine._maybe_handle_addon_user_text_command = lambda *_args, **_kwargs: None
    engine.dry_run.begin_reply = lambda *_args, **_kwargs: "queued-reply"
    engine.dry_run.finalize_reply = lambda *_args, **_kwargs: None
    engine.dry_run.auto_replies_enabled = lambda: False
    engine._presence_set_state = lambda *_args, **_kwargs: None
    engine._presence_set_audio_level = lambda *_args, **_kwargs: None
    engine.RUNTIME_CONFIG["input_message_role"] = "user"
    engine.RUNTIME_CONFIG["stream_mode"] = False
    engine.RUNTIME_CONFIG["offline_replay_only"] = False

    try:
        engine.replace_chat_conversation_history([])
        engine.pending_loaded_input_turn = None
        engine.stop_flag.clear()
        assert engine.queue_typed_chat_message("queued typed turn")["queued"] is True
        assert engine.conversation_history == []
        runtime.live_context = FrozenContext("live-changed")

        engine.run_conversation_flow(None)

        assert runtime.capture_calls == [runtime.accepted_context]
        assert len(runtime.prepared) == len(runtime.completed) == 1
        assert runtime.completed[0] is runtime.prepared[0]
        assert runtime.completed[0].context is runtime.accepted_context
        assert relay_calls == ["identity_relay.capture_turn"]
        assert [turn["role"] for turn in engine.conversation_history] == ["user", "assistant"]
        assert engine.conversation_history[0]["content"] == "queued typed turn"
        assert engine.conversation_history[0]["identity_relay"]["status"] == "suspended"
        assert (
            engine.conversation_history[1]["identity_relay"]
            == engine.conversation_history[0]["identity_relay"]
        )
        serialized = json.dumps(runtime.completed[0].params_copy()["messages"])
        assert serialized.count("queued typed turn") == 1
    finally:
        engine.threading.Thread = original_thread
        engine._chat_runtime = original_runtime
        engine._invoke_targeted_addon_capability = original_invoke
        engine.speak_async = original_speak
        engine._maybe_handle_addon_user_text_command = original_addon_command
        engine.dry_run.begin_reply = original_begin_reply
        engine.dry_run.finalize_reply = original_finalize_reply
        engine.dry_run.auto_replies_enabled = original_auto_replies_enabled
        engine._presence_set_state = original_presence_state
        engine._presence_set_audio_level = original_presence_audio
        engine.RUNTIME_CONFIG["stream_mode"] = original_stream_mode
        engine.RUNTIME_CONFIG["input_message_role"] = original_input_role
        engine.RUNTIME_CONFIG["offline_replay_only"] = original_offline_replay
        engine.replace_chat_conversation_history(original_history)
        engine.pending_loaded_input_turn = original_pending_turn
        with engine.identity_relay_snapshot_lock:
            engine.identity_relay_snapshot_registry.clear()
            engine.identity_relay_snapshot_registry.update(original_registry)
        if stop_was_set:
            engine.stop_flag.set()
        else:
            engine.stop_flag.clear()


def test_phase2_final_stt_freezes_before_addon_command_once() -> None:
    class NoopSensoryThread:
        def __init__(self, *_args, **kwargs):
            assert kwargs.get("name") == "nc-sensory-loop"

        def start(self):
            return None

    class FrozenContext:
        provider_name = "stt-provider"
        model_name = "stt-model"
        provider_config = {"provider_is_remote": False}
        generation_fields = {"max_tokens": 32}

        def to_summary(self):
            return {
                "provider_name": self.provider_name,
                "model_name": self.model_name,
                "strict_relay_available": False,
            }

    class FrozenRequest:
        def __init__(self, context, params, additional):
            self.context = context
            self._params = copy.deepcopy(params)
            self._additional = copy.deepcopy(additional)

        def params_copy(self):
            return copy.deepcopy(self._params)

        def additional_params_copy(self):
            return copy.deepcopy(self._additional)

    class FrozenRuntime:
        def __init__(self):
            self.context = FrozenContext()
            self.prepared = []
            self.completed = []

        def capture_frozen_context(self):
            return self.context

        def frozen_execution_available(self, context, *, stream=False):
            del stream
            return context is self.context

        def prepare_frozen_request(self, context, params, additional_params=None):
            prepared_params = dict(params or {})
            prepared_params["model"] = context.model_name
            prepared_params.setdefault("max_tokens", context.generation_fields["max_tokens"])
            request = FrozenRequest(context, prepared_params, additional_params or {})
            self.prepared.append(request)
            return request

        def complete_frozen(self, request, *, timeout=None, cancel_token=None):
            del timeout
            assert cancel_token is not None
            self.completed.append(request)
            order.append("provider")
            engine.stop_flag.set()
            return "actual frozen STT reply"

    class FakeTTSController:
        def __init__(self):
            self.done = threading.Event()
            self.done.set()

        def get_spoken_text(self):
            return "actual frozen STT reply"

    original_history = copy.deepcopy(engine.conversation_history)
    original_pending_turn = copy.deepcopy(engine.pending_loaded_input_turn)
    original_thread = engine.threading.Thread
    original_check_status = engine.check_interaction_status
    original_listen = engine.listen_for_speech_push_to_talk
    original_runtime = engine._chat_runtime
    original_invoke = engine._invoke_targeted_addon_capability
    original_addon_command = engine._maybe_handle_addon_user_text_command
    original_begin_reply = engine.dry_run.begin_reply
    original_auto_replies_enabled = engine.dry_run.auto_replies_enabled
    original_speak = engine.speak_async
    original_finalize_reply = engine.dry_run.finalize_reply
    original_presence_state = engine._presence_set_state
    original_presence_audio = engine._presence_set_audio_level
    original_stream_mode = engine.RUNTIME_CONFIG.get("stream_mode")
    original_input_role = engine.RUNTIME_CONFIG.get("input_message_role")
    original_offline_replay = engine.RUNTIME_CONFIG.get("offline_replay_only")
    stop_was_set = engine.stop_flag.is_set()
    order = []
    runtime = FrozenRuntime()

    def invoke(addon_id, capability, payload=None):
        if capability == "identity_relay.capture_turn":
            order.append("capture")
            assert dict(payload or {}).get("schema_version") == 2
            return types.SimpleNamespace(
                enabled=False,
                artifact_ref=ACTIVE["artifact_ref"],
                artifact_hash=ACTIVE["artifact_hash"],
            )
        if capability == "identity_relay.chat_session.reset":
            return None
        return None

    def addon_command(*_args, **_kwargs):
        order.append("addon_command")
        return None

    def begin_reply(*_args, **_kwargs):
        order.append("dry_run")
        return None

    engine.replace_chat_conversation_history([])
    engine.pending_loaded_input_turn = None
    engine.threading.Thread = lambda *args, **kwargs: (
        NoopSensoryThread(*args, **kwargs)
        if kwargs.get("name") == "nc-sensory-loop"
        else original_thread(*args, **kwargs)
    )
    engine.check_interaction_status = lambda _source: "push_to_talk"
    engine.listen_for_speech_push_to_talk = lambda _source: "final microphone transcript"
    engine._chat_runtime = runtime
    engine._invoke_targeted_addon_capability = invoke
    engine._maybe_handle_addon_user_text_command = addon_command
    engine.dry_run.begin_reply = begin_reply
    engine.dry_run.finalize_reply = lambda *_args, **_kwargs: None
    engine.dry_run.auto_replies_enabled = lambda: False
    engine.speak_async = lambda *_args, **_kwargs: FakeTTSController()
    engine._presence_set_state = lambda *_args, **_kwargs: None
    engine._presence_set_audio_level = lambda *_args, **_kwargs: None
    engine.RUNTIME_CONFIG["stream_mode"] = False
    engine.RUNTIME_CONFIG["input_message_role"] = "user"
    engine.RUNTIME_CONFIG["offline_replay_only"] = False
    engine.stop_flag.clear()

    try:
        engine.run_conversation_flow(object())

        assert order == ["capture", "addon_command", "dry_run", "provider"], order
        assert sum(item == "capture" for item in order) == 1
        assert runtime.completed == runtime.prepared
        assert len(runtime.completed) == 1
        assert runtime.completed[0].context is runtime.context
        assert [item["role"] for item in engine.conversation_history] == ["user", "assistant"]
        accepted = engine.conversation_history[0]
        assert accepted["content"] == "final microphone transcript"
        assert accepted["identity_relay"]["schema_version"] == 2
        assert accepted["identity_relay"]["status"] == "suspended"
        serialized = json.dumps(runtime.completed[0].params_copy()["messages"])
        assert serialized.count("final microphone transcript") == 1
    finally:
        engine.threading.Thread = original_thread
        engine.check_interaction_status = original_check_status
        engine.listen_for_speech_push_to_talk = original_listen
        engine._chat_runtime = original_runtime
        engine._invoke_targeted_addon_capability = original_invoke
        engine._maybe_handle_addon_user_text_command = original_addon_command
        engine.dry_run.begin_reply = original_begin_reply
        engine.dry_run.finalize_reply = original_finalize_reply
        engine.dry_run.auto_replies_enabled = original_auto_replies_enabled
        engine.speak_async = original_speak
        engine._presence_set_state = original_presence_state
        engine._presence_set_audio_level = original_presence_audio
        engine.RUNTIME_CONFIG["stream_mode"] = original_stream_mode
        engine.RUNTIME_CONFIG["input_message_role"] = original_input_role
        engine.RUNTIME_CONFIG["offline_replay_only"] = original_offline_replay
        engine.replace_chat_conversation_history(original_history)
        engine.pending_loaded_input_turn = original_pending_turn
        if stop_was_set:
            engine.stop_flag.set()
        else:
            engine.stop_flag.clear()


def test_loaded_active_regeneration_without_persisted_snapshot_blocks() -> None:
    class NoopSensoryThread:
        def __init__(self, *_args, **kwargs):
            assert kwargs.get("name") == "nc-sensory-loop"

        def start(self):
            return None

    original_history = copy.deepcopy(engine.conversation_history)
    original_pending_turn = copy.deepcopy(engine.pending_loaded_input_turn)
    original_thread = engine.threading.Thread
    original_check_status = engine.check_interaction_status
    original_addon_command = engine._maybe_handle_addon_user_text_command
    original_begin_reply = engine.dry_run.begin_reply
    original_finalize_reply = engine.dry_run.finalize_reply
    original_auto_replies_enabled = engine.dry_run.auto_replies_enabled
    original_request = engine.chat_with_llm
    original_presence_state = engine._presence_set_state
    original_presence_audio = engine._presence_set_audio_level
    original_stream_mode = engine.RUNTIME_CONFIG.get("stream_mode")
    original_input_role = engine.RUNTIME_CONFIG.get("input_message_role")
    original_offline_replay = engine.RUNTIME_CONFIG.get("offline_replay_only")
    stop_was_set = engine.stop_flag.is_set()
    with engine.identity_relay_snapshot_lock:
        original_registry = copy.deepcopy(engine.identity_relay_snapshot_registry)

    metadata, _registry_entry = engine._freeze_identity_relay_snapshot(ACTIVE)
    provider_calls = []
    finalized_replies = []

    def request(request_context=None):
        provider_calls.append(copy.deepcopy(request_context))
        return ""

    def presence_state(state, *_args, **_kwargs):
        if state == "idle":
            engine.stop_flag.set()

    engine.replace_chat_conversation_history(
        [
            {"role": "user", "content": "historical active turn", "identity_relay": metadata},
            {"role": "assistant", "content": "old reply", "identity_relay": metadata},
        ]
    )
    engine.pending_loaded_input_turn = None
    with engine.identity_relay_snapshot_lock:
        engine.identity_relay_snapshot_registry.clear()
    saved = engine.export_chat_session_state()
    assert saved["conversation_history"][0]["identity_relay"] == metadata
    assert saved["identity_relay_snapshots"] == {}
    engine.import_chat_session_state(saved)
    assert engine.conversation_history[0]["identity_relay"] == metadata
    engine.threading.Thread = NoopSensoryThread
    engine.check_interaction_status = lambda _source: "regenerate_response"
    engine._maybe_handle_addon_user_text_command = lambda *_args, **_kwargs: None
    engine.dry_run.begin_reply = lambda *_args, **_kwargs: "regen-reply"
    engine.dry_run.finalize_reply = lambda reply_id: finalized_replies.append(reply_id)
    engine.dry_run.auto_replies_enabled = lambda: False
    engine.chat_with_llm = request
    engine._presence_set_state = presence_state
    engine._presence_set_audio_level = lambda *_args, **_kwargs: None
    engine.RUNTIME_CONFIG["stream_mode"] = False
    engine.RUNTIME_CONFIG["input_message_role"] = "user"
    engine.RUNTIME_CONFIG["offline_replay_only"] = False
    engine.stop_flag.clear()
    output = io.StringIO()

    try:
        with redirect_stdout(output):
            engine.run_conversation_flow(None)

        assert provider_calls == []
        assert [turn["role"] for turn in engine.conversation_history] == ["user"]
        assert engine.conversation_history[0]["identity_relay"] == metadata
        assert finalized_replies == ["regen-reply"]
        assert "identity relay/normal chat" in output.getvalue().lower()
        assert "prior relay on turn" in output.getvalue().lower()
        assert "persisted relay projection" in output.getvalue().lower()
    finally:
        engine.threading.Thread = original_thread
        engine.check_interaction_status = original_check_status
        engine._maybe_handle_addon_user_text_command = original_addon_command
        engine.dry_run.begin_reply = original_begin_reply
        engine.dry_run.finalize_reply = original_finalize_reply
        engine.dry_run.auto_replies_enabled = original_auto_replies_enabled
        engine.chat_with_llm = original_request
        engine._presence_set_state = original_presence_state
        engine._presence_set_audio_level = original_presence_audio
        engine.RUNTIME_CONFIG["stream_mode"] = original_stream_mode
        engine.RUNTIME_CONFIG["input_message_role"] = original_input_role
        engine.RUNTIME_CONFIG["offline_replay_only"] = original_offline_replay
        engine.replace_chat_conversation_history(original_history)
        engine.pending_loaded_input_turn = original_pending_turn
        with engine.identity_relay_snapshot_lock:
            engine.identity_relay_snapshot_registry.clear()
            engine.identity_relay_snapshot_registry.update(original_registry)
        if stop_was_set:
            engine.stop_flag.set()
        else:
            engine.stop_flag.clear()


def test_regeneration_suspended_snapshot_remains_available() -> None:
    suspended = {**ACTIVE, "state": "suspended", "hot_identity_text": ""}
    metadata, _registry_entry = engine._freeze_identity_relay_snapshot(suspended)
    accepted_turn = {
        "role": "user",
        "content": "historical suspended turn",
        "identity_relay": metadata,
    }
    request = {"identity_relay_metadata": metadata}

    assert engine._identity_relay_regeneration_failure_code(accepted_turn, request) == ""


def test_regeneration_legacy_off_and_suspended_history_stays_relay_free() -> None:
    class FrozenContext:
        provider_name = "regeneration-provider"
        model_name = "regeneration-model"
        provider_config = {"provider_is_remote": False}
        generation_fields = {"max_tokens": 32}

        def to_summary(self):
            return {
                "provider_name": self.provider_name,
                "model_name": self.model_name,
                "strict_relay_available": False,
            }

    class FrozenRuntime:
        def __init__(self):
            self.captures = []

        def capture_frozen_context(self):
            context = FrozenContext()
            self.captures.append(context)
            return context

    legacy_suspended, _entry = engine._freeze_identity_relay_snapshot(
        {**ACTIVE, "state": "suspended", "hot_identity_text": ""}
    )
    v2_suspended = {
        "schema_version": 2,
        "projection_kind": "normalized_projection",
        "status": "suspended",
        "artifact_ref": ACTIVE["artifact_ref"],
        "artifact_hash": ACTIVE["artifact_hash"],
    }
    historical_turns = (
        {"role": "user", "content": "legacy ordinary history"},
        {
            "role": "user",
            "content": "legacy relay off history",
            "identity_relay": legacy_suspended,
        },
        {
            "role": "user",
            "content": "v2 relay suspended history",
            "identity_relay": v2_suspended,
        },
    )
    runtime = FrozenRuntime()
    relay_capture_calls = []
    original_runtime = engine._chat_runtime
    original_invoke = engine._invoke_targeted_addon_capability
    original_getter = engine._addon_manager_getter

    def currently_enabled_relay(_addon_id, capability, _payload=None):
        relay_capture_calls.append(capability)
        if capability == "identity_relay.capture_turn":
            return types.SimpleNamespace(
                enabled=True,
                artifact_ref=ACTIVE["artifact_ref"],
                artifact_hash=ACTIVE["artifact_hash"],
            )
        return None

    try:
        engine._chat_runtime = runtime
        engine._addon_manager_getter = None
        engine._invoke_targeted_addon_capability = currently_enabled_relay
        for turn in historical_turns:
            engine.reset_chat_runtime_state()
            relay_capture_calls.clear()
            engine.replace_chat_conversation_history([turn])
            request = engine._freeze_normal_chat_request(
                turn,
                require_existing_transaction=True,
            )
            transaction = engine._normal_chat_transaction_for_request(request)

            assert transaction is not None
            assert transaction["provider_context"] is runtime.captures[-1]
            assert transaction["relay_capture"] is None
            assert transaction["restored_relay_snapshot"] is None
            assert request["identity_relay_snapshot"] is None
            assert request["identity_relay_metadata"] is None
            assert relay_capture_calls == []
    finally:
        engine._chat_runtime = original_runtime
        engine._invoke_targeted_addon_capability = original_invoke
        engine._addon_manager_getter = original_getter
        engine.reset_chat_runtime_state()


def test_regeneration_prior_on_requires_and_reuses_exact_persisted_snapshot() -> None:
    class FrozenContext:
        provider_name = "restored-provider"
        model_name = "restored-model"
        provider_config = {"provider_is_remote": False}
        generation_fields = {"max_tokens": 32}

        def to_summary(self):
            return {
                "provider_name": self.provider_name,
                "model_name": self.model_name,
                "strict_relay_available": True,
            }

    class FrozenRuntime:
        def capture_frozen_context(self):
            return FrozenContext()

    snapshot = engine._identity_relay_v2_snapshot_payload(
        {
            "schema_version": 2,
            "projection_kind": "normalized_projection",
            "status": "ready",
            "artifact_ref": ACTIVE["artifact_ref"],
            "artifact_hash": ACTIVE["artifact_hash"],
            "prompt_text": "Exact persisted continuity",
            "persistence_mode": "persistent",
        }
    )
    snapshot["snapshot_hash"] = engine._identity_relay_v2_snapshot_hash(snapshot)
    metadata = engine._identity_relay_v2_metadata(snapshot)
    turn = {
        "role": "user",
        "content": "historical relay on turn",
        "identity_relay": metadata,
    }
    original_runtime = engine._chat_runtime
    original_invoke = engine._invoke_targeted_addon_capability
    original_getter = engine._addon_manager_getter

    def no_current_relay_recapture(_addon_id, capability, _payload=None):
        if capability == "identity_relay.capture_turn":
            raise AssertionError(
                "restored Relay ON must not recapture current UI state"
            )
        return None

    try:
        engine._chat_runtime = FrozenRuntime()
        engine._addon_manager_getter = None
        engine._invoke_targeted_addon_capability = no_current_relay_recapture
        engine.reset_chat_runtime_state()
        with engine.identity_relay_snapshot_lock:
            engine.identity_relay_snapshot_registry[snapshot["snapshot_hash"]] = snapshot
        engine.replace_chat_conversation_history([turn])

        request = engine._freeze_normal_chat_request(
            turn,
            require_existing_transaction=True,
        )
        transaction = engine._normal_chat_transaction_for_request(request)
        assert transaction["restored_relay_snapshot"] == snapshot
        assert transaction["relay_capture"] is None

        engine.reset_chat_runtime_state()
        engine.replace_chat_conversation_history([turn])
        try:
            engine._freeze_normal_chat_request(
                turn,
                require_existing_transaction=True,
            )
        except engine.NormalChatTurnBlocked as exc:
            assert "persisted Relay projection" in str(exc)
        else:
            raise AssertionError("prior Relay ON without its exact snapshot must block")
    finally:
        engine._chat_runtime = original_runtime
        engine._invoke_targeted_addon_capability = original_invoke
        engine._addon_manager_getter = original_getter
        engine.reset_chat_runtime_state()


def test_corrupt_unavailable_capture_survives_turn_finalization() -> None:
    corrupt = {
        "state": "unavailable",
        "artifact_ref": ACTIVE["artifact_ref"],
        "failure_code": "corrupt",
    }
    original = _install_capture_result(corrupt)
    try:
        _clear_relay_runtime()
        turn = engine._finalize_identity_relay_for_user_turn({"role": "user", "content": "one"})

        assert turn["identity_relay"] == corrupt
    finally:
        engine._invoke_targeted_addon_capability = original


def test_stale_assistant_output_is_rejected_and_metadata_is_inherited() -> None:
    original = _install_capture_result(ACTIVE)
    try:
        _clear_relay_runtime()
        user_turn = engine._finalize_identity_relay_for_user_turn({"role": "user", "content": "one"})
        generation = engine.chat_session_state_generation
        assistant = engine._append_assistant_history_turn(
            "reply",
            identity_relay=user_turn["identity_relay"],
            expected_session_generation=generation,
        )
        assert assistant["identity_relay"] == user_turn["identity_relay"]
        before = list(engine.conversation_history)
        assert engine._append_assistant_history_turn(
            "late",
            identity_relay=user_turn["identity_relay"],
            expected_session_generation=generation + 1,
        ) is None
        assert engine.conversation_history == before
    finally:
        engine._invoke_targeted_addon_capability = original


def test_import_advances_generation_before_replacement_history_is_visible() -> None:
    original_replace = engine.replace_chat_conversation_history
    expected_generation = engine.chat_session_state_generation
    stale_append_results = []

    def replace_and_probe(*args, **kwargs):
        result = original_replace(*args, **kwargs)
        stale_append_results.append(
            engine._append_assistant_history_turn(
                "stale reply",
                expected_session_generation=expected_generation,
            )
        )
        return result

    engine.replace_chat_conversation_history = replace_and_probe
    try:
        engine.import_chat_session_state({"conversation_history": []})
        assert stale_append_results == [None]
        assert engine.conversation_history == []
    finally:
        engine.replace_chat_conversation_history = original_replace


def test_new_chat_reset_clears_relay_state_and_invokes_addon() -> None:
    original = _install_capture_result(ACTIVE)
    calls = []
    try:
        _clear_relay_runtime()
        engine._finalize_identity_relay_for_user_turn({"role": "user", "content": "one"})
        assert engine.identity_relay_snapshot_registry
        engine._invoke_targeted_addon_capability = (
            lambda addon_id, capability, payload=None: calls.append((addon_id, capability, payload))
        )
        engine.reset_session_state()
        assert engine.identity_relay_snapshot_registry == {}
        assert calls == [
            (engine.IDENTITY_RELAY_ADDON_ID, "identity_relay.chat_session.reset", {})
        ]
    finally:
        engine._invoke_targeted_addon_capability = original


def test_new_chat_advances_generation_before_cleared_history_is_visible() -> None:
    original_new_memory_id = engine.continuity_memory.new_memory_id
    expected_generation = engine.chat_session_state_generation
    stale_append_results = []

    def new_memory_id_and_probe():
        stale_append_results.append(
            engine._append_assistant_history_turn(
                "stale reply",
                expected_session_generation=expected_generation,
            )
        )
        return original_new_memory_id()

    engine.continuity_memory.new_memory_id = new_memory_id_and_probe
    try:
        engine.reset_session_state()
        assert stale_append_results == [None]
        assert engine.conversation_history == []
    finally:
        engine.continuity_memory.new_memory_id = original_new_memory_id


def main() -> int:
    test_targeted_capability_uses_exact_addon_route()
    test_targeted_projection_preserves_exact_context_text()
    test_typed_acceptance_captures_before_append()
    test_relay_off_typed_turn_freezes_provider_without_identity_work()
    test_suspended_and_proactive_turns_do_not_store_active_text()
    test_saved_session_keeps_one_snapshot_copy_and_round_trips_metadata()
    test_active_persistence_preserves_history_when_snapshot_is_missing()
    test_stream_request_and_fallback_reuse_frozen_history_and_relay()
    test_relay_snapshot_is_targeted_and_generic_collectors_see_no_relay()
    test_failed_active_projection_blocks_turn_without_assistant_provenance()
    test_malformed_v2_projection_fails_closed_before_provider_dispatch()
    test_export_freezes_history_and_registry_without_orphan_split()
    test_missing_or_mismatched_snapshot_fails_closed()
    test_loaded_chat_blocks_projection_purge_and_unrelated_snapshots_survive()
    test_phase2_queued_turn_anchors_stream_and_request_relay()
    test_phase2_final_stt_freezes_before_addon_command_once()
    test_loaded_active_regeneration_without_persisted_snapshot_blocks()
    test_regeneration_suspended_snapshot_remains_available()
    test_regeneration_legacy_off_and_suspended_history_stays_relay_free()
    test_regeneration_prior_on_requires_and_reuses_exact_persisted_snapshot()
    test_corrupt_unavailable_capture_survives_turn_finalization()
    test_stale_assistant_output_is_rejected_and_metadata_is_inherited()
    test_import_advances_generation_before_replacement_history_is_visible()
    test_new_chat_reset_clears_relay_state_and_invokes_addon()
    test_new_chat_advances_generation_before_cleared_history_is_visible()
    print("smoke_identity_relay_chat: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
