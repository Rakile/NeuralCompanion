from __future__ import annotations

import copy
import gc
import hashlib
import io
import json
import importlib
import queue
import sys
import tempfile
import threading
import types
import weakref
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

addons_module = types.ModuleType("addons")
addons_module.__path__ = [str(ROOT / "addons")]
sys.modules["addons"] = addons_module
importlib.import_module("addons.vam_avatar.config")

engine = importlib.import_module("engine")


ARTIFACT_REF = "library/" + "a" * 64 + ".json"
ARTIFACT_HASH = "a" * 64


class FrozenContext:
    provider_name = "frozen-provider"
    model_name = "frozen-model"
    generation_fields = {"max_tokens": 32}

    def __init__(self, *, provider_is_remote=False, context_limit=512):
        self.provider_config = {
            "base_url": (
                "https://remote.example/v1"
                if provider_is_remote
                else "http://127.0.0.1:1234/v1"
            ),
            "provider_is_remote": provider_is_remote,
        }
        self.capabilities = type(
            "Capabilities", (), {"context_limit": context_limit}
        )()

    def __deepcopy__(self, _memo):
        raise TypeError("frozen provider context must never be deep-copied")

    def to_summary(self):
        return {
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "strict_relay_available": False,
        }


@dataclass(frozen=True)
class Capture:
    enabled: bool
    artifact_ref: str = ARTIFACT_REF
    artifact_hash: str = ARTIFACT_HASH
    connected: bool = True
    connection_revision: int = 1


@dataclass(frozen=True)
class PreparedRelay:
    status: str
    failure_code: str = ""


@dataclass(frozen=True)
class JudgeBatch:
    batch_id: str
    candidate_ids: tuple[str, ...]
    prompt_text: str


@dataclass(frozen=True)
class RelaySnapshot:
    status: str
    prompt_text: str = ""
    snapshot_hash: str = "b" * 64
    failure_code: str = ""
    schema_version: int = 2
    projection_kind: str = "normalized_projection"
    artifact_ref: str = ARTIFACT_REF
    artifact_hash: str = ARTIFACT_HASH
    normalizer_revision: str = "normalizer-v2"
    attestation_revision: int = 3
    transient_state: object = ()
    effective_use_decisions: object = ()
    kernel_record_ids: tuple[str, ...] = ("record:kernel",)
    selected_record_ids: tuple[str, ...] = ()
    selection_reasons: object = ()
    signals_considered: object = ()
    unresolved_record_ids: tuple[str, ...] = ()
    trace: object = ()
    persistence_mode: str = "persistent"
    authorization_record_id: str = "a" * 64


class FrozenRequest:
    def __init__(self, context, messages, output_tokens=32):
        self.context = context
        self._params = {
            "model": context.model_name,
            "messages": copy.deepcopy(messages),
        }
        if output_tokens is not None:
            self._params["max_tokens"] = output_tokens

    def params_copy(self):
        return copy.deepcopy(self._params)

    def additional_params_copy(self):
        return {}


class Runtime:
    def __init__(
        self,
        *,
        strict=True,
        token_count=64,
        execution_available=True,
        judge_error=False,
        judge_started=None,
        judge_release=None,
        reply_text="reply",
        provider_is_remote=False,
        context_limit=512,
        output_tokens=32,
    ):
        self.context = FrozenContext(
            provider_is_remote=provider_is_remote,
            context_limit=context_limit,
        )
        self.strict = strict
        self.token_count = token_count
        self.execution_available = execution_available
        self.judge_error = judge_error
        self.judge_started = judge_started
        self.judge_release = judge_release
        self.reply_text = reply_text
        self.output_tokens = output_tokens
        self.capture_count = 0
        self.prepare_calls = []
        self.prepare_threads = []
        self.complete_calls = []
        self.stream_calls = []
        self.reply_calls = []
        self.upgrade_count = 0
        self.count_calls = []

    def capture_frozen_context(self):
        self.capture_count += 1
        return self.context

    def upgrade_frozen_context_for_relay(self, context):
        assert context is self.context
        self.upgrade_count += 1
        return context

    def strict_relay_capability_available(self, context):
        return self.strict and context is self.context

    def frozen_execution_available(self, context, *, stream=False):
        return self.execution_available and context is self.context

    def prepare_frozen_request(self, context, params, additional_params=None):
        request = FrozenRequest(
            context,
            params.get("messages") or [],
            self.output_tokens,
        )
        self.prepare_calls.append(request)
        self.prepare_threads.append(threading.current_thread().name)
        return request

    def complete_frozen(self, request, *, timeout=None, cancel_token=None):
        self.complete_calls.append(request)
        if any("judge" in str(message.get("content", "")) for message in request.params_copy()["messages"]):
            if self.judge_started is not None:
                self.judge_started.set()
            if self.judge_release is not None:
                assert self.judge_release.wait(timeout=3.0)
            if self.judge_error:
                raise RuntimeError("judge unavailable")
            return json.dumps(
                {
                    "record_ids": ["record:ambiguous"],
                    "reasons": {"record:ambiguous": "relevant"},
                    "signals_considered": {"record:ambiguous": ["topic"]},
                    "unresolved_record_ids": [],
                }
            )
        self.reply_calls.append(request)
        return self.reply_text

    def stream_frozen(self, request, *, timeout=None, cancel_token=None):
        self.stream_calls.append(request)
        return iter(("reply",))

    def count_frozen_chat_tokens(self, context, messages):
        assert context is self.context
        self.count_calls.append(copy.deepcopy(list(messages)))
        return self.token_count


def _install_harness(
    *,
    enabled=True,
    prepared_status="ready_without_judge",
    strict=True,
    token_count=64,
    execution_available=True,
    judge_error=False,
    judge_started=None,
    judge_release=None,
    reply_text="reply",
    finalize_status="ready",
    provider_is_remote=False,
    context_limit=512,
    output_tokens=32,
    restore_authorized=True,
    restore_snapshot_hash="",
):
    runtime = Runtime(
        strict=strict,
        token_count=token_count,
        execution_available=execution_available,
        judge_error=judge_error,
        judge_started=judge_started,
        judge_release=judge_release,
        reply_text=reply_text,
        provider_is_remote=provider_is_remote,
        context_limit=context_limit,
        output_tokens=output_tokens,
    )
    calls = []
    batch = JudgeBatch("judge-batch:0001", ("record:ambiguous",), "judge this identity record")

    def invoke(_addon_id, capability, payload=None):
        payload = dict(payload or {})
        if capability == "identity_relay.capture_mode":
            return Capture(enabled=enabled)
        calls.append((capability, payload, threading.current_thread().name))
        if capability == "identity_relay.capture_turn":
            assert payload["schema_version"] == 2
            assert payload["frozen_provider"]["provider_name"] == runtime.context.provider_name
            assert payload["frozen_provider"]["model_name"] == runtime.context.model_name
            return Capture(enabled=enabled)
        if capability == "identity_relay.prepare_turn":
            return PreparedRelay(prepared_status)
        if capability == "identity_relay.render_judge_request":
            return (batch,)
        if capability == "identity_relay.finalize_turn":
            if finalize_status != "ready":
                return RelaySnapshot(finalize_status, failure_code="finalize_blocked")
            return RelaySnapshot("ready", prompt_text="V2 continuity projection")
        if capability == "identity_relay.restore_persisted_snapshot":
            snapshot = dict(payload.get("snapshot") or {})
            return {
                "authorized": bool(restore_authorized),
                "failure_code": (
                    "persisted_snapshot_authorization_required"
                    if not restore_authorized
                    else ""
                ),
                "snapshot_hash": str(
                    restore_snapshot_hash or snapshot.get("snapshot_hash") or ""
                ),
                "authorization_record_id": str(
                    snapshot.get("authorization_record_id") or ""
                ),
                "provider_is_remote": bool(provider_is_remote),
            }
        raise AssertionError(f"unexpected Relay capability: {capability}")

    originals = (
        engine._chat_runtime,
        engine._invoke_targeted_addon_capability,
        engine.build_llm_request,
        engine.chat_providers.count_frozen_chat_tokens,
    )
    engine._chat_runtime = runtime
    engine._invoke_targeted_addon_capability = invoke

    def build(request_context=None):
        projection = dict((request_context or {}).get("identity_relay_snapshot") or {})
        messages = [{"role": "user", "content": "accepted turn"}]
        if projection.get("prompt_text"):
            messages.insert(0, {"role": "system", "content": projection["prompt_text"]})
        params = {"model": "live-model-must-not-win", "messages": messages}
        if output_tokens is not None:
            params["max_tokens"] = output_tokens
        return params, {}

    engine.build_llm_request = build
    engine.chat_providers.count_frozen_chat_tokens = runtime.count_frozen_chat_tokens
    return runtime, calls, originals


def _restore_harness(originals):
    (
        engine._chat_runtime,
        engine._invoke_targeted_addon_capability,
        engine.build_llm_request,
        engine.chat_providers.count_frozen_chat_tokens,
    ) = originals
    engine.reset_session_state()


def _accepted_request(text="accepted turn"):
    turn = engine._begin_normal_chat_transaction(
        {"role": "user", "content": text, "origin": "input"}
    )
    return turn, engine._freeze_normal_chat_request(turn)


