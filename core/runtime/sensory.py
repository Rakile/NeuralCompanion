"""Lease-bound sensory capture, pure decisions, effects, and hidden cycles."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import hashlib
import json
import logging
from pathlib import Path
import re
import sys
import threading
import time
from types import MappingProxyType
import uuid

from core import chat_providers, sensory as sensory_core
from core.runtime.config import RuntimeConfigSnapshot
from core.runtime.contracts import CancellationToken, CommandResult, RuntimeFailure
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import WorkerHandle, WorkerSupervisor
from core.runtime.prompt_assembly import PromptRequest
from core.sensory import SensoryRecord, SensoryRegistry
from core.sensory_source_selection import enabled_source_ids, normalize_source_tokens
from core.runtime.supervisor_actions import resolve_supervisor_action
from core.screen_review import screen_review_contributor, screen_images, resolve_screen_matches, clipboard_image_is_new
from core.communication_trace import record_to, lease_correlation, correlation_scope


ConfigSnapshot = Callable[[], RuntimeConfigSnapshot]
LeaseFactory = Callable[[], WorkLease]
LeaseCheck = Callable[[WorkLease], bool]
EffectAdmission = Callable[[WorkLease], object | None]
EffectRelease = Callable[[object], None]


_INTERNAL_LOGGER = logging.getLogger(__name__)


def _watch_policy_record(record):
    """Watch-owned frames (evaluated or paused) never become a second image review."""
    if record.get('source') == 'companion_orb_target' and 'orb_watch_evaluated' in (record.get('metadata') or {}):
        return {k:v for k,v in record.items() if k not in {'image_path','image','image_url','image_tiles'}}
    return record


def _report_diagnostic_callback_failure(
    callback_name: str,
    exc: BaseException,
) -> None:
    message = (
        f"Sensory {callback_name} callback failed: "
        f"{type(exc).__name__}: {exc}"
    )
    try:
        _INTERNAL_LOGGER.error(
            "%s",
            message,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return
    except BaseException:
        pass
    try:
        sys.stderr.write(f"{message}\n")
        sys.stderr.flush()
    except BaseException:
        pass


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return [_thaw(item) for item in value]
    return value


def _freeze_mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return _freeze(dict(value or {}))


def _copy_mapping(value: Mapping[str, object] | None) -> dict[str, object]:
    copied = _thaw(_freeze_mapping(value))
    return dict(copied) if isinstance(copied, Mapping) else {}


@dataclass(frozen=True, slots=True)
class SensoryEffect:
    """One explicit effect emitted by pure sensory reduction."""

    kind: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", str(self.kind or "").strip())
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))


@dataclass(frozen=True, slots=True)
class SensorySnapshot:
    """Immutable captures and cycle identity used by one provider decision."""

    records: tuple[SensoryRecord, ...]
    cycle_id: str
    lease: WorkLease
    config_revision: int
    config_values: Mapping[str, object] = field(default_factory=dict, repr=False)
    retained_history: tuple[Mapping[str, object], ...] = field(
        default_factory=tuple,
        repr=False,
    )
    state_values: Mapping[str, object] = field(default_factory=dict, repr=False)
    priority: bool = False
    priority_source: str = ""
    trace_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "cycle_id", str(self.cycle_id or ""))
        object.__setattr__(self, "config_revision", int(self.config_revision))
        object.__setattr__(
            self,
            "config_values",
            _freeze_mapping(self.config_values),
        )
        object.__setattr__(
            self,
            "retained_history",
            tuple(_freeze_mapping(item) for item in self.retained_history),
        )
        object.__setattr__(self, "state_values", _freeze_mapping(self.state_values))
        object.__setattr__(self, "priority", bool(self.priority))
        object.__setattr__(
            self,
            "priority_source",
            str(self.priority_source or ""),
        )
        object.__setattr__(self, "trace_id", str(self.trace_id or ""))

    def mappings(self) -> tuple[dict[str, object], ...]:
        return tuple(record.to_mapping() for record in self.records)

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(record.source for record in self.records)


@dataclass(frozen=True, slots=True)
class SensoryDecision:
    """Pure normalized model output plus its typed effect plan."""

    cycle_id: str
    lease: WorkLease
    config_revision: int
    effects: tuple[SensoryEffect, ...]
    model_result: Mapping[str, object] = field(default_factory=dict, repr=False)
    meaningful: bool = False
    config_values: Mapping[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cycle_id", str(self.cycle_id or ""))
        object.__setattr__(self, "config_revision", int(self.config_revision))
        object.__setattr__(self, "effects", tuple(self.effects))
        object.__setattr__(
            self,
            "model_result",
            _freeze_mapping(self.model_result),
        )
        object.__setattr__(self, "meaningful", bool(self.meaningful))
        object.__setattr__(self, "config_values", _freeze_mapping(self.config_values))


@dataclass(frozen=True, slots=True)
class SensoryCapabilities:
    """Explicit engine/addon targets; no engine or Qt object is exposed."""

    orb_target: Callable[[Mapping[str, object], WorkLease], object] | None = None
    orb_focus: Callable[[Mapping[str, object], WorkLease], object] | None = None
    avatar_emotion: Callable[[str, WorkLease], object] | None = None
    proactive: Callable[[Mapping[str, object], WorkLease], object] | None = None
    visual: Callable[
        [Mapping[str, object], WorkLease, RuntimeConfigSnapshot],
        object,
    ] | None = None
    publish_event: Callable[[str, Mapping[str, object], WorkLease], object] | None = None
    request_chat_rebuild: Callable[[WorkLease], object] | None = None
    log: Callable[[str], object] | None = None
    debug: Callable[[str, Mapping[str, object]], object] | None = None
    loop_ready: Callable[[], bool] | None = None
    blocked_reasons: Callable[[bool], Sequence[str]] | None = None
    build_messages: Callable[
        [
            Sequence[Mapping[str, object]],
            bool | None,
            bool,
            RuntimeConfigSnapshot,
            Sequence[Mapping[str, object]],
        ],
        Sequence[Mapping[str, object]],
    ] | None = None
    model_supports_images: Callable[[RuntimeConfigSnapshot], bool] | None = None
    emotion_allowed: Callable[[str], bool] | None = None
    visual_allowed: Callable[[RuntimeConfigSnapshot], bool] | None = None
    proactive_ready: Callable[[], bool] | None = None
    buddy_contextual_payload: Callable[[Mapping[str, object]], object] | None = None
    output_directory: Path | str | None = None
    auto_start_hidden_loop: bool = False


@dataclass(frozen=True, slots=True)
class SensoryStateSnapshot:
    cache: Mapping[str, Mapping[str, object]]
    hidden_history: tuple[Mapping[str, object], ...]
    pingpong: Mapping[str, object]
    hidden_actions: Mapping[str, object]
    running: bool
    active_cycle_id: str
    hidden_loop_id: str


@dataclass(frozen=True, slots=True)
class _CycleBinding:
    cycle_id: str
    lease: WorkLease
    config_revision: int
    config_values: Mapping[str, object]
    retained_history: tuple[Mapping[str, object], ...]
    state_values: Mapping[str, object]
    provider_selection: object | None = field(compare=False, repr=False)
    priority: bool
    priority_source: str
    trace_id: str
    loop_id: str
    token: CancellationToken = field(compare=False, repr=False)


class SensoryCycle:
    """One immutable completion authority returned by ``begin_cycle``."""

    def __init__(self, service: "SensoryService", binding: _CycleBinding) -> None:
        self._service = service
        self._binding = binding

    @property
    def cycle_id(self) -> str:
        return self._binding.cycle_id

    @property
    def lease(self) -> WorkLease:
        return self._binding.lease

    def snapshot(
        self,
        records: Sequence[SensoryRecord | Mapping[str, object]],
    ) -> SensorySnapshot:
        normalized = tuple(
            record
            if isinstance(record, SensoryRecord)
            else SensoryRecord.from_mapping(dict(record))
            for record in records
        )
        binding = self._binding
        return SensorySnapshot(
            records=normalized,
            cycle_id=binding.cycle_id,
            lease=binding.lease,
            config_revision=binding.config_revision,
            config_values=binding.config_values,
            retained_history=binding.retained_history,
            state_values=binding.state_values,
            priority=binding.priority,
            priority_source=binding.priority_source,
            trace_id=binding.trace_id,
        )

    def complete(
        self,
        model_result: Mapping[str, object] | str,
    ) -> CommandResult[tuple[SensoryEffect, ...]]:
        if not self._service._cycle_is_current(self._binding):
            return _stale_cycle()
        decision = self._service.reduce(self.snapshot(()), model_result)
        return self._service.apply(decision, self._binding.lease)


class SensoryService:
    """Own sensory state, cycle admission, reduction, and hidden workers."""

    name = "sensory"

    def __init__(
        self,
        *,
        workers: WorkerSupervisor,
        providers: object | None,
        config_snapshot: ConfigSnapshot,
        lease_factory: LeaseFactory,
        lease_is_current: LeaseCheck,
        registry: SensoryRegistry | None = None,
        capabilities: SensoryCapabilities | None = None,
        admit_effect: EffectAdmission | None = None,
        release_effect: EffectRelease | None = None,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._workers = workers
        self._providers = providers
        self._config_snapshot = config_snapshot
        self._lease_factory = lease_factory
        self._lease_is_current = lease_is_current
        self._registry = registry or sensory_core.get_registry()
        self._capabilities = capabilities or SensoryCapabilities()
        self._admit_effect = admit_effect
        self._release_effect = release_effect
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._lock = threading.Lock()
        self._running = False
        self._active_cycle: _CycleBinding | None = None
        self._hidden_loop_id = ""
        self._hidden_loop_handle: WorkerHandle | None = None
        self._hidden_loop_replacement_id = ""
        self._hidden_loop_replacement_lease: WorkLease | None = None
        self._hidden_loop_pending_replacement_id = ""
        self._hidden_loop_pending_replacement_lease: WorkLease | None = None
        self._hidden_loop_replacement_condition = threading.Condition(self._lock)
        self._effect_execution_id = ""
        self._effect_handle: WorkerHandle | None = None
        self._feedback_cache: dict[str, dict[str, object]] = {}
        self._hidden_history: list[dict[str, object]] = []
        self._pingpong_state = _default_pingpong_state()
        self._hidden_action_state = _default_hidden_action_state()
        self._image_model_key = None
        self._image_retry_generation = 0
        self._image_fallback: dict[str, object] = {}
        self._image_notice: dict[str, object] = {}
        self._image_notice_sequence = 0

    @property
    def workers(self) -> WorkerSupervisor:
        return self._workers

    def start(self) -> CommandResult[None]:
        with self._lock:
            if self._running:
                return CommandResult(True)
            if self._hidden_loop_replacement_id:
                return _failure(
                    "sensory_worker_restart_busy",
                    "Sensory hidden-loop retirement is still in progress",
                )
            if self._effect_execution_id:
                handle = self._effect_handle
                if handle is None or handle.is_alive():
                    return _failure(
                        "sensory_effect_restart_busy",
                        "Sensory effect execution is still in progress",
                    )
                self._effect_execution_id = ""
                self._effect_handle = None
            self._running = True
        if self._capabilities.auto_start_hidden_loop:
            started = self.start_hidden_loop(self._lease_factory())
            if not started.accepted:
                with self._lock:
                    self._running = False
                return CommandResult(False, failure=started.failure)
        return CommandResult(True)

    def stop(self) -> CommandResult[None]:
        with self._hidden_loop_replacement_condition:
            self._running = False
            self._hidden_loop_pending_replacement_id = ""
            self._hidden_loop_pending_replacement_lease = None
            active_cycle = self._active_cycle
            self._active_cycle = None
            self._hidden_loop_id = ""
            loop_handle = self._hidden_loop_handle
            effect_handle = self._effect_handle
            self._hidden_loop_replacement_condition.notify_all()
        if active_cycle is not None:
            active_cycle.token.cancel("sensory_runtime_stop")
        failures: list[CommandResult[None]] = []
        if effect_handle is not None:
            retired = self._retire_effect_handle(
                effect_handle,
                "sensory_runtime_stop",
            )
            if retired.accepted:
                with self._lock:
                    if self._effect_handle is effect_handle:
                        self._effect_handle = None
                        self._effect_execution_id = ""
            else:
                failures.append(retired)
                if retired.failure is not None:
                    self._log(retired.failure.message)
        if loop_handle is not None:
            retired = self._retire_hidden_loop_handle(
                loop_handle,
                "sensory_runtime_stop",
            )
            if not retired.accepted:
                failures.append(retired)
                if retired.failure is not None:
                    self._log(retired.failure.message)
            else:
                with self._lock:
                    if self._hidden_loop_handle is loop_handle:
                        self._hidden_loop_handle = None
        if failures:
            return failures[0]
        return CommandResult(True)

    def begin_cycle(
        self,
        lease: WorkLease,
        config: RuntimeConfigSnapshot | None = None,
        *,
        priority: bool = False,
        priority_source: str = "",
        trace_id: str = "",
        loop_id: str = "",
        capture_provider: bool = False,
    ) -> CommandResult[SensoryCycle]:
        snapshot = config or self._config_snapshot()
        self._sync_image_model()
        if not isinstance(snapshot, RuntimeConfigSnapshot):
            return _failure(
                "sensory_config_required",
                "Sensory cycles require RuntimeConfigSnapshot",
            )
        if not self._lease_is_current(lease):
            return _stale_lease()
        current_config = self._config_snapshot()
        if current_config.revision != snapshot.revision:
            return _failure(
                "sensory_stale_config",
                "Sensory cycle configuration is stale",
            )
        provider_selection = None
        capture_selection = getattr(self._providers, "capture_selection", None)
        if capture_provider and callable(capture_selection):
            try:
                provider_selection = capture_selection(snapshot)
            except BaseException as exc:
                return _failure(
                    "sensory_provider_selection",
                    str(exc) or type(exc).__name__,
                    exc,
                )
        if (
            not self._lease_is_current(lease)
            or self._config_snapshot().revision != snapshot.revision
        ):
            return _stale_cycle()
        with self._lock:
            if not self._running:
                return _failure("sensory_stopped", "Sensory service is not running")
            normalized_loop_id = str(loop_id or "")
            if normalized_loop_id and normalized_loop_id != self._hidden_loop_id:
                return _stale_cycle()
            binding = _CycleBinding(
                cycle_id=uuid.uuid4().hex,
                lease=lease,
                config_revision=snapshot.revision,
                config_values=_freeze_mapping(snapshot.values),
                retained_history=tuple(
                    _freeze_mapping(item) for item in self._hidden_history
                ),
                state_values=_freeze_mapping(self._hidden_action_state),
                provider_selection=provider_selection,
                priority=bool(priority),
                priority_source=str(priority_source or ""),
                trace_id=str(trace_id or ""),
                loop_id=normalized_loop_id,
                token=CancellationToken(),
            )
            previous = self._active_cycle
            self._active_cycle = binding
        if previous is not None:
            previous.token.cancel("sensory_cycle_superseded")
        return CommandResult(True, SensoryCycle(self, binding))

    def capture(
        self,
        lease: WorkLease,
        config: RuntimeConfigSnapshot,
        *,
        cycle: SensoryCycle | None = None,
        force: bool = False,
        selected_sources: Sequence[str] | None = None,
    ) -> CommandResult[SensorySnapshot]:
        active_cycle = cycle
        if active_cycle is None:
            started = self.begin_cycle(lease, config)
            if not started.accepted or started.value is None:
                return CommandResult(False, failure=started.failure)
            active_cycle = started.value
        binding = active_cycle._binding
        if binding.lease != lease or binding.config_revision != config.revision:
            return _stale_cycle()
        if not self._cycle_is_current(binding):
            return _stale_cycle()

        providers = tuple(self._registry.list_providers())
        configured_sources: object = (
            tuple(selected_sources)
            if selected_sources is not None
            else config.values.get("sensory_feedback_source", "off")
        )
        sources = enabled_source_ids(
            configured_sources,
            (provider.id for provider in providers),
        )
        if "companion_orb_target" in sources:
            sources = tuple(
                sorted(
                    sources,
                    key=lambda source: 0 if source == "companion_orb_target" else 1,
                )
            )
        interval = _feedback_interval(config.values)
        now = self._wall_clock()
        records: list[SensoryRecord] = []

        for source in sources:
            if not self._cycle_is_current(binding):
                return _stale_cycle()
            with self._lock:
                cached = dict(self._feedback_cache.get(source) or {})
            cached_at = float(cached.get("captured_at", 0.0) or 0.0)
            if (
                not force
                and _snapshot_has_payload(cached)
                and (now - cached_at) < interval
            ):
                record = SensoryRecord.from_mapping(cached)
            else:
                try:
                    record = self._registry.capture_record(
                        source,
                        {
                            "output_dir": str(
                                self._capabilities.output_directory or ""
                            ),
                            "runtime_config": _thaw(binding.config_values),
                            "timestamp": now,
                            "selected_sources": list(sources),
                        },
                    )
                except BaseException as exc:
                    self._log(f"Sensory capture failed for {source}: {exc}")
                    record = None
                if not self._cycle_is_current(binding):
                    return _stale_cycle()
                if record is not None:
                    captured = record.to_mapping()
                    metadata = captured.get("metadata") or {}
                    if (source == "companion_orb_target"
                            and metadata.get("orb_watch_evaluated") is False
                            and not (metadata.get("orb_watch") or {}).get("eligible")):
                        # Waiting is intentional, not a failed capture: never replay the last frame.
                        with self._lock:
                            if self._active_cycle is binding:
                                self._feedback_cache.pop(source, None)
                        continue
                    captured.setdefault("captured_at", now)
                    record = SensoryRecord.from_mapping(captured)
                    if _snapshot_has_payload(captured):
                        with self._lock:
                            if self._active_cycle is binding:
                                self._feedback_cache[source] = dict(captured)
                    else:
                        record = None
                if record is None and _snapshot_can_reuse(cached):
                    record = SensoryRecord.from_mapping(cached)
            if record is not None and _snapshot_has_payload(record.to_mapping()):
                records.append(record)
                if _manual_orb_record(record):
                    records = [record]
                    break

        if not self._cycle_is_current(binding):
            return _stale_cycle()
        with self._lock:
            if self._active_cycle is not binding:
                return _stale_cycle()
            stale_sources = set(self._feedback_cache).difference(sources)
            for source in stale_sources:
                self._feedback_cache.pop(source, None)
        return CommandResult(True, active_cycle.snapshot(tuple(records)))

    def reduce(
        self,
        snapshot: SensorySnapshot,
        model_result: Mapping[str, object] | str,
    ) -> SensoryDecision:
        """Normalize provider output into effects without mutating runtime state."""

        result = _coerce_model_result(model_result)
        compact = screen_review_contributor(self._registry, snapshot.sources, snapshot.config_values)
        if compact is not None:
            return self._reduce_screen_review(snapshot, result, compact)
        explicit_orb_target = result.get("orb_target")
        if isinstance(explicit_orb_target, Mapping):
            effects = (SensoryEffect("orb_target", explicit_orb_target),)
            return SensoryDecision(
                snapshot.cycle_id,
                snapshot.lease,
                snapshot.config_revision,
                effects,
                result,
                meaningful=True,
                config_values=snapshot.config_values,
            )

        emotion = _clean_text(result.get("emotion"), 40, lower=True)
        emotion_allowed = self._capabilities.emotion_allowed
        if emotion and emotion_allowed is not None and not emotion_allowed(emotion):
            emotion = ""
        attention = _clean_text(result.get("attention"), 80, lower=True)
        summary = _clean_text(result.get("summary"), 220)
        proactive_candidate = _clean_text(
            result.get("proactive_candidate"),
            4000,
        )
        visual_candidate = _clean_text(result.get("visual_candidate"), 220)
        focus_bounds = _focus_bounds(result.get("focus_bounds"))
        focus_label = _clean_text(result.get("focus_label"), 80)
        focus_text = _clean_text(result.get("focus_text"), 180)
        tags = _unique_texts(result.get("tags"), 80)
        should_speak = _boolish(result.get("should_speak"))
        should_generate_image = _boolish(result.get("should_generate_image"))
        keep = _boolish(result.get("keep"))
        source = ",".join(snapshot.sources) or "sensory"
        config = RuntimeConfigSnapshot(
            snapshot.config_revision,
            snapshot.config_values,
        )
        behavior_active = _behavior_prompt_active(
            self._registry,
            snapshot.sources,
            snapshot.records,
        )
        supervisor = resolve_supervisor_action(
            self._registry, tuple(record.source for record in snapshot.records), tags,
            snapshot.state_values.get('supervisor_progress', {}), summary,
        )
        tags = supervisor['tags']
        action = supervisor['action']
        if should_speak and not proactive_candidate:
            proactive_candidate = _derive_proactive_candidate(
                summary,
                attention,
                emotion,
            )

        manual_bounds, manual_label, manual_text = _manual_orb_focus(
            snapshot.records
        )
        if manual_bounds and not action and not supervisor['candidate_source']:
            proactive_candidate = _sanitize_manual_candidate(proactive_candidate)
            if summary:
                summary = _sanitize_manual_candidate(summary, fallback=False)
            if focus_text:
                focus_text = _sanitize_manual_candidate(focus_text)
            if should_speak and not proactive_candidate:
                should_speak = False
            if (
                should_speak
                or proactive_candidate
                or focus_text
                or focus_label
            ) and (
                not focus_bounds
                or not _bounds_center_inside(focus_bounds, manual_bounds)
            ):
                focus_bounds = manual_bounds
                focus_label = focus_label or manual_label
                focus_text = (
                    focus_text
                    or manual_text
                    or proactive_candidate
                    or summary
                    or attention
                )
        orb_policy = _orb_supervisor_policy(
            self._registry,
            snapshot.sources,
            snapshot.records,
            summary=summary,
            attention=attention,
            proactive_candidate=proactive_candidate,
            focus_label=focus_label,
            focus_text=focus_text,
            tags=tags,
        )
        tags = tuple(orb_policy["tags"])
        if supervisor['managed'] and (action or not (
                supervisor['candidate_source'] or orb_policy['matched'])):
            should_speak = bool(action and supervisor['due'])
            proactive_candidate = action['action'] if should_speak else ''
            if action and action['emotion'] not in ('', 'Auto'):
                requested_emotion = action['emotion']
                if emotion_allowed is None or emotion_allowed(requested_emotion):
                    emotion = requested_emotion
        # A source-specific rule must not veto another source's selected Action.
        orb_applies = orb_policy['active'] and not action and not supervisor['candidate_source']
        if not action and orb_policy['matched'] and should_speak:
            rule = orb_policy['behavior'] or {}
            if str(rule.get('action', '')).strip():
                action = {key: str(rule.get(key, '') or '') for key in
                          ('id', 'trigger', 'action', 'strictness', 'emotion')}
                action.update(source='companion_orb_target', **orb_policy['persona'])
                proactive_candidate = action['action']
                if action['emotion'] not in ('', 'Auto'):
                    if emotion_allowed is None or emotion_allowed(action['emotion']):
                        emotion = action['emotion']
        orb_new_meaningful = False
        orb_diagnostic = ""
        orb_diagnostic_event = ""
        if orb_applies:
            if (should_speak or proactive_candidate) and not orb_policy["matched"]:
                if orb_policy["model_match"] and not orb_policy["trigger_matched"]:
                    selected_ids = ", ".join(
                        str(item) for item in orb_policy["selected_rule_ids"]
                    )
                    orb_diagnostic_event = "orb_rule_rejected"
                    orb_diagnostic = (
                        "[Sensory/Orb] Rule rejected: the hidden model signaled a match "
                        "without selecting an active rule ID "
                        f"({selected_ids or 'no orb_rule tag'})."
                    )
                should_speak = False
                proactive_candidate = ""
            if (
                (should_speak or proactive_candidate)
                and orb_policy["repeat_mode"] == "Meaningful change only"
            ):
                last_key = str(
                    snapshot.state_values.get(
                        "last_orb_supervisor_evidence_key",
                        "",
                    )
                    or ""
                )
                last_fingerprint = str(
                    snapshot.state_values.get(
                        "last_orb_supervisor_visual_fingerprint",
                        "",
                    )
                    or ""
                )
                same_evidence = bool(
                    orb_policy["evidence_key"]
                    and orb_policy["evidence_key"] == last_key
                    and _visual_fingerprints_similar(
                        str(orb_policy["visual_fingerprint"] or ""),
                        last_fingerprint,
                    )
                )
                if same_evidence:
                    orb_diagnostic_event = "orb_rule_suppressed_unchanged"
                    orb_diagnostic = (
                        "[Sensory/Orb] Rule suppressed: Meaningful change only found "
                        "the same target, OCR text, and visual fingerprint."
                    )
                    should_speak = False
                    proactive_candidate = ""
                else:
                    orb_new_meaningful = True

        screen_policy = _screen_supervisor_policy(
            self._registry,
            () if action or (supervisor['managed'] and not supervisor['candidate_source'])
            or supervisor['candidate_source'] not in ('', 'screen') else snapshot.sources,
            summary=summary,
            attention=attention,
            proactive_candidate=proactive_candidate,
            tags=tags,
        )
        tags = tuple(screen_policy["tags"])
        screen_subject = str(screen_policy["subject"] or "")
        screen_repeat_key = str(screen_policy["repeat_key"] or "")
        screen_repeat_mode = str(screen_policy["repeat_mode"] or "")
        screen_new_meaningful = False
        screen_allow_same_subject_repeat = screen_repeat_mode == "Every Nth match"
        if screen_policy["active"]:
            if (should_speak or proactive_candidate) and not screen_policy["matched"]:
                proactive_candidate = ""
                should_speak = False
            if (
                not should_speak
                and not proactive_candidate
                and screen_policy["matched"]
                and screen_policy["token_matched"]
                and screen_policy["behavior"]
            ):
                proactive_candidate = _derive_proactive_candidate(
                    summary,
                    attention,
                    emotion,
                )
                should_speak = bool(proactive_candidate)
            if should_speak or proactive_candidate:
                state = snapshot.state_values
                if screen_repeat_mode == "Meaningful change only" and screen_repeat_key:
                    last_key = str(
                        state.get("last_screen_supervisor_meaningful_key", "") or ""
                    )
                    last_subject = str(
                        state.get("last_screen_supervisor_meaningful_subject", "")
                        or ""
                    )
                    last_trigger = str(
                        state.get("last_screen_supervisor_meaningful_trigger", "")
                        or ""
                    )
                    trigger = _canonical_text(screen_policy["trigger"])
                    same_subject = bool(
                        trigger == last_trigger
                        and _subject_keys_similar(screen_subject, last_subject)
                    )
                    if screen_repeat_key == last_key or same_subject:
                        proactive_candidate = ""
                        should_speak = False
                    else:
                        screen_new_meaningful = True
            if (
                should_speak
                and proactive_candidate
                and screen_subject
                and not screen_allow_same_subject_repeat
                and screen_subject
                == str(
                    snapshot.state_values.get(
                        "last_screen_subject_comment_key",
                        "",
                    )
                    or ""
                )
            ):
                proactive_candidate = ""
                should_speak = False

        if (
            should_speak
            and proactive_candidate
            and not action
            and not supervisor['candidate_source']
            and not screen_new_meaningful
            and _candidate_reuses_stale_history(
                proactive_candidate,
                summary,
                snapshot.retained_history,
            )
        ):
            proactive_candidate = ""
            should_speak = False
        candidate_source = str((action or {}).get('source') or supervisor['candidate_source'])
        if candidate_source in ('', 'companion_orb_target') and _orb_suppresses_proactive(snapshot.records):
            should_speak = False
            proactive_candidate = ''
        if (should_speak or proactive_candidate) and candidate_source in ('', 'spotify_sense') and not _spotify_action_allowed(
            snapshot.records
        ):
            should_speak = False
            proactive_candidate = ""
        if (should_speak or proactive_candidate) and not behavior_active:
            should_speak = False
            proactive_candidate = ""

        if should_generate_image and not visual_candidate:
            visual_candidate = _derive_visual_candidate(
                summary,
                attention,
                emotion,
            )
        if (should_generate_image or visual_candidate) and not behavior_active:
            should_generate_image = False
            visual_candidate = ""
        if "companion_orb_target" in snapshot.sources:
            should_generate_image = False
            visual_candidate = ""
        if (screen_policy["active"] or candidate_source == 'screen') and should_generate_image:
            should_generate_image = False
            visual_candidate = ""
        meaningful = bool(
            emotion
            or attention
            or summary
            or proactive_candidate
            or visual_candidate
            or focus_bounds
            or focus_label
            or focus_text
            or should_speak
            or should_generate_image
            or tags
        )
        normalized = {
            "source": candidate_source or source,
            "snapshots": snapshot.mappings(),
            "keep": keep,
            "emotion": emotion,
            "attention": attention,
            "summary": summary,
            "proactive_candidate": proactive_candidate,
            "visual_candidate": visual_candidate,
            "should_speak": should_speak,
            "should_generate_image": should_generate_image,
            "focus_bounds": focus_bounds,
            "focus_label": focus_label,
            "focus_text": focus_text,
            "tags": tags,
            "meaningful": meaningful,
            "supervisor_progress": supervisor['progress'],
        }
        if action:
            normalized['supervisor_action'] = action
        if not _manual_orb_focus(snapshot.records)[0]:
            selected_source = str((action or {}).get('source') or candidate_source or source)
            if selected_source == 'companion_orb_target' or (not action and orb_applies):
                watch = next(((record.payload.get('metadata') or {}).get('orb_watch') for record in snapshot.records
                    if record.source == 'companion_orb_target' and 'orb_watch' in (record.payload.get('metadata') or {})), None)
                if watch is not None:
                    normalized['orb_watch'] = _thaw(watch)
                    normalized['source'] = 'companion_orb_target'
                    if not self.orb_watch_candidate_is_current(normalized):
                        should_speak = False
                        proactive_candidate = ''
                        focus_bounds, focus_text = (), ''
                        normalized.update(should_speak=False, proactive_candidate='', focus_bounds=(), focus_text='')
        effects: list[SensoryEffect] = [
            SensoryEffect(
                "publish_event",
                {"name": "sensory.hidden_pong.parsed", "payload": normalized},
            )
        ]
        if bool(snapshot.config_values.get("companion_orb_debug_enabled", False)):
            if not orb_diagnostic and orb_policy["active"] and orb_policy["matched"]:
                orb_diagnostic_event = "orb_rule_matched"
                orb_diagnostic = (
                    "[Sensory/Orb] Rule matched: "
                    f"trigger={orb_policy['trigger']!r}, "
                    f"repeat={orb_policy['repeat_mode'] or 'model controlled'}."
                )
            if orb_diagnostic:
                effects.append(
                    SensoryEffect("log", {"message": orb_diagnostic})
                )
                effects.append(
                    SensoryEffect(
                        "debug",
                        {
                            "event": orb_diagnostic_event or "orb_rule_decision",
                            "fields": {
                                "message": orb_diagnostic,
                                "trigger": orb_policy["trigger"],
                                "trigger_terms": orb_policy["trigger_terms"],
                                "selected_rule_ids": orb_policy[
                                    "selected_rule_ids"
                                ],
                                "model_match": orb_policy["model_match"],
                                "trigger_matched": orb_policy["trigger_matched"],
                                "repeat_mode": orb_policy["repeat_mode"],
                                "focus_label": focus_label,
                                "focus_text": focus_text,
                                "evidence_key": orb_policy["evidence_key"],
                                "visual_fingerprint": orb_policy[
                                    "visual_fingerprint"
                                ],
                            },
                        },
                    )
                )
        if focus_bounds or focus_text:
            effects.append(SensoryEffect("orb_focus", normalized))
        if emotion:
            effects.append(SensoryEffect("avatar_emotion", {"emotion": emotion}))
        effects.append(SensoryEffect("state_update", normalized))
        if keep and meaningful:
            effects.append(SensoryEffect("retain_history", normalized))
        if (
            should_speak
            and proactive_candidate
            and bool(
                snapshot.config_values.get(
                    "sensory_allow_hidden_proactive_speech",
                    False,
                )
            )
        ):
            proactive_payload = dict(normalized)
            proactive_payload["candidate"] = proactive_candidate
            proactive_payload["focus_duration_seconds"] = 14.0
            proactive_payload["focus_label"] = focus_label or attention
            proactive_payload["focus_text"] = (
                focus_text or proactive_candidate or summary
            )
            proactive_payload["trace_id"] = (
                snapshot.trace_id or _manual_trace_id(snapshot.records)
            )
            proactive_payload["allow_repeated_candidate"] = bool(
                behavior_active
                or orb_new_meaningful
                or screen_new_meaningful
                or screen_allow_same_subject_repeat
            )
            proactive_payload["orb_supervisor_evidence_key"] = str(
                orb_policy["evidence_key"] or ""
            )
            proactive_payload["orb_supervisor_visual_fingerprint"] = str(
                orb_policy["visual_fingerprint"] or ""
            )
            proactive_payload["screen_subject_identity"] = screen_subject
            proactive_payload["screen_supervisor_repeat_key"] = screen_repeat_key
            proactive_payload["screen_supervisor_trigger"] = str(
                screen_policy["trigger"] or ""
            )
            effects.append(SensoryEffect("proactive", proactive_payload))
        if tags:
            effects.append(
                SensoryEffect(
                    "publish_event",
                    {
                        "name": "sensory.hidden_action.tags_emitted",
                        "payload": {
                            "source": source,
                            "tags": tags,
                            "summary": summary,
                            "attention": attention,
                            "emotion": emotion,
                        },
                    },
                )
            )
        visual_allowed = self._capabilities.visual_allowed
        if (
            should_generate_image
            and visual_candidate
            and (visual_allowed is None or bool(visual_allowed(config)))
        ):
            effects.append(SensoryEffect("visual", normalized))
        return SensoryDecision(
            snapshot.cycle_id,
            snapshot.lease,
            snapshot.config_revision,
            tuple(effects),
            normalized,
            meaningful=meaningful,
            config_values=snapshot.config_values,
        )

    def _reduce_screen_review(self, snapshot, result, contributor):
        source = contributor.source_id
        records = snapshot.mappings()
        if source == 'clipboard' and not clipboard_image_is_new(records):
            result = {'matches': []}
        images = screen_images(snapshot.mappings())
        image_id = hashlib.sha256(json.dumps(images, sort_keys=True).encode()).hexdigest() if source == 'clipboard' else ''
        resolved = resolve_screen_matches(contributor, result,
            snapshot.state_values.get('supervisor_progress', {}), image_id=image_id) if images else None
        if resolved is None:
            return SensoryDecision(snapshot.cycle_id, snapshot.lease, snapshot.config_revision,
                                   (), {}, config_values=snapshot.config_values)
        actions = resolved['actions']
        candidate = '\n'.join(action['action'] for action in actions)
        emotion = next((action['emotion'] for action in actions
                        if action['emotion'] not in ('', 'Auto')), '')
        allowed = self._capabilities.emotion_allowed
        if emotion and allowed is not None and not allowed(emotion):
            emotion = ''
        normalized = {'source': source, 'tags': resolved['tags'],
                      'should_speak': bool(actions), 'proactive_candidate': candidate,
                      'supervisor_actions': actions, 'supervisor_progress': resolved['progress'],
                      'emotion': emotion, 'meaningful': bool(actions)}
        effects = [SensoryEffect('publish_event', {
            'name': 'sensory.hidden_pong.parsed',
            'payload': {**normalized, 'match_reasons': resolved['reasons']}}),
            SensoryEffect('state_update', normalized)]
        effects.extend(SensoryEffect('log', {
            'message': f'[Sensory] {source.capitalize()} match {tag}: {reason}'})
            for tag, reason in resolved['reasons'].items())
        if emotion:
            effects.append(SensoryEffect('avatar_emotion', {'emotion': emotion}))
        if actions and snapshot.config_values.get('sensory_allow_hidden_proactive_speech', False):
            payload = {**normalized, 'candidate': candidate, 'allow_repeated_candidate': True}
            if any(action['needs_image'] for action in actions):
                payload['supervisor_images'] = images
            effects.append(SensoryEffect('proactive', payload))
        return SensoryDecision(snapshot.cycle_id, snapshot.lease, snapshot.config_revision,
                               tuple(effects), normalized, meaningful=bool(actions),
                               config_values=snapshot.config_values)

    def decide(
        self,
        snapshot: SensorySnapshot,
        lease: WorkLease,
    ) -> CommandResult[SensoryDecision]:
        binding = self._binding_for_snapshot(snapshot, lease)
        if binding is None:
            return _stale_cycle()
        if self._providers is None or self._capabilities.build_messages is None:
            return _failure(
                "sensory_provider_unavailable",
                "Sensory provider decision execution is not configured",
            )
        compact_review = screen_review_contributor(
            self._registry, snapshot.sources, snapshot.config_values)
        if compact_review is not None:
            if compact_review.source_id == 'clipboard' and not clipboard_image_is_new(snapshot.mappings()):
                return CommandResult(True, self.reduce(snapshot, {'matches': []}))
            # Encode once before inference; a delayed assistant gets those exact
            # bytes even if a provider reuses or removes its capture file later.
            images = screen_images(snapshot.mappings())
            if not images:
                return _failure('sensory_image_unavailable', 'Visual review requires a current image.')
            snapshot = replace(snapshot, records=(SensoryRecord.from_mapping({
                'source': compact_review.source_id, 'image_is_new': True,
                'message': {'role': 'user', 'content': images}}),))
        source_text = ", ".join(snapshot.sources) or "sensory"
        with self._lock:
            fallback_source = str(
                self._pingpong_state.get("fallback_request_source", "") or ""
            )
            fallback_until = float(
                self._pingpong_state.get("fallback_request_until", 0.0) or 0.0
            )
            no_format_source = str(
                self._pingpong_state.get("no_json_response_format_source", "") or ""
            )
            no_format_until = float(
                self._pingpong_state.get("no_json_response_format_until", 0.0)
                or 0.0
            )
            retry_generation = self._image_retry_generation
        now = self._wall_clock()
        use_fallback = fallback_source == source_text and fallback_until > now
        skip_json_format = no_format_source == source_text and no_format_until > now
        config = RuntimeConfigSnapshot(
            snapshot.config_revision,
            snapshot.config_values,
        )
        prepare_model = getattr(self._providers, "prepare_model", None)
        if callable(prepare_model):
            try:
                ready = prepare_model(
                    binding.provider_selection,
                    reason="hidden sensory cycle",
                )
            except BaseException as exc:
                return _failure(
                    "sensory_model_prepare",
                    str(exc) or type(exc).__name__,
                    exc,
                )
            if not ready:
                return _failure(
                    "sensory_model_prepare",
                    "Sensory provider model was not ready",
                )
            if not self._cycle_is_current(binding):
                return _stale_cycle()
        initial = self._complete_provider_request(
            snapshot,
            binding,
            config,
            allow_images=False if use_fallback else None,
            # Compact visual review uses prompt-directed JSON, not a forced tool call.
            response_format=compact_review is None and not use_fallback and not skip_json_format,
        )
        retried_text_only = False
        if not initial.accepted:
            failure_text = initial.failure.message if initial.failure else ""
            response_format_error = (
                "response_format" in failure_text or "json_object" in failure_text
            )
            if not self._cycle_is_current(binding):
                return _stale_cycle()
            retry = self._complete_provider_request(
                snapshot,
                binding,
                config,
                allow_images=(None if response_format_error else False),
                response_format=False,
            )
            if not retry.accepted and response_format_error:
                failure_text = retry.failure.message if retry.failure else failure_text
                retry = self._complete_provider_request(
                    snapshot,
                    binding,
                    config,
                    allow_images=False,
                    response_format=False,
                )
                retried_text_only = True
            elif not response_format_error:
                retried_text_only = True
            if not retry.accepted:
                return CommandResult(False, failure=retry.failure or initial.failure)
            initial = retry
            if response_format_error and not retried_text_only:
                self._remember_no_json_format(binding, source_text, retry_generation)
            if retried_text_only:
                self._remember_text_only(binding, source_text, retry_generation,
                                         *_image_failure_reason(failure_text))
        payload_text = str(initial.value or "")
        parsed = self._parse_model_result(payload_text)
        if not parsed and not retried_text_only and not use_fallback:
            retry = self._complete_provider_request(
                snapshot,
                binding,
                config,
                allow_images=False,
                response_format=False,
            )
            if retry.accepted:
                payload_text = str(retry.value or "")
                parsed = self._parse_model_result(payload_text)
                retried_text_only = True
                self._remember_text_only(binding, source_text, retry_generation,
                                         "invalid_response", "The model returned a response NC could not interpret.")
            elif not self._cycle_is_current(binding):
                return _stale_cycle()
            else:
                return CommandResult(False, failure=retry.failure)
        if not self._cycle_is_current(binding):
            return _stale_cycle()
        if not parsed:
            cooldown, count = self._remember_invalid_response(
                binding,
                source_text,
                payload_text,
                retry_generation,
            )
            return _failure(
                "sensory_invalid_response",
                "Hidden sensory provider response was invalid; "
                f"cooldown={cooldown:.0f}s count={count}",
            )
        self._clear_invalid_response(binding, source_text)
        return CommandResult(True, self.reduce(snapshot, parsed))

    def run_cycle(
        self,
        *,
        force: bool = False,
        snapshots_override: Sequence[Mapping[str, object]] | None = None,
        priority: bool = False,
        priority_source: str = "",
        trace_id: str = "",
        lease: WorkLease | None = None,
        loop_id: str = "",
    ) -> bool:
        """Run one synchronous hidden cycle for periodic or manual callers."""

        cycle_lease = lease or self._lease_factory()
        config = self._config_snapshot()
        if not self.enabled(config):
            self._debug("engine_hidden_ping_skipped", {"reason": "disabled", "trace_id": trace_id})
            return False
        override_records = tuple(
            SensoryRecord.from_mapping(dict(item))
            for item in (snapshots_override or ())
            if isinstance(item, Mapping) and _snapshot_has_payload(item)
        )
        manual_override = any(_manual_orb_record(record) for record in override_records)
        if not manual_override and trace_id:
            manual_override = any(
                record.source == "companion_orb_target"
                for record in override_records
            )
        cycle_priority = bool(priority or manual_override)
        blocked = self._capabilities.blocked_reasons
        block_reasons = tuple(blocked(manual_override)) if blocked is not None else ()
        if block_reasons:
            self._debug(
                "engine_hidden_ping_blocked",
                {
                    "trace_id": trace_id,
                    "priority": cycle_priority,
                    "priority_source": str(priority_source or ""),
                    "reasons": block_reasons,
                },
            )
            return False
        started = self.begin_cycle(
            cycle_lease,
            config,
            priority=cycle_priority,
            priority_source=priority_source,
            trace_id=trace_id,
            loop_id=loop_id,
            capture_provider=True,
        )
        if not started.accepted or started.value is None:
            return False
        cycle = started.value
        if snapshots_override is None:
            captured = self.capture(
                cycle_lease,
                config,
                cycle=cycle,
                force=force,
            )
            if not captured.accepted or captured.value is None:
                return False
            snapshot = captured.value
        else:
            if manual_override:
                manual_records = tuple(
                    record for record in override_records if _manual_orb_record(record)
                )
                if manual_records:
                    override_records = manual_records
            snapshot = cycle.snapshot(override_records)
        filtered_records = tuple(
            record
            for record in snapshot.records
            if (
                cycle_priority and _manual_orb_record(record)
            )
            or _source_has_pingpong_guidance(
                self._registry,
                record.source,
                config.values,
            )
        )
        skipped_sources = tuple(
            dict.fromkeys(
                record.source
                for record in snapshot.records
                if record not in filtered_records
            )
        )
        if skipped_sources:
            self._debug(
                "engine_hidden_ping_source_skipped",
                {
                    "reason": "no_source_pingpong_guidance",
                    "sources": skipped_sources,
                },
            )
        snapshot = cycle.snapshot(filtered_records)
        if not snapshot.records:
            self._debug(
                "engine_hidden_ping_skipped",
                {"trace_id": trace_id, "reason": "no_snapshots"},
            )
            return False
        source_text = ", ".join(snapshot.sources) or "sensory"
        if self._invalid_response_active(source_text):
            self._mark_cycle_attempt(cycle._binding, source_text)
            self._debug(
                "engine_hidden_ping_skipped",
                {
                    "trace_id": trace_id,
                    "reason": "invalid_response_cooldown",
                    "source_text": source_text,
                },
            )
            return False
        ping_event = SensoryDecision(
            snapshot.cycle_id,
            snapshot.lease,
            snapshot.config_revision,
            (
                SensoryEffect(
                    "publish_event",
                    {
                        "name": "sensory.hidden_ping",
                        "payload": {
                            "snapshots": snapshot.mappings(),
                            "sources": snapshot.sources,
                        },
                    },
                ),
            ),
            config_values=snapshot.config_values,
        )
        if not self.apply(ping_event, cycle_lease).accepted:
            return False
        self._mark_cycle_attempt(cycle._binding, source_text)
        decided = self.decide(snapshot, cycle_lease)
        if not decided.accepted or decided.value is None:
            return False
        applied = self.apply(decided.value, cycle_lease)
        return bool(applied.accepted and decided.value.meaningful)

    def enabled(self, config: RuntimeConfigSnapshot | None = None) -> bool:
        snapshot = config or self._config_snapshot()
        providers = tuple(provider.id for provider in self._registry.list_providers())
        return bool(
            enabled_source_ids(
                snapshot.values.get("sensory_feedback_source", "off"),
                providers,
            )
            and snapshot.values.get("sensory_pingpong_enabled", False)
        )

    def feedback_interval_seconds(
        self,
        config: RuntimeConfigSnapshot | None = None,
    ) -> float:
        return _feedback_interval((config or self._config_snapshot()).values)

    def orb_watch_candidate_is_current(self, payload) -> bool:
        if not isinstance(payload, Mapping):
            return True
        action = payload.get('supervisor_action')
        selected_source = str(action.get('source') if isinstance(action, Mapping) else payload.get('source', ''))
        if selected_source != 'companion_orb_target' or 'orb_watch' not in payload:
            return True
        watch = payload['orb_watch']
        if not isinstance(watch, Mapping) or (watch.get('schema_version') != 2 and type(watch.get('revision')) is not int):
            return False
        lease = self._lease_factory()
        if watch.get('session_key') != f'{lease.run_id.value}/{lease.session_generation.value}':
            return False
        config = self._config_snapshot().values
        if not all(config.get(key, False) for key in ('companion_orb_enabled',
                'companion_orb_sensory_target_enabled')):
            return False
        current = next((c.metadata.get('orb_watch') for c in self._registry.list_prompt_contributors('companion_orb_target')
            if c.id == 'nc.companion_orb_overlay.behavior'), None)
        if isinstance(current, Mapping) and current.get('paused_reasons'):
            return False
        if watch.get('schema_version') == 2:
            from core.orb_watch_contract import watch_bundle_is_current
            return bool('companion_orb_target' in normalize_source_tokens(config.get('sensory_feedback_source','off')) and
                all(config.get(key,False) for key in ('companion_orb_vision_enabled',
                    'sensory_pingpong_enabled','sensory_allow_hidden_proactive_speech')) and
                watch_bundle_is_current(watch,current))
        if not isinstance(current, Mapping) or any(current.get(k) != watch.get(k) for k in ('session_key','revision','active')):
            return False
        if watch.get('active'):
            if 'companion_orb_target' not in normalize_source_tokens(config.get('sensory_feedback_source', 'off')):
                return False
            if not all(config.get(key, False) for key in ('companion_orb_vision_enabled',
                    'sensory_pingpong_enabled',
                    'sensory_allow_hidden_proactive_speech')):
                return False
            return bool(watch.get('eligible') is True and current.get('eligible') is True
                and watch.get('event_id') and watch.get('event_id') == (current.get('event') or {}).get('event_id'))
        return bool(config.get('companion_orb_supervisor_enabled', False))

    def orb_watch_reply_delivered(self, payload):
        if isinstance(payload, Mapping) and payload.get('orb_watch') and self.orb_watch_candidate_is_current(payload):
            publisher = self._capabilities.publish_event
            if publisher is not None:
                publisher('sensory.orb_watch.reply_delivered', dict(payload), self._lease_factory())

    def publish_orb_watch_reply(self, payload, publish):
        """The Orb state owner serializes this bounded commit against cancellation."""
        from core.orb_watch_contract import WatchReplyPublication
        if not self.orb_watch_candidate_is_current(payload):
            return None
        publisher=self._capabilities.publish_event
        if publisher is None:
            return None
        command=WatchReplyPublication(payload['orb_watch'],
            lambda:publish() if self.orb_watch_candidate_is_current(payload) else None)
        publisher('sensory.orb_watch.publish_reply',dict(publication=command),self._lease_factory())
        return command.result

    def queue_proactive(
        self,
        payload: Mapping[str, object],
        lease: WorkLease,
        *,
        decision: SensoryDecision | None = None,
    ) -> bool:
        if not self._lease_is_current(lease) or not self.orb_watch_candidate_is_current(payload):
            record_to(getattr(self._providers,'communication_trace',None),'sensory.proactive_suppressed',
                dict(reason='stale lease or watch event',request=payload),lease_correlation(lease))
            return False
        request = _proactive_request(payload, self._wall_clock())
        if not request:
            return False
        correlation=lease_correlation(lease,cycle_id=decision.cycle_id if decision is not None else '')
        request['communication_correlation']=correlation
        ready = self._capabilities.proactive_ready
        if ready is not None and not bool(ready()):
            record_to(getattr(self._providers,'communication_trace',None),'sensory.proactive_suppressed',
                dict(reason='speech unavailable',request=payload),lease_correlation(lease))
            self._log("Sensory proactive candidate suppressed because speech is unavailable")
            return False
        allow_repeat = bool(payload.get("allow_repeated_candidate", False))
        request_key = "|".join(
            str(request.get(key, "") or "")
            for key in ("source", "candidate", "summary", "attention")
        )
        candidate_key = "|".join(
            (
                str(request.get("source", "sensory") or "sensory"),
                _canonical_text(request.get("candidate", "")),
            )
        )
        now = self._wall_clock()
        with self._lock:
            if not self._running or (
                decision is not None and not self._decision_matches_locked(decision)
            ):
                return False
            state = self._hidden_action_state
            if (
                not allow_repeat
                and request_key
                and request_key == str(state.get("last_proactive_key", "") or "")
                and now - float(state.get("last_proactive_at", 0.0) or 0.0) < 45.0
            ):
                return False
            if (
                not allow_repeat
                and candidate_key
                and candidate_key
                == str(state.get("last_proactive_candidate_key", "") or "")
                and now
                - float(state.get("last_proactive_candidate_at", 0.0) or 0.0)
                < 300.0
            ):
                return False
            state["pending_proactive"] = _copy_mapping(request)
            state["last_proactive_key"] = request_key
            state["last_proactive_at"] = now
            state["last_proactive_candidate_key"] = candidate_key
            state["last_proactive_candidate_at"] = now
        callback = self._capabilities.proactive
        record_to(getattr(self._providers,'communication_trace',None),'sensory.proactive_queued',request,correlation)
        if callback is not None:
            callback(_freeze_mapping(request), lease)
        return True

    def current_pending_proactive(self) -> dict[str, object] | None:
        with self._lock:
            pending = self._hidden_action_state.get("pending_proactive")
            return _copy_mapping(pending) if isinstance(pending, Mapping) else None

    def current_pending_proactive_candidate(self) -> dict[str, object] | None:
        return self.current_pending_proactive()

    def consume_pending_proactive(self) -> dict[str, object] | None:
        with self._lock:
            pending = self._hidden_action_state.get("pending_proactive")
            active = _copy_mapping(pending) if isinstance(pending, Mapping) else None
            request = _copy_mapping(active) if active is not None else None
            if request is not None and not self.orb_watch_candidate_is_current(request):
                record_to(getattr(self._providers,'communication_trace',None),'sensory.wake_suppressed',
                    dict(reason='watch changed after queueing',request=request),request.get('communication_correlation',{}))
                request = active = None
            self._hidden_action_state["pending_proactive"] = None
            self._hidden_action_state["active_proactive"] = active
            if request is not None:
                record_to(getattr(self._providers,'communication_trace',None),'sensory.wake_consumed',request,request.get('communication_correlation',{}))
            return request

    def consume_hidden_proactive_candidate(self) -> dict[str, object] | None:
        return self.consume_pending_proactive()

    def clear_pending_proactive(self) -> None:
        with self._lock:
            self._hidden_action_state["pending_proactive"] = None

    def clear_pending_hidden_proactive_candidate(self) -> None:
        self.clear_pending_proactive()

    def clear_active_proactive(self) -> None:
        with self._lock:
            self._hidden_action_state["active_proactive"] = None

    def clear_active_hidden_proactive_candidate(self) -> None:
        self.clear_active_proactive()

    def active_hidden_proactive_candidate(self) -> dict[str, object] | None:
        with self._lock:
            active = self._hidden_action_state.get("active_proactive")
            return _copy_mapping(active) if isinstance(active, Mapping) else None

    def hidden_proactive_speech_allowed(self) -> bool:
        return bool(
            self._config_snapshot().values.get(
                "sensory_allow_hidden_proactive_speech",
                False,
            )
        )

    def buddy_contextual_payload_from_hidden_proactive(
        self,
        request: Mapping[str, object],
    ) -> object:
        callback = self._capabilities.buddy_contextual_payload
        return callback(request) if callback is not None else None

    def log_companion_orb_debug_event(
        self,
        event: str,
        *,
        trace_id: str = "",
        **fields: object,
    ) -> None:
        payload = dict(fields)
        if trace_id:
            payload["trace_id"] = str(trace_id)
        self._debug(event, payload)

    def apply(
        self,
        decision: SensoryDecision,
        lease: WorkLease,
    ) -> CommandResult[tuple[SensoryEffect, ...]]:
        if decision.lease != lease or not self._decision_is_current(decision):
            return _stale_cycle()
        execution_id = uuid.uuid4().hex
        with self._lock:
            if self._effect_execution_id:
                handle = self._effect_handle
                if handle is None or handle.is_alive():
                    return _failure(
                        "sensory_effect_busy",
                        "Sensory effect execution is already in progress",
                    )
                self._effect_execution_id = ""
                self._effect_handle = None
            if not self._decision_matches_locked(decision):
                return _stale_cycle()
            self._effect_execution_id = execution_id

        results: list[CommandResult[tuple[SensoryEffect, ...]]] = []

        def execute(token: CancellationToken) -> None:
            results.append(
                self._execute_effects(decision, lease, execution_id, token)
            )

        try:
            handle = self._workers.spawn(
                name="nc-sensory-effects",
                lease=lease,
                target=execute,
                identity=execution_id,
            )
        except BaseException as exc:
            with self._lock:
                if self._effect_execution_id == execution_id:
                    self._effect_execution_id = ""
                    self._effect_handle = None
            return _failure(
                "sensory_effect_start_failed",
                f"Could not start sensory effect execution: {exc}",
                exc,
            )
        with self._lock:
            current = self._effect_execution_id == execution_id
            if current:
                self._effect_handle = handle
        if not current:
            self._workers.cancel_handles((handle,), "sensory_effect_superseded")
            self._workers.join_handles((handle,))
            return _stale_cycle()
        try:
            self._workers.join_handles((handle,))
        except BaseException as exc:
            self._workers.cancel_handles((handle,), "sensory_effect_join_failed")
            return _failure(
                "sensory_effect_join_failed",
                f"Could not join sensory effect execution: {exc}",
                exc,
            )
        if handle.timed_out or handle.is_alive():
            self._workers.cancel_handles((handle,), "sensory_effect_timeout")
            message = (
                "Sensory effect execution did not finish before the supervisor "
                "timeout; cancellation was requested"
            )
            self._log(message)
            return _failure("sensory_effect_timeout", message)
        with self._lock:
            if self._effect_handle is handle:
                self._effect_handle = None
                self._effect_execution_id = ""
        if not results:
            return _failure(
                "sensory_effect_failed",
                "Sensory effect execution ended without a result",
            )
        return results[0]

    def _execute_effects(
        self,
        decision: SensoryDecision,
        lease: WorkLease,
        execution_id: str,
        token: CancellationToken,
    ) -> CommandResult[tuple[SensoryEffect, ...]]:
        if token.cancelled or not self._effect_execution_is_current(
            decision,
            execution_id,
        ):
            return _stale_cycle()
        admission = self._admit_effect(lease) if self._admit_effect else None
        if self._admit_effect is not None and admission is None:
            return _stale_lease()
        try:
            current = bool(
                not token.cancelled
                and self._effect_execution_is_current(decision, execution_id)
            )
        finally:
            if admission is not None and self._release_effect is not None:
                self._release_effect(admission)
        if not current:
            return _stale_cycle()
        try:
            for effect in decision.effects:
                if token.cancelled or not self._effect_execution_is_current(
                    decision,
                    execution_id,
                ):
                    return _stale_cycle()
                self._apply_effect(effect, decision)
                if token.cancelled or not self._effect_execution_is_current(
                    decision,
                    execution_id,
                ):
                    return _stale_cycle()
        except _StaleSensoryEffect:
            return _stale_cycle()
        except BaseException as exc:
            return _failure(
                "sensory_effect_failed",
                f"Could not apply sensory effect: {exc}",
                exc,
            )
        return CommandResult(True, decision.effects)

    def _effect_execution_is_current(
        self,
        decision: SensoryDecision,
        execution_id: str,
    ) -> bool:
        with self._lock:
            current = self._effect_execution_id == execution_id
        return bool(current and self._decision_is_current(decision))

    def _claim_hidden_loop_replacement(
        self,
        replacement_id: str,
        lease: WorkLease,
    ) -> CommandResult[tuple[WorkerHandle | None, _CycleBinding | None]]:
        owner_claimed = False
        try:
            result = self._claim_hidden_loop_replacement_inner(
                replacement_id,
                lease,
            )
            owner_claimed = bool(result.accepted)
            return result
        finally:
            with self._hidden_loop_replacement_condition:
                if self._hidden_loop_pending_replacement_id == replacement_id:
                    self._hidden_loop_pending_replacement_id = ""
                    self._hidden_loop_pending_replacement_lease = None
                if (
                    not owner_claimed
                    and self._hidden_loop_replacement_id == replacement_id
                ):
                    self._hidden_loop_replacement_id = ""
                    self._hidden_loop_replacement_lease = None
                self._hidden_loop_replacement_condition.notify_all()

    def _claim_hidden_loop_replacement_inner(
        self,
        replacement_id: str,
        lease: WorkLease,
    ) -> CommandResult[tuple[WorkerHandle | None, _CycleBinding | None]]:
        announced_handoff = False
        while True:
            if not self._lease_is_current(lease):
                with self._hidden_loop_replacement_condition:
                    if self._hidden_loop_pending_replacement_id == replacement_id:
                        self._hidden_loop_pending_replacement_id = ""
                        self._hidden_loop_pending_replacement_lease = None
                        self._hidden_loop_replacement_condition.notify_all()
                return _stale_lease()

            busy_message = ""
            wait_for_handoff = False
            with self._hidden_loop_replacement_condition:
                if not self._running:
                    if self._hidden_loop_pending_replacement_id == replacement_id:
                        self._hidden_loop_pending_replacement_id = ""
                        self._hidden_loop_pending_replacement_lease = None
                        self._hidden_loop_replacement_condition.notify_all()
                    return _failure(
                        "sensory_stopped",
                        "Sensory service is not running",
                    )

                owner_id = self._hidden_loop_replacement_id
                owner_lease = self._hidden_loop_replacement_lease
                if owner_id:
                    pending_lease = self._hidden_loop_pending_replacement_lease
                    if owner_lease == lease or pending_lease == lease:
                        busy_message = (
                            "Sensory hidden-loop replacement is already in "
                            "progress; overlapping start was rejected"
                        )
                    else:
                        self._hidden_loop_pending_replacement_id = replacement_id
                        self._hidden_loop_pending_replacement_lease = lease
                        self._hidden_loop_replacement_condition.notify_all()
                        wait_for_handoff = True
                else:
                    pending_id = self._hidden_loop_pending_replacement_id
                    pending_lease = self._hidden_loop_pending_replacement_lease
                    if pending_id and pending_id != replacement_id:
                        if pending_lease == lease:
                            busy_message = (
                                "Sensory hidden-loop replacement is already in "
                                "progress; overlapping start was rejected"
                            )
                        else:
                            self._hidden_loop_pending_replacement_id = replacement_id
                            self._hidden_loop_pending_replacement_lease = lease
                            self._hidden_loop_replacement_condition.notify_all()
                    if not busy_message:
                        self._hidden_loop_replacement_id = replacement_id
                        self._hidden_loop_replacement_lease = lease
                        if (
                            self._hidden_loop_pending_replacement_id
                            == replacement_id
                        ):
                            self._hidden_loop_pending_replacement_id = ""
                            self._hidden_loop_pending_replacement_lease = None
                        previous = self._hidden_loop_handle
                        previous_cycle = self._active_cycle
                        self._active_cycle = None
                        return CommandResult(
                            True,
                            (previous, previous_cycle),
                        )

            if busy_message:
                self._log(busy_message)
                return _failure("sensory_worker_restart_busy", busy_message)
            if wait_for_handoff:
                if not announced_handoff:
                    self._log(
                        "Sensory hidden-loop replacement is waiting for the "
                        "current retirement handoff"
                    )
                    announced_handoff = True
                with self._hidden_loop_replacement_condition:
                    self._hidden_loop_replacement_condition.wait_for(
                        lambda: bool(
                            not self._running
                            or not self._hidden_loop_replacement_id
                            or self._hidden_loop_pending_replacement_id
                            != replacement_id
                        )
                    )

    def start_hidden_loop(
        self,
        lease: WorkLease,
    ) -> CommandResult[WorkerHandle]:
        if not self._lease_is_current(lease):
            return _stale_lease()
        replacement_id = uuid.uuid4().hex
        claimed = self._claim_hidden_loop_replacement(replacement_id, lease)
        if not claimed.accepted or claimed.value is None:
            return CommandResult(False, failure=claimed.failure)
        previous, previous_cycle = claimed.value
        try:
            if previous_cycle is not None:
                previous_cycle.token.cancel("sensory_loop_restarted")
            if previous is not None:
                retired = self._retire_hidden_loop_handle(
                    previous,
                    "sensory_loop_restarted",
                )
                if not retired.accepted:
                    if retired.failure is not None:
                        self._log(retired.failure.message)
                    return CommandResult(False, failure=retired.failure)
            if not self._lease_is_current(lease):
                return _stale_lease()
            admission = self._admit_effect(lease) if self._admit_effect else None
            if self._admit_effect is not None and admission is None:
                return _stale_lease()
            loop_id = uuid.uuid4().hex
            try:
                with self._lock:
                    current = bool(
                        self._running
                        and self._hidden_loop_replacement_id == replacement_id
                        and self._hidden_loop_handle is previous
                    )
                    if current:
                        self._hidden_loop_handle = None
                        self._hidden_loop_id = loop_id
                if not current or not self._lease_is_current(lease):
                    with self._lock:
                        if (
                            self._hidden_loop_id == loop_id
                            and self._hidden_loop_handle is None
                        ):
                            self._hidden_loop_id = ""
                    return _stale_lease()
                try:
                    handle = self._workers.spawn(
                        name="nc-sensory-loop",
                        lease=lease,
                        target=lambda token: self._hidden_loop_worker(
                            loop_id,
                            lease,
                            token,
                        ),
                        identity=loop_id,
                    )
                except BaseException as exc:
                    with self._lock:
                        if self._hidden_loop_id == loop_id:
                            self._hidden_loop_id = ""
                    return _failure(
                        "sensory_worker_start_failed",
                        f"Could not start sensory hidden loop: {exc}",
                        exc,
                    )
                lease_current = self._lease_is_current(lease)
                with self._lock:
                    current = bool(
                        lease_current
                        and self._running
                        and self._hidden_loop_id == loop_id
                        and self._hidden_loop_replacement_id == replacement_id
                    )
                    if current:
                        self._hidden_loop_handle = handle
                    elif self._hidden_loop_handle is None:
                        self._hidden_loop_handle = handle
                if not current:
                    retired = self._retire_hidden_loop_handle(
                        handle,
                        "sensory_loop_superseded",
                    )
                    if not retired.accepted:
                        if retired.failure is not None:
                            self._log(retired.failure.message)
                        return CommandResult(False, failure=retired.failure)
                    with self._lock:
                        if self._hidden_loop_handle is handle:
                            self._hidden_loop_handle = None
                        if self._hidden_loop_id == loop_id:
                            self._hidden_loop_id = ""
                    return _stale_lease() if not lease_current else _stale_cycle()
            finally:
                if admission is not None and self._release_effect is not None:
                    self._release_effect(admission)
            return CommandResult(True, handle)
        finally:
            with self._hidden_loop_replacement_condition:
                if self._hidden_loop_replacement_id == replacement_id:
                    self._hidden_loop_replacement_id = ""
                    self._hidden_loop_replacement_lease = None
                self._hidden_loop_replacement_condition.notify_all()

    def _retire_hidden_loop_handle(
        self,
        handle: WorkerHandle,
        reason: str,
    ) -> CommandResult[None]:
        try:
            was_alive = bool(handle.is_alive())
            previous_failure = handle.failure
            handle.timed_out = False
            self._workers.cancel_handles((handle,), reason)
            joined = self._workers.join_handles((handle,))
            joined_handles = tuple(joined or ())
            is_alive = bool(handle.is_alive())
        except BaseException as exc:
            return _failure(
                "sensory_worker_retirement_failed",
                f"Sensory hidden loop retirement failed: {exc}",
                exc,
            )
        if handle.timed_out:
            return _failure(
                "sensory_worker_stop_timeout",
                "Sensory hidden loop did not stop before the supervisor timeout; "
                "replacement was not started",
            )
        if handle.failure is not None and handle.failure is not previous_failure:
            return _failure(
                "sensory_worker_retirement_failed",
                "Sensory hidden loop retirement failed: "
                f"{handle.failure.message}",
                handle.failure.cause,
            )
        if was_alive and not any(item is handle for item in joined_handles):
            return _failure(
                "sensory_worker_retirement_unconfirmed",
                "Sensory hidden loop retirement could not be confirmed because "
                "the live worker join was skipped or already claimed; replacement "
                "was not started",
            )
        if is_alive:
            return _failure(
                "sensory_worker_retirement_unconfirmed",
                "Sensory hidden loop retirement could not be confirmed because "
                "the worker is still alive; replacement was not started",
            )
        return CommandResult(True)

    def _retire_effect_handle(
        self,
        handle: WorkerHandle,
        reason: str,
    ) -> CommandResult[None]:
        try:
            handle.timed_out = False
            self._workers.cancel_handles((handle,), reason)
            self._workers.join_handles((handle,))
            alive = bool(handle.is_alive())
        except BaseException as exc:
            return _failure(
                "sensory_effect_stop_failed",
                f"Sensory effect execution cancellation failed: {exc}",
                exc,
            )
        if handle.timed_out or alive:
            return _failure(
                "sensory_effect_stop_timeout",
                "Sensory effect execution did not stop before the supervisor "
                "timeout; cancellation remains requested",
            )
        return CommandResult(True)

    def current_last_cycle_at(self) -> float:
        with self._lock:
            return float(self._pingpong_state.get("last_cycle_at", 0.0) or 0.0)

    def snapshot_state(self) -> SensoryStateSnapshot:
        with self._lock:
            active_cycle_id = (
                self._active_cycle.cycle_id if self._active_cycle is not None else ""
            )
            return SensoryStateSnapshot(
                cache=_freeze_mapping(self._feedback_cache),
                hidden_history=tuple(
                    _freeze_mapping(item) for item in self._hidden_history
                ),
                pingpong=_freeze_mapping(self._pingpong_state),
                hidden_actions=_freeze_mapping(self._hidden_action_state),
                running=self._running,
                active_cycle_id=active_cycle_id,
                hidden_loop_id=self._hidden_loop_id,
            )

    def reset_session(self) -> CommandResult[None]:
        with self._lock:
            active_cycle = self._active_cycle
            self._active_cycle = None
            effect_handle = self._effect_handle
            effect_pending = bool(
                self._effect_execution_id and effect_handle is None
            )
            self._feedback_cache.clear()
            self._hidden_history.clear()
            self._pingpong_state.clear()
            self._pingpong_state.update(_default_pingpong_state())
            self._image_retry_generation += 1
            self._image_fallback.clear()
            self._image_notice.clear()
            self._hidden_action_state.clear()
            self._hidden_action_state.update(_default_hidden_action_state())
        if active_cycle is not None:
            active_cycle.token.cancel("sensory_session_reset")
        if effect_handle is not None:
            retired = self._retire_effect_handle(
                effect_handle,
                "sensory_session_reset",
            )
            if not retired.accepted:
                if retired.failure is not None:
                    self._log(retired.failure.message)
                return retired
            with self._lock:
                if self._effect_handle is effect_handle:
                    self._effect_handle = None
                    self._effect_execution_id = ""
        elif effect_pending:
            return _failure(
                "sensory_effect_restart_busy",
                "Sensory effect execution is still being published",
            )
        return CommandResult(True)

    def clear_feedback_cache(self) -> None:
        with self._lock:
            self._feedback_cache.clear()

    def restore_hidden_history(
        self,
        entries: Sequence[Mapping[str, object]],
    ) -> None:
        restored = [
            _copy_mapping(entry)
            for entry in entries
            if isinstance(entry, Mapping)
        ]
        with self._lock:
            self._hidden_history.clear()
            self._hidden_history.extend(restored)

    def hidden_history_snapshot(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            return tuple(_copy_mapping(entry) for entry in self._hidden_history)

    def prune_hidden_history(self, depth: int | None = None) -> None:
        if depth is None:
            depth = int(
                self._config_snapshot().values.get(
                    "sensory_pingpong_history_depth",
                    3,
                )
                or 3
            )
        bounded_depth = max(0, int(depth))
        with self._lock:
            if bounded_depth <= 0:
                self._hidden_history.clear()
            elif len(self._hidden_history) > bounded_depth:
                del self._hidden_history[:-bounded_depth]

    def _hidden_loop_worker(
        self,
        loop_id: str,
        lease: WorkLease,
        token: CancellationToken,
    ) -> None:
        while not token.cancelled:
            if not self._loop_is_current(loop_id, lease):
                return
            ready = self._capabilities.loop_ready
            if ready is not None and not bool(ready()):
                self._sleep(token, 0.25)
                continue
            config = self._config_snapshot()
            if not self.enabled(config):
                self._sleep(token, 0.5)
                continue
            blocked = self._capabilities.blocked_reasons
            if blocked is not None and tuple(blocked(False)):
                self._sleep(token, 0.25)
                continue
            interval = _feedback_interval(config.values)
            last_cycle_at = self.current_last_cycle_at()
            now = self._wall_clock()
            if last_cycle_at > 0 and (now - last_cycle_at) < interval:
                self._sleep(token, 0.25)
                continue
            self.run_cycle(force=False, lease=lease, loop_id=loop_id)
            self._sleep(token, 0.25)

    @staticmethod
    def _sleep(token: CancellationToken, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, float(seconds))
        while not token.cancelled:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.05, remaining))

    def _cycle_is_current(self, binding: _CycleBinding) -> bool:
        with self._lock:
            internal = self._running and self._active_cycle is binding
            if internal and binding.loop_id:
                internal = binding.loop_id == self._hidden_loop_id
        if not internal or not self._lease_is_current(binding.lease):
            return False
        return self._config_snapshot().revision == binding.config_revision

    def _decision_is_current(self, decision: SensoryDecision) -> bool:
        with self._lock:
            binding = self._active_cycle
            internal = bool(
                self._running
                and binding is not None
                and binding.cycle_id == decision.cycle_id
                and binding.lease == decision.lease
                and binding.config_revision == decision.config_revision
            )
        if not internal or not self._lease_is_current(decision.lease):
            return False
        return self._config_snapshot().revision == decision.config_revision

    def _loop_is_current(self, loop_id: str, lease: WorkLease) -> bool:
        with self._lock:
            internal = self._running and self._hidden_loop_id == loop_id
        return bool(internal and self._lease_is_current(lease))

    def _apply_effect(
        self,
        effect: SensoryEffect,
        decision: SensoryDecision,
    ) -> None:
        payload = effect.payload
        lease = decision.lease
        record_to(getattr(self._providers,'communication_trace',None),'sensory.'+effect.kind,
            dict(payload),lease_correlation(lease,cycle_id=decision.cycle_id))
        if effect.kind == "orb_target":
            callback = self._capabilities.orb_target
            if callback is not None:
                callback(payload, lease)
            return
        if effect.kind == "orb_focus":
            if not self.orb_watch_candidate_is_current(payload):
                return
            callback = self._capabilities.orb_focus
            if callback is not None:
                callback(payload, lease)
            return
        if effect.kind == "avatar_emotion":
            callback = self._capabilities.avatar_emotion
            if callback is not None:
                callback(str(payload.get("emotion", "") or ""), lease)
            return
        if effect.kind == "proactive":
            if not self.queue_proactive(payload, lease, decision=decision):
                return
            with self._lock:
                if not self._decision_matches_locked(decision):
                    raise _StaleSensoryEffect()
                action = payload.get('supervisor_action')
                actions = payload.get('supervisor_actions') or ([action] if isinstance(action, Mapping) else [])
                for action in actions:
                    progress = self._hidden_action_state.get('supervisor_progress', {})
                    current = progress.get(f"{action.get('source', '')}:{action.get('id', '')}")
                    if current is not None:
                        current['delivered'] = True
                        current['delivered_subject'] = current.get('subject', '')
                subject = str(payload.get("screen_subject_identity", "") or "")
                repeat_key = str(
                    payload.get("screen_supervisor_repeat_key", "") or ""
                )
                if subject:
                    self._hidden_action_state[
                        "last_screen_subject_comment_key"
                    ] = subject
                if repeat_key:
                    self._hidden_action_state[
                        "last_screen_supervisor_meaningful_key"
                    ] = repeat_key
                    self._hidden_action_state[
                        "last_screen_supervisor_meaningful_subject"
                    ] = subject
                    self._hidden_action_state[
                        "last_screen_supervisor_meaningful_trigger"
                    ] = _canonical_text(
                        payload.get("screen_supervisor_trigger", "")
                    )
                orb_evidence_key = str(
                    payload.get("orb_supervisor_evidence_key", "") or ""
                )
                if orb_evidence_key:
                    self._hidden_action_state[
                        "last_orb_supervisor_evidence_key"
                    ] = orb_evidence_key
                    self._hidden_action_state[
                        "last_orb_supervisor_visual_fingerprint"
                    ] = str(
                        payload.get(
                            "orb_supervisor_visual_fingerprint",
                            "",
                        )
                        or ""
                    )
            publisher = self._capabilities.publish_event
            if publisher is not None:
                publisher(
                    "sensory.hidden_action.proactive_queued",
                    {
                        "source": payload.get("source", "sensory"),
                        **({'orb_watch': payload['orb_watch']} if 'orb_watch' in payload else {}),
                        "candidate": payload.get("proactive_candidate", ""),
                        "summary": payload.get("summary", ""),
                        "attention": payload.get("attention", ""),
                        "emotion": payload.get("emotion", ""),
                        "focus_bounds": payload.get("focus_bounds", ()),
                        "focus_label": payload.get("focus_label", ""),
                        "focus_text": payload.get("focus_text", ""),
                    },
                    lease,
                )
            return
        if effect.kind == "visual":
            request_key = "|".join(
                (
                    str(payload.get("source", "sensory") or "sensory")
                    .strip()
                    .lower(),
                    str(payload.get("visual_candidate", "") or ""),
                    str(payload.get("summary", "") or "")[:120],
                )
            )
            now = self._wall_clock()
            with self._lock:
                if not self._decision_matches_locked(decision):
                    raise _StaleSensoryEffect()
                last_key = str(
                    self._hidden_action_state.get("last_visual_key", "") or ""
                )
                last_at = float(
                    self._hidden_action_state.get("last_visual_at", 0.0) or 0.0
                )
                if request_key == last_key and now - last_at < 45.0:
                    return
                self._hidden_action_state["last_visual_key"] = request_key
                self._hidden_action_state["last_visual_at"] = now
            self._log(
                "Sensory hidden PONG requested visual reply: "
                f"{payload.get('visual_candidate', '')}"
            )
            callback = self._capabilities.visual
            if callback is not None:
                callback(
                    payload,
                    lease,
                    RuntimeConfigSnapshot(
                        decision.config_revision,
                        decision.config_values,
                    ),
                )
            publisher = self._capabilities.publish_event
            if publisher is not None:
                publisher(
                    "sensory.hidden_action.visual_requested",
                    {
                        "source": payload.get("source", "sensory"),
                        "candidate": payload.get("visual_candidate", ""),
                        "summary": payload.get("summary", ""),
                        "attention": payload.get("attention", ""),
                        "emotion": payload.get("emotion", ""),
                    },
                    lease,
                )
            return
        if effect.kind == "log":
            self._log(str(payload.get("message", "") or ""))
            return
        if effect.kind == "debug":
            fields = payload.get("fields")
            self._debug(
                str(payload.get("event", "sensory_event") or "sensory_event"),
                dict(fields) if isinstance(fields, Mapping) else {},
            )
            return
        if effect.kind == "publish_event":
            event_payload = payload.get('payload', {})
            if payload.get('name') == 'sensory.hidden_pong.parsed' and not self.orb_watch_candidate_is_current(event_payload):
                return
            callback = self._capabilities.publish_event
            if callback is not None:
                callback(
                    str(payload.get("name", "") or ""),
                    payload.get("payload", {}),
                    lease,
                )
            return
        if effect.kind == "state_update":
            with self._lock:
                if not self._decision_matches_locked(decision):
                    raise _StaleSensoryEffect()
                self._pingpong_state["last_cycle_at"] = self._wall_clock()
                self._hidden_action_state['supervisor_progress'] = _copy_mapping(
                    payload.get('supervisor_progress', {})
                )
                self._pingpong_state["last_source"] = str(
                    payload.get("source", "sensory") or "sensory"
                )
                if payload.get("meaningful"):
                    self._pingpong_state["last_emotion"] = str(
                        payload.get("emotion", "") or ""
                    )
                    self._pingpong_state["last_attention"] = str(
                        payload.get("attention", "") or ""
                    )
                    self._pingpong_state["last_summary"] = str(
                        payload.get("summary", "") or ""
                    )
            return
        if effect.kind == "retain_history":
            retained = {
                key: _thaw(payload.get(key))
                for key in (
                    "source",
                    "summary",
                    "emotion",
                    "attention",
                    "proactive_candidate",
                    "visual_candidate",
                    "should_speak",
                    "should_generate_image",
                    "tags",
                )
            }
            retained["created_at"] = self._wall_clock()
            stored_retained = _copy_mapping(retained)
            with self._lock:
                if not self._decision_matches_locked(decision):
                    raise _StaleSensoryEffect()
                comparable = tuple(
                    key for key in stored_retained if key != "created_at"
                )
                previous = self._hidden_history[-1] if self._hidden_history else None
                if previous is None or any(
                    previous.get(key) != stored_retained.get(key)
                    for key in comparable
                ):
                    self._hidden_history.append(stored_retained)
                    depth = max(
                        0,
                        int(
                            self._active_cycle.config_values.get(
                                "sensory_pingpong_history_depth",
                                3,
                            )
                            or 3
                        ),
                    )
                    if depth <= 0:
                        self._hidden_history.clear()
                    elif len(self._hidden_history) > depth:
                        del self._hidden_history[:-depth]
                    self._pingpong_state["last_retained_at"] = self._wall_clock()
                    retained_now = True
                else:
                    retained_now = False
            if retained_now:
                publisher = self._capabilities.publish_event
                if publisher is not None:
                    event_retained = _copy_mapping(retained)
                    publisher(
                        "sensory.hidden_pong.retained",
                        _copy_mapping(
                            {
                                "event": event_retained,
                                "source": event_retained["source"],
                            }
                        ),
                        lease,
                    )
                rebuild = self._capabilities.request_chat_rebuild
                if rebuild is not None:
                    rebuild(lease)
            return
        raise ValueError(f"Unknown sensory effect kind: {effect.kind}")

    def _binding_for_snapshot(
        self,
        snapshot: SensorySnapshot,
        lease: WorkLease,
    ) -> _CycleBinding | None:
        with self._lock:
            binding = self._active_cycle
            matched = bool(
                binding is not None
                and binding.cycle_id == snapshot.cycle_id
                and binding.lease == lease
                and snapshot.lease == lease
                and binding.config_revision == snapshot.config_revision
            )
        if not matched or binding is None or not self._cycle_is_current(binding):
            return None
        return binding

    def _complete_provider_request(
        self,
        snapshot: SensorySnapshot,
        binding: _CycleBinding,
        config: RuntimeConfigSnapshot,
        *,
        allow_images: bool | None,
        response_format: bool,
    ) -> CommandResult[str]:
        builder = self._capabilities.build_messages
        if builder is None or self._providers is None:
            return _failure(
                "sensory_provider_unavailable",
                "Sensory provider decision execution is not configured",
            )
        messages = tuple(
            dict(message)
            for message in builder(
                tuple(_watch_policy_record(record) for record in snapshot.mappings()),
                allow_images,
                snapshot.priority,
                config,
                snapshot.retained_history,
            )
            if isinstance(message, Mapping)
        )
        if not self._cycle_is_current(binding):
            return _stale_cycle()
        if not messages:
            return _failure(
                "sensory_prompt_empty",
                "Sensory provider request has no messages",
            )
        values = config.values
        with self._lock:
            image_generation = self._image_retry_generation
        output_budget = 150 if snapshot.priority else 1024
        params: dict[str, object] = {
            "model": str(values.get("model_name", "") or ""),
            "messages": messages,
            "temperature": 0.12 if snapshot.priority else 0.2,
            "top_p": min(0.8, float(values.get("top_p", 0.8) or 0.8)),
            "max_tokens": output_budget,
        }
        if response_format:
            params["response_format"] = {"type": "json_object"}
        additional = {
            "top_k": int(values.get("top_k", 40) or 40),
            "min_p": float(values.get("min_p", 0.05) or 0.05),
            "repeat_penalty": float(values.get("repeat_penalty", 1.1) or 1.1),
            chat_providers.FROZEN_OUTPUT_TOKEN_BUDGET_OVERRIDE: output_budget,
        }
        try:
            prepared = self._providers.prepare(
                binding.provider_selection,
                PromptRequest.from_payload(params, additional),
            )
            if not self._cycle_is_current(binding):
                return _stale_cycle()
            with correlation_scope(lease_correlation(snapshot.lease,cycle_id=snapshot.cycle_id,kind='hidden_ping_pong')):
                completed = self._providers.complete(prepared, binding.token)
        except BaseException as exc:
            return _failure(
                "sensory_provider_execution",
                str(exc) or type(exc).__name__,
                exc,
            )
        if not self._cycle_is_current(binding):
            return _stale_cycle()
        if not isinstance(completed, CommandResult):
            return _failure(
                "sensory_provider_execution",
                "ProviderService returned an invalid sensory completion result",
            )
        if completed.accepted and self._parse_model_result(str(completed.value or "")):
            has_image = any(
                isinstance(message.get("content"), (list, tuple))
                and any(isinstance(part, Mapping) and part.get("type") == "image_url"
                        for part in message["content"])
                for message in messages
            )
            if has_image:
                self._image_recovered(binding, ", ".join(snapshot.sources) or "sensory", image_generation)
        return completed

    def _parse_model_result(self, payload_text: str) -> dict[str, object]:
        parsed = _parse_sensory_result(payload_text)
        return dict(parsed) if isinstance(parsed, Mapping) else {}

    def _mark_cycle_attempt(self, binding: _CycleBinding, source_text: str) -> None:
        with self._lock:
            if self._active_cycle is not binding:
                return
            self._pingpong_state["last_cycle_at"] = self._wall_clock()
            self._pingpong_state["last_source"] = str(source_text or "sensory")

    def _invalid_response_active(self, source_text: str) -> bool:
        with self._lock:
            source = str(self._pingpong_state.get("invalid_response_source", "") or "")
            until = float(self._pingpong_state.get("invalid_response_until", 0.0) or 0.0)
        return source == str(source_text or "") and until > self._wall_clock()

    def _remember_invalid_response(
        self,
        binding: _CycleBinding,
        source_text: str,
        payload_text: str,
        generation: int,
    ) -> tuple[float, int]:
        now = self._wall_clock()
        source = str(source_text or "")
        with self._lock:
            if self._active_cycle is not binding or generation != self._image_retry_generation:
                return 0.0, 0
            previous_source = str(
                self._pingpong_state.get("invalid_response_source", "") or ""
            )
            previous_until = float(
                self._pingpong_state.get("invalid_response_until", 0.0) or 0.0
            )
            previous_count = int(
                self._pingpong_state.get("invalid_response_count", 0) or 0
            )
            count = (
                previous_count + 1
                if previous_source == source and previous_until > now
                else 1
            )
            cooldown = min(180.0, 30.0 * max(1, count))
            self._pingpong_state["invalid_response_source"] = source
            self._pingpong_state["invalid_response_count"] = count
            self._pingpong_state["invalid_response_until"] = now + cooldown
            self._pingpong_state["last_failure_at"] = now
            self._pingpong_state["last_failure_key"] = (
                f"{source}|invalid_json|{payload_text[:120]}"
            )
        return cooldown, count

    def _clear_invalid_response(
        self,
        binding: _CycleBinding,
        source_text: str,
    ) -> None:
        with self._lock:
            if self._active_cycle is not binding:
                return
            if str(self._pingpong_state.get("invalid_response_source", "") or "") != str(source_text or ""):
                return
            self._pingpong_state["invalid_response_source"] = ""
            self._pingpong_state["invalid_response_count"] = 0
            self._pingpong_state["invalid_response_until"] = 0.0

    def _remember_text_only(self, binding: _CycleBinding, source_text: str,
                            generation: int, reason_code: str, reason: str) -> None:
        if not self._cycle_is_current(binding):
            return
        with self._lock:
            if self._active_cycle is not binding or generation != self._image_retry_generation:
                return
            retry_at = self._wall_clock() + 300.0
            self._pingpong_state["fallback_request_source"] = str(source_text or "")
            self._pingpong_state["fallback_request_until"] = retry_at
            self._image_fallback = {
                "active": True, "source": str(source_text), "phase": "paused",
                "reason_code": reason_code, "reason": reason, "retry_at": retry_at,
            }
            event = self._image_event_locked("paused", self._image_fallback)
        self._report_image_event(event)

    def _image_event_locked(self, kind: str, fields: Mapping[str, object]) -> dict[str, object]:
        self._image_notice_sequence += 1
        self._image_notice = {**dict(fields), "kind": kind, "id": self._image_notice_sequence}
        return dict(self._image_notice)

    def _report_image_event(self, event: Mapping[str, object]) -> None:
        # Only controlled reason categories enter diagnostics; provider error bodies may
        # contain credentials, prompts or encoded captures and must never be copied here.
        self._log("[Sensory images] " + json.dumps(dict(event), ensure_ascii=True))
        self._debug("sensory_image_fallback", event)

    def _clear_image_wait_locked(self, reason: str) -> dict[str, object] | None:
        self._image_retry_generation += 1
        for key in ("fallback_request_until", "no_json_response_format_until",
                    "invalid_response_until"):
            self._pingpong_state[key] = 0.0
        self._pingpong_state["invalid_response_count"] = 0
        if not self._image_fallback.get("active"):
            return None
        self._image_fallback.update(phase="retry_pending", retry_at=0.0)
        return self._image_event_locked("retry_pending", {**self._image_fallback, "reset_reason": reason})

    def _sync_image_model(self) -> None:
        values = self._config_snapshot().values
        key = (str(values.get("chat_provider", "")), str(values.get("model_name", "")))
        event = None
        with self._lock:
            if self._image_model_key is not None and key != self._image_model_key:
                event = self._clear_image_wait_locked("model_changed")
            self._image_model_key = key
        if event:
            self._report_image_event(event)

    def image_fallback_status(self) -> dict[str, object]:
        """Small, thread-safe UI projection; never exposes captures or provider bodies."""
        self._sync_image_model()
        event = None
        with self._lock:
            if (self._image_fallback.get("phase") == "paused"
                    and float(self._image_fallback["retry_at"]) <= self._wall_clock()):
                self._image_fallback["phase"] = "retry_pending"
                event = self._image_event_locked("retry_pending", {
                    **self._image_fallback, "reset_reason": "timer_expired"})
            status = dict(self._image_fallback)
            status["remaining_seconds"] = max(0, int(
                float(status.get("retry_at", 0.0)) - self._wall_clock() + 0.999))
            status["notice"] = dict(self._image_notice)
        if event:
            self._report_image_event(event)
        return status

    def retry_images(self) -> CommandResult[None]:
        """Clear suppression for the next eligible check-in, without cancelling work."""
        self._sync_image_model()
        with self._lock:
            event = self._clear_image_wait_locked("user_retry")
        if event:
            self._report_image_event(event)
        return CommandResult(True)

    def _image_recovered(self, binding: _CycleBinding, source: str, generation: int) -> None:
        with self._lock:
            if (self._active_cycle is not binding or generation != self._image_retry_generation
                    or not self._image_fallback.get("active")
                    or self._image_fallback.get("source") != source):
                return
            self._image_fallback.update(active=False, phase="recovered", retry_at=0.0)
            self._pingpong_state["fallback_request_until"] = 0.0
            event = self._image_event_locked("recovered", self._image_fallback)
        self._report_image_event(event)

    def _remember_no_json_format(self, binding: _CycleBinding, source_text: str, generation: int) -> None:
        with self._lock:
            if self._active_cycle is binding and generation == self._image_retry_generation:
                self._pingpong_state["no_json_response_format_source"] = str(source_text or "")
                self._pingpong_state["no_json_response_format_until"] = self._wall_clock() + 300.0

    def _debug(self, event: str, fields: Mapping[str, object]) -> None:
        callback = self._capabilities.debug
        if callback is not None:
            try:
                callback(str(event or "sensory_event"), _freeze_mapping(fields))
            except BaseException as exc:
                _report_diagnostic_callback_failure("debug", exc)

    def _decision_matches_locked(self, decision: SensoryDecision) -> bool:
        binding = self._active_cycle
        return bool(
            self._running
            and binding is not None
            and binding.cycle_id == decision.cycle_id
            and binding.lease == decision.lease
            and binding.config_revision == decision.config_revision
        )

    def _log(self, message: str) -> None:
        callback = self._capabilities.log
        if callback is not None:
            try:
                callback(str(message))
            except BaseException as exc:
                _report_diagnostic_callback_failure("log", exc)


def _image_failure_reason(message: str) -> tuple[str, str]:
    """Classify errors without leaking arbitrary provider response/request contents."""
    text = message.lower()
    if any(word in text for word in ("401", "403", "unauthorized", "authentication", "api key")):
        return "authentication", "The provider rejected authentication or access. Check its API credentials and permissions."
    if any(word in text for word in ("429", "rate limit", "quota")):
        return "rate_limit", "The provider reported a rate or quota limit."
    if any(word in text for word in ("timeout", "timed out", "connection", "unreachable")):
        return "connection", "The provider could not be reached or did not respond in time."
    if any(word in text for word in ("image", "vision", "multimodal")):
        return "image_rejected", "The provider rejected the image request. Check that the selected model supports images."
    return "request_failed", "The provider request failed. NC could not determine a more specific cause."


class _StaleSensoryEffect(RuntimeError):
    pass


def _default_pingpong_state() -> dict[str, object]:
    return {
        "last_cycle_at": 0.0,
        "last_retained_at": 0.0,
        "last_failure_at": 0.0,
        "last_failure_key": "",
        "fallback_request_until": 0.0,
        "fallback_request_source": "",
        "no_json_response_format_until": 0.0,
        "no_json_response_format_source": "",
        "invalid_response_until": 0.0,
        "invalid_response_source": "",
        "invalid_response_count": 0,
        "last_emotion": "",
        "last_attention": "",
        "last_summary": "",
        "last_source": "off",
    }


def _default_hidden_action_state() -> dict[str, object]:
    return {
        "supervisor_progress": {},
        "pending_proactive": None,
        "active_proactive": None,
        "last_proactive_key": "",
        "last_proactive_at": 0.0,
        "last_proactive_candidate_key": "",
        "last_proactive_candidate_at": 0.0,
        "last_visual_key": "",
        "last_visual_at": 0.0,
        "last_screen_subject_comment_key": "",
        "last_screen_supervisor_meaningful_key": "",
        "last_screen_supervisor_meaningful_subject": "",
        "last_screen_supervisor_meaningful_trigger": "",
        "last_orb_supervisor_evidence_key": "",
        "last_orb_supervisor_visual_fingerprint": "",
    }


def _feedback_interval(values: Mapping[str, object]) -> float:
    return max(
        2.0,
        float(values.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
    )


def _snapshot_has_payload(snapshot: Mapping[str, object]) -> bool:
    image_path = str(snapshot.get("image_path", "") or "")
    return bool(
        (image_path and Path(image_path).is_file())
        or snapshot.get("message")
        or snapshot.get("content")
    )


def _snapshot_can_reuse(snapshot: Mapping[str, object]) -> bool:
    if not _snapshot_has_payload(snapshot):
        return False
    metadata = snapshot.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    cache_policy = str(metadata.get("cache_policy", "") or "").strip().lower()
    return cache_policy not in {"one_shot", "no_reuse", "transient"} and not _boolish(
        metadata.get("hidden_response_one_shot")
    )


def _manual_orb_record(record: SensoryRecord) -> bool:
    if record.source != "companion_orb_target":
        return False
    payload = record.to_mapping()
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    manual = metadata.get("manual_inspection")
    manual = manual if isinstance(manual, Mapping) else {}
    return bool(
        metadata.get("manual_inspection_primary")
        or _focus_bounds(metadata.get("drop_focus_bounds"))
        or _focus_bounds(manual.get("focus_bounds"))
    )


def _orb_suppresses_proactive(records: Sequence[SensoryRecord]) -> bool:
    for record in records:
        if record.source != "companion_orb_target":
            continue
        metadata = record.to_mapping().get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        if metadata.get("suppress_hidden_proactive") or metadata.get(
            "immediate_image_delivery"
        ):
            return True
    return False


def _spotify_action_allowed(records: Sequence[SensoryRecord]) -> bool:
    saw_spotify = False
    for record in records:
        if record.source != "spotify_sense":
            continue
        saw_spotify = True
        metadata = record.to_mapping().get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        if _boolish(metadata.get("hidden_response_allowed")) or _boolish(
            metadata.get("should_speak_recommended")
        ):
            return True
    return not saw_spotify


def _source_has_pingpong_guidance(
    registry: SensoryRegistry,
    source_id: str,
    config: Mapping[str, object],
) -> bool:
    source = str(source_id or "").strip().lower()
    if not source:
        return False
    provider = registry.get_provider(source)
    metadata = dict(getattr(provider, "metadata", None) or {})
    overrides = config.get("sensory_provider_metadata_overrides", {})
    if isinstance(overrides, Mapping):
        source_override = overrides.get(source, {})
        if isinstance(source_override, Mapping):
            metadata_override = source_override.get("metadata", {})
            if isinstance(metadata_override, Mapping):
                metadata.update(dict(metadata_override))
    source_prompts = config.get("sensory_pingpong_source_prompts", {})
    if isinstance(source_prompts, Mapping) and source in source_prompts:
        metadata["pingpong_prompt"] = str(source_prompts.get(source) or "")
    contributor_guidance = any(
        _prompt_contributor_has_active_guidance(
            contributor,
            input_scope="background_check_in",
        )
        for contributor in registry.list_prompt_contributors(source)
    )
    if _boolish(metadata.get("requires_prompt_contributor")):
        return contributor_guidance
    if (
        metadata.get("prompt_fragment_enabled", True) is not False
        and str(metadata.get("pingpong_prompt", "") or "").strip()
    ):
        return True
    return contributor_guidance


def _derive_proactive_candidate(summary: str, attention: str, emotion: str) -> str:
    if summary:
        return summary[:220]
    if attention:
        return f"I noticed the sensory cue: {attention}."[:220]
    if emotion:
        return (
            f"I noticed something worth reacting to and feel {emotion} about it."
        )[:220]
    return ""


def _derive_visual_candidate(summary: str, attention: str, emotion: str) -> str:
    if summary:
        return summary[:220]
    if attention and emotion:
        return f"{attention}, {emotion} mood"[:220]
    if attention:
        return f"sensory scene focused on {attention}"[:220]
    if emotion:
        return f"sensory scene with a {emotion} mood"[:220]
    return ""


def _manual_orb_focus(
    records: Sequence[SensoryRecord],
) -> tuple[tuple[int, int, int, int] | tuple[()], str, str]:
    for record in records:
        if not _manual_orb_record(record):
            continue
        payload = record.to_mapping()
        metadata = payload.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        manual = metadata.get("manual_inspection")
        manual = dict(manual) if isinstance(manual, Mapping) else {}
        bounds = (
            _focus_bounds(metadata.get("drop_focus_bounds"))
            or _focus_bounds(metadata.get("screen_bounds"))
            or _focus_bounds(manual.get("focus_bounds"))
        )
        if bounds:
            return (
                bounds,
                "selected content",
                _clean_text(metadata.get("ocr_text"), 180),
            )
    return (), "", ""


def _manual_trace_id(records: Sequence[SensoryRecord]) -> str:
    for record in records:
        if record.source != "companion_orb_target":
            continue
        metadata = record.to_mapping().get("metadata")
        if isinstance(metadata, Mapping):
            trace_id = str(metadata.get("drop_trace_id", "") or "").strip()
            if trace_id:
                return trace_id
    return ""


def _sanitize_manual_candidate(value: object, *, fallback: bool = True) -> str:
    text = _clean_text(value, 240)
    if not text:
        return ""
    blocked_patterns = (
        r"\bcompanion orb\b.*\b(?:dropped|dragged|sensory ping|manual(?:ly)? dropped|specific region)\b",
        r"\b(?:has been|was|is)\s+(?:manually\s+)?(?:dropped|dragged)\b",
        r"\b(?:dropped|dragged)\s+(?:onto|on|at|to)\b",
        r"\bsensory ping\b",
        r"\bpoint of interest\b",
        r"\bfocus_bounds\b",
        r"\bmetadata\b",
        r"\[[\s\d,.-]{7,}\]",
    )
    cleaned = text
    for pattern in blocked_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:,.")
    generic = {
        "interesting",
        "section",
        "spot",
        "region",
        "area",
        "screen",
        "content",
        "something",
        "here",
        "there",
        "marked",
        "look",
        "looks",
        "little",
        "right",
        "bits",
        "information",
        "thing",
        "things",
        "visible",
    }
    content_tokens = [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_+-]{2,}", cleaned.lower())
        if token not in generic
    ]
    if not cleaned or len(content_tokens) < 2:
        if not fallback:
            return ""
        return (
            "I can see the area, but not enough detail to identify it clearly yet. "
            "Move me a little closer to the detail."
        )
    return cleaned[:220]


def _bounds_center_inside(
    bounds: Sequence[int],
    container: Sequence[int],
    *,
    margin: int = 16,
) -> bool:
    if len(bounds) != 4 or len(container) != 4:
        return False
    x, y, width, height = bounds
    left, top, container_width, container_height = container
    center_x = x + width * 0.5
    center_y = y + height * 0.5
    return bool(
        left - margin <= center_x <= left + container_width + margin
        and top - margin <= center_y <= top + container_height + margin
    )


def _candidate_reuses_stale_history(
    candidate: str,
    summary: str,
    history: Sequence[Mapping[str, object]],
) -> bool:
    candidate_key = _canonical_text(candidate)
    summary_key = _canonical_text(summary)
    if not candidate_key:
        return False
    for entry in reversed(tuple(history)[-6:]):
        if _canonical_text(entry.get("proactive_candidate", "")) != candidate_key:
            continue
        previous_summary = _canonical_text(entry.get("summary", ""))
        if summary_key and previous_summary and summary_key != previous_summary:
            return True
    return False


def _source_matches(contributor_source: object, source_ids: Sequence[str]) -> bool:
    source = str(contributor_source or "").strip().lower()
    selected = {str(item or "").strip().lower() for item in source_ids}
    return bool(
        source in selected
        or (source == "screen" and any("screen" in item for item in selected))
    )


def _prompt_contributor_has_active_guidance(
    contributor: object,
    *,
    input_scope: str = "",
) -> bool:
    if not str(getattr(contributor, "prompt", "") or "").strip():
        return False
    metadata = dict(getattr(contributor, "metadata", None) or {})
    if "active_behaviors" in metadata:
        active_behaviors = tuple(metadata.get("active_behaviors") or ())
        if input_scope:
            scoped_behaviors = tuple(
                behavior
                for behavior in active_behaviors
                if not isinstance(behavior, Mapping)
                or input_scope not in behavior
                or _boolish(behavior.get(input_scope))
            )
            return bool(scoped_behaviors)
        return bool(active_behaviors)
    return True


def _behavior_prompt_active(
    registry: SensoryRegistry,
    source_ids: Sequence[str],
    records: Sequence[SensoryRecord] = (),
) -> bool:
    for contributor in registry.list_prompt_contributors():
        if not _source_matches(contributor.source_id, source_ids):
            continue
        metadata = dict(contributor.metadata or {})
        behavior_type = str(metadata.get("type", "") or "").strip().lower()
        if behavior_type != "behavior_rule" and not contributor.id.endswith(
            ".behavior"
        ):
            continue
        input_scope = ""
        if str(contributor.source_id or "").strip().lower() == "companion_orb_target":
            input_scope = (
                "manual_inspection"
                if any(_manual_orb_record(record) for record in records)
                else "background_check_in"
            )
        if _prompt_contributor_has_active_guidance(
            contributor,
            input_scope=input_scope,
        ):
            return True
    return False


def _orb_supervisor_policy(
    registry: SensoryRegistry,
    source_ids: Sequence[str],
    records: Sequence[SensoryRecord],
    *,
    summary: str,
    attention: str,
    proactive_candidate: str,
    focus_label: str,
    focus_text: str,
    tags: Sequence[str],
) -> dict[str, object]:
    contributors = tuple(
        contributor
        for contributor in registry.list_prompt_contributors("companion_orb_target")
        if contributor.id == "nc.companion_orb_overlay.behavior"
        and str(contributor.prompt or "").strip()
        and _source_matches(contributor.source_id, source_ids)
    )
    manual_cycle = any(_manual_orb_record(record) for record in records)
    input_scope = "manual_inspection" if manual_cycle else "background_check_in"
    behaviors: list[dict[str, object]] = []
    for contributor in contributors:
        metadata = dict(contributor.metadata or {})
        for item in metadata.get("active_behaviors", ()) or ():
            if not isinstance(item, Mapping):
                continue
            if input_scope in item and not _boolish(item.get(input_scope)):
                continue
            behaviors.append(dict(item))
    generic_model_match = any(
        _screen_tag_key(tag) == "companion_orb_supervisor_match" for tag in tags
    )
    selected_rule_ids = _orb_selected_rule_ids(tags)
    model_match = bool(generic_model_match or selected_rule_ids)
    clean_tags = tuple(
        tag
        for tag in tags
        if _screen_tag_key(tag) != "companion_orb_supervisor_match"
        and not re.match(
            r"^\[?orb_rule\s*:",
            str(tag or "").strip(),
            flags=re.IGNORECASE,
        )
        and not re.match(
            r"^\[?orb_subject\s*:",
            str(tag or "").strip(),
            flags=re.IGNORECASE,
        )
    )
    behavior = next(
        (
            item
            for item in behaviors
            if str(item.get("id", "") or "").strip().lower()
            in selected_rule_ids
        ),
        None,
    )
    if behavior is None and generic_model_match:
        if len(behaviors) == 1 and not selected_rule_ids:
            behavior = behaviors[0]
    trigger_matched = behavior is not None
    behavior = dict(behavior or {})
    trigger_terms = _orb_trigger_terms(behavior.get("trigger", ""))
    evidence_key, visual_fingerprint = _orb_snapshot_evidence(records, behavior)
    return {
        "active": bool(contributors and behaviors),
        "matched": bool(model_match and trigger_matched and behavior),
        "model_match": model_match,
        "selected_rule_ids": selected_rule_ids,
        "trigger_matched": trigger_matched,
        "behavior": behavior or None,
        "persona": next(({
            'persona_name': str(c.metadata.get('persona_name', '') or ''),
            'persona_style': str(c.metadata.get('persona_style', '') or ''),
        } for c in contributors if any(
            isinstance(item, Mapping) and item.get('id') == behavior.get('id')
            for item in c.metadata.get('active_behaviors', ()))), {}),
        "trigger": str(behavior.get("trigger", "") or ""),
        "trigger_terms": trigger_terms,
        "repeat_mode": str(behavior.get("repeat_mode", "") or ""),
        "evidence_key": evidence_key,
        "visual_fingerprint": visual_fingerprint,
        "tags": clean_tags,
    }


def _orb_selected_rule_ids(tags: Sequence[str]) -> tuple[str, ...]:
    selected: list[str] = []
    for tag in tags:
        match = re.match(
            r"^\[?orb_rule\s*:\s*([^\]]+?)\s*\]?$",
            str(tag or "").strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        rule_id = str(match.group(1) or "").strip().lower()
        if rule_id and rule_id not in selected:
            selected.append(rule_id)
    return tuple(selected)


_ORB_TRIGGER_STOPWORDS = {
    "activity",
    "another",
    "anything",
    "app",
    "application",
    "around",
    "browser",
    "comment",
    "content",
    "current",
    "detail",
    "image",
    "looks",
    "meaningful",
    "notices",
    "notice",
    "orb",
    "places",
    "reads",
    "screen",
    "sees",
    "selected",
    "showing",
    "shows",
    "site",
    "something",
    "target",
    "text",
    "that",
    "the",
    "this",
    "user",
    "video",
    "view",
    "visible",
    "watching",
    "when",
    "with",
}


def _orb_trigger_decision(
    behaviors: Sequence[Mapping[str, object]],
    records: Sequence[SensoryRecord],
    *,
    summary: str,
    attention: str,
    proactive_candidate: str,
    focus_label: str,
    focus_text: str,
    manual_cycle: bool,
) -> tuple[bool, Mapping[str, object] | None]:
    if not behaviors:
        return False, None
    evidence_parts = [
        summary,
        attention,
        proactive_candidate,
        focus_label,
        focus_text,
    ]
    for record in records:
        if record.source != "companion_orb_target":
            continue
        payload = record.to_mapping()
        metadata = payload.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        target = metadata.get("target")
        target = dict(target) if isinstance(target, Mapping) else {}
        evidence_parts.extend(
            (
                str(metadata.get("ocr_text", "") or ""),
                str(target.get("title", "") or ""),
                str(target.get("process_name", "") or ""),
            )
        )
    evidence = " ".join(str(item or "").lower() for item in evidence_parts if item)
    fallback = dict(behaviors[0])
    for behavior in behaviors:
        behavior_id = str(behavior.get("id", "") or "").strip()
        if behavior_id == "orb_behavior_manual_drop":
            if manual_cycle:
                return True, behavior
            continue
        if behavior_id == "orb_behavior_full_screen_subject":
            return True, behavior
        tokens = _orb_trigger_terms(behavior.get("trigger", ""))
        if not tokens:
            return True, behavior
        if any(
            re.search(
                rf"(?<![a-z0-9_+-]){re.escape(token)}(?![a-z0-9_+-])",
                evidence,
            )
            for token in tokens
        ):
            return True, behavior
    return False, fallback


def _orb_trigger_terms(trigger: object) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            word
            for word in re.findall(
                r"[a-z0-9][a-z0-9_+-]{2,}",
                str(trigger or "").lower(),
            )
            if word not in _ORB_TRIGGER_STOPWORDS
        )
    )


def _orb_snapshot_evidence(
    records: Sequence[SensoryRecord],
    behavior: Mapping[str, object],
) -> tuple[str, str]:
    for record in records:
        if record.source != "companion_orb_target":
            continue
        payload = record.to_mapping()
        metadata = payload.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        target = metadata.get("target")
        target = dict(target) if isinstance(target, Mapping) else {}
        evidence = {
            "behavior": str(behavior.get("id", "") or ""),
            "target_type": str(target.get("type", target.get("target_type", "")) or ""),
            "target_title": str(target.get("title", "") or ""),
            "process_name": str(target.get("process_name", "") or ""),
            "ocr_text": _canonical_text(metadata.get("ocr_text", "")),
        }
        return (
            json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            str(metadata.get("visual_fingerprint", "") or ""),
        )
    return "", ""


def _visual_fingerprints_similar(current: str, previous: str) -> bool:
    current_key = str(current or "").strip().lower()
    previous_key = str(previous or "").strip().lower()
    if not current_key or not previous_key:
        return current_key == previous_key
    if len(current_key) != len(previous_key):
        return False
    try:
        distance = (int(current_key, 16) ^ int(previous_key, 16)).bit_count()
    except (TypeError, ValueError):
        return current_key == previous_key
    return distance <= 12


def _screen_supervisor_policy(
    registry: SensoryRegistry,
    source_ids: Sequence[str],
    *,
    summary: str,
    attention: str,
    proactive_candidate: str,
    tags: Sequence[str],
) -> dict[str, object]:
    contributors = tuple(
        contributor
        for contributor in registry.list_prompt_contributors("screen")
        if contributor.id == "nc.screen_supervisor.behavior"
        and str(contributor.prompt or "").strip()
        and _source_matches(contributor.source_id, source_ids)
    )
    if not contributors:
        return {
            "active": False,
            "matched": False,
            "token_matched": False,
            "behavior": None,
            "trigger": "",
            "subject": "",
            "repeat_key": "",
            "repeat_mode": "",
            "tags": tuple(tags),
        }
    model_match = any(
        _screen_tag_key(tag) == "screen_supervisor_match" for tag in tags
    )
    tagged_subject = _screen_subject_from_tags(tags)
    clean_tags = tuple(
        tag
        for tag in tags
        if _screen_tag_key(tag) != "screen_supervisor_match"
        and not re.match(
            r"^\[?screen_subject\s*:",
            str(tag or "").strip(),
            flags=re.IGNORECASE,
        )
    )
    behaviors = _screen_behaviors(contributors)
    token_matched, behavior = _screen_trigger_decision(
        behaviors,
        summary,
        attention,
        proactive_candidate,
    )
    matched = bool(model_match or token_matched)
    behavior = dict(behavior or {}) if behavior else None
    subject = _extract_screen_subject(summary) or tagged_subject
    if not subject and behavior:
        subject = _canonical_text(summary)
    trigger = str((behavior or {}).get("trigger", "") or "")
    repeat_mode = str((behavior or {}).get("repeat_mode", "") or "")
    repeat_key = (
        f"{_canonical_text(trigger) or 'screen-supervisor'}::"
        f"{_canonical_text(subject) or 'unknown-subject'}"
        if behavior
        else ""
    )
    return {
        "active": True,
        "matched": matched,
        "token_matched": token_matched,
        "behavior": behavior,
        "trigger": trigger,
        "subject": subject,
        "repeat_key": repeat_key,
        "repeat_mode": repeat_mode,
        "tags": clean_tags,
    }


def _screen_behaviors(contributors: Sequence[object]) -> tuple[dict[str, object], ...]:
    behaviors: list[dict[str, object]] = []
    fallback_triggers: list[str] = []
    for contributor in contributors:
        metadata = dict(getattr(contributor, "metadata", None) or {})
        for item in metadata.get("active_behaviors", ()) or ():
            if not isinstance(item, Mapping):
                continue
            trigger = str(item.get("trigger", "") or "").strip()
            if trigger:
                behaviors.append(
                    {
                        "trigger": trigger,
                        "repeat_mode": str(
                            item.get("repeat_mode", "")
                            or "Meaningful change only"
                        ),
                        "repeat_interval": item.get("repeat_interval"),
                    }
                )
        if behaviors:
            continue
        for trigger in re.findall(
            r"Visual Trigger:\s*(.+)",
            str(getattr(contributor, "prompt", "") or ""),
        ):
            trigger = str(trigger or "").strip()
            if trigger and trigger not in fallback_triggers:
                fallback_triggers.append(trigger)
    if behaviors:
        return tuple(behaviors)
    return tuple(
        {"trigger": trigger, "repeat_mode": "Meaningful change only"}
        for trigger in fallback_triggers
    )


_SCREEN_TRIGGER_STOPWORDS = {
    "activity",
    "app",
    "application",
    "browser",
    "content",
    "current",
    "image",
    "page",
    "screen",
    "showing",
    "shows",
    "site",
    "something",
    "that",
    "the",
    "this",
    "user",
    "video",
    "view",
    "visible",
    "watching",
    "with",
}


def _screen_trigger_decision(
    behaviors: Sequence[Mapping[str, object]],
    summary: str,
    attention: str,
    proactive_candidate: str,
) -> tuple[bool, Mapping[str, object] | None]:
    if not behaviors:
        return True, None
    full_text = " ".join(
        item.lower()
        for item in (summary, attention, proactive_candidate)
        if item
    )
    current_text = re.sub(
        r"^.*?\b(?:switched|changed|went)\s+from\b.*?\bto\s+",
        "",
        full_text,
        flags=re.IGNORECASE,
    )
    fallback = dict(behaviors[0])
    saw_tokens = False
    for behavior in behaviors:
        trigger = str(behavior.get("trigger", "") or "")
        tokens = [
            word
            for word in re.findall(r"[a-z0-9][a-z0-9_+-]{2,}", trigger.lower())
            if word not in _SCREEN_TRIGGER_STOPWORDS
        ]
        if not tokens:
            continue
        saw_tokens = True
        for token in tokens:
            pattern = rf"(?<![a-z0-9_+-]){re.escape(token)}(?![a-z0-9_+-])"
            if re.search(pattern, current_text):
                return True, behavior
            if re.search(pattern, full_text):
                return False, behavior
    return (True, fallback) if not saw_tokens else (False, fallback)


def _screen_tag_key(tag: object) -> str:
    return re.sub(
        r"[\s-]+",
        "_",
        str(tag or "").strip().lower().strip("[]").strip(),
    )


def _screen_subject_from_tags(tags: Sequence[str]) -> str:
    for tag in tags:
        match = re.match(
            r"^\[?screen_subject\s*:\s*(?P<subject>.+?)\]?$",
            str(tag or "").strip(),
            flags=re.IGNORECASE,
        )
        if match:
            subject = _canonical_text(match.group("subject"))
            if subject:
                return subject[:180]
    return ""


def _extract_screen_subject(summary: str) -> str:
    text = re.sub(r"\s+", " ", str(summary or "")).strip()
    patterns = (
        r"\b(?:video|post|thread|article|page|item)\s*:\s*['\"“”‘’](?P<title>.+?)['\"“”‘’]",
        r"\b(?:titled|called|named)\s+['\"“”‘’](?P<title>.+?)['\"“”‘’]",
        r"\b(?:watching|viewing|browsing|reading|playing)\s+['\"“”‘’](?P<title>.+?)['\"“”‘’]",
        r"\bswitched\s+from\b.+?\bto\s+(?P<title>.+?)(?:[.;]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            subject = _canonical_text(match.group("title"))
            if subject:
                return subject[:180]
    quoted = re.findall(r"['\"“”‘’]([^'\"“”‘’]{4,})['\"“”‘’]", text)
    return _canonical_text(quoted[-1])[:180] if quoted else ""


def _subject_keys_similar(left: str, right: str) -> bool:
    left_key = _canonical_text(left)
    right_key = _canonical_text(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key or left_key in right_key or right_key in left_key:
        return True
    ignored = {
        "activity",
        "content",
        "current",
        "image",
        "page",
        "screen",
        "showing",
        "the",
        "user",
        "video",
        "visible",
    }
    left_tokens = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_+-]{2,}", left_key)
        if token not in ignored
    }
    right_tokens = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_+-]{2,}", right_key)
        if token not in ignored
    }
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    return bool(overlap >= 2 and overlap / min(len(left_tokens), len(right_tokens)) >= 0.5)


def _extract_json_object(text: object) -> dict[str, object] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(raw[start : end + 1])
    except (TypeError, ValueError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def _repair_sensory_json(text: object) -> str:
    repaired = str(text or "").strip()
    if not repaired:
        return ""
    repaired = (
        repaired.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    repaired = re.sub(
        r'"visual\s+candidate"',
        '"visual_candidate"',
        repaired,
        flags=re.IGNORECASE,
    )
    repaired = re.sub(
        r'"visualCandidate"',
        '"visual_candidate"',
        repaired,
        flags=re.IGNORECASE,
    )
    keys = (
        "keep|emotion|attention|summary|proactive_candidate|visual_candidate|"
        "should_speak|should_generate_image|focus_bounds|focus_label|focus_text|tags"
    )
    repaired = re.sub(rf'(?<!")\b({keys})\b\s*:', r'"\1":', repaired)
    for key in (
        "emotion",
        "attention",
        "summary",
        "proactive_candidate",
        "visual_candidate",
        "focus_label",
        "focus_text",
    ):
        repaired = re.sub(
            rf'("{key}"\s*:\s*)([A-Za-z_][A-Za-z0-9_\- ]*)(?=\s*[,}}])',
            lambda match: match.group(1)
            + '"'
            + match.group(2).strip().rstrip('"')
            + '"',
            repaired,
        )
        repaired = re.sub(
            rf'("{key}"\s*:\s*)([A-Za-z_][A-Za-z0-9_\- ]*)"\s*(?=[,}}])',
            lambda match: match.group(1)
            + '"'
            + match.group(2).strip()
            + '"',
            repaired,
        )
    return re.sub(r",\s*([}\]])", r"\1", repaired)


def _normalized_quote_text(text: object) -> str:
    return (
        str(text or "")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )


def _extract_string_field(text: object, *keys: str) -> str:
    raw = _normalized_quote_text(text)
    for key in keys:
        key_pattern = re.escape(str(key or "")).replace(r"\ ", r"\s+")
        match = re.search(
            rf'["\']?{key_pattern}["\']?\s*:?\s*(["\'])'
            rf'(?P<value>(?:\\.|(?!\1).)*?)\1',
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            value = match.group("value")
            if "\\" in value:
                value = value.replace(r'\"', '"').replace(r"\'", "'")
            return re.sub(r"\s+", " ", value).strip()
    return ""


def _extract_bool_field(text: object, *keys: str) -> bool:
    raw = _normalized_quote_text(text)
    for key in keys:
        key_pattern = re.escape(str(key or "")).replace(r"\ ", r"\s+")
        match = re.search(
            rf'["\']?{key_pattern}["\']?\s*:?\s*'
            r"(?P<value>true|false|yes|no|on|off|1|0)\b",
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return _boolish(match.group("value"))
    return False


def _extract_tags_field(text: object) -> list[str]:
    raw = _normalized_quote_text(text)
    match = re.search(
        r'["\']?tags["\']?\s*:?\s*\[(?P<items>[^\]]*)\]',
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    tags: list[str] = []
    for item in re.findall(r'(["\'])(?P<value>.*?)(?:\1)', match.group("items")):
        value = _clean_text(item[1], 80)
        if value and value not in tags:
            tags.append(value)
    return tags


def _coerce_sensory_text(text: object) -> dict[str, object] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    payload = {
        "keep": _extract_bool_field(raw, "keep"),
        "emotion": _extract_string_field(raw, "emotion"),
        "attention": _extract_string_field(raw, "attention"),
        "summary": _extract_string_field(raw, "summary"),
        "proactive_candidate": _extract_string_field(
            raw,
            "proactive_candidate",
            "proactive candidate",
            "proactive",
        ),
        "visual_candidate": _extract_string_field(
            raw,
            "visual_candidate",
            "visual candidate",
            "visualCandidate",
        ),
        "should_speak": _extract_bool_field(raw, "should_speak", "should speak"),
        "should_generate_image": _extract_bool_field(
            raw,
            "should_generate_image",
            "should generate image",
            "visual_generate_image",
        ),
        "focus_bounds": [],
        "focus_label": _extract_string_field(raw, "focus_label", "focus label"),
        "focus_text": _extract_string_field(raw, "focus_text", "focus text"),
        "tags": _extract_tags_field(raw),
    }
    return payload if any(payload.values()) else None


def _parse_sensory_result(text: object) -> dict[str, object] | None:
    payload = _extract_json_object(text)
    repaired = False
    if payload is None:
        repaired_text = _repair_sensory_json(text)
        if repaired_text and repaired_text != str(text or ""):
            payload = _extract_json_object(repaired_text)
            repaired = payload is not None
    if payload is None:
        payload = _coerce_sensory_text(text)
        repaired = payload is not None
    if payload is None:
        return None
    if set(payload) == {'matches'}:
        return {'matches': payload['matches']}
    emotion = _clean_text(payload.get("emotion"), 40, lower=True)
    attention = _clean_text(payload.get("attention"), 80, lower=True)
    summary = _clean_text(payload.get("summary"), 220)
    proactive = _clean_text(payload.get("proactive_candidate"), 4000)
    visual = _clean_text(payload.get("visual_candidate"), 220)
    should_speak = _boolish(payload.get("should_speak"))
    should_generate = _boolish(payload.get("should_generate_image"))
    if should_speak and not proactive:
        proactive = _derive_proactive_candidate(summary, attention, emotion)
    if should_generate and not visual:
        visual = _derive_visual_candidate(summary, attention, emotion)
    bounds = _focus_bounds(
        payload.get("focus_bounds") or payload.get("focusBounds") or ()
    )
    focus_label = _clean_text(
        payload.get("focus_label") or payload.get("focusLabel"),
        80,
    )
    focus_text = _clean_text(
        payload.get("focus_text") or payload.get("focusText"),
        180,
    )
    tags = _unique_texts(payload.get("tags"), 80)
    meaningful = bool(
        emotion
        or attention
        or summary
        or proactive
        or visual
        or bounds
        or focus_label
        or focus_text
        or should_speak
        or should_generate
        or tags
    )
    result: dict[str, object] = {
        "keep": bool(_boolish(payload.get("keep")) or meaningful),
        "emotion": emotion,
        "attention": attention,
        "summary": summary,
        "proactive_candidate": proactive,
        "visual_candidate": visual,
        "should_speak": should_speak,
        "should_generate_image": should_generate,
        "focus_bounds": bounds,
        "focus_label": focus_label,
        "focus_text": focus_text,
        "tags": tags[:12],
    }
    if repaired:
        result["_repaired_json"] = True
    if 'matches' in payload:
        result['matches'] = payload['matches']
    return result


def _coerce_model_result(
    model_result: Mapping[str, object] | str,
) -> dict[str, object]:
    if isinstance(model_result, Mapping):
        return {str(key): _thaw(value) for key, value in model_result.items()}
    if isinstance(model_result, str):
        parsed = _parse_sensory_result(model_result)
        if isinstance(parsed, Mapping):
            return {str(key): _thaw(value) for key, value in parsed.items()}
    return {}


def _clean_text(value: object, limit: int, *, lower: bool = False) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if lower:
        text = text.lower()
    return text[: max(0, int(limit))]


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _focus_bounds(value: object) -> tuple[int, int, int, int] | tuple[()]:
    try:
        values = tuple(int(item) for item in list(value or ())[:4])
    except (TypeError, ValueError):
        return ()
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        return ()
    return values


def _unique_texts(value: object, limit: int) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    result = []
    for item in value:
        text = _clean_text(item, limit)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _canonical_text(value: object) -> str:
    text = _clean_text(value, 220, lower=True)
    return " ".join(
        part for part in "".join(
            character if character.isalnum() else " " for character in text
        ).split()
        if part
    )


def _proactive_request(
    payload: Mapping[str, object],
    now: float,
) -> dict[str, object] | None:
    candidate = _clean_text(
        payload.get("candidate") or payload.get("proactive_candidate"),
        4000,
    )
    action = payload.get('supervisor_action')
    if isinstance(action, Mapping) and str(action.get('action', '')).strip():
        candidate = str(action['action'])
    if not candidate:
        return None
    bounds = _focus_bounds(payload.get("focus_bounds"))
    request: dict[str, object] = {
        "candidate": candidate,
        "summary": _clean_text(payload.get("summary"), 220),
        "attention": _clean_text(payload.get("attention"), 80, lower=True),
        "emotion": _clean_text(payload.get("emotion"), 40, lower=True),
        "source": _clean_text(payload.get("source") or "sensory", 40, lower=True)
        or "sensory",
        "created_at": float(payload.get("created_at", now) or now),
        "focus_duration_seconds": max(
            1.0,
            min(30.0, float(payload.get("focus_duration_seconds", 14.0) or 14.0)),
        ),
    }
    if isinstance(action, Mapping):
        request['supervisor_action'] = _copy_mapping(action)
    if 'orb_watch' in payload:
        request['orb_watch'] = _thaw(payload['orb_watch'])
    actions = payload.get('supervisor_actions')
    if isinstance(actions, (list, tuple)) and actions:
        request['supervisor_actions'] = [_copy_mapping(item) for item in actions]
        # Do not truncate a batch's configured action text to the legacy cue limit.
        request['candidate'] = '\n'.join(str(item['action']) for item in actions)
        if payload.get('supervisor_images'):
            request['supervisor_images'] = _thaw(payload['supervisor_images'])
    if bounds:
        request["focus_bounds"] = list(bounds)
    focus_label = _clean_text(payload.get("focus_label"), 80)
    focus_text = _clean_text(payload.get("focus_text"), 160)
    trace_id = _clean_text(payload.get("trace_id"), 80)
    if focus_label:
        request["focus_label"] = focus_label
    if focus_text:
        request["focus_text"] = focus_text
    if trace_id:
        request["trace_id"] = trace_id
    return request


def _failure(
    category: str,
    message: str,
    cause: BaseException | None = None,
) -> CommandResult:
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


def _stale_cycle() -> CommandResult:
    return _failure(
        "sensory_stale_cycle",
        "Sensory work no longer owns the active cycle",
    )


def _stale_lease() -> CommandResult:
    return _failure("sensory_stale_lease", "Sensory work lease is stale")


__all__ = [
    "SensoryCapabilities",
    "SensoryCycle",
    "SensoryDecision",
    "SensoryEffect",
    "SensoryService",
    "SensorySnapshot",
    "SensoryStateSnapshot",
]
