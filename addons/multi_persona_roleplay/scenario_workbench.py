"""Addon-owned QML authoring window; drafts and model proposals never run effects."""

from __future__ import annotations

import copy
import json
from PySide6 import QtCore
from .scenario_native import (
    DraftSnapshot,
    ScenarioDraftEditor,
    empty_extension,
    refinement_targets,
    _container,
)
from .scenario_models import ScenarioValidationError, validate_story_extension
from .master_story_refinement import (
    ProviderIdentity,
    build_refinement_request,
    refinement_messages,
    parse_refinement_result,
    apply_refinement,
    validate_builder_options,
)

GROUPS = {
    "Overview": "",
    "Scenes": "scenes",
    "Lorebooks": "lorebooks",
    "Lore entries": "entries",
    "Variables": "variables",
    "Events": "events",
    "Choices": "choices",
    "Cast roles": "roles",
    "Effects": "effects",
    "Story fields": "story",
    "Builder options": "options",
}


def _fingerprint(story: dict) -> str:
    return json.dumps(story, sort_keys=True, ensure_ascii=False)


def _provider(controller) -> ProviderIdentity:
    config = controller.runtime_config
    return ProviderIdentity(
        str(config.get("chat_provider", "current")),
        controller._current_provider_model(),
    )


def _builder_options(controller) -> dict:
    from .native_controls import _SETTING_FIELDS
    from .native_contract import MPRC_CONTROL_SPECS

    specs = {s[0]: s for s in MPRC_CONTROL_SPECS}
    options = {
        key: copy.deepcopy(controller.settings.get(key, specs[control][4]))
        for control, key in _SETTING_FIELDS.items()
        if key.startswith("master_story_")
        and control in specs
        and specs[control][2]
        in ("boolean", "integer", "number", "text", "multiline", "choice")
        and not any(word in key for word in ("path", "draft", "narrator_id"))
    }
    for key, default in {
        "master_story_include_scenario": False,
        "master_story_scenario_context_limit": 0,
        "master_story_scenario_reply_reserve": 1024,
    }.items():
        options[key] = controller.settings.get(key, default)
    return options