def _valid_relay_snapshot(**changes):
    snapshot = engine._identity_relay_v2_snapshot_payload(
        RelaySnapshot(
            "ready",
            prompt_text="Persisted immutable continuity projection",
            persistence_mode="persistent",
        )
    )
    snapshot.update(changes)
    hash_payload = dict(snapshot)
    hash_payload.pop("snapshot_hash", None)
    hash_payload.pop("authorization_record_id", None)
    snapshot["snapshot_hash"] = hashlib.sha256(
        json.dumps(
            hash_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return snapshot


def _install_pre_dispatch_barrier(*, claim_kind, legacy_stage):
    reached = threading.Event()
    release = threading.Event()
    if hasattr(engine, "_claim_normal_chat_provider_dispatch"):
        original = engine._claim_normal_chat_provider_dispatch

        def delayed_claim(transaction, provider_request, *, kind, final_reply=False):
            if kind == claim_kind:
                reached.set()
                assert release.wait(timeout=3.0)
            return original(
                transaction,
                provider_request,
                kind=kind,
                final_reply=final_reply,
            )

        engine._claim_normal_chat_provider_dispatch = delayed_claim

        def restore():
            engine._claim_normal_chat_provider_dispatch = original

        return reached, release, restore

    original = engine._assert_normal_chat_transaction_current

    def delayed_assert(transaction, stage):
        result = original(transaction, stage)
        if stage == legacy_stage:
            reached.set()
            assert release.wait(timeout=3.0)
        return result

    engine._assert_normal_chat_transaction_current = delayed_assert

    def restore():
        engine._assert_normal_chat_transaction_current = original

    return reached, release, restore


def test_relay_off_captures_once_then_does_zero_service_work() -> None:
    runtime, calls, originals = _install_harness(enabled=False, strict=False)
    try:
        engine.replace_chat_conversation_history([])
        turn, request = _accepted_request("Relay OFF")
        assert engine.conversation_history == []
        engine._ensure_normal_chat_transaction_ready(request)

        assert [item[0] for item in calls] == ["identity_relay.capture_turn"]
        assert len(runtime.prepare_calls) == 1
        assert engine.conversation_history[-1]["content"] == "Relay OFF"
        assert engine.conversation_history[-1]["identity_relay"]["status"] == "suspended"
        assert engine.conversation_history[-1]["normal_chat_transaction_id"]
        assert turn["normal_chat_transaction_id"] == request["normal_chat_transaction_id"]
    finally:
        _restore_harness(originals)


def test_frozen_lmstudio_turn_prepares_selected_model_before_provider_work() -> None:
    runtime, _calls, originals = _install_harness(enabled=False, strict=False)
    original_ensure = engine._ensure_chat_provider_model_ready
    ensure_calls = []
    try:
        runtime.context.provider_name = "lmstudio"
        runtime.context.model_name = "newly-selected-model"
        engine._ensure_chat_provider_model_ready = (
            lambda provider, model: ensure_calls.append((provider, model)) or True
        )
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("prepare selected local model")

        engine._ensure_normal_chat_transaction_ready(request)

        assert ensure_calls == [("lmstudio", "newly-selected-model")]
        assert len(runtime.prepare_calls) == 1
    finally:
        engine._ensure_chat_provider_model_ready = original_ensure
        _restore_harness(originals)


def test_relay_off_capture_copy_failure_is_non_blocking_but_on_fails_closed() -> None:
    from addons.identity_artifacts import relay_state
    from addons.identity_artifacts.relay_state import IdentityRelayModel
    from addons.identity_artifacts.storage import ArtifactResolution

    model = IdentityRelayModel()
    model.set_connection(
        ArtifactResolution(
            ARTIFACT_REF,
            ARTIFACT_HASH,
            "Frozen continuity",
            None,
        )
    )
    model.set_capture_context(
        normalizer_revision="normalizer-v2",
        normalized_digest="c" * 64,
        attestation_revision=3,
        transient_activation={"transient:one": {"active": True}},
        runtime_use={"subject_approved": True},
        frozen_provider={"provider_name": "stale-provider"},
        frozen_normalized_model={"records": [{"record_id": "record:one"}]},
        frozen_model_digest="d" * 64,
    )
    assert model.set_enabled(False) is True
    runtime, _calls, originals = _install_harness(enabled=False, strict=False)
    original_manager_getter = engine._addon_manager_getter
    original_freeze = relay_state._freeze_mapping

    class Manager:
        def invoke_addon_capability_strict(self, _addon_id, capability, payload):
            if capability == "identity_relay.capture_mode":
                return model.capture_mode()
            assert capability == "identity_relay.capture_turn"
            return model.capture_turn(
                frozen_provider=dict(payload or {}).get("frozen_provider"),
                mode_snapshot=dict(payload or {}).get("mode_snapshot"),
            )

    def reject_identity_copy(_value):
        raise RuntimeError("identity authority copy failed")

    try:
        engine.set_addon_manager_getter(lambda: Manager())
        relay_state._freeze_mapping = reject_identity_copy
        engine.replace_chat_conversation_history([])
        off_turn, off_request = _accepted_request("Relay OFF copy isolation")
        engine._ensure_normal_chat_transaction_ready(off_request)
        assert engine.chat_with_llm(off_request) == "reply"
        assert runtime.reply_calls
        assert engine.conversation_history[-1]["content"] == off_turn["content"]
        assert engine.conversation_history[-1]["identity_relay"]["status"] == (
            "suspended"
        )

        assert model.set_enabled(True) is True
        on_turn = engine._begin_normal_chat_transaction(
            {"role": "user", "content": "Relay ON must fail", "origin": "input"}
        )
        on_request = engine._freeze_normal_chat_request(on_turn)
        reply_count = len(runtime.reply_calls)
        try:
            engine._ensure_normal_chat_transaction_ready(on_request)
        except engine.NormalChatTurnBlocked as exc:
            assert "identity authority copy failed" in str(exc)
        else:
            raise AssertionError("Relay ON capture copy failure did not fail closed")
        assert len(runtime.reply_calls) == reply_count
    finally:
        relay_state._freeze_mapping = original_freeze
        engine.set_addon_manager_getter(original_manager_getter)
        _restore_harness(originals)


def test_capture_capability_exception_dispatches_only_for_confirmed_off_mode() -> None:
    runtime, _calls, originals = _install_harness(enabled=False, strict=False)
    original_manager_getter = engine._addon_manager_getter

    class ModeThenFailManager:
        enabled = False
        calls = []

        def invoke_addon_capability_strict(self, _addon_id, capability, payload):
            self.calls.append((capability, dict(payload or {})))
            if capability == "identity_relay.capture_mode":
                return Capture(enabled=self.enabled)
            if capability == "identity_relay.capture_turn":
                state = "enabled" if self.enabled else "disabled"
                raise RuntimeError(f"{state} capture capability failed")
            raise AssertionError(f"unexpected strict capability: {capability}")

    manager = ModeThenFailManager()
    try:
        engine.set_addon_manager_getter(lambda: manager)
        engine.replace_chat_conversation_history([])

        off_turn, off_request = _accepted_request("confirmed OFF capability failure")
        engine._ensure_normal_chat_transaction_ready(off_request)
        assert engine.chat_with_llm(off_request) == "reply"
        assert runtime.reply_calls
        assert engine.conversation_history[-1]["content"] == off_turn["content"]
        assert engine.conversation_history[-1]["identity_relay"]["status"] == (
            "suspended"
        )

        manager.enabled = True
        on_turn = engine._begin_normal_chat_transaction(
            {
                "role": "user",
                "content": "confirmed ON capability failure",
                "origin": "input",
            }
        )
        on_request = engine._freeze_normal_chat_request(on_turn)
        reply_count = len(runtime.reply_calls)
        try:
            engine._ensure_normal_chat_transaction_ready(on_request)
        except engine.NormalChatTurnBlocked as exc:
            assert "enabled capture capability failed" in str(exc)
        else:
            raise AssertionError("confirmed Relay ON capture failure did not block")
        assert len(runtime.reply_calls) == reply_count
        assert [capability for capability, _payload in manager.calls] == [
            "identity_relay.capture_mode",
            "identity_relay.capture_turn",
            "identity_relay.capture_mode",
            "identity_relay.capture_turn",
        ]
    finally:
        engine.set_addon_manager_getter(original_manager_getter)
        _restore_harness(originals)


def test_unconnected_controller_handshake_dispatches_relay_free() -> None:
    from addons.identity_artifacts.controller import IdentityArtifactsController

    runtime, _calls, originals = _install_harness(enabled=False, strict=False)
    original_manager_getter = engine._addon_manager_getter
    controller = IdentityArtifactsController(context=None)

    class Manager:
        calls = []

        def invoke_addon_capability_strict(self, _addon_id, capability, payload):
            self.calls.append(capability)
            if capability == "identity_relay.capture_mode":
                return controller.capture_mode()
            if capability == "identity_relay.capture_turn":
                return controller.capture_turn(payload)
            raise AssertionError(f"unexpected strict capability: {capability}")

    manager = Manager()
    try:
        engine.set_addon_manager_getter(lambda: manager)
        engine.replace_chat_conversation_history([])
        turn, request = _accepted_request("default unconnected Relay")
        transaction = engine._normal_chat_transaction_for_request(request)

        assert transaction["relay_capture"] is None
        assert transaction["relay_capture_error"] == ""
        assert manager.calls == ["identity_relay.capture_mode"]

        engine._ensure_normal_chat_transaction_ready(request)
        assert engine.chat_with_llm(request) == "reply"
        assert len(runtime.reply_calls) == 1
        assert engine.conversation_history[-1]["content"] == turn["content"]
        assert "identity_relay" not in engine.conversation_history[-1]
    finally:
        engine.set_addon_manager_getter(original_manager_getter)
        _restore_harness(originals)
        controller.shutdown()


def test_confirmed_on_requires_matching_enabled_capture() -> None:
    accepted_mode = Capture(enabled=True, connection_revision=7)
    other_hash = "b" * 64
    rejected = (
        ("none", None),
        (
            "disabled",
            Capture(enabled=False, connection_revision=7),
        ),
        ("malformed", types.SimpleNamespace(enabled=True)),
        (
            "invalid-enabled",
            types.SimpleNamespace(
                enabled=1,
                artifact_ref=ARTIFACT_REF,
                artifact_hash=ARTIFACT_HASH,
                connection_revision=7,
            ),
        ),
        (
            "artifact-ref-mismatch",
            Capture(
                enabled=True,
                artifact_ref=f"library/{other_hash}.json",
                artifact_hash=other_hash,
                connection_revision=7,
            ),
        ),
        (
            "artifact-hash-mismatch",
            Capture(
                enabled=True,
                artifact_ref=ARTIFACT_REF,
                artifact_hash=other_hash,
                connection_revision=7,
            ),
        ),
        (
            "connection-revision-mismatch",
            Capture(enabled=True, connection_revision=8),
        ),
    )

    for label, returned_capture in rejected:
        runtime, _calls, originals = _install_harness(enabled=True, strict=True)
        original_manager_getter = engine._addon_manager_getter

        class Manager:
            def invoke_addon_capability_strict(
                self, _addon_id, capability, _payload
            ):
                if capability == "identity_relay.capture_mode":
                    return accepted_mode
                if capability == "identity_relay.capture_turn":
                    return returned_capture
                raise AssertionError(f"unexpected strict capability: {capability}")

        try:
            engine.set_addon_manager_getter(lambda: Manager())
            engine.replace_chat_conversation_history([])
            _turn, request = _accepted_request(f"rejected ON capture: {label}")
            transaction = engine._normal_chat_transaction_for_request(request)
            assert transaction["relay_capture"] is None
            assert transaction["relay_capture_error"] == (
                "Identity Relay returned an invalid active capture."
            )

            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except engine.NormalChatTurnBlocked as exc:
                assert "invalid active capture" in str(exc)
            else:
                raise AssertionError(f"confirmed ON {label} capture dispatched")
            assert engine.conversation_history == []
            assert runtime.prepare_calls == []
            assert runtime.reply_calls == []
        finally:
            engine.set_addon_manager_getter(original_manager_getter)
            _restore_harness(originals)

    runtime, _calls, originals = _install_harness(enabled=True, strict=True)
    original_manager_getter = engine._addon_manager_getter

    class ValidManager:
        def invoke_addon_capability_strict(self, _addon_id, capability, _payload):
            if capability == "identity_relay.capture_mode":
                return accepted_mode
            if capability == "identity_relay.capture_turn":
                return Capture(enabled=True, connection_revision=7)
            raise AssertionError(f"unexpected strict capability: {capability}")

    try:
        engine.set_addon_manager_getter(lambda: ValidManager())
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("matching ON capture")
        engine._ensure_normal_chat_transaction_ready(request)
        assert engine.chat_with_llm(request) == "reply"
        assert len(runtime.reply_calls) == 1
    finally:
        engine.set_addon_manager_getter(original_manager_getter)
        _restore_harness(originals)


def test_invalid_mode_handshakes_block_before_capture_or_dispatch() -> None:
    invalid_modes = (
        ("missing", None),
        (
            "connected-off-without-identity",
            Capture(
                enabled=False,
                artifact_ref="",
                artifact_hash="",
                connection_revision=1,
            ),
        ),
        (
            "unconnected-enabled",
            Capture(enabled=True, connected=False, connection_revision=1),
        ),
        (
            "non-boolean-connected",
            types.SimpleNamespace(
                connected="false",
                enabled=False,
                artifact_ref=ARTIFACT_REF,
                artifact_hash=ARTIFACT_HASH,
                connection_revision=1,
            ),
        ),
        (
            "negative-revision",
            Capture(enabled=True, connection_revision=-1),
        ),
    )

    for label, mode_snapshot in invalid_modes:
        runtime, _calls, originals = _install_harness(enabled=True, strict=True)
        original_manager_getter = engine._addon_manager_getter

        class Manager:
            calls = []

            def invoke_addon_capability_strict(
                self, _addon_id, capability, _payload
            ):
                self.calls.append(capability)
                if capability == "identity_relay.capture_mode":
                    return mode_snapshot
                if capability == "identity_relay.capture_turn":
                    return Capture(enabled=True, connection_revision=1)
                raise AssertionError(f"unexpected strict capability: {capability}")

        manager = Manager()
        try:
            engine.set_addon_manager_getter(lambda: manager)
            engine.replace_chat_conversation_history([])
            _turn, request = _accepted_request(f"invalid mode: {label}")
            transaction = engine._normal_chat_transaction_for_request(request)
            assert transaction["relay_capture"] is None
            assert transaction["relay_capture_error"] == (
                "Identity Relay returned an invalid mode snapshot."
            )
            assert manager.calls == ["identity_relay.capture_mode"]

            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except engine.NormalChatTurnBlocked as exc:
                assert "invalid mode snapshot" in str(exc)
            else:
                raise AssertionError(f"invalid {label} mode dispatched")
            assert engine.conversation_history == []
            assert runtime.prepare_calls == []
            assert runtime.reply_calls == []
        finally:
            engine.set_addon_manager_getter(original_manager_getter)
            _restore_harness(originals)


def test_missing_provider_locality_is_not_coerced_to_local() -> None:
    runtime, calls, originals = _install_harness(enabled=False, strict=False)
    try:
        runtime.context.provider_config = {"base_url": "http://remote-host:11434"}
        engine.replace_chat_conversation_history([])
        _turn, _request = _accepted_request("unknown locality")

        capture_payload = calls[0][1]
        assert capture_payload["frozen_provider"]["provider_is_remote"] is None
        assert "provider_is_remote" not in capture_payload["frozen_provider"]["provider_config"]
    finally:
        _restore_harness(originals)


def test_schema_v2_capture_exception_blocks_before_history_or_provider_prepare() -> None:
    runtime = Runtime(strict=False)
    original_runtime = engine._chat_runtime
    original_manager_getter = engine._addon_manager_getter
    original_build = engine.build_llm_request

    class FailingManager:
        def invoke_addon_capability(self, _addon_id, _capability, _payload):
            raise RuntimeError("capture transport failed")

        def invoke_addon_capability_strict(self, _addon_id, _capability, _payload):
            raise RuntimeError("capture transport failed")

    try:
        engine.reset_session_state()
        engine._chat_runtime = runtime
        engine.set_addon_manager_getter(lambda: FailingManager())
        engine.build_llm_request = lambda _request=None: (
            {"model": "frozen-model", "messages": [{"role": "user", "content": "turn"}]},
            {},
        )
        turn = engine._begin_normal_chat_transaction(
            {"role": "user", "content": "capture must not downgrade", "origin": "input"}
        )
        request = engine._freeze_normal_chat_request(turn)

        try:
            engine._ensure_normal_chat_transaction_ready(request)
        except engine.NormalChatTurnBlocked as exc:
            assert "capture transport failed" in str(exc)
        else:
            raise AssertionError("schema-v2 capture failure silently disabled Relay")
        assert engine.conversation_history == []
        assert runtime.prepare_calls == []
        assert runtime.reply_calls == []
    finally:
        engine._chat_runtime = original_runtime
        engine.set_addon_manager_getter(original_manager_getter)
        engine.build_llm_request = original_build
        engine.reset_session_state()


def test_relay_on_runs_v2_judge_pipeline_on_worker_with_frozen_model() -> None:
    runtime, calls, originals = _install_harness(prepared_status="judge_required")
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request()
        engine._ensure_normal_chat_transaction_ready(request)

        assert [item[0] for item in calls] == [
            "identity_relay.capture_turn",
            "identity_relay.prepare_turn",
            "identity_relay.render_judge_request",
            "identity_relay.finalize_turn",
        ]
        assert all(name == "nc-identity-relay-turn" for _capability, _payload, name in calls[1:])
        judge_capacity = calls[1][1]["judge_capacity"]
        assert judge_capacity["context_limit"] == runtime.context.capabilities.context_limit
        assert callable(judge_capacity["token_counter"])
        assert callable(judge_capacity["output_budget"])
        assert len(runtime.complete_calls) == 1
        assert len(runtime.count_calls) == 2
        assert runtime.complete_calls[0].context is runtime.context
        transaction = engine._normal_chat_transaction_for_request(request)
        assert transaction["relay_snapshot"]["prompt_text"] == "V2 continuity projection"
        assert transaction["prepared_provider_request"] is runtime.prepare_calls[-1]
        assert engine.conversation_history[-1]["identity_relay"]["schema_version"] == 2
        assert transaction["relay_snapshot"]["snapshot_hash"] in engine.identity_relay_snapshot_registry
        assert runtime.prepare_threads == ["nc-identity-relay-turn", "nc-identity-relay-turn"]
    finally:
        _restore_harness(originals)


def test_identity_relay_judge_output_budget_scales_with_batch_size() -> None:
    assert engine._identity_relay_judge_output_budget(0) == 1200
    assert engine._identity_relay_judge_output_budget(1) == 1200
    assert engine._identity_relay_judge_output_budget(11) == 4032


def test_actual_request_contains_accepted_turn_and_v2_projection() -> None:
    runtime, _calls, originals = _install_harness(prepared_status="ready_without_judge")
    try:
        engine.replace_chat_conversation_history([])
        engine.build_llm_request = originals[2]
        _turn, request = _accepted_request("accepted request text")
        engine._ensure_normal_chat_transaction_ready(request)

        params = runtime.prepare_calls[-1].params_copy()
        serialized = json.dumps(params["messages"])
        assert serialized.count("accepted request text") == 1
        assert serialized.count("V2 continuity projection") == 1
        assert params["model"] == "frozen-model"
    finally:
        _restore_harness(originals)


def test_accepted_turn_freezes_persona_and_system_instructions() -> None:
    runtime, calls, originals = _install_harness(
        enabled=True,
        prepared_status="ready_without_judge",
    )
    real_build_llm_request = originals[2]
    keys = ("active_preset_name", "emotional_instructions", "system_prompt")
    original_config = {key: engine.RUNTIME_CONFIG.get(key) for key in keys}
    try:
        engine.build_llm_request = real_build_llm_request
        engine.replace_chat_conversation_history([])
        engine.RUNTIME_CONFIG.update(
            {
                "active_preset_name": "Accepted Persona",
                "emotional_instructions": "Accepted emotional instructions.",
                "system_prompt": "Accepted system prompt.",
            }
        )
        turn = engine._begin_normal_chat_transaction(
            {"role": "user", "content": "freeze my prompt state", "origin": "input"}
        )
        request = engine._freeze_normal_chat_request(turn)

        engine.RUNTIME_CONFIG.update(
            {
                "active_preset_name": "Live Persona",
                "emotional_instructions": "Live emotional instructions.",
                "system_prompt": "Live system prompt.",
            }
        )
        engine._ensure_normal_chat_transaction_ready(request)

        prepare_payload = next(
            payload
            for capability, payload, _thread in calls
            if capability == "identity_relay.prepare_turn"
        )
        assert prepare_payload["query"]["active_persona"] == "Accepted Persona"
        final_request = runtime.prepare_calls[-1].params_copy()
        assert final_request["messages"][0] == {
            "role": "system",
            "content": (
                "Accepted emotional instructions.\n\nAccepted system prompt."
            ),
        }
        serialized = json.dumps(final_request, ensure_ascii=False)
        assert "Live Persona" not in serialized
        assert "Live emotional instructions." not in serialized
        assert "Live system prompt." not in serialized
    finally:
        for key, value in original_config.items():
            if value is None:
                engine.RUNTIME_CONFIG.pop(key, None)
            else:
                engine.RUNTIME_CONFIG[key] = value
        _restore_harness(originals)


def test_accepted_turn_freezes_all_structured_retrieval_signals() -> None:
    _runtime, calls, originals = _install_harness(
        enabled=True,
        prepared_status="ready_without_judge",
    )
    structured = {
        "recent_trajectory": ["accepted trajectory"],
        "named_entities": ["Accepted Entity"],
        "relationships": ["Accepted Relationship"],
        "active_projects": ["Accepted Project"],
        "unresolved_threads": ["Accepted Thread"],
        "explicit_corrections": ["Accepted Correction"],
        "kernel_terms": ["Accepted Kernel"],
    }
    original_persona = engine.RUNTIME_CONFIG.get("active_preset_name")
    try:
        engine.RUNTIME_CONFIG["active_preset_name"] = "Accepted Persona"
        engine.replace_chat_conversation_history(
            [{"role": "assistant", "content": "accepted history"}]
        )
        turn = engine._begin_normal_chat_transaction(
            {
                "role": "user",
                "content": "accepted structured turn",
                "origin": "input",
                "structured_turn_state": structured,
            }
        )
        request = engine._freeze_normal_chat_request(turn)

        for values in structured.values():
            values[:] = ["mutated after acceptance"]
        engine.RUNTIME_CONFIG["active_preset_name"] = "Mutated Persona"
        engine._ensure_normal_chat_transaction_ready(request)

        payload = next(
            item
            for capability, item, _thread in calls
            if capability == "identity_relay.prepare_turn"
        )
        query = payload["query"]
        assert query["active_persona"] == "Accepted Persona"
        assert query["recent_trajectory"] == [
            "accepted history",
            "accepted structured turn",
            "accepted trajectory",
        ]
        assert query["named_entities"] == ["Accepted Entity"]
        assert query["relationships"] == ["Accepted Relationship"]
        assert query["active_projects"] == ["Accepted Project"]
        assert query["unresolved_threads"] == ["Accepted Thread"]
        assert query["explicit_corrections"] == ["Accepted Correction"]
        assert query["kernel_terms"] == ["Accepted Kernel"]
        assert "mutated after acceptance" not in json.dumps(query)
    finally:
        if original_persona is None:
            engine.RUNTIME_CONFIG.pop("active_preset_name", None)
        else:
            engine.RUNTIME_CONFIG["active_preset_name"] = original_persona
        _restore_harness(originals)


def test_deterministic_v2_path_bypasses_judge() -> None:
    runtime, calls, originals = _install_harness(prepared_status="ready_without_judge")
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request()
        engine._ensure_normal_chat_transaction_ready(request)
        assert [item[0] for item in calls] == [
            "identity_relay.capture_turn",
            "identity_relay.prepare_turn",
            "identity_relay.finalize_turn",
        ]
        assert runtime.complete_calls == []
    finally:
        _restore_harness(originals)


def test_judge_failure_degrades_through_finalize_without_recapturing() -> None:
    runtime, calls, originals = _install_harness(
        prepared_status="judge_required",
        judge_error=True,
    )
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("degraded judge")
        engine._ensure_normal_chat_transaction_ready(request)
        finalize_payload = next(
            payload for capability, payload, _thread in calls
            if capability == "identity_relay.finalize_turn"
        )
        failure = finalize_payload["judge_payload"]["judge-batch:0001"]
        assert failure["failure_category"] == "provider_exception"
        assert failure["affected_record_ids"] == ("record:ambiguous",)
        assert "RuntimeError" in failure["reason"]
        assert "judge unavailable" in failure["reason"]
        assert runtime.capture_count == 1
        assert runtime.reply_calls == []
        assert engine.chat_with_llm(request) == "reply"
        assert runtime.reply_calls == [runtime.prepare_calls[-1]]
    finally:
        _restore_harness(originals)


def test_active_finalize_failure_blocks_before_reply() -> None:
    runtime, _calls, originals = _install_harness(finalize_status="blocked")
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("blocked finalize")
        try:
            engine._ensure_normal_chat_transaction_ready(request)
        except engine.NormalChatTurnBlocked as exc:
            assert "finalize_blocked" in str(exc)
        else:
            raise AssertionError("active Relay finalize failure did not block")
        assert runtime.reply_calls == []
        assert engine.conversation_history == []
    finally:
        _restore_harness(originals)


def test_relay_on_non_strict_and_capacity_overflow_fail_before_reply() -> None:
    for strict, token_count, expected in (
        (False, 64, "strict"),
        (True, 481, "capacity"),
    ):
        runtime, _calls, originals = _install_harness(
            strict=strict,
            token_count=token_count,
        )
        try:
            engine.replace_chat_conversation_history([])
            _turn, request = _accepted_request()
            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except engine.NormalChatTurnBlocked as exc:
                assert expected in str(exc).lower()
            else:
                raise AssertionError("Relay ON failure did not block the turn")
            assert runtime.reply_calls == []
            assert engine.conversation_history == []
        finally:
            _restore_harness(originals)


def test_exact_capacity_fit_is_accepted_without_truncating_relay() -> None:
    runtime, _calls, originals = _install_harness(token_count=480)
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request()
        engine._ensure_normal_chat_transaction_ready(request)
        assert engine._normal_chat_transaction_for_request(request)[
            "relay_snapshot"
        ]["prompt_text"] == "V2 continuity projection"
        assert len(runtime.prepare_calls) == 1
    finally:
        _restore_harness(originals)


def test_unknown_exact_capacity_warns_once_and_proceeds_for_any_locality() -> None:
    for provider_is_remote in (False, True):
        runtime, _calls, originals = _install_harness(
            context_limit=None,
            provider_is_remote=provider_is_remote,
            prepared_status="judge_required",
        )
        warning_keys = getattr(
            engine,
            "_identity_relay_unknown_capacity_warning_keys",
            None,
        )
        if warning_keys is not None:
            warning_keys.clear()
        output = io.StringIO()
        try:
            engine.replace_chat_conversation_history([])
            with redirect_stdout(output):
                for index in range(2):
                    _turn, request = _accepted_request(
                        f"unknown capacity turn {index}"
                    )
                    transaction = engine._ensure_normal_chat_transaction_ready(
                        request
                    )
                    assert transaction["status"] == "ready"

            text = output.getvalue()
            assert text.count("Exact context limit is unavailable") == 1
            assert len(runtime.prepare_calls) == 4
            assert len(runtime.complete_calls) == 2
            assert len(runtime.count_calls) == 4
        finally:
            _restore_harness(originals)


def test_missing_frozen_execution_hook_fails_closed() -> None:
    runtime, _calls, originals = _install_harness(
        enabled=False,
        strict=False,
        execution_available=False,
    )
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("missing hook")
        try:
            engine._ensure_normal_chat_transaction_ready(request)
        except engine.NormalChatTurnBlocked as exc:
            assert "frozen completion" in str(exc).lower()
        else:
            raise AssertionError("missing frozen execution hook used a legacy fallback")
        assert runtime.reply_calls == []
        assert engine.conversation_history == []
    finally:
        _restore_harness(originals)


def test_concurrent_prepare_is_exactly_once_and_fallback_identity_is_stable() -> None:
    runtime, _calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request()
        errors = []

        def ensure():
            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=ensure) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3.0)

        assert errors == []
        assert len(runtime.prepare_calls) == 1
        prepared = engine._prepared_normal_chat_provider_request(request)
        assert prepared is runtime.prepare_calls[0]
        assert engine.chat_with_llm(request, prepared_request=prepared) == "reply"
        assert runtime.reply_calls == [prepared]
    finally:
        _restore_harness(originals)


