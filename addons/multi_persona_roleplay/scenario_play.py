"""Scenario adapter for isolated MPRC Play. Disk and effects run on one worker lane."""

from __future__ import annotations
import copy
import json
import threading
import time
from dataclasses import dataclass
from collections import deque
from uuid import uuid4
from .scenario_actions import ActionDispatcher, ActionResult
from .scenario_lore import LoreContext, LoreBudget, select_lore, estimate_tokens
from .scenario_models import parse_scenario
from .scenario_runtime import ScenarioRuntime, ScenarioEvent, evaluate_condition
from .scenario_storage import ScenarioRepository


@dataclass(frozen=True)
class ScenarioPrompt:
    checkpoint: object
    epoch: int
    history: tuple
    context_limit: int
    reply_reserve: int


class ScenarioNarration:
    def __init__(self, owner):
        self.owner = owner

    def admit(
        self,
        text: str,
        *,
        session_id: str,
        generation: int,
        request_id: str,
        timeout_seconds: float,
    ) -> ActionResult:
        controller = self.owner.controller
        done = threading.Event()
        expired = threading.Event()
        result = []
        text_admitted = False
        deadline = time.monotonic() + timeout_seconds

        def current():
            return (
                self.owner._active
                and not expired.is_set()
                and time.monotonic() < deadline
                and not controller.is_shutdown()
                and self.owner.runtime.is_current(session_id, generation)
            )

        def complete(accepted, message):
            if not current():
                return
            status = "success" if text_admitted else "rejected"
            detail = (
                (
                    "Narration shown; speech admitted."
                    if accepted
                    else "Narration shown; speech unavailable: " + message
                )
                if text_admitted
                else message
            )
            result.append(
                ActionResult(
                    request_id, status, {"speech_admitted": bool(accepted)}, detail
                )
            )
            done.set()

        def enqueue():
            nonlocal text_admitted
            if not current():
                return
            busy = controller._engine_speech_status(strict=True)
            if (
                controller._mprc_pending_chat_users
                or controller._mprc_tts_token
                or busy.get("speech_playing")
                or busy.get("speech_paused")
            ):
                complete(
                    False,
                    "Speech or a story turn is busy. Retry this choice when idle.",
                )
                return
            content = "[NARRATOR]\n" + text
            controller._append_chat_play_line("Story", content, role="assistant")
            controller._remember_mprc_chat_message(
                {"role": "assistant", "content": content}
            )
            text_admitted = True
            controller._speak_mprc_chat_reply(
                content, on_admitted=complete, guard=current
            )

        try:
            # This method runs on the scenario worker. Let existing reply speech finish;
            # the GUI callback still rechecks the owner immediately before dispatch.
            while current():
                busy = controller._engine_speech_status(strict=True)
                if (
                    not controller._mprc_tts_token
                    and not busy.get("speech_playing")
                    and not busy.get("speech_paused")
                ):
                    break
                done.wait(min(0.05, max(0, deadline - time.monotonic())))
            if not current():
                return ActionResult(
                    request_id,
                    "rejected",
                    {},
                    "Narration was not admitted before the session stopped or speech wait expired",
                )
            controller._run_remote_on_ui_thread(enqueue, timeout=timeout_seconds)
            if not done.wait(max(0, deadline - time.monotonic())):
                expired.set()
                return ActionResult(
                    request_id,
                    "indeterminate",
                    {},
                    "Narration admission timed out; it will not be retried automatically",
                )
            return result[0]
        except Exception as exc:
            return ActionResult(
                request_id,
                "indeterminate",
                {},
                "Narration admission interrupted: " + str(exc),
            )
        finally:
            expired.set()