class ScenarioWorkbench(QtCore.QObject):
    changed = QtCore.Signal()
    playChanged = QtCore.Signal()
    refinementFinished = QtCore.Signal(object)
    loreFinished = QtCore.Signal(object)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        story = copy.deepcopy(
            controller._master_story_draft
            or controller._current_master_story_snapshot()
        )
        self._source = _fingerprint(controller._master_story_draft or {})
        self._source_options = _fingerprint(_builder_options(controller))
        story.setdefault("scenario_extension", empty_extension())
        self.editor = ScenarioDraftEditor(
            DraftSnapshot(
                str(story.get("id") or "story"), 1, story, _builder_options(controller)
            )
        )
        self._clean_revision = self.editor.snapshot().revision
        self.group = "Overview"
        self.parent_id = ""
        self.record_id = ""
        self.status = "Edit a draft here, then Send to Master Draft. Use Master Story’s Apply Draft to activate it."
        self._proposal = None
        self._request = None
        self._token = ""
        self._lore_token = ""
        self.lore_preview = (
            "Enter a player action to preview which authored facts match this draft."
        )
        self._closed = False
        self.refinementFinished.connect(self._on_refinement)
        self.loreFinished.connect(self._on_lore_preview)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(750)
        self._timer.timeout.connect(self.playChanged)
        self._timer.start()
        self.changed.connect(self._publish_state)
        self.playChanged.connect(self._publish_play)
        self._publish_state()
        self._publish_play()

    @QtCore.Slot()
    def _publish_state(self) -> None:
        state = self.state
        # Only the GUI thread publishes. Replace the entire cache; never mutate
        # a published dict, so worker snapshots can copy their captured object
        # without making this GUI slot wait on the storage/controller lock.
        cached = dict(getattr(self.controller, "_scenario_native_snapshot", {}))
        cached["state"] = state
        self.controller._scenario_native_snapshot = cached

    @QtCore.Slot()
    def _publish_play(self) -> None:
        cached = dict(getattr(self.controller, "_scenario_native_snapshot", {}))
        cached["playState"] = self.playState
        cached["currentModel"] = self.currentModel
        self.controller._scenario_native_snapshot = cached

    @QtCore.Property("QVariantMap", notify=playChanged)
    def playState(self):
        play = getattr(self.controller, "_scenario_play", None)
        return (
            play.status_snapshot()
            if play
            else {
                "status": "Start MPRC Play to load the applied scenario.",
                "choices": [],
                "retries": [],
            }
        )

    @QtCore.Property(str, notify=playChanged)
    def currentModel(self):
        return _provider(self.controller).model_id

    def _records(self):
        ext = self.editor.snapshot().story["scenario_extension"]
        kind = GROUPS[self.group]
        if kind in ("entries", "effects"):
            parents = (
                ext["lorebooks"] if kind == "entries" else ext["scenes"] + ext["events"]
            )
            if self.parent_id not in [p["id"] for p in parents]:
                self.parent_id = parents[0]["id"] if parents else ""
            parent = next((p for p in parents if p["id"] == self.parent_id), {})
            return parent.get(kind, []), parents
        return ext.get(kind, []), []

    @QtCore.Property("QVariantMap", notify=changed)
    def state(self):
        snapshot = self.editor.snapshot()
        ext = snapshot.story["scenario_extension"]
        records, parents = self._records()
        if self.record_id not in [r["id"] for r in records]:
            self.record_id = records[0]["id"] if records else ""
        targets = refinement_targets(snapshot)
        kind = GROUPS[self.group]
        prefix = "/story/scenario_extension"
        selected_path = ""
        if kind == "story":
            predicate = lambda t: (
                t.id.startswith("/story/") and not t.id.startswith(prefix)
            )
        elif kind == "options":
            predicate = lambda t: t.id.startswith("/options/")
        elif not kind:
            predicate = lambda t: t.id.startswith(prefix + "/") and t.id.count("/") == 3
        else:

            def find_path(value, path):
                if isinstance(value, dict):
                    if value.get("id") == self.record_id:
                        return path
                    for key, child in value.items():
                        found = find_path(child, path + "/" + key)
                        if found:
                            return found
                elif isinstance(value, list):
                    for index, child in enumerate(value):
                        found = find_path(child, path + "/" + str(index))
                        if found:
                            return found
                return ""

            selected_path = find_path(ext, prefix) if self.record_id else ""
            predicate = lambda t: (
                bool(selected_path) and t.id.startswith(selected_path + "/")
            )
        fields = []
        for target in targets:
            if not predicate(target) or target.value_schema["type"] == "object":
                continue
            value = target.value
            # Child records have their own page. Empty collections are managed by Add.
            if isinstance(value, list) and target.id.rsplit("/", 1)[-1] in (
                "scenes",
                "lorebooks",
                "entries",
                "variables",
                "events",
                "choices",
                "roles",
                "effects",
            ):
                continue
            fields.append(
                {
                    "id": target.id,
                    "label": target.label.split(" / ", 1)[-1],
                    "kind": target.value_schema["type"],
                    "value": value,
                    "text": "\n".join(str(v) for v in value)
                    if isinstance(value, list)
                    else str(value),
                    "options": target.value_schema.get("enum", []),
                    "help": target.help_text,
                }
            )
        proposal = self._proposal
        play = getattr(self.controller, "_scenario_play", None)
        return {
            "groups": list(GROUPS),
            "group": self.group,
            "fields": fields,
            "sectionTarget": (
                "/options"
                if kind == "options"
                else "/story"
                if kind == "story"
                else selected_path.rsplit("/", 1)[0]
                if selected_path
                else prefix
            ),
            "recordTarget": selected_path,
            "records": [
                {
                    "id": r["id"],
                    "label": str(r.get("title") or r.get("label") or r["id"]),
                }
                for r in records
            ],
            "parents": [
                {"id": p["id"], "label": str(p.get("title") or p["id"])}
                for p in parents
            ],
            "recordId": self.record_id,
            "parentId": self.parent_id,
            "canManage": kind not in ("", "story", "options"),
            "canCondition": kind in ("events", "choices") and bool(self.record_id),
            "variables": [
                {"id": v["id"], "label": v["id"], "type": v["type"]}
                for v in ext["variables"]
            ],
            "status": self.status,
            "busy": bool(self._token),
            "model": _provider(self.controller).model_id,
            "lorePreview": self.lore_preview,
            "loreBusy": bool(self._lore_token),
            "proposal": {
                "before": json.dumps(proposal.original, ensure_ascii=False, indent=2),
                "after": json.dumps(proposal.proposed, ensure_ascii=False, indent=2),
                "summary": proposal.summary,
            }
            if proposal
            else {},
            "play": play.status_snapshot()
            if play
            else {
                "status": "Start MPRC Play to load the applied scenario.",
                "choices": [],
            },
        }

    def _run(self, operation):
        try:
            operation()
            self._proposal = None
            self.status = (
                "Draft updated. Send to Master Draft when ready; changes are not live."
            )
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self.status = str(exc)
        self.changed.emit()

    @QtCore.Slot(str)
    def selectGroup(self, group):
        if group in GROUPS:
            self.group = group
            self.record_id = ""
            self.parent_id = ""
            self.changed.emit()

    @QtCore.Slot(str)
    def selectParent(self, parent):
        self.parent_id = parent
        self.record_id = ""
        self.changed.emit()

    @QtCore.Slot(str)
    def selectRecord(self, record):
        self.record_id = record
        self.changed.emit()

    @QtCore.Slot(str, "QVariant")
    def editField(self, target, value):
        if hasattr(value, "toVariant"):
            value = value.toVariant()

        def update():
            snap = self.editor.snapshot()
            item = next(t for t in refinement_targets(snap) if t.id == target)
            if item.value_schema["type"] == "array" and isinstance(value, str):
                converted = [
                    line.strip() for line in value.splitlines() if line.strip()
                ]
                if target.endswith("/enum"):
                    variable = _container(
                        {"story": snap.story, "options": snap.options},
                        target.strip("/").split("/")[:-1],
                    )
                    converted = [self._typed(v, variable["type"]) for v in converted]
            elif (
                item.value_schema["type"] == "integer"
                and type(value) is float
                and value.is_integer()
            ):
                converted = int(value)
            else:
                converted = value
            editor = ScenarioDraftEditor(snap)
            editor.set_value(target, converted)
            if target.endswith("/action_id"):
                snapshot = editor.snapshot()
                root = {"story": snapshot.story, "options": snapshot.options}
                effect = _container(root, target.strip("/").split("/")[:-1])
                ext = snapshot.story["scenario_extension"]
                if value == "mprc.story.narrate":
                    args = {"text": "Describe the next moment."}
                elif value == "mprc.scenario.change_scene":
                    args = {"scene_id": ext["scenes"][0]["id"]}
                else:
                    if not ext["variables"]:
                        raise ScenarioValidationError(
                            "Create a variable before choosing Set state."
                        )
                    variable = ext["variables"][0]
                    args = {"variable_id": variable["id"], "value": variable["initial"]}
                effect["arguments"] = args
                editor = ScenarioDraftEditor(snapshot)
            elif target.endswith("/type") and "/variables/" in target:
                snapshot = editor.snapshot()
                variable = _container(
                    {"story": snapshot.story}, target.strip("/").split("/")[:-1]
                )
                variable["initial"] = {
                    "boolean": False,
                    "integer": 0,
                    "number": 0.0,
                    "string": "",
                }[value]
                variable["enum"] = []
                editor = ScenarioDraftEditor(snapshot)
            elif target.endswith("/variable_id") and "/arguments/" in target:
                snapshot = editor.snapshot()
                args = _container(
                    {"story": snapshot.story}, target.strip("/").split("/")[:-1]
                )
                args["value"] = next(
                    v["initial"]
                    for v in snapshot.story["scenario_extension"]["variables"]
                    if v["id"] == value
                )
                editor = ScenarioDraftEditor(snapshot)
            self.editor = editor

        self._run(update)

    @staticmethod
    def _typed(value, kind):
        if kind == "boolean":
            if str(value).lower() not in ("true", "false"):
                raise ValueError("Boolean values must be true or false.")
            return str(value).lower() == "true"
        return (
            int(value)
            if kind == "integer"
            else float(value)
            if kind == "number"
            else str(value)
        )

    @QtCore.Slot(str)
    def manageRecord(self, operation):
        def update():
            kind = GROUPS[self.group]
            if operation == "add":
                self.editor.create(kind, self.parent_id or None)
                self.record_id = self._records()[0][-1]["id"]
            elif operation == "duplicate":
                self.editor.duplicate(kind, self.record_id, self.parent_id or None)
                self.record_id = self._records()[0][-1]["id"]
            elif operation == "delete":
                self.editor.remove(kind, self.record_id, self.parent_id or None)

        self._run(update)

    @QtCore.Slot(str, str, str, str)
    def condition(self, variable_id, operator, value, group):
        def update():
            variables = self.editor.snapshot().story["scenario_extension"]["variables"]
            variable = next((v for v in variables if v["id"] == variable_id), None)
            typed = (
                self._typed(value, variable["type"])
                if variable and group != "clear"
                else None
            )
            self.editor.set_condition(
                GROUPS[self.group],
                self.record_id,
                variable_id,
                operator,
                typed,
                group=group,
            )

        self._run(update)

    @QtCore.Slot(str, str)
    def refine(self, target, instruction):
        if self._token:
            return
        try:
            request = build_refinement_request(
                self.editor.snapshot(), target, instruction, _provider(self.controller)
            )
            token = self.controller._new_worker_token("mprc_refine")
            if not token:
                raise ValueError("MPRC is shutting down.")
            self._token = token
            self._request = request
            self._proposal = None
            self.status = (
                "Refining with the current main LLM. You can cancel and keep editing."
            )

            def worker():
                proposal = None
                error = ""
                if self._closed or not self.controller._worker_should_emit(token):
                    return
                try:
                    if _provider(self.controller) != request.provider:
                        raise ValueError("The main model changed; retry refinement.")
                    raw = self.controller._complete_provider_request(
                        {
                            "model": request.provider.model_id,
                            "messages": refinement_messages(request),
                            "response_format": {"type": "json_object"},
                        },
                        {},
                    )
                    if _provider(self.controller) != request.provider:
                        raise ValueError("The main model changed; proposal discarded.")
                    proposal = parse_refinement_result(request, raw)
                except Exception as exc:
                    error = str(exc)
                if self.controller._worker_should_emit(token):
                    self.refinementFinished.emit((token, proposal, error))

            if not self.controller._start_daemon_worker(
                token, worker, name="nc-mprc-refine"
            ):
                self.controller._cancel_worker_token(token)
                self._token = ""
                raise ValueError("Could not start refinement worker.")
        except (ValueError, TypeError) as exc:
            self.status = str(exc)
        self.changed.emit()

    @QtCore.Slot(object)
    def _on_refinement(self, result):
        token, proposal, error = result
        if token != self._token or self._closed:
            return
        self.controller._finish_worker_token(token)
        self._token = ""
        if error:
            self.status = "Refinement failed: " + error
        elif _provider(self.controller) != proposal.provider:
            self.status = "Main model changed before delivery; proposal discarded."
        elif self.editor.snapshot().revision != proposal.source_revision:
            self.status = "Draft changed while refining; stale proposal discarded."
        else:
            self._proposal = proposal
            self.status = "Review the original and proposal. Apply Preview changes only this draft."
        self.changed.emit()

    @QtCore.Slot()
    def cancelRefinement(self):
        if self._token:
            self.controller._cancel_worker_token(self._token)
        self._token = ""
        self._request = None
        self._proposal = None
        self.status = "Refinement discarded; draft kept."
        self.changed.emit()

    @QtCore.Slot()
    def applyPreview(self):
        def update():
            if self._proposal is None:
                raise ValueError("No proposal to apply.")
            self.editor = ScenarioDraftEditor(
                apply_refinement(self.editor.snapshot(), self._proposal)
            )

        self._run(update)

    @QtCore.Slot()
    def acceptDraft(self):
        try:
            if _fingerprint(self.controller._master_story_draft or {}) != self._source:
                raise ValueError(
                    "Master draft changed elsewhere. Use Reload Master Draft before sending changes."
                )
            if _fingerprint(_builder_options(self.controller)) != self._source_options:
                raise ValueError(
                    "Master settings changed elsewhere. Your unsent edits are preserved. "
                    "Copy any edits you need, then Reload Master Draft before sending changes."
                )
            self.editor.validate()
            snapshot = self.editor.snapshot()
            validate_builder_options(snapshot)
            self.controller._master_story_draft = copy.deepcopy(snapshot.story)
            self.controller.settings["master_story_draft"] = json.dumps(
                snapshot.story, ensure_ascii=False, indent=2
            )
            self.controller.settings.update(copy.deepcopy(snapshot.options))
            self._source = _fingerprint(snapshot.story)
            self._source_options = _fingerprint(_builder_options(self.controller))
            self._clean_revision = snapshot.revision
            self.status = "Sent to Master Draft. Review Save/Apply Draft in Master Story to activate it. The active scenario is unchanged."
            self.controller.refresh_ui()
        except (ValueError, TypeError) as exc:
            self.status = str(exc)
        self.changed.emit()

    @QtCore.Slot()
    def loadExample(self):
        from .scenario_demo import lighthouse_example

        snapshot = self.editor.snapshot()
        original = snapshot.story["scenario_extension"]
        example = lighthouse_example()
        example["id"] = original["id"]
        example["revision"] = original["revision"]
        if snapshot.story.get("personas"):
            example["roles"] = [
                {
                    "id": "harbour_guide_role",
                    "persona_id": snapshot.story["personas"][0]["id"],
                    "instructions": "Act as the player’s harbour guide without deciding the player’s actions.",
                }
            ]
        snapshot.story["scenario_extension"] = example
        self.editor = ScenarioDraftEditor(
            DraftSnapshot(
                snapshot.story_id,
                snapshot.revision + 1,
                snapshot.story,
                snapshot.options,
            )
        )
        self.group = "Overview"
        self.status = "Lighthouse example loaded into this draft. No actions have run."
        self.changed.emit()

    @QtCore.Slot(str)
    def previewLore(self, player_text):
        if self._lore_token:
            return
        snapshot = self.editor.snapshot()
        scene_id = (
            self.record_id
            if self.group == "Scenes"
            else snapshot.story["scenario_extension"]["initial_scene_id"]
        )
        token = self.controller._new_worker_token("mprc_lore_preview")
        if not token:
            return
        self._lore_token = token

        def worker():
            from .scenario_lore import (
                LoreContext,
                LoreBudget,
                select_lore,
                estimate_tokens,
            )

            try:
                definition = validate_story_extension(snapshot.story)
                mandatory = {
                    key: value
                    for key, value in snapshot.story.items()
                    if key != "scenario_extension"
                }
                mandatory["scenario_instructions"] = definition.instructions
                limit = int(
                    snapshot.options.get("master_story_scenario_context_limit", 0) or 0
                )
                budget = LoreBudget(
                    limit or None,
                    estimate_tokens(json.dumps(mandatory, ensure_ascii=False)),
                    int(
                        snapshot.options.get(
                            "master_story_scenario_reply_reserve", 1024
                        )
                    ),
                )
                selection = select_lore(
                    definition,
                    LoreContext(snapshot.story_id, scene_id, (), player_text),
                    budget,
                    count_tokens=estimate_tokens,
                )
                text = f"Draft estimate; Play recomputes the full request budget. Scene: {scene_id}. Selected: {', '.join(selection.selected_ids) or 'none'}. Estimated lore tokens: {selection.tokens}.\n"
                text += (
                    selection.text
                    + "\n"
                    + "\n".join(
                        f"{key}: {reason}" for key, reason in selection.omitted.items()
                    )
                )
            except Exception as exc:
                text = str(exc)
            if self.controller._worker_should_emit(token):
                self.loreFinished.emit((token, snapshot.revision, text))

        if not self.controller._start_daemon_worker(
            token, worker, name="nc-mprc-lore-preview"
        ):
            self.controller._cancel_worker_token(token)
            self._lore_token = ""
            self.lore_preview = "Could not start lore preview."
        self.changed.emit()

    @QtCore.Slot(object)
    def _on_lore_preview(self, result):
        token, revision, text = result
        if token != self._lore_token or self._closed:
            return
        self.controller._finish_worker_token(token)
        self._lore_token = ""
        self.lore_preview = (
            text
            if revision == self.editor.snapshot().revision
            else "Draft changed; preview lore again."
        )
        self.changed.emit()

    @QtCore.Slot(str)
    def executeChoice(self, choice_id):
        play = getattr(self.controller, "_scenario_play", None)
        if play:
            play.choose(choice_id)

    @QtCore.Slot(str)
    def retryEvent(self, event_id):
        play = getattr(self.controller, "_scenario_play", None)
        if play:
            play.retry(event_id)

    @QtCore.Slot()
    def close(self):
        if self._lore_token:
            self.controller._cancel_worker_token(self._lore_token)
        self._lore_token = ""
        self._closed = True
        self._timer.stop()
        self.cancelRefinement()