def test_queued_turn_keeps_original_binding_without_partial_history() -> None:
    runtime, calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history([])
        result = engine.queue_typed_chat_message("queued once")
        assert result["queued"] is True
        assert engine.conversation_history == []
        pending = engine._consume_pending_loaded_input_turn()
        assert pending["normal_chat_transaction_id"]
        request = engine._freeze_normal_chat_request(
            pending,
            require_existing_transaction=True,
        )
        engine._ensure_normal_chat_transaction_ready(request)
        assert len(runtime.prepare_calls) == 1
        assert [item[0] for item in calls] == ["identity_relay.capture_turn"]
        assert engine.conversation_history[-1]["content"] == "queued once"
    finally:
        _restore_harness(originals)


def test_queued_image_turn_captures_at_acceptance_and_commits_after_prepare() -> None:
    runtime, calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history([])
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "queued-image.png"
            image_path.write_bytes(b"not-a-real-image-but-an-existing-file")

            returned = engine.queue_user_image_turn(
                str(image_path),
                content="queued image once",
            )
            assert returned["attachment_image_path"] == str(image_path.resolve())
            assert engine.conversation_history == []
            assert runtime.capture_count == 1
            assert [item[0] for item in calls] == ["identity_relay.capture_turn"]

            pending = engine._consume_pending_loaded_input_turn()
            assert pending["normal_chat_transaction_id"]
            assert pending["attachment_image_path"] == str(image_path.resolve())
            request = engine._freeze_normal_chat_request(
                pending,
                require_existing_transaction=True,
            )
            engine._ensure_normal_chat_transaction_ready(request)

            assert runtime.capture_count == 1
            assert len(runtime.prepare_calls) == 1
            assert len(engine.conversation_history) == 1
            committed = engine.conversation_history[0]
            assert committed["content"] == "queued image once"
            assert committed["attachment_image_path"] == str(image_path.resolve())
            assert committed["normal_chat_transaction_id"] == pending[
                "normal_chat_transaction_id"
            ]
    finally:
        _restore_harness(originals)


