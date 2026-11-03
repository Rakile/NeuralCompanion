"""Bounded deterministic events and per-session lifecycle, owned by MPRC."""

from __future__ import annotations
import copy
import operator
import threading
import hashlib
from collections import deque
from dataclasses import dataclass, replace
from uuid import uuid4
from .scenario_models import ScenarioDefinition, ScenarioValidationError
from .scenario_storage import ScenarioRepository, SessionCheckpoint
from .scenario_actions import ActionDispatcher, ActionRequest, ActionResult


@dataclass(frozen=True)
class ScenarioEvent:
    id: str
    trigger: str
    root_id: str
    payload: dict
    depth: int = 0


def evaluate_condition(condition, values) -> bool:
    if condition is None:
        return True
    if condition["op"] in ("all", "any"):
        results = [evaluate_condition(c, values) for c in condition["children"]]
        return all(results) if condition["op"] == "all" else any(results)
    operations = {
        "eq": operator.eq,
        "ne": operator.ne,
        "lt": operator.lt,
        "le": operator.le,
        "gt": operator.gt,
        "ge": operator.ge,
    }
    return operations[condition["op"]](
        values[condition["variable_id"]], condition["value"]
    )


class ScenarioRuntime:
    def __init__(self, repository: ScenarioRepository, dispatcher: ActionDispatcher):
        self.repository = repository
        self.dispatcher = dispatcher
        self._cp = None
        self._generation = 0
        self._lock = threading.RLock()

    def is_current(self, session_id: str, generation: int) -> bool:
        cp = self._cp
        return (
            cp is not None
            and not cp.paused
            and cp.session_id == session_id
            and generation == self._generation
        )

    def invalidate(self) -> None:
        # Intentionally independent from I/O lock: GUI stop never waits for disk/model work.
        self._generation += 1

    def _save(self, cp):
        self._cp = self.repository.save_checkpoint(
            cp, expected_revision=cp.checkpoint_revision or None
        )
        return self.snapshot()

    def start(self, story_id: str, definition: ScenarioDefinition) -> SessionCheckpoint:
        with self._lock:
            self.invalidate()
            cp = replace(
                SessionCheckpoint.create(story_id, definition),
                generation=self._generation,
            )
            return self._save(cp)

    def resume(self, story_id: str, session_id: str) -> SessionCheckpoint:
        with self._lock:
            cp = self.repository.recover(
                self.repository.load_checkpoint(story_id, session_id)
            )
            self._generation = max(self._generation + 1, cp.generation)
            return self._save(replace(cp, generation=self._generation))

    def snapshot(self) -> SessionCheckpoint:
        if self._cp is None:
            raise ScenarioValidationError("No scenario session loaded")
        return copy.deepcopy(self._cp)

    def stop(self) -> SessionCheckpoint:
        self.invalidate()
        with self._lock:
            return self._save(
                replace(self.snapshot(), generation=self._generation, paused=True)
            )

    def restart(self) -> SessionCheckpoint:
        cp = self.snapshot()
        return self.start(cp.story_id, cp.definition)

    def play(self) -> SessionCheckpoint:
        with self._lock:
            cp = self.snapshot()
            first = not cp.started
            self._save(
                replace(cp, paused=False, started=True, generation=self._generation)
            )
            if first:
                if cp.definition.opening:
                    self._action(
                        {
                            "id": "opening",
                            "action_id": "mprc.story.narrate",
                            "arguments": {"text": cp.definition.opening},
                        },
                        "opening",
                        "start",
                    )
                self.emit(ScenarioEvent("start", "session_started", "start", {}))
            return self.snapshot()

    def _action(self, effect, request_id, event_id="", source="scenario_event"):
        cp = self.snapshot()
        request = ActionRequest(
            request_id,
            effect["action_id"],
            effect["arguments"],
            source,
            cp.story_id,
            cp.session_id,
            cp.generation,
            event_id,
            effect["id"],
        )
        updated, result = self.dispatcher.dispatch(request, cp)
        self._cp = updated
        return result

    def execute_choice(
        self, choice_id: str, *, request_id: str
    ) -> tuple[ActionResult, ...]:
        with self._lock:
            cp = self.snapshot()
            if not self.is_current(cp.session_id, cp.generation):
                return ()
            choice = next(
                (c for c in cp.definition.payload()["choices"] if c["id"] == choice_id),
                None,
            )
            if choice is None or not evaluate_condition(
                choice["condition"], cp.variables
            ):
                return (
                    ActionResult(
                        request_id, "rejected", {}, "Choice is not currently available"
                    ),
                )
            existing = request_id in cp.effects
            result = self._action(choice["effect"], request_id, source="manual")
            if result.status != "success" or existing:
                return (result,)
            seeds = [
                ScenarioEvent(
                    request_id, "choice_clicked", request_id, {"choice_id": choice_id}
                ),
                ScenarioEvent(
                    request_id + "-action",
                    "action_completed",
                    request_id,
                    dict(result.output),
                ),
            ]
            return (result,) + self._process(seeds)

    def emit(self, event: ScenarioEvent) -> tuple[ActionResult, ...]:
        with self._lock:
            return self._process([event])

    def retry_event(self, event_id: str) -> tuple[ActionResult, ...]:
        """Explicit retry of a partially failed once-event; never replay successes or uncertain work."""
        with self._lock:
            cp = self.snapshot()
            request_id = uuid4().hex
            rule = next(
                (
                    r
                    for r in cp.definition.payload()["events"]
                    if r["id"] == event_id and r["once"]
                ),
                None,
            )
            if (
                not self.is_current(cp.session_id, cp.generation)
                or rule is None
                or event_id in cp.completed_events
            ):
                return (
                    ActionResult(
                        request_id, "rejected", {}, "No retryable once-event selected"
                    ),
                )
            if not evaluate_condition(rule["condition"], cp.variables):
                return (
                    ActionResult(
                        request_id, "rejected", {}, "Event condition is no longer true"
                    ),
                )
            records = [r for r in cp.effects.values() if r.get("event_id") == event_id]
            if not any(r["status"] == "failed" for r in records):
                return (
                    ActionResult(
                        request_id, "rejected", {}, "No failed effect to retry"
                    ),
                )
            if any(r["status"] in ("pending", "indeterminate") for r in records):
                return (
                    ActionResult(
                        request_id,
                        "rejected",
                        {},
                        "An effect has an uncertain outcome; automatic or event retry is blocked",
                    ),
                )
            completed = {r["effect_id"] for r in records if r["status"] == "completed"}
            results = []
            seeds = []
            for effect in rule["effects"]:
                if effect["id"] in completed:
                    continue
                identity = hashlib.sha256(
                    f"{request_id}:{effect['id']}".encode()
                ).hexdigest()
                result = self._action(effect, identity, event_id)
                results.append(result)
                if result.status != "success":
                    return tuple(results)
                seeds.append(
                    ScenarioEvent(
                        identity, "action_completed", request_id, dict(result.output)
                    )
                )
            cp = self.snapshot()
            self._save(replace(cp, completed_events=cp.completed_events + (event_id,)))
            return tuple(results) + self._process(seeds)

    def _process(self, seeds):
        queue = deque(seeds)
        results = []
        processed = 0
        while queue:
            cp = self.snapshot()
            if not self.is_current(cp.session_id, cp.generation):
                break
            event = queue.popleft()
            processed += 1
            if processed > 32 or event.depth > 8:
                results.append(
                    ActionResult(
                        event.root_id,
                        "rejected",
                        {},
                        "Scenario event limit reached; chain stopped",
                    )
                )
                break
            payload = cp.definition.payload()
            if event.trigger == "action_completed" and event.payload.get("changed"):
                scene = next(
                    s for s in payload["scenes"] if s["id"] == event.payload["scene_id"]
                )
                rules = [
                    {
                        "id": "entry-" + scene["id"],
                        "effects": scene["effects"],
                        "condition": None,
                        "once": False,
                    }
                ]
            else:
                rules = []
            rules += [e for e in payload["events"] if e["trigger"] == event.trigger]
            for rule in rules:
                cp = self.snapshot()
                if rule["once"] and rule["id"] in cp.completed_events:
                    continue
                if not evaluate_condition(rule["condition"], cp.variables):
                    continue
                success = True
                for index, effect in enumerate(rule["effects"]):
                    raw_identity = (
                        f"once:{rule['id']}:{effect['id']}"
                        if rule["once"]
                        else f"{event.root_id}:{processed}:{rule['id']}:{index}"
                    )
                    identity = hashlib.sha256(raw_identity.encode()).hexdigest()
                    if (
                        rule["once"]
                        and self.snapshot().effects.get(identity, {}).get("status")
                        == "completed"
                    ):
                        continue
                    result = self._action(effect, identity, rule["id"])
                    results.append(result)
                    if result.status != "success":
                        success = False
                        break
                    queue.append(
                        ScenarioEvent(
                            identity,
                            "action_completed",
                            event.root_id,
                            dict(result.output),
                            event.depth + 1,
                        )
                    )
                if success and rule["once"]:
                    cp = self.snapshot()
                    self._save(
                        replace(
                            cp, completed_events=cp.completed_events + (rule["id"],)
                        )
                    )
        return tuple(results)