def get_workbench(controller) -> ScenarioWorkbench:
    """One GUI-owned detached editor survives navigation between MPRC tabs."""
    backend = getattr(controller, "_scenario_workbench", None)
    if backend is None or backend._closed:
        backend = ScenarioWorkbench(controller)
        controller._scenario_workbench = backend
    return backend


def handle_native_command(controller, payload: dict) -> None:
    """Allowlisted UI commands through MPRC's existing native action boundary."""
    operations = {
        "selectGroup": 1,
        "selectParent": 1,
        "selectRecord": 1,
        "editField": 2,
        "manageRecord": 1,
        "condition": 4,
        "refine": 2,
        "cancelRefinement": 0,
        "applyPreview": 0,
        "acceptDraft": 0,
        "loadExample": 0,
        "previewLore": 1,
        "executeChoice": 1,
        "retryEvent": 1,
        "open": 0,
        "reload": 0,
    }
    operation = payload.get("operation", "open")
    args = payload.get("args", [])
    if not isinstance(operation, str) or operation not in operations:
        raise ValueError("Unknown scenario editor command")
    if not isinstance(args, list) or len(args) != operations[operation]:
        raise ValueError("Invalid scenario editor arguments")
    if not controller._is_ui_thread():
        controller._run_remote_on_ui_thread(
            lambda: handle_native_command(controller, payload), timeout=10
        )
        return
    old = getattr(controller, "_scenario_workbench", None)
    if operation == "open" and old is not None and not old._closed:
        if (old._source != _fingerprint(controller._master_story_draft or {})
                or old._source_options != _fingerprint(_builder_options(controller))):
            if old.editor.snapshot().revision == old._clean_revision and not old._token:
                operation = "reload"
            else:
                old.status = "The Master draft or settings changed elsewhere. Your unsent edits are preserved. Copy any edits you need, then Reload to view the current draft and settings."
                old.changed.emit()
    if operation == "reload":
        old = getattr(controller, "_scenario_workbench", None)
        if old is not None:
            old.close()
            old.deleteLater()
        controller._scenario_workbench = None
    backend = get_workbench(controller)
    if operation not in {"open", "reload"}:
        getattr(backend, operation)(*args)
    backend._publish_play()