def test_queued_image_turn_prepare_failure_leaves_history_unchanged() -> None:
    runtime, _calls, originals = _install_harness(
        enabled=False,
        strict=False,
        execution_available=False,
    )
    try:
        engine.replace_chat_conversation_history([])
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "failed-image.png"
            image_path.write_bytes(b"existing-file")
            engine.queue_user_image_turn(str(image_path), content="must stay detached")
            pending = engine._consume_pending_loaded_input_turn()
            assert pending["normal_chat_transaction_id"]
            request = engine._freeze_normal_chat_request(
                pending,
                require_existing_transaction=True,
            )

            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except engine.NormalChatTurnBlocked:
                pass
            else:
                raise AssertionError("failed image preparation committed partial history")

            assert engine.conversation_history == []
            assert runtime.prepare_calls == []
            assert runtime.reply_calls == []
    finally:
        _restore_harness(originals)


def test_queue_image_turn_legacy_append_callback_remains_compatible() -> None:
    events = []
    pending = []
    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "legacy-image.png"
        image_path.write_bytes(b"existing-file")

        def append_turn(turn):
            events.append(("append", dict(turn)))
            return None

        returned = engine.user_image_turns.queue_image_turn(
            str(image_path),
            content="legacy callback",
            sanitize_chat_turn=lambda turn: dict(turn),
            append_chat_turn=append_turn,
            apply_stored_chat_history_limit=lambda: events.append(("limit", None)),
            set_pending_loaded_input_turn=lambda turn: (
                events.append(("pending", dict(turn))),
                pending.append(dict(turn)),
            ),
            request_chat_view_rebuild=lambda: events.append(("rebuild", None)),
        )

    assert [name for name, _value in events] == [
        "append",
        "limit",
        "pending",
        "rebuild",
    ]
    assert pending == [returned]
    assert "normal_chat_transaction_id" not in returned


def test_reset_before_judge_cancels_projection_and_rejects_late_history() -> None:
    runtime, calls, originals = _install_harness(prepared_status="judge_required")
    original_invoke = engine._invoke_targeted_addon_capability
    prepare_started = threading.Event()
    release_prepare = threading.Event()

    def delayed_invoke(addon_id, capability, payload=None):
        if capability == "identity_relay.chat_session.reset":
            return None
        if capability == "identity_relay.prepare_turn":
            prepare_started.set()
            assert release_prepare.wait(timeout=3.0)
        return original_invoke(addon_id, capability, payload)

    try:
        engine.replace_chat_conversation_history([])
        engine._invoke_targeted_addon_capability = delayed_invoke
        _turn, request = _accepted_request("cancel me")
        transaction = engine._normal_chat_transaction_for_request(request)
        errors = []

        def ensure():
            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=ensure)
        worker.start()
        assert prepare_started.wait(timeout=3.0)
        engine.reset_session_state()
        assert transaction["cancel_event"].is_set()
        release_prepare.set()
        worker.join(timeout=3.0)
        assert not worker.is_alive()
        assert errors and isinstance(errors[0], engine.NormalChatTurnBlocked)
        assert "identity_relay.render_judge_request" not in [item[0] for item in calls]
        assert "identity_relay.finalize_turn" not in [item[0] for item in calls]
        assert engine.conversation_history == []
        assert runtime.reply_calls == []
    finally:
        release_prepare.set()
        engine._invoke_targeted_addon_capability = original_invoke
        _restore_harness(originals)


def test_cancellation_after_judge_discards_finalize_and_history() -> None:
    judge_started = threading.Event()
    judge_release = threading.Event()
    runtime, calls, originals = _install_harness(
        prepared_status="judge_required",
        judge_started=judge_started,
        judge_release=judge_release,
    )
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("cancel after judge")
        errors = []

        def ensure():
            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except Exception as exc:
                errors.append(exc)

        waiter = threading.Thread(target=ensure)
        waiter.start()
        assert judge_started.wait(timeout=3.0)
        assert engine._cancel_normal_chat_request(request) is True
        judge_release.set()
        waiter.join(timeout=3.0)
        assert not waiter.is_alive()
        assert errors and isinstance(errors[0], engine.NormalChatTurnBlocked)
        assert "identity_relay.finalize_turn" not in [item[0] for item in calls]
        assert engine.conversation_history == []
        assert runtime.reply_calls == []
    finally:
        judge_release.set()
        _restore_harness(originals)


def test_load_during_prepare_cancels_stale_worker() -> None:
    runtime, _calls, originals = _install_harness()
    original_invoke = engine._invoke_targeted_addon_capability
    prepare_started = threading.Event()
    release_prepare = threading.Event()

    def delayed_invoke(addon_id, capability, payload=None):
        if capability in {
            "identity_relay.chat_session.reset",
            "identity_relay.chat_session.import",
        }:
            return None
        if capability == "identity_relay.prepare_turn":
            prepare_started.set()
            assert release_prepare.wait(timeout=3.0)
        return original_invoke(addon_id, capability, payload)

    try:
        engine.replace_chat_conversation_history([])
        engine._invoke_targeted_addon_capability = delayed_invoke
        _turn, request = _accepted_request("load cancellation")
        transaction = engine._normal_chat_transaction_for_request(request)
        errors = []

        def ensure():
            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except Exception as exc:
                errors.append(exc)

        waiter = threading.Thread(target=ensure)
        waiter.start()
        assert prepare_started.wait(timeout=3.0)
        engine.import_chat_session_state({"conversation_history": []})
        assert transaction["cancel_event"].is_set()
        release_prepare.set()
        waiter.join(timeout=3.0)
        assert not waiter.is_alive()
        assert errors and isinstance(errors[0], engine.NormalChatTurnBlocked)
        assert engine.conversation_history == []
        assert runtime.reply_calls == []
    finally:
        release_prepare.set()
        engine._invoke_targeted_addon_capability = original_invoke
        _restore_harness(originals)


def test_loaded_ordinary_regeneration_recaptures_provider_without_relay() -> None:
    runtime, calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history(
            [{"role": "user", "content": "loaded legacy turn", "origin": "input"}]
        )
        resumed, _removed = engine.conversation_history_runtime.prepare_regeneration_turn(
            engine.conversation_history,
            target_in_history=True,
            input_roles={"user"},
        )
        request = engine._freeze_normal_chat_request(
            resumed,
            require_existing_transaction=True,
        )
        transaction = engine._normal_chat_transaction_for_request(request)

        assert transaction is not None
        assert transaction["provider_context"] is runtime.context
        assert transaction["relay_capture"] is None
        assert transaction["restored_relay_snapshot"] is None
        assert request["identity_relay_snapshot"] is None
        assert request["identity_relay_metadata"] is None
        assert runtime.capture_count == 1
        assert len(runtime.prepare_calls) == 0
        assert calls == []
    finally:
        _restore_harness(originals)


