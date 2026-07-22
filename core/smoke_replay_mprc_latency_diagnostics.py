"""Focused diagnostics contracts for replay latency with MPRC loaded."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != SCRIPT_DIR]
sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != str(ROOT)]
sys.path.insert(0, str(ROOT))


def test_trace_rows_include_high_resolution_clock_and_runtime_state() -> None:
    from core.tts_latency_diagnostics import TtsLatencyDiagnostics, runtime_diagnostic_fields

    snapshot = runtime_diagnostic_fields()
    assert int(snapshot.get("python_threads", 0)) >= 1

    with tempfile.TemporaryDirectory(prefix="nc-replay-mprc-trace-") as temp_dir:
        diagnostics = TtsLatencyDiagnostics(Path(temp_dir))
        diagnostics.record_event("runtime_probe", **snapshot)
        assert diagnostics.flush(timeout=1.0)
        diagnostics.close()

        trace_path = Path(temp_dir) / "runtime" / "logs" / "tts_addon_latency.jsonl"
        rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        assert rows and float(rows[-1].get("monotonic_ms", 0.0)) > 0.0
        assert int(rows[-1].get("python_threads", 0)) >= 1


def test_addons_receive_the_shared_latency_recorder() -> None:
    from core.addons.manager import AddonManager

    with tempfile.TemporaryDirectory(prefix="nc-replay-mprc-manager-") as temp_dir:
        manager = AddonManager(
            app_root=Path(temp_dir),
            llm_snapshot_getter=lambda: {},
            tts_snapshot_getter=lambda: {},
            avatar_snapshot_getter=lambda: {},
        )
        try:
            recorder = manager._host_services.get("diagnostics.tts_latency")
            assert callable(recorder)
            recorder("shared_recorder_probe", source="smoke")
            assert manager.flush_latency_diagnostics(timeout=1.0)
        finally:
            manager.close_latency_diagnostics()


def test_chatterbox_reports_lock_wait_separately_from_model_work() -> None:
    from addons.chatterbox_tts.service import ChatterboxTTSService

    events: list[tuple[str, dict[str, object]]] = []

    class _Context:
        @staticmethod
        def get_service(name, default=None):
            if name == "diagnostics.tts_latency":
                return lambda event, **fields: events.append((str(event), dict(fields)))
            return default

    class _Tokens:
        shape = (1, 321)

        @staticmethod
        def numel():
            return 321

    class _T3:
        @staticmethod
        def inference_turbo(*_args, **_kwargs):
            time.sleep(0.006)
            return _Tokens()

    class _S3:
        @staticmethod
        def inference(*_args, **_kwargs):
            time.sleep(0.007)
            return [0.0], None

    class _Model:
        def __init__(self):
            self.t3 = _T3()
            self.s3gen = _S3()

        def generate(self, _value, **_kwargs):
            self.t3.inference_turbo()
            self.s3gen.inference()
            return [0.0]

    service = ChatterboxTTSService(_Context())
    service._generation_request = lambda _kwargs: (_Model(), {})
    service._use_cloned_voice = lambda: True
    service._restore_builtin_conditionals = lambda _model: None

    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock() -> None:
        with service._tracked_lock("prepare_voice"):
            lock_held.set()
            release_lock.wait(1.0)

    holder = threading.Thread(target=hold_lock, name="nc-chatterbox-lock-holder", daemon=True)
    holder.start()
    assert lock_held.wait(1.0)

    result: dict[str, object] = {}

    def generate() -> None:
        result["value"] = service.generate(
            "Replay diagnostic probe",
            audio_prompt_path="Q:/voices/test_persona.wav",
        )

    caller = threading.Thread(target=generate, name="nc-replay-generator-probe", daemon=True)
    caller.start()
    time.sleep(0.05)
    release_lock.set()
    caller.join(timeout=1.0)
    holder.join(timeout=1.0)
    assert "value" in result

    by_name = {name: fields for name, fields in events}
    assert {
        "chatterbox_generate_requested",
        "chatterbox_lock_acquired",
        "chatterbox_model_start",
        "chatterbox_model_end",
        "chatterbox_t3_inference",
        "chatterbox_s3_inference",
    }.issubset(by_name)
    assert float(by_name["chatterbox_lock_acquired"].get("lock_wait_ms", 0.0)) >= 30.0
    assert float(by_name["chatterbox_model_end"].get("model_ms", 0.0)) >= 5.0
    assert float(by_name["chatterbox_t3_inference"].get("duration_ms", 0.0)) >= 3.0
    assert int(by_name["chatterbox_t3_inference"].get("token_count", 0)) == 321
    assert float(by_name["chatterbox_s3_inference"].get("duration_ms", 0.0)) >= 3.0
    assert by_name["chatterbox_generate_requested"].get("voice_file") == "test_persona.wav"
    assert by_name["chatterbox_model_start"].get("voice_file") == "test_persona.wav"
    assert "prepare_voice" in str(by_name["chatterbox_generate_requested"].get("observed_owner_thread", ""))
    operation_events = [fields for name, fields in events if name == "chatterbox_lock_operation_start"]
    assert operation_events and operation_events[-1].get("operation") == "prepare_voice"


def test_replay_pipeline_has_all_timing_boundaries() -> None:
    source = (ROOT / "engine.py").read_text(encoding="utf-8")
    required_events = {
        "replay_source_start",
        "replay_voice_route",
        "replay_lookahead_wait",
        "tts_generation_start",
        "tts_audio_file_saved",
        "tts_preprocess",
        "tts_chunk_playback_start",
    }
    missing = sorted(event for event in required_events if f'"{event}"' not in source)
    assert not missing, f"Missing replay diagnostic events: {', '.join(missing)}"


def test_mprc_initialization_records_before_and_after_runtime_state() -> None:
    source = (ROOT / "addons" / "multi_persona_roleplay" / "main.py").read_text(encoding="utf-8")
    assert '"mprc_initialize_start"' in source
    assert '"mprc_initialize_end"' in source
    assert "runtime_diagnostic_fields" in source


def test_disabled_mprc_normal_chat_hooks_never_acquire_state_lock() -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    probe = object.__new__(MultiPersonaRoleplayController)
    probe._state_lock = threading.RLock()
    probe._shutting_down = False
    probe.session = type("Session", (), {"enabled": False})()
    probe.mprc_play_isolated_active = lambda: False

    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock() -> None:
        with probe._state_lock:
            lock_held.set()
            release_lock.wait(1.0)

    holder = threading.Thread(target=hold_lock, name="nc-disabled-mprc-lock-holder", daemon=True)
    holder.start()
    assert lock_held.wait(1.0)

    capabilities = (
        "chat_context.collect",
        "roleplay.assistant_reply",
        "roleplay.audio_settings",
        "roleplay.play_audio_cues",
        "tts.audio_chunk_ready",
        "tts.segment_started",
        "tts.voice_route",
        "tts.voice_segments",
    )
    completed = {name: threading.Event() for name in capabilities}
    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}

    def invoke(name: str) -> None:
        try:
            results[name] = probe.invoke_capability_threadsafe(name, {})
        except BaseException as exc:
            errors[name] = exc
        finally:
            completed[name].set()

    callers = [threading.Thread(target=invoke, args=(name,), daemon=True) for name in capabilities]
    for caller in callers:
        caller.start()
    deadline = time.monotonic() + 0.20
    try:
        while time.monotonic() < deadline and not all(event.is_set() for event in completed.values()):
            time.sleep(0.005)
        blocked = [name for name, event in completed.items() if not event.is_set()]
        assert not blocked, f"Disabled MPRC hooks waited for _state_lock: {', '.join(blocked)}"
        assert not errors, f"Disabled MPRC hooks reached active handlers: {sorted(errors)}"
        assert all(results.get(name) is None for name in capabilities)
    finally:
        release_lock.set()
        holder.join(timeout=1.0)
        for caller in callers:
            caller.join(timeout=1.0)


def test_report_classifies_chatterbox_lock_contention() -> None:
    from core.replay_mprc_latency_report import summarize_latest_replay

    rows = [
        {
            "event": "mprc_initialize_start",
            "monotonic_ms": 5.0,
            "python_threads": 10,
            "torch_threads": 4,
            "cuda_reserved_mb": 100.0,
        },
        {
            "event": "mprc_initialize_end",
            "monotonic_ms": 10.0,
            "roleplay_enabled": False,
            "python_threads": 14,
            "torch_threads": 8,
            "cuda_reserved_mb": 500.0,
        },
        {"event": "tts_pipeline_start", "monotonic_ms": 100.0, "trace_id": "replay-1", "replay": True},
        {"event": "replay_source_start", "monotonic_ms": 101.0, "trace_id": "replay-1", "item_count": 2},
        {
            "event": "tts_generation_start",
            "monotonic_ms": 110.0,
            "trace_id": "replay-1",
            "sequence": 0,
            "replay_index": 1,
        },
        {
            "event": "chatterbox_generate_requested",
            "monotonic_ms": 111.0,
            "call_id": "call-1",
            "observed_owner_thread": "nc-mprc-tts:prepare_voice",
        },
        {
            "event": "chatterbox_lock_acquired",
            "monotonic_ms": 711.0,
            "call_id": "call-1",
            "lock_wait_ms": 600.0,
            "observed_owner_thread": "nc-mprc-tts:prepare_voice",
        },
        {"event": "chatterbox_model_start", "monotonic_ms": 712.0, "call_id": "call-1", "setup_ms": 1.0},
        {"event": "chatterbox_model_end", "monotonic_ms": 812.0, "call_id": "call-1", "model_ms": 100.0},
        {
            "event": "tts_generation",
            "monotonic_ms": 813.0,
            "trace_id": "replay-1",
            "sequence": 0,
            "duration_ms": 703.0,
        },
    ]

    summary = summarize_latest_replay(rows)
    assert summary["classification"] == "chatterbox_lock_contention"
    assert float(summary["max_lock_wait_ms"]) == 600.0
    assert summary["lock_owner"] == "nc-mprc-tts:prepare_voice"
    assert summary["mprc_roleplay_enabled"] is False
    assert summary["mprc_runtime_before"]["python_threads"] == 10
    assert summary["mprc_runtime_after"]["cuda_reserved_mb"] == 500.0


def test_report_classifies_t3_token_inference() -> None:
    from core.replay_mprc_latency_report import summarize_latest_replay

    rows = [
        {"event": "replay_source_start", "monotonic_ms": 100.0, "trace_id": "replay-2", "item_count": 1},
        {"event": "tts_generation_start", "monotonic_ms": 101.0, "trace_id": "replay-2", "sequence": 0},
        {"event": "chatterbox_generate_requested", "monotonic_ms": 102.0, "call_id": "call-2"},
        {"event": "chatterbox_lock_acquired", "monotonic_ms": 103.0, "call_id": "call-2", "lock_wait_ms": 1.0},
        {"event": "chatterbox_model_start", "monotonic_ms": 104.0, "call_id": "call-2", "setup_ms": 1.0},
        {"event": "chatterbox_t3_inference", "monotonic_ms": 5104.0, "call_id": "call-2", "duration_ms": 5000.0},
        {"event": "chatterbox_s3_inference", "monotonic_ms": 5204.0, "call_id": "call-2", "duration_ms": 100.0},
        {"event": "chatterbox_model_end", "monotonic_ms": 5304.0, "call_id": "call-2", "model_ms": 5200.0},
        {
            "event": "tts_generation",
            "monotonic_ms": 5305.0,
            "trace_id": "replay-2",
            "sequence": 0,
            "duration_ms": 5204.0,
        },
    ]

    summary = summarize_latest_replay(rows)
    assert summary["classification"] == "chatterbox_t3_inference"
    assert float(summary["max_t3_ms"]) == 5000.0


def main() -> None:
    test_trace_rows_include_high_resolution_clock_and_runtime_state()
    test_addons_receive_the_shared_latency_recorder()
    test_chatterbox_reports_lock_wait_separately_from_model_work()
    test_replay_pipeline_has_all_timing_boundaries()
    test_mprc_initialization_records_before_and_after_runtime_state()
    test_disabled_mprc_normal_chat_hooks_never_acquire_state_lock()
    test_report_classifies_chatterbox_lock_contention()
    test_report_classifies_t3_token_inference()
    print("Replay/MPRC latency diagnostic contracts passed.")


if __name__ == "__main__":
    main()