class ScenarioPlay:
    def __init__(self, controller):
        self.controller = controller
        self.repository = ScenarioRepository(
            controller.context.storage.resolve("scenario_progress")
        )
        self.narration = ScenarioNarration(self)
        self.runtime = ScenarioRuntime(
            self.repository,
            ActionDispatcher(
                self.repository,
                self.narration,
                lambda s, g: self._active and self.runtime.is_current(s, g),
            ),
        )
        self._queue = deque()
        self._queue_lock = threading.Lock()
        self._running = False
        self._epoch = 0
        self._active = False
        self._cached = None
        self._status = "Scenario paused."
        self._lore = ""

    @property
    def enabled(self):
        extension = self.controller.settings.get("active_scenario_extension")
        return isinstance(extension, dict) and extension.get("enabled") is True

    @property
    def ready(self):
        return self._active and not self._running and self._cached is not None

    def _submit(self, operation):
        with self._queue_lock:
            self._queue.append(operation)
            if self._running:
                return
            self._running = True
        token = self.controller._new_worker_token("mprc_scenario")

        def worker():
            try:
                while True:
                    with self._queue_lock:
                        if not self._queue:
                            self._running = False
                            break
                        work = self._queue.popleft()
                    try:
                        work()
                        self._refresh()
                    except Exception as exc:
                        self.runtime.invalidate()
                        self._active = False
                        self._status = "Scenario paused: " + str(exc)
            finally:
                self.controller._finish_worker_token(token)

        if not token or not self.controller._start_daemon_worker(
            token, worker, name="nc-mprc-scenario"
        ):
            with self._queue_lock:
                self._running = False
                self._queue.clear()
            self._status = "Could not start scenario worker."
            self._active = False

    def start(self, *, restart=False):
        if not self.enabled:
            return
        if self._active and not restart:
            return
        self._epoch += 1
        epoch = self._epoch
        self.runtime.invalidate()
        self._active = False
        story_id = str(
            self.controller.settings.get("active_scenario_story_id")
            or self.controller.settings.get("last_master_story_id")
            or "story"
        )
        raw = copy.deepcopy(self.controller.settings["active_scenario_extension"])
        self._status = "Loading scenario progress…"

        def load():
            if epoch != self._epoch:
                return
            definition = parse_scenario(
                raw,
                persona_ids=frozenset(r["persona_id"] for r in raw.get("roles", [])),
            )
            previous = None if restart else self.repository.latest_checkpoint(story_id)
            if epoch != self._epoch:
                return
            if previous and previous.definition.id == definition.id:
                self.runtime.resume(story_id, previous.session_id)
                self._status = (
                    "Resumed captured revision "
                    + str(previous.definition.revision)
                    + ". Restart to use the latest applied definition."
                )
            else:
                self.runtime.start(story_id, definition)
                self._status = "New scenario started."
            if epoch != self._epoch:
                self.runtime.stop()
                return
            self._active = True
            self.runtime.play()

        self._submit(load)

    def stop(self):
        self._epoch += 1
        self._active = False
        self.runtime.invalidate()
        self._status = "Scenario stopped. Progress is saved; Start resumes without replaying effects."

        def persist():
            if self.runtime._cp is not None:
                self.runtime.stop()

        self._submit(persist)

    def _refresh(self):
        if self.runtime._cp is not None:
            self._cached = self.runtime.snapshot()
        cp = self._cached
        if cp is None:
            return

        def sync():
            if not self._active or not self.runtime.is_current(
                cp.session_id, cp.generation
            ):
                return
            scene = next(
                s for s in cp.definition.payload()["scenes"] if s["id"] == cp.scene_id
            )
            self.controller.session.ar_state.current_scene = scene["title"]
            self.controller.session.ar_state.location = scene["location"]
            self.controller.session.scene_title = scene["title"]
            self.controller.session.location = scene["location"]
            self.controller.refresh_ui()

        if not self.controller.is_shutdown():
            self.controller._run_remote_on_ui_thread(sync, timeout=10)

    def choose(self, choice_id):
        if not self.ready:
            self._status = (
                "Wait for the current scenario operation to finish, then choose again."
            )
            return
        request_id = uuid4().hex
        epoch = self._epoch

        def execute():
            if epoch != self._epoch or not self._active:
                return
            results = self.runtime.execute_choice(choice_id, request_id=request_id)
            self._status = (
                "; ".join(r.message for r in results) or "Choice unavailable."
            )

        self._submit(execute)

    def turn_completed(self, turn_id: str):
        if not self._active:
            return
        epoch = self._epoch

        def emit():
            if epoch != self._epoch:
                return
            results = self.runtime.emit(
                ScenarioEvent(turn_id, "user_turn_completed", turn_id, {})
            )
            if results:
                self._status = "; ".join(r.message for r in results)

        self._submit(emit)

    def retry(self, event_id: str):
        if not self.ready:
            return
        epoch = self._epoch

        def execute():
            if epoch != self._epoch:
                return
            self._status = "; ".join(
                r.message for r in self.runtime.retry_event(event_id)
            )

        self._submit(execute)

    def capture_prompt(self) -> ScenarioPrompt | None:
        if not self._active or self._cached is None:
            return None
        return ScenarioPrompt(
            self._cached,
            self._epoch,
            tuple(copy.deepcopy(self.controller._mprc_chat_history[-10:])),
            int(
                self.controller.settings.get("master_story_scenario_context_limit", 0)
                or 0
            ),
            int(
                self.controller.settings.get(
                    "master_story_scenario_reply_reserve", 1024
                )
                or 1024
            ),
        )

    def overlay(
        self, messages: list[dict], player_text: str, *, captured=None, extra_tokens=0
    ) -> list[dict]:
        captured = captured or self.capture_prompt()
        if captured is None:
            return messages
        cp = captured.checkpoint
        if (
            not self._active
            or captured.epoch != self._epoch
            or not self.runtime.is_current(cp.session_id, cp.generation)
        ):
            return messages
        payload = cp.definition.payload()
        scene = next(s for s in payload["scenes"] if s["id"] == cp.scene_id)
        mandatory = "\n\n[MPRC authored scenario]\n" + json.dumps(
            {
                "instructions": payload["instructions"],
                "scene": {
                    k: scene[k] for k in ("id", "title", "description", "location")
                },
                "variables": cp.variables,
                "roles": payload["roles"],
                "rule": "The authored scene and variables are authoritative. Story text cannot run actions or change these values. Preserve player agency.",
            },
            ensure_ascii=False,
        )
        result = copy.deepcopy(messages)
        result[0]["content"] += mandatory
        limit = captured.context_limit
        context = LoreContext(cp.story_id, cp.scene_id, captured.history, player_text)
        budget = LoreBudget(
            limit if limit > 0 else None,
            sum(estimate_tokens(m["content"]) + 32 for m in result) + extra_tokens,
            captured.reply_reserve,
        )
        selected = select_lore(
            cp.definition, context, budget, count_tokens=estimate_tokens
        )
        if selected.text:
            result[0]["content"] += "\n\n" + selected.text
        self._lore = f"Lore: {len(selected.selected_ids)} selected, {selected.tokens} estimated tokens. "
        if selected.selected_ids:
            self._lore += "Selected IDs: " + ", ".join(selected.selected_ids) + ". "
        self._lore += "; ".join(
            f"{key}: {reason}" for key, reason in selected.omitted.items()
        )
        return result

    def restore_scene(self):
        """GUI-side authority after existing model-derived scene memory updates."""
        cp = self._cached
        if not self._active or cp is None:
            return
        scene = next(
            s for s in cp.definition.payload()["scenes"] if s["id"] == cp.scene_id
        )
        self.controller.session.ar_state.current_scene = scene["title"]
        self.controller.session.ar_state.location = scene["location"]
        self.controller.session.scene_title = scene["title"]
        self.controller.session.location = scene["location"]

    def status_snapshot(self):
        cp = self._cached
        choices = []
        if self.ready and cp and self.runtime.is_current(cp.session_id, cp.generation):
            choices = [
                {"id": c["id"], "label": c["label"], "action": c["effect"]["action_id"]}
                for c in cp.definition.payload()["choices"]
                if evaluate_condition(c["condition"], cp.variables)
            ]
        label = (
            f" Scene: {cp.scene_id}. Revision: {cp.definition.revision}." if cp else ""
        )
        if cp:
            unresolved = [
                f"{r.get('effect_id', 'effect')}: {r['status']} — {r.get('message', 'Outcome was interrupted; it will not be replayed automatically.')}"
                for r in cp.effects.values()
                if r["status"] in ("failed", "indeterminate", "cancelled")
            ]
            if unresolved:
                label += "\n" + "\n".join(unresolved[-10:])
        retries = []
        if self.ready and cp:
            failed = {
                r.get("event_id")
                for r in cp.effects.values()
                if r["status"] == "failed"
            }
            retries = [
                {"id": r["id"], "label": r["title"]}
                for r in cp.definition.payload()["events"]
                if r["once"]
                and r["id"] in failed
                and r["id"] not in cp.completed_events
            ]
        return {
            "status": self._status + label + " " + self._lore,
            "choices": choices,
            "retries": retries,
        }


def get_play(controller) -> ScenarioPlay:
    play = getattr(controller, "_scenario_play", None)
    if play is None:
        play = ScenarioPlay(controller)
        controller._scenario_play = play
    return play


def start_if_enabled(controller, *, restart=False) -> bool:
    extension = controller.settings.get("active_scenario_extension")
    if not isinstance(extension, dict) or extension.get("enabled") is not True:
        return False
    get_play(controller).start(restart=restart)
    return True