def test_volatile_projection_is_not_exported_from_snapshot_registry() -> None:
    _runtime, _calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history([])
        snapshot = engine._identity_relay_v2_snapshot_payload(
            RelaySnapshot(
                "ready",
                prompt_text="Volatile continuity projection",
                persistence_mode="volatile",
            )
        )
        metadata = engine._identity_relay_v2_metadata(snapshot)
        with engine.identity_relay_snapshot_lock:
            engine.identity_relay_snapshot_registry[snapshot["snapshot_hash"]] = snapshot
        engine.replace_chat_conversation_history(
            [
                {
                    "role": "user",
                    "content": "volatile historical turn",
                    "origin": "input",
                    "identity_relay": metadata,
                }
            ]
        )

        _history, exported = engine._freeze_chat_persistence_relay_state()

        assert exported == {}
    finally:
        _restore_harness(originals)


def test_import_rejects_tampered_persisted_snapshot_hash() -> None:
    _runtime, _calls, originals = _install_harness(enabled=False)
    harness_invoke = engine._invoke_targeted_addon_capability
    try:
        snapshot = _valid_relay_snapshot()
        snapshot["prompt_text"] = "User-edited projection"

        def invoke_with_session_lifecycle(addon_id, capability, payload=None):
            if capability in {
                "identity_relay.chat_session.reset",
                "identity_relay.chat_session.import",
            }:
                return None
            return harness_invoke(addon_id, capability, payload)

        engine._invoke_targeted_addon_capability = invoke_with_session_lifecycle

        engine.import_chat_session_state(
            {
                "conversation_history": [],
                "identity_relay_snapshots": {
                    snapshot["snapshot_hash"]: snapshot,
                },
            }
        )

        assert engine.identity_relay_snapshot_registry == {}
    finally:
        _restore_harness(originals)


def test_restart_regeneration_requires_matching_trusted_authorization() -> None:
    for restore_authorized, restore_snapshot_hash in (
        (False, ""),
        (True, "f" * 64),
    ):
        runtime, _calls, originals = _install_harness(
            enabled=False,
            restore_authorized=restore_authorized,
            restore_snapshot_hash=restore_snapshot_hash,
        )
        try:
            snapshot = _valid_relay_snapshot()
            metadata = engine._identity_relay_v2_metadata(snapshot)
            with engine.identity_relay_snapshot_lock:
                engine.identity_relay_snapshot_registry[snapshot["snapshot_hash"]] = snapshot
            engine.replace_chat_conversation_history(
                [
                    {
                        "role": "user",
                        "content": "persisted historical turn",
                        "origin": "input",
                        "identity_relay": metadata,
                    }
                ]
            )
            resumed, _removed = (
                engine.conversation_history_runtime.prepare_regeneration_turn(
                    engine.conversation_history,
                    target_in_history=True,
                    input_roles={"user"},
                )
            )
            request = engine._freeze_normal_chat_request(
                resumed,
                require_existing_transaction=True,
            )

            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except engine.NormalChatTurnBlocked as exc:
                assert "authorization" in str(exc).lower()
            else:
                raise AssertionError("untrusted persisted snapshot reached reply preparation")
            assert runtime.reply_calls == []
            assert runtime.prepare_calls == []
        finally:
            _restore_harness(originals)


def test_restart_regeneration_blocks_local_projection_for_remote_provider() -> None:
    runtime, calls, originals = _install_harness(
        enabled=False,
        provider_is_remote=True,
        restore_authorized=False,
    )
    try:
        snapshot = _valid_relay_snapshot()
        metadata = engine._identity_relay_v2_metadata(snapshot)
        with engine.identity_relay_snapshot_lock:
            engine.identity_relay_snapshot_registry[snapshot["snapshot_hash"]] = snapshot
        engine.replace_chat_conversation_history(
            [
                {
                    "role": "user",
                    "content": "persisted historical turn",
                    "origin": "input",
                    "identity_relay": metadata,
                }
            ]
        )
        resumed, _removed = engine.conversation_history_runtime.prepare_regeneration_turn(
            engine.conversation_history,
            target_in_history=True,
            input_roles={"user"},
        )
        request = engine._freeze_normal_chat_request(
            resumed,
            require_existing_transaction=True,
        )

        try:
            engine._ensure_normal_chat_transaction_ready(request)
        except engine.NormalChatTurnBlocked as exc:
            assert "authorization" in str(exc).lower()
        else:
            raise AssertionError("local-only projection reached a remote provider")
        assert any(
            capability == "identity_relay.restore_persisted_snapshot"
            for capability, _payload, _thread in calls
        )
        assert runtime.reply_calls == []
        assert runtime.prepare_calls == []
    finally:
        _restore_harness(originals)


def test_restart_regeneration_upgrades_and_counts_exact_outbound_request() -> None:
    runtime, _calls, originals = _install_harness(
        enabled=False,
        token_count=500,
        context_limit=512,
    )
    try:
        snapshot = _valid_relay_snapshot()
        metadata = engine._identity_relay_v2_metadata(snapshot)
        with engine.identity_relay_snapshot_lock:
            engine.identity_relay_snapshot_registry[snapshot["snapshot_hash"]] = snapshot
        engine.replace_chat_conversation_history(
            [
                {
                    "role": "user",
                    "content": "persisted historical turn",
                    "origin": "input",
                    "identity_relay": metadata,
                }
            ]
        )
        resumed, _removed = engine.conversation_history_runtime.prepare_regeneration_turn(
            engine.conversation_history,
            target_in_history=True,
            input_roles={"user"},
        )
        request = engine._freeze_normal_chat_request(
            resumed,
            require_existing_transaction=True,
        )

        try:
            engine._ensure_normal_chat_transaction_ready(request)
        except engine.NormalChatTurnBlocked as exc:
            assert "capacity" in str(exc).lower()
        else:
            raise AssertionError("strict capacity overflow reached reply dispatch")
        assert runtime.upgrade_count == 1
        assert len(runtime.prepare_calls) == 1
        assert runtime.count_calls == [
            runtime.prepare_calls[0].params_copy()["messages"]
        ]
        assert runtime.reply_calls == []
    finally:
        _restore_harness(originals)


def test_uncapped_prepared_request_uses_remaining_context_capacity() -> None:
    runtime, _calls, originals = _install_harness(
        token_count=64,
        context_limit=512,
        output_tokens=None,
    )
    try:
        _turn, request = _accepted_request("uncapped provider request")
        transaction = engine._ensure_normal_chat_transaction_ready(request)
        prepared = transaction["prepared_provider_request"]

        assert prepared.params_copy() == {
            "model": runtime.context.model_name,
            "messages": [
                {"role": "system", "content": "V2 continuity projection"},
                {"role": "user", "content": "accepted turn"},
            ],
        }
        assert len(runtime.count_calls) == 1
        assert transaction["status"] == "ready"
    finally:
        _restore_harness(originals)


def test_responses_prepared_request_exposes_exact_input_and_budget() -> None:
    messages = [
        {"role": "system", "content": "continuity"},
        {"role": "user", "content": "hello"},
    ]

    class ResponsesRequest:
        def params_copy(self):
            return {
                "model": "opaque-responses-model",
                "input": copy.deepcopy(messages),
                "max_output_tokens": 128,
            }

        def additional_params_copy(self):
            return {}

    actual_messages, output_budget = engine._prepared_request_messages_and_output_budget(
        ResponsesRequest()
    )

    assert actual_messages == messages
    assert output_budget == 128


def test_restart_capacity_uses_registered_provider_and_production_counting() -> None:
    from core import chat_providers, runtime_chat

    provider_id = "identity-relay-capacity-fixture"
    context_limit = 1400
    output_budget = 24
    projection_text = "RESTORED_CAPACITY_PROJECTION:" + (" continuity" * 250)
    prepared_messages = []
    counted_messages = []
    measured_counts = []
    reply_calls = []
    capability_calls = []

    def normalized_messages(messages):
        return tuple(
            (
                str(message.get("role") or ""),
                str(message.get("content") or ""),
            )
            for message in tuple(messages or ())
        )

    def token_units(messages):
        return sum(
            len(role.encode("utf-8")) + len(content.encode("utf-8")) + 2
            for role, content in normalized_messages(messages)
        )

    def count_tokens(messages):
        frozen = normalized_messages(messages)
        counted_messages.append(frozen)
        measured = token_units(
            {"role": role, "content": content}
            for role, content in frozen
        )
        measured_counts.append(measured)
        return measured

    def prepare(_binding, params, additional_params):
        prepared = dict(params)
        prepared["max_tokens"] = output_budget
        prepared_messages.append(normalized_messages(prepared.get("messages")))
        return prepared, dict(additional_params or {})

    def capabilities(binding):
        capability_calls.append(binding.execution_identity)
        return {
            "context_limit": context_limit,
            "capability_identity": binding.execution_identity,
            "token_counter_identity": binding.execution_identity,
        }

    def complete(request, *, timeout=None, cancel_token=None):
        reply_calls.append(request)
        return "must not dispatch"

    original_runtime = engine._chat_runtime
    original_invoke = engine._invoke_targeted_addon_capability
    production_builder = engine.build_llm_request
    production_counter = engine.chat_providers.count_frozen_chat_tokens
    original_prompt = {
        key: engine.RUNTIME_CONFIG.get(key)
        for key in (
            "active_preset_name",
            "emotional_instructions",
            "system_prompt",
        )
    }

    def invoke(_addon_id, capability, payload=None):
        if capability == "identity_relay.restore_persisted_snapshot":
            snapshot = dict((payload or {}).get("snapshot") or {})
            return {
                "authorized": True,
                "failure_code": "",
                "snapshot_hash": str(snapshot.get("snapshot_hash") or ""),
                "authorization_record_id": str(
                    snapshot.get("authorization_record_id") or ""
                ),
                "provider_is_remote": False,
            }
        if capability in {
            "identity_relay.chat_session.reset",
            "identity_relay.chat_session.import",
        }:
            return None
        raise AssertionError(f"unexpected Relay capability: {capability}")

    try:
        chat_providers.register_provider(
            provider_id=provider_id,
            label="Identity Relay Capacity Fixture",
            frozen_execution_version=1,
            frozen_prepare_handler=prepare,
            frozen_completion_handler=complete,
            frozen_stream_handler=lambda _request, **_kwargs: iter(()),
            model_capabilities_handler=capabilities,
            token_counter=count_tokens,
            frozen_private_config_getter=lambda: {
                "base_url": "http://127.0.0.1:1234/v1",
                "provider_is_remote": False,
            },
            frozen_public_config_fields=("base_url", "provider_is_remote"),
        )
        engine._chat_runtime = runtime_chat.ChatProviderRuntime(
            lambda: {
                "chat_provider": provider_id,
                "model_name": "capacity-model",
            }
        )
        engine._invoke_targeted_addon_capability = invoke
        engine.RUNTIME_CONFIG.update(
            {
                "active_preset_name": "",
                "emotional_instructions": "",
                "system_prompt": "",
            }
        )
        engine.reset_session_state()
        snapshot = _valid_relay_snapshot(prompt_text=projection_text)
        metadata = engine._identity_relay_v2_metadata(snapshot)
        with engine.identity_relay_snapshot_lock:
            engine.identity_relay_snapshot_registry[snapshot["snapshot_hash"]] = snapshot
        engine.replace_chat_conversation_history(
            [
                {
                    "role": "user",
                    "content": "persisted historical turn",
                    "origin": "input",
                    "identity_relay": metadata,
                }
            ]
        )
        resumed, _removed = engine.conversation_history_runtime.prepare_regeneration_turn(
            engine.conversation_history,
            target_in_history=True,
            input_roles={"user"},
        )
        request = engine._freeze_normal_chat_request(
            resumed,
            require_existing_transaction=True,
        )

        try:
            engine._ensure_normal_chat_transaction_ready(request)
        except engine.NormalChatTurnBlocked as exc:
            assert "capacity" in str(exc).casefold()
        else:
            raise AssertionError("restored production request overflow reached dispatch")

        assert engine.build_llm_request is production_builder
        assert engine.chat_providers.count_frozen_chat_tokens is production_counter
        assert len(capability_calls) == 1
        assert len(prepared_messages) == 1
        assert counted_messages == prepared_messages
        assert len(measured_counts) == 1
        projection_messages = tuple(
            item for item in counted_messages[0] if item[1] == projection_text
        )
        assert projection_messages == (("system", projection_text),)
        without_projection = tuple(
            {"role": role, "content": content}
            for role, content in counted_messages[0]
            if content != projection_text
        )
        assert token_units(without_projection) + output_budget <= context_limit
        assert measured_counts[0] + output_budget > context_limit
        assert reply_calls == []
    finally:
        try:
            engine.reset_session_state()
        finally:
            engine._chat_runtime = original_runtime
            engine._invoke_targeted_addon_capability = original_invoke
            engine.RUNTIME_CONFIG.update(original_prompt)
            chat_providers.unregister_provider(provider_id)


