"""MPRC-only action admission and durable request deduplication."""

from __future__ import annotations
import copy
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Protocol
from .scenario_models import JSONValue, validate_action, ScenarioValidationError
from .scenario_storage import ScenarioRepository, SessionCheckpoint


@dataclass(frozen=True)
class ActionRequest:
    request_id: str
    action_id: str
    arguments: Mapping[str, JSONValue]
    source: str
    story_id: str
    session_id: str
    generation: int
    event_id: str = ""
    effect_id: str = ""


@dataclass(frozen=True)
class ActionResult:
    request_id: str
    status: str
    output: Mapping[str, JSONValue]
    message: str


class NarrationPort(Protocol):
    def admit(
        self,
        text: str,
        *,
        session_id: str,
        generation: int,
        request_id: str,
        timeout_seconds: float,
    ) -> ActionResult: ...


class ActionDispatcher:
    def __init__(
        self,
        repository: ScenarioRepository,
        narration: NarrationPort,
        is_current: Callable[[str, int], bool],
    ):
        self.repository = repository
        self.narration = narration
        self.is_current = is_current
        self._lock = threading.RLock()

    def dispatch(
        self, request: ActionRequest, checkpoint: SessionCheckpoint
    ) -> tuple[SessionCheckpoint, ActionResult]:
        with self._lock:
            return self._dispatch(request, checkpoint)

    def _dispatch(self, request, checkpoint):
        def result(status, message, output=None):
            return ActionResult(request.request_id, status, output or {}, message)

        current = lambda: self.is_current(request.session_id, request.generation)
        if (
            checkpoint.paused
            or not checkpoint.definition.enabled
            or request.source not in ("manual", "scenario_event")
            or request.story_id != checkpoint.story_id
            or request.session_id != checkpoint.session_id
            or request.generation != checkpoint.generation
            or not current()
            or not isinstance(request.request_id, str)
            or not 1 <= len(request.request_id) <= 240
        ):
            return checkpoint, result(
                "rejected", "Inactive scenario, stale request or forbidden source"
            )
        try:
            validate_action(
                request.action_id,
                dict(request.arguments),
                checkpoint.definition.payload(),
            )
        except (ScenarioValidationError, TypeError, ValueError):
            return checkpoint, result(
                "rejected", "Invalid or unavailable scenario action"
            )
        prior = checkpoint.effects.get(request.request_id)
        if prior:
            status = (
                "success"
                if prior["status"] == "completed"
                else prior.get("result_status", "indeterminate")
            )
            return checkpoint, result(
                status,
                "Request already recorded; no effect repeated",
                prior.get("output", {}),
            )
        if len(checkpoint.effects) >= 10000:
            return checkpoint, result(
                "rejected", "Scenario journal is full; save and start a new session"
            )
        effects = copy.deepcopy(checkpoint.effects)
        record = {
            "event_id": request.event_id,
            "effect_id": request.effect_id,
            "status": "pending",
            "dispatch_started": False,
            "output": {},
        }
        effects[request.request_id] = record

        def save(cp):
            return self.repository.save_checkpoint(
                cp, expected_revision=cp.checkpoint_revision
            )

        checkpoint = save(replace(checkpoint, effects=effects))
        if not current():
            return checkpoint, result(
                "cancelled", "Scenario stopped before action admission"
            )
        durable_checkpoint = checkpoint
        if request.action_id == "mprc.story.narrate":
            effects = copy.deepcopy(checkpoint.effects)
            effects[request.request_id]["dispatch_started"] = True
            checkpoint = save(replace(checkpoint, effects=effects))
            durable_checkpoint = checkpoint
            if not current():
                return checkpoint, result(
                    "cancelled", "Scenario stopped before narration"
                )
            try:
                outcome = self.narration.admit(
                    str(request.arguments["text"]),
                    session_id=request.session_id,
                    generation=request.generation,
                    request_id=request.request_id,
                    timeout_seconds=10.0,
                )
            except Exception:
                outcome = result(
                    "indeterminate",
                    "Narration admission was interrupted; it will not be retried automatically",
                )
        elif request.action_id == "mprc.scenario.set_state":
            values = dict(checkpoint.variables)
            values[str(request.arguments["variable_id"])] = request.arguments["value"]
            checkpoint = replace(checkpoint, variables=values)
            outcome = result("success", "Scenario variable updated")
        else:
            scene_id = str(request.arguments["scene_id"])
            changed = checkpoint.scene_id != scene_id
            checkpoint = replace(checkpoint, scene_id=scene_id)
            outcome = result(
                "success",
                "Scene changed" if changed else "Scene already selected",
                {"changed": changed, "scene_id": scene_id},
            )
        if not current():
            return durable_checkpoint, result(
                "cancelled", "Late action result discarded"
            )
        effects = copy.deepcopy(checkpoint.effects)
        effects[request.request_id].update(
            status="completed"
            if outcome.status == "success"
            else "indeterminate"
            if outcome.status == "indeterminate"
            else "failed",
            result_status=outcome.status,
            output=dict(outcome.output),
            message=outcome.message,
        )
        checkpoint = save(replace(checkpoint, effects=effects))
        return checkpoint, outcome