def test_restart_regeneration_uses_authorized_persisted_projection() -> None:
    runtime, calls, originals = _install_harness(enabled=False)
    harness_invoke = engine._invoke_targeted_addon_capability
    try:
        engine.replace_chat_conversation_history([])
        snapshot = _valid_relay_snapshot()
        metadata = engine._identity_relay_v2_metadata(snapshot)
        with engine.identity_relay_snapshot_lock:
            engine.identity_relay_snapshot_registry[snapshot["snapshot_hash"]] = snapshot
        engine.replace_chat_conversation_history(
            [
                {
                    "role": "user",
                    "content": "persisted historical turn",
                    "origin": "input",
                    "identity_relay": metadata,
                },
                {
                    "role": "assistant",
                    "content": "old reply",
                    "origin": "assistant_reply",
                },
            ]
        )
        exported_history, exported_snapshots = (
            engine._freeze_chat_persistence_relay_state()
        )
        assert exported_snapshots == {snapshot["snapshot_hash"]: snapshot}

        def invoke_with_session_lifecycle(addon_id, capability, payload=None):
            if capability in {
                "identity_relay.chat_session.reset",
                "identity_relay.chat_session.import",
            }:
                return None
            return harness_invoke(addon_id, capability, payload)

        engine._invoke_targeted_addon_capability = invoke_with_session_lifecycle
        engine.import_chat_session_state(
            {
                "conversation_history": exported_history,
                "identity_relay_snapshots": exported_snapshots,
            }
        )
        resumed, _removed = engine.conversation_history_runtime.prepare_regeneration_turn(
            engine.conversation_history,
            target_in_history=True,
            input_roles={"user"},
        )

        request = engine._freeze_normal_chat_request(
            resumed,
            require_existing_transaction=True,
        )
        transaction = engine._ensure_normal_chat_transaction_ready(request)
        final_params = transaction["prepared_provider_request"].params_copy()

        assert runtime.capture_count == 1
        assert [item[0] for item in calls] == [
            "identity_relay.restore_persisted_snapshot"
        ]
        assert transaction["relay_pipeline_complete"] is True
        assert transaction["relay_snapshot"]["snapshot_hash"] == snapshot["snapshot_hash"]
        assert "Persisted immutable continuity projection" in json.dumps(final_params)
        assert runtime.upgrade_count == 1
        assert runtime.count_calls == [final_params["messages"]]
    finally:
        _restore_harness(originals)


def test_regeneration_copies_only_transaction_id_not_frozen_context() -> None:
    _runtime, _calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history([])
        turn, request = _accepted_request()
        engine._ensure_normal_chat_transaction_ready(request)
        original_prepared = engine._normal_chat_transaction_for_request(request)[
            "prepared_provider_request"
        ]
        resumed, _removed = engine.conversation_history_runtime.prepare_regeneration_turn(
            engine.conversation_history,
            target_in_history=False,
            input_roles={"user"},
        )
        assert resumed["normal_chat_transaction_id"] == turn["normal_chat_transaction_id"]
        assert "normal_chat_transaction" not in resumed
        assert engine._normal_chat_transaction_for_turn(resumed)["provider_context"] is _runtime.context
        regenerated_request = engine._freeze_normal_chat_request(
            resumed,
            require_existing_transaction=True,
        )
        assert engine._prepared_normal_chat_provider_request(regenerated_request) is original_prepared
        assert _runtime.capture_count == 1
        assert len(_runtime.prepare_calls) == 1
    finally:
        _restore_harness(originals)


def test_completed_regeneration_recaptures_current_provider_binding() -> None:
    runtime, _calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history([])
        turn, request = _accepted_request("regenerate with another model")
        engine._ensure_normal_chat_transaction_ready(request)
        original_prepared = engine._prepared_normal_chat_provider_request(request)
        assistant_turn = engine._append_assistant_history_turn(
            "original reply",
            expected_session_generation=request["session_generation"],
            expected_turn_id=request["normal_chat_transaction_id"],
        )
        assert assistant_turn is not None

        next_context = FrozenContext()
        next_context.model_name = "newly-selected-model"
        runtime.context = next_context
        resumed, removed = engine.conversation_history_runtime.prepare_regeneration_turn(
            engine.conversation_history,
            target_in_history=True,
            input_roles={"user"},
        )
        assert removed is True
        assert resumed["normal_chat_transaction_id"] == turn["normal_chat_transaction_id"]

        regenerated_request = engine._freeze_normal_chat_request(
            resumed,
            request_only_continue_cue=True,
            require_existing_transaction=True,
        )
        regenerated_transaction = engine._normal_chat_transaction_for_request(
            regenerated_request
        )
        engine._ensure_normal_chat_transaction_ready(regenerated_request)

        assert regenerated_request["normal_chat_transaction_id"] != request["normal_chat_transaction_id"]
        assert regenerated_transaction["provider_context"] is next_context
        assert engine._prepared_normal_chat_provider_request(regenerated_request) is not original_prepared
        assert runtime.capture_count == 2
        assert len(runtime.prepare_calls) == 2
        assert len(engine.conversation_history) == 1
        assert engine.conversation_history[0]["content"] == "regenerate with another model"
        assert (
            engine.conversation_history[0]["normal_chat_transaction_id"]
            == regenerated_request["normal_chat_transaction_id"]
        )
        assert request["normal_chat_transaction_id"] not in engine.normal_chat_transaction_registry
    finally:
        _restore_harness(originals)


def test_detached_continuation_retains_frozen_binding_for_regeneration() -> None:
    runtime, _calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history(
            [{"role": "assistant", "content": "prior reply", "origin": "assistant_reply"}]
        )
        request = engine._freeze_normal_chat_request(
            request_only_continue_cue=True,
        )
        engine._ensure_normal_chat_transaction_ready(request)
        transaction_id = request["normal_chat_transaction_id"]
        original_prepared = engine._prepared_normal_chat_provider_request(request)

        assistant_turn = engine._append_assistant_history_turn(
            "continued reply",
            expected_session_generation=request["session_generation"],
            expected_turn_id=transaction_id,
        )
        assert assistant_turn["normal_chat_transaction_id"] == transaction_id
        assert transaction_id in engine.normal_chat_transaction_registry

        resumed, removed = engine.conversation_history_runtime.prepare_regeneration_turn(
            engine.conversation_history,
            target_in_history=True,
            input_roles={"user"},
        )
        assert removed is True
        assert resumed["content"] == engine.conversation_history_runtime.REQUEST_ONLY_CONTINUATION_CUE
        assert resumed["normal_chat_transaction_id"] == transaction_id

        regenerated_request = engine._freeze_normal_chat_request(
            resumed,
            request_only_continue_cue=True,
            require_existing_transaction=True,
        )
        assert engine._prepared_normal_chat_provider_request(regenerated_request) is original_prepared
        assert runtime.capture_count == 1
        assert len(runtime.prepare_calls) == 1
    finally:
        _restore_harness(originals)


def test_history_trimming_prunes_obsolete_prepared_payloads() -> None:
    runtime, _calls, originals = _install_harness(enabled=False)
    original_limit = engine.RUNTIME_CONFIG.get("stored_chat_history_limit")
    try:
        engine.replace_chat_conversation_history([])
        first_turn, first_request = _accepted_request("first")
        engine._ensure_normal_chat_transaction_ready(first_request)
        first_transaction = engine._normal_chat_transaction_for_turn(first_turn)
        engine._append_assistant_history_turn(
            "first reply",
            expected_session_generation=first_request["session_generation"],
            expected_turn_id=first_request["normal_chat_transaction_id"],
        )

        second_turn, second_request = _accepted_request("second")
        engine._ensure_normal_chat_transaction_ready(second_request)
        second_transaction = engine._normal_chat_transaction_for_turn(second_turn)
        engine._append_assistant_history_turn(
            "second reply",
            expected_session_generation=second_request["session_generation"],
            expected_turn_id=second_request["normal_chat_transaction_id"],
        )

        engine.RUNTIME_CONFIG["stored_chat_history_limit"] = 2
        engine._apply_stored_chat_history_limit()
        assert first_transaction["prepared_provider_request"] is None
        assert first_turn["normal_chat_transaction_id"] not in engine.normal_chat_transaction_registry
        assert second_turn["normal_chat_transaction_id"] in engine.normal_chat_transaction_registry
        assert second_transaction["provider_context"] is runtime.context
    finally:
        if original_limit is None:
            engine.RUNTIME_CONFIG.pop("stored_chat_history_limit", None)
        else:
            engine.RUNTIME_CONFIG["stored_chat_history_limit"] = original_limit
        _restore_harness(originals)


def test_cancel_between_completion_readiness_and_dispatch_blocks_provider() -> None:
    runtime, _calls, originals = _install_harness(enabled=False)
    reached = release = restore_dispatch = None
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("cancel before completion claim")
        transaction = engine._ensure_normal_chat_transaction_ready(request)
        reached, release, restore_dispatch = _install_pre_dispatch_barrier(
            claim_kind="completion",
            legacy_stage="provider completion dispatch",
        )
        errors = []

        def complete():
            try:
                engine.chat_with_llm(request)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=complete, name="completion-dispatch-race")
        worker.start()
        assert reached.wait(timeout=3.0)
        assert engine._cancel_normal_chat_request(request) is True
        release.set()
        worker.join(timeout=3.0)
        assert not worker.is_alive()
        assert runtime.reply_calls == []
        assert errors and isinstance(errors[0], engine.NormalChatTurnBlocked)
        assert transaction.get("provider_dispatch_claims") == []
    finally:
        if release is not None:
            release.set()
        if restore_dispatch is not None:
            restore_dispatch()
        _restore_harness(originals)


def test_reset_between_stream_readiness_and_dispatch_blocks_provider() -> None:
    runtime, _calls, originals = _install_harness(enabled=False)
    original_invoke = engine._invoke_targeted_addon_capability
    reached = release = restore_dispatch = None
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("reset before stream claim")
        transaction = engine._ensure_normal_chat_transaction_ready(request)

        def allow_reset(addon_id, capability, payload=None):
            if capability == "identity_relay.chat_session.reset":
                return None
            return original_invoke(addon_id, capability, payload)

        engine._invoke_targeted_addon_capability = allow_reset
        reached, release, restore_dispatch = _install_pre_dispatch_barrier(
            claim_kind="stream",
            legacy_stage="provider stream dispatch",
        )
        state = engine.start_streamed_llm_reply(queue.Queue(), request_context=request)
        assert reached.wait(timeout=3.0)
        engine.reset_session_state()
        release.set()
        assert state.done.wait(timeout=3.0)
        assert runtime.stream_calls == []
        assert transaction.get("provider_dispatch_claims") == []
        assert transaction["cancel_event"].is_set()
    finally:
        if release is not None:
            release.set()
        if restore_dispatch is not None:
            restore_dispatch()
        engine._invoke_targeted_addon_capability = original_invoke
        _restore_harness(originals)


def test_cancel_after_judge_request_preparation_blocks_judge_dispatch() -> None:
    runtime, _calls, originals = _install_harness(prepared_status="judge_required")
    original_prepare = runtime.prepare_frozen_request
    judge_prepared = threading.Event()
    release_judge = threading.Event()
    try:
        engine.replace_chat_conversation_history([])

        def delayed_prepare(context, params, additional_params=None):
            prepared = original_prepare(context, params, additional_params)
            if any(
                "judge" in str(message.get("content", ""))
                for message in params.get("messages") or []
            ):
                judge_prepared.set()
                assert release_judge.wait(timeout=3.0)
            return prepared

        runtime.prepare_frozen_request = delayed_prepare
        _turn, request = _accepted_request("cancel prepared judge")
        transaction = engine._normal_chat_transaction_for_request(request)
        errors = []

        def ensure():
            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=ensure, name="judge-dispatch-race")
        worker.start()
        assert judge_prepared.wait(timeout=3.0)
        assert engine._cancel_normal_chat_request(request) is True
        release_judge.set()
        worker.join(timeout=3.0)
        assert not worker.is_alive()
        assert runtime.complete_calls == []
        assert errors and isinstance(errors[0], engine.NormalChatTurnBlocked)
        assert transaction.get("provider_dispatch_claims") == []
    finally:
        release_judge.set()
        runtime.prepare_frozen_request = original_prepare
        _restore_harness(originals)


def test_cancelled_worker_cannot_republish_ready_or_survive_pruning() -> None:
    _runtime, _calls, originals = _install_harness(enabled=False)
    original_assert = engine._assert_normal_chat_transaction_current
    handoff_checked = threading.Event()
    release_handoff = threading.Event()
    try:
        engine.replace_chat_conversation_history([])

        def delayed_assert(transaction, stage):
            result = original_assert(transaction, stage)
            if stage == "provider handoff":
                handoff_checked.set()
                assert release_handoff.wait(timeout=3.0)
            return result

        engine._assert_normal_chat_transaction_current = delayed_assert
        turn, request = _accepted_request("cancel before ready publish")
        transaction = engine._normal_chat_transaction_for_request(request)
        errors = []

        def ensure():
            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=ensure, name="ready-publish-race")
        worker.start()
        assert handoff_checked.wait(timeout=3.0)
        assert engine._cancel_normal_chat_request(request) is True
        release_handoff.set()
        worker.join(timeout=3.0)
        assert not worker.is_alive()
        assert errors and isinstance(errors[0], engine.NormalChatTurnBlocked)
        assert transaction["status"] == "cancelled"
        assert turn["normal_chat_transaction_id"] not in engine.normal_chat_transaction_registry
        engine._prune_normal_chat_transactions()
        assert turn["normal_chat_transaction_id"] not in engine.normal_chat_transaction_registry

        stale_turn = engine._begin_normal_chat_transaction(
            {"role": "user", "content": "cancelled ready text", "origin": "input"}
        )
        stale_id = stale_turn["normal_chat_transaction_id"]
        stale_transaction = engine.normal_chat_transaction_registry[stale_id]
        stale_transaction["cancel_event"].set()
        stale_transaction["status"] = "ready"
        engine._prune_normal_chat_transactions()
        assert stale_id not in engine.normal_chat_transaction_registry
        assert stale_transaction["status"] == "cancelled"
        assert stale_transaction["provider_context"] is None
    finally:
        release_handoff.set()
        engine._assert_normal_chat_transaction_current = original_assert
        _restore_harness(originals)


def test_replacing_pending_typed_turn_discards_previous_binding() -> None:
    _runtime, _calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history([])
        assert engine.queue_typed_chat_message("first pending")["queued"] is True
        first_pending = dict(engine.pending_loaded_input_turn or {})
        first_id = first_pending["normal_chat_transaction_id"]
        first_transaction = engine.normal_chat_transaction_registry[first_id]

        assert engine.queue_typed_chat_message("replacement pending")["queued"] is True
        replacement_id = str(
            (engine.pending_loaded_input_turn or {}).get("normal_chat_transaction_id") or ""
        )
        assert replacement_id and replacement_id != first_id
        assert first_id not in engine.normal_chat_transaction_registry
        assert first_transaction["cancel_event"].is_set()
        assert first_transaction["status"] == "cancelled"
        for field in (
            "prepared_provider_request",
            "request_context",
            "provider_context",
            "relay_capture",
            "relay_snapshot",
            "relay_metadata",
            "accepted_turn",
        ):
            assert first_transaction[field] is None
    finally:
        _restore_harness(originals)


def test_pending_consume_and_replacement_have_one_ownership_winner() -> None:
    _runtime, _calls, originals = _install_harness(enabled=False)
    original_reconstruct = engine._reconstruct_input_turn
    consume_reconstructing = threading.Event()
    release_consume = threading.Event()
    replacement_reconstructed = threading.Event()
    replacement_done = threading.Event()
    consume_result = []
    try:
        engine.replace_chat_conversation_history([])
        engine.queue_typed_chat_message("owned by consumer")
        old_pending = dict(engine.pending_loaded_input_turn or {})
        old_id = old_pending["normal_chat_transaction_id"]
        old_transaction = engine.normal_chat_transaction_registry[old_id]
        replacement_turn = engine._begin_normal_chat_transaction(
            {"role": "user", "content": "owned by pending slot", "origin": "input"}
        )
        replacement_id = replacement_turn["normal_chat_transaction_id"]

        def blocking_reconstruct(turn):
            result = original_reconstruct(turn)
            transaction_id = str((turn or {}).get("normal_chat_transaction_id") or "")
            thread_name = threading.current_thread().name
            if transaction_id == old_id and thread_name == "pending-consumer":
                consume_reconstructing.set()
                assert release_consume.wait(timeout=3.0)
            elif transaction_id == replacement_id and thread_name == "pending-replacer":
                replacement_reconstructed.set()
            return result

        engine._reconstruct_input_turn = blocking_reconstruct

        consumer = threading.Thread(
            target=lambda: consume_result.append(engine._consume_pending_loaded_input_turn()),
            name="pending-consumer",
        )

        def replace_pending():
            engine._set_pending_loaded_input_turn(replacement_turn)
            replacement_done.set()

        replacer = threading.Thread(target=replace_pending, name="pending-replacer")
        consumer.start()
        assert consume_reconstructing.wait(timeout=3.0)
        replacer.start()
        assert replacement_reconstructed.wait(timeout=3.0)
        replacement_done.wait(timeout=0.5)
        release_consume.set()
        consumer.join(timeout=3.0)
        replacer.join(timeout=3.0)
        assert not consumer.is_alive() and not replacer.is_alive()
        assert consume_result and consume_result[0]["normal_chat_transaction_id"] == old_id
        assert (engine.pending_loaded_input_turn or {}).get(
            "normal_chat_transaction_id"
        ) == replacement_id
        assert engine.normal_chat_transaction_registry.get(old_id) is old_transaction
        assert not old_transaction["cancel_event"].is_set()
    finally:
        release_consume.set()
        engine._reconstruct_input_turn = original_reconstruct
        _restore_harness(originals)


def test_empty_synchronous_reply_releases_completed_transaction() -> None:
    runtime, _calls, originals = _install_harness(enabled=False, reply_text="")
    try:
        engine.replace_chat_conversation_history([])
        turn, request = _accepted_request("empty reply")
        transaction = engine._normal_chat_transaction_for_request(request)
        assert engine.chat_with_llm(request) == ""
        transaction_id = turn["normal_chat_transaction_id"]
        assert runtime.reply_calls
        assert transaction_id not in engine.normal_chat_transaction_registry
        assert transaction["prepared_provider_request"] is None
        assert transaction["request_context"] is None
        assert transaction["provider_context"] is None
        assert [
            claim["kind"] for claim in transaction["provider_dispatch_claims"]
        ] == ["completion"]
    finally:
        _restore_harness(originals)


def test_abandoned_image_transaction_releases_frozen_data_url() -> None:
    runtime, _calls, originals = _install_harness(enabled=False)
    harness_build = engine.build_llm_request
    unique_data_url = "data:image/png;base64,IDENTITY_RELAY_UNIQUE_FROZEN_PAYLOAD"
    try:
        engine.replace_chat_conversation_history([])

        def build_with_image(_request_context=None):
            return {
                "model": "live-model-must-not-win",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "inspect image"},
                            {
                                "type": "image_url",
                                "image_url": {"url": unique_data_url},
                            },
                        ],
                    }
                ],
                "max_tokens": 32,
            }, {}

        engine.build_llm_request = build_with_image
        turn = engine._begin_normal_chat_transaction(
            {"role": "user", "content": "image turn", "origin": "input"}
        )
        engine._set_pending_loaded_input_turn(turn)
        request = engine._freeze_normal_chat_request(turn)
        transaction = engine._ensure_normal_chat_transaction_ready(request)
        transaction_id = turn["normal_chat_transaction_id"]
        prepared_ref = weakref.ref(transaction["prepared_provider_request"])
        assert unique_data_url in repr(prepared_ref().params_copy())
        runtime.prepare_calls.clear()

        engine.replace_chat_conversation_history([])
        gc.collect()
        assert transaction_id not in engine.normal_chat_transaction_registry
        assert transaction["prepared_provider_request"] is None
        assert transaction["request_context"] is None
        assert unique_data_url not in repr(transaction)
        assert prepared_ref() is None
    finally:
        engine.build_llm_request = harness_build
        _restore_harness(originals)


def test_failed_stream_fallback_records_two_dispatch_claims() -> None:
    runtime, _calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("stream fallback")
        transaction = engine._ensure_normal_chat_transaction_ready(request)

        def failed_stream(prepared_request, *, timeout=None, cancel_token=None):
            runtime.stream_calls.append(prepared_request)
            raise RuntimeError("stream startup failed")

        runtime.stream_frozen = failed_stream
        state = engine.start_streamed_llm_reply(queue.Queue(), request_context=request)
        assert state.done.wait(timeout=3.0)
        assert state.full_text == "reply"
        assert len(runtime.stream_calls) == 1
        assert len(runtime.reply_calls) == 1
        claims = transaction["provider_dispatch_claims"]
        assert [claim["sequence"] for claim in claims] == [1, 2]
        assert [claim["kind"] for claim in claims] == ["stream", "completion"]
        assert claims[0]["request_id"] == claims[1]["request_id"]
    finally:
        _restore_harness(originals)


def test_empty_stream_fallback_retains_binding_for_terminal_owner() -> None:
    runtime, _calls, originals = _install_harness(enabled=False, reply_text="")
    try:
        engine.replace_chat_conversation_history([])
        turn, request = _accepted_request("empty stream fallback")
        transaction = engine._ensure_normal_chat_transaction_ready(request)

        def failed_stream(prepared_request, *, timeout=None, cancel_token=None):
            runtime.stream_calls.append(prepared_request)
            raise RuntimeError("stream startup failed")

        runtime.stream_frozen = failed_stream
        state = engine.start_streamed_llm_reply(queue.Queue(), request_context=request)
        assert state.done.wait(timeout=3.0)
        assert state.full_text == ""
        assert state.error == "stream startup failed"
        transaction_id = turn["normal_chat_transaction_id"]
        assert engine.normal_chat_transaction_registry.get(transaction_id) is transaction
        assert transaction["prepared_provider_request"] is not None
        assert [
            claim["kind"] for claim in transaction["provider_dispatch_claims"]
        ] == ["stream", "completion"]

        assistant_turn = engine._append_assistant_history_turn(
            "I'm having trouble thinking right now.",
            expected_session_generation=request["session_generation"],
            expected_turn_id=transaction_id,
        )
        assert assistant_turn is not None
        assert assistant_turn["content"] == "I'm having trouble thinking right now."
    finally:
        _restore_harness(originals)


def test_cancel_during_relay_capability_upgrade_does_not_restore_provider_context() -> None:
    runtime, _calls, originals = _install_harness(enabled=True)
    original_upgrade = runtime.upgrade_frozen_context_for_relay
    entered = threading.Event()
    release = threading.Event()
    try:
        engine.replace_chat_conversation_history([])

        def delayed_upgrade(context):
            upgraded = original_upgrade(context)
            entered.set()
            assert release.wait(timeout=3.0)
            return upgraded

        runtime.upgrade_frozen_context_for_relay = delayed_upgrade
        turn, request = _accepted_request("cancel capability publication")
        transaction = engine._normal_chat_transaction_for_request(request)
        errors = []

        def ensure():
            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=ensure, name="relay-capability-publish-race")
        worker.start()
        assert entered.wait(timeout=3.0)
        assert engine._cancel_normal_chat_request(request) is True
        release.set()
        worker.join(timeout=3.0)
        assert not worker.is_alive()
        assert errors and isinstance(errors[0], engine.NormalChatTurnBlocked)
        assert turn["normal_chat_transaction_id"] not in engine.normal_chat_transaction_registry
        assert transaction["provider_context"] is None
    finally:
        release.set()
        runtime.upgrade_frozen_context_for_relay = original_upgrade
        _restore_harness(originals)


def test_cancel_during_relay_snapshot_publication_does_not_restore_discarded_fields() -> None:
    _runtime, _calls, originals = _install_harness(enabled=True)
    original_metadata = engine._identity_relay_v2_metadata
    entered = threading.Event()
    release = threading.Event()
    try:
        engine.replace_chat_conversation_history([])

        def delayed_metadata(snapshot_payload):
            metadata = original_metadata(snapshot_payload)
            entered.set()
            assert release.wait(timeout=3.0)
            return metadata

        engine._identity_relay_v2_metadata = delayed_metadata
        turn, request = _accepted_request("cancel relay publication")
        transaction = engine._normal_chat_transaction_for_request(request)
        errors = []

        def ensure():
            try:
                engine._ensure_normal_chat_transaction_ready(request)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=ensure, name="relay-snapshot-publish-race")
        worker.start()
        assert entered.wait(timeout=3.0)
        assert engine._cancel_normal_chat_request(request) is True
        release.set()
        worker.join(timeout=3.0)
        assert not worker.is_alive()
        assert errors and isinstance(errors[0], engine.NormalChatTurnBlocked)
        assert turn["normal_chat_transaction_id"] not in engine.normal_chat_transaction_registry
        for field in (
            "provider_context",
            "relay_capture",
            "relay_snapshot",
            "relay_metadata",
            "accepted_turn",
        ):
            assert transaction[field] is None
    finally:
        release.set()
        engine._identity_relay_v2_metadata = original_metadata
        _restore_harness(originals)


def test_final_dispatch_rejects_non_transaction_prepared_request() -> None:
    runtime, _calls, originals = _install_harness(enabled=False)
    try:
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("request identity")
        transaction = engine._ensure_normal_chat_transaction_ready(request)
        rogue_request = FrozenRequest(
            runtime.context,
            [{"role": "user", "content": "rogue"}],
        )
        try:
            engine.chat_with_llm(request, prepared_request=rogue_request)
        except engine.NormalChatTurnBlocked:
            pass
        else:
            raise AssertionError("non-transaction prepared request reached provider")
        assert runtime.reply_calls == []
        assert transaction.get("provider_dispatch_claims") == []
    finally:
        _restore_harness(originals)


def test_frozen_blank_model_never_falls_back_to_live_state() -> None:
    runtime, calls, originals = _install_harness(enabled=False)
    original_model_name = engine.RUNTIME_CONFIG.get("model_name")
    original_collect = engine._collect_addon_chat_contexts
    prepare_models = []
    stream_models = []
    fallback_models = []
    try:
        engine.build_llm_request = originals[2]
        engine._collect_addon_chat_contexts = lambda _history, **_payload: []
        runtime.context.model_name = ""
        engine.RUNTIME_CONFIG["model_name"] = "live-before-acceptance"
        engine.replace_chat_conversation_history([])
        _turn, request = _accepted_request("blank frozen model")
        engine.RUNTIME_CONFIG["model_name"] = "live-after-acceptance"

        def prepare(context, params, additional_params=None):
            prepare_models.append(params.get("model"))
            prepared = FrozenRequest(
                context,
                params.get("messages") or (),
                int(params.get("max_tokens", 32) or 32),
            )
            prepared._params["model"] = params.get("model")
            runtime.prepare_calls.append(prepared)
            return prepared

        def failed_stream(prepared_request, *, timeout=None, cancel_token=None):
            stream_models.append(prepared_request.params_copy().get("model"))
            raise RuntimeError("stream startup failed")

        def fallback(prepared_request, *, timeout=None, cancel_token=None):
            fallback_models.append(prepared_request.params_copy().get("model"))
            runtime.reply_calls.append(prepared_request)
            return "blank model fallback"

        runtime.prepare_frozen_request = prepare
        runtime.stream_frozen = failed_stream
        runtime.complete_frozen = fallback
        transaction = engine._ensure_normal_chat_transaction_ready(request)
        state = engine.start_streamed_llm_reply(queue.Queue(), request_context=request)
        assert state.done.wait(timeout=3.0)

        capture_payload = next(
            payload
            for capability, payload, _thread_name in calls
            if capability == "identity_relay.capture_turn"
        )
        assert capture_payload["frozen_provider"]["model_name"] == ""
        assert prepare_models == [""]
        assert transaction["prepared_provider_request"].params_copy()["model"] == ""
        assert stream_models == [""]
        assert fallback_models == [""]
        assert state.full_text == "blank model fallback"
    finally:
        engine.RUNTIME_CONFIG["model_name"] = original_model_name
        engine._collect_addon_chat_contexts = original_collect
        _restore_harness(originals)


def test_loaded_reference_race_blocks_delete_before_commit() -> None:
    assert hasattr(engine, "_identity_relay_delete_transaction")
    original_history = None
    original_pending = None
    original_registry = None
    loader_holds_lock = threading.Event()
    release_loader = threading.Event()
    commit_calls = []
    deletion_result = []

    with engine.conversation_history_lock:
        original_history = list(engine.conversation_history)
        engine.conversation_history[:] = []
    with engine.normal_chat_transaction_lock:
        original_pending = engine.pending_loaded_input_turn
        original_registry = dict(engine.normal_chat_transaction_registry)
        engine.pending_loaded_input_turn = None
        engine.normal_chat_transaction_registry.clear()

    def load_reference():
        with engine.normal_chat_transaction_lock:
            loader_holds_lock.set()
            assert release_loader.wait(timeout=3.0)
            engine.normal_chat_transaction_registry["delete-race"] = {
                "relay_capture": Capture(True),
                "relay_snapshot": None,
                "accepted_turn": None,
            }

    def delete_reference():
        deletion_result.append(
            engine._identity_relay_delete_transaction(
                ARTIFACT_REF,
                lambda: commit_calls.append("committed") or "deleted",
            )
        )

    loader = threading.Thread(target=load_reference, name="relay-delete-loader-race")
    deleter = threading.Thread(target=delete_reference, name="relay-delete-commit-race")
    try:
        loader.start()
        assert loader_holds_lock.wait(timeout=3.0)
        deleter.start()
        release_loader.set()
        loader.join(timeout=3.0)
        deleter.join(timeout=3.0)
        assert not loader.is_alive()
        assert not deleter.is_alive()
        assert commit_calls == []
        assert deletion_result == [
            {
                "committed": False,
                "blocked_by": ("loaded_chat:active_transaction",),
                "result": None,
            }
        ]
    finally:
        release_loader.set()
        loader.join(timeout=3.0)
        deleter.join(timeout=3.0)
        with engine.conversation_history_lock:
            engine.conversation_history[:] = original_history
        with engine.normal_chat_transaction_lock:
            engine.pending_loaded_input_turn = original_pending
            engine.normal_chat_transaction_registry.clear()
            engine.normal_chat_transaction_registry.update(original_registry)


def main() -> int:
    test_relay_off_captures_once_then_does_zero_service_work()
    test_frozen_lmstudio_turn_prepares_selected_model_before_provider_work()
    test_relay_off_capture_copy_failure_is_non_blocking_but_on_fails_closed()
    test_capture_capability_exception_dispatches_only_for_confirmed_off_mode()
    test_unconnected_controller_handshake_dispatches_relay_free()
    test_confirmed_on_requires_matching_enabled_capture()
    test_invalid_mode_handshakes_block_before_capture_or_dispatch()
    test_missing_provider_locality_is_not_coerced_to_local()
    test_schema_v2_capture_exception_blocks_before_history_or_provider_prepare()
    test_relay_on_runs_v2_judge_pipeline_on_worker_with_frozen_model()
    test_identity_relay_judge_output_budget_scales_with_batch_size()
    test_actual_request_contains_accepted_turn_and_v2_projection()
    test_accepted_turn_freezes_persona_and_system_instructions()
    test_accepted_turn_freezes_all_structured_retrieval_signals()
    test_deterministic_v2_path_bypasses_judge()
    test_judge_failure_degrades_through_finalize_without_recapturing()
    test_active_finalize_failure_blocks_before_reply()
    test_relay_on_non_strict_and_capacity_overflow_fail_before_reply()
    test_exact_capacity_fit_is_accepted_without_truncating_relay()
    test_unknown_exact_capacity_warns_once_and_proceeds_for_any_locality()
    test_missing_frozen_execution_hook_fails_closed()
    test_concurrent_prepare_is_exactly_once_and_fallback_identity_is_stable()
    test_queued_turn_keeps_original_binding_without_partial_history()
    test_queued_image_turn_captures_at_acceptance_and_commits_after_prepare()
    test_queued_image_turn_prepare_failure_leaves_history_unchanged()
    test_queue_image_turn_legacy_append_callback_remains_compatible()
    test_reset_before_judge_cancels_projection_and_rejects_late_history()
    test_cancellation_after_judge_discards_finalize_and_history()
    test_load_during_prepare_cancels_stale_worker()
    test_loaded_ordinary_regeneration_recaptures_provider_without_relay()
    test_volatile_projection_is_not_exported_from_snapshot_registry()
    test_import_rejects_tampered_persisted_snapshot_hash()
    test_restart_regeneration_requires_matching_trusted_authorization()
    test_restart_regeneration_blocks_local_projection_for_remote_provider()
    test_restart_regeneration_upgrades_and_counts_exact_outbound_request()
    test_uncapped_prepared_request_uses_remaining_context_capacity()
    test_responses_prepared_request_exposes_exact_input_and_budget()
    test_restart_capacity_uses_registered_provider_and_production_counting()
    test_restart_regeneration_uses_authorized_persisted_projection()
    test_regeneration_copies_only_transaction_id_not_frozen_context()
    test_completed_regeneration_recaptures_current_provider_binding()
    test_detached_continuation_retains_frozen_binding_for_regeneration()
    test_history_trimming_prunes_obsolete_prepared_payloads()
    test_cancel_between_completion_readiness_and_dispatch_blocks_provider()
    test_reset_between_stream_readiness_and_dispatch_blocks_provider()
    test_cancel_after_judge_request_preparation_blocks_judge_dispatch()
    test_cancelled_worker_cannot_republish_ready_or_survive_pruning()
    test_replacing_pending_typed_turn_discards_previous_binding()
    test_pending_consume_and_replacement_have_one_ownership_winner()
    test_empty_synchronous_reply_releases_completed_transaction()
    test_abandoned_image_transaction_releases_frozen_data_url()
    test_failed_stream_fallback_records_two_dispatch_claims()
    test_empty_stream_fallback_retains_binding_for_terminal_owner()
    test_cancel_during_relay_capability_upgrade_does_not_restore_provider_context()
    test_cancel_during_relay_snapshot_publication_does_not_restore_discarded_fields()
    test_final_dispatch_rejects_non_transaction_prepared_request()
    test_frozen_blank_model_never_falls_back_to_live_state()
    test_loaded_reference_race_blocks_delete_before_commit()
    print("smoke_identity_relay_transaction: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
