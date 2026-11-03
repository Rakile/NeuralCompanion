"""Staged Persona prompt editing with asynchronous generation and persistence."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PySide6 import QtCore, QtGui
from core.runtime.contracts import CancellationToken
from core.persona_prompt_builder import (
    CONTROLS, ENABLED_TYPES, PROMPT_TYPES, clean_candidate, normalize_builder, normalize_type,
)


class PersonaPromptBuilderController(QtCore.QObject):
    changed = QtCore.Signal()
    _generated = QtCore.Signal(str, int, str, str)
    _catalogReceived = QtCore.Signal(int, object, str)
    _saved = QtCore.Signal(str, object, bool, str)

    def __init__(self, *, context: Callable, providers: Callable, models: Callable,
                 refine: Callable, save: Callable, applied: Callable,
                 executor: Any = None, writer: Any = None,
                 parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._providers_query = providers
        self._models_query = models
        self._refine = refine
        self._save = save
        self._applied_callback = applied
        self._executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="nc-persona-refiner")
        self._writer = writer or ThreadPoolExecutor(max_workers=1, thread_name_prefix="nc-persona-draft")
        self._owns_executor = executor is None
        self._owns_writer = writer is None
        self._key = ""
        self._draft = normalize_builder(None)
        self._drafts: dict[str, dict[str, Any]] = {}
        self._applied_prompt = ""
        self._applied_type = ""
        self._active_edit = ""
        self._active_edits: dict[str, str] = {}
        self._revision = 0
        self._catalog_revision = 0
        self._providers: list[dict[str, Any]] = []
        self._models: list[dict[str, str]] = []
        self._models_loading = False
        self._in_flight = False
        self._applying = False
        self._closing = False
        self._cancel_token: CancellationToken | None = None
        self._dirty = False
        self._pending_writes = 0
        self._error = ""
        self._message = ""
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self.flush)
        self._generated.connect(self._on_generated, QtCore.Qt.QueuedConnection)
        self._catalogReceived.connect(self._on_catalog, QtCore.Qt.QueuedConnection)
        self._saved.connect(self._on_saved, QtCore.Qt.QueuedConnection)

    @QtCore.Property("QVariantMap", notify=changed)
    def state(self) -> dict[str, Any]:
        draft = normalize_builder(self._draft)
        valid_provider = any(row["id"] == draft["provider_id"] for row in self._providers)
        valid_model = any(row["id"] == draft["model_id"] for row in self._models)
        changed = (draft["candidate"] != self._applied_prompt
                   or normalize_type(draft["prompt_type"]) != self._applied_type)
        active_edit_dirty = self._active_edit != self._applied_prompt
        return {
            **draft, "providers": self._providers, "models": self._models,
            "types": [{"value": "custom", "label": "Custom / existing (no type preset)"}]
                     + [{"value": key, "label": label} for key, label in PROMPT_TYPES if key in ENABLED_TYPES],
            "appliedPrompt": self._applied_prompt, "appliedType": self._applied_type,
            "activeEdit": self._active_edit, "activeEditDirty": active_edit_dirty,
            "inFlight": self._in_flight, "applying": self._applying,
            "saving": self.saving,
            "modelsLoading": self._models_loading, "error": self._error, "message": self._message,
            "canRefine": bool(valid_provider and valid_model and draft["description"].strip()
                              and draft["prompt_type"] in ENABLED_TYPES | {"custom"}
                              and not self._in_flight and not self._applying and not self._models_loading),
            "canRefineDraft": bool(valid_provider and valid_model and draft["candidate"].strip()
                                   and not self._in_flight and not self._applying and not self._models_loading),
            "canApplyDescription": bool(draft["description"].strip()
                                        and draft["description"] != self._applied_prompt
                                        and not self._applying and not self._in_flight),
            "canApply": bool(draft["candidate"].strip() and changed and not self._applying and not self._in_flight),
            "canApplyActiveEdit": bool(self._active_edit.strip() and active_edit_dirty
                                       and not self._applying and not self._in_flight),
            "hasChanges": changed or active_edit_dirty,
        }

    @property
    def applying(self) -> bool:
        return self._applying

    @property
    def saving(self) -> bool:
        return self._dirty or self._pending_writes > 0 or self._applying

    def adopt_saved_persona(self, key: str, draft: Mapping[str, Any]) -> None:
        """Replace a target's cached draft after an explicit Save persona operation."""
        self._drafts[key] = normalize_builder(draft)
        if key == self._key:
            self._draft = normalize_builder(draft)
        self._revision += 1
        self.changed.emit()

    @QtCore.Slot()
    def synchronize(self) -> None:
        if self._closing:
            return
        context = self._context()
        key = str(context.get("id") or "__session__")
        previous_applied = self._applied_prompt
        self._applied_prompt = str(context.get("appliedPrompt") or "")
        self._applied_type = normalize_type(context.get("appliedType"))
        if key != self._key:
            self.flush()
            self._key = key
            self._revision += 1
            self._draft = normalize_builder(self._drafts.get(key, context.get("builder")))
            if not self._draft["candidate"] and not self._draft["description"]:
                self._draft["candidate"] = self._applied_prompt
                self._draft["prompt_type"] = self._applied_type or "custom"
            self._error = ""
            self._message = ""
            self._active_edit = self._active_edits.get(key, self._applied_prompt)
            self.refreshProviders()
        elif self._active_edit == previous_applied:
            self._active_edit = self._applied_prompt
        self._active_edits[key] = self._active_edit
        self.changed.emit()

    @QtCore.Slot(str)
    def setActivePromptText(self, value: str) -> None:
        if self._closing or self._applying or self._active_edit == value:
            return
        self._active_edit = value
        self._active_edits[self._key] = value
        self._error = ""
        self.changed.emit()

    @QtCore.Slot()
    def refreshProviders(self) -> None:
        if self._closing or not self._key:
            return
        self._providers = list(self._providers_query())
        if not self._draft["provider_id"] and self._providers:
            preferred = next((row for row in self._providers if row.get("active")), self._providers[0])
            self._draft["provider_id"] = str(preferred["id"])
        self._choose_default_model()
        self.refreshModels()

    def _choose_default_model(self) -> None:
        provider_id = self._draft["provider_id"]
        provider = next((row for row in self._providers if row["id"] == provider_id), {})
        if not self._draft["model_id"]:
            self._draft["model_id"] = self._draft["models_by_provider"].get(
                provider_id, str(provider.get("model") or ""))

    @QtCore.Slot(str, str)
    def setField(self, key: str, value: str) -> None:
        allowed = {"description", "candidate", "prompt_type", "provider_id", "model_id", *CONTROLS}
        if key not in allowed or self._closing or self._applying or self._draft.get(key) == value:
            return
        if key == "prompt_type" and value not in ENABLED_TYPES and value != "custom":
            return
        if key in CONTROLS and value not in CONTROLS[key]:
            return
        if key == "provider_id":
            old_provider = self._draft["provider_id"]
            if old_provider and self._draft["model_id"]:
                self._draft["models_by_provider"][old_provider] = self._draft["model_id"]
            self._draft["model_id"] = self._draft["models_by_provider"].get(value, "")
        self._draft[key] = value
        if key == "model_id":
            self._draft["models_by_provider"][self._draft["provider_id"]] = value
        self._revision += 1
        self._error = ""
        self._drafts[self._key] = normalize_builder(self._draft)
        self._dirty = True
        self._timer.start()
        if key == "provider_id":
            self._choose_default_model()
            self.refreshModels()
        self.changed.emit()

    @QtCore.Slot()
    def refreshModels(self) -> None:
        if self._closing:
            return
        self._catalog_revision += 1
        revision = self._catalog_revision
        provider_id = self._draft["provider_id"]
        self._models = []
        self._models_loading = False
        if not any(row["id"] == provider_id for row in self._providers):
            self._error = "Configure an available refiner provider in Runtime."
            self.changed.emit()
            return
        self._models_loading = True
        self.changed.emit()

        def fetch() -> None:
            try:
                rows = list(self._models_query(provider_id))
                if not self._closing:
                    self._catalogReceived.emit(revision, rows, "")
            except Exception as error:
                if not self._closing:
                    self._catalogReceived.emit(revision, [], str(error))
        self._executor.submit(fetch)

    @QtCore.Slot(int, object, str)
    def _on_catalog(self, revision: int, rows: object, error: str) -> None:
        if self._closing or revision != self._catalog_revision:
            return
        self._models_loading = False
        self._models = list(rows or [])
        self._error = error
        if not error and not self._models:
            self._error = "No models available. Check the provider in Runtime, then refresh."
        elif not error and not any(row["id"] == self._draft["model_id"] for row in self._models):
            self._error = "Choose an available model for prompt refinement."
        self.changed.emit()

    @QtCore.Slot(bool)
    def generate(self, regenerate: bool = False) -> None:
        if not self.state["canRefine"]:
            return
        self._start_refinement(regenerate=regenerate, source="description")

    @QtCore.Slot()
    def refineDraft(self) -> None:
        if not self.state["canRefineDraft"]:
            return
        self._start_refinement(regenerate=False, source="candidate")

    def _start_refinement(self, *, regenerate: bool, source: str) -> None:
        key, revision = self._key, self._revision
        draft = normalize_builder(self._draft)
        if source == "candidate":
            draft["refine_source"] = "candidate"
        self._in_flight = True
        token = CancellationToken()
        self._cancel_token = token
        self._error = ""
        self._message = "Regenerating…" if regenerate else "Refining…"
        self.changed.emit()

        def work() -> None:
            if token.cancelled:
                return
            try:
                value = self._refine(draft, provider_id=draft["provider_id"],
                                     model_id=draft["model_id"], regenerate=regenerate, cancel_token=token)
                value = clean_candidate(value)
                if not self._closing:
                    self._generated.emit(key, revision, value, "")
            except Exception as error:
                if not self._closing:
                    self._generated.emit(key, revision, "", str(error))
        self._executor.submit(work)

    @QtCore.Slot(str, int, str, str)
    def _on_generated(self, key: str, revision: int, value: str, error: str) -> None:
        if self._closing:
            return
        self._in_flight = False
        self._cancel_token = None
        self._message = ""
        if key != self._key or revision != self._revision:
            self._message = "The draft changed during refinement. Your edits were kept; refine again when ready."
        elif error:
            self._error = error
        else:
            self._draft["previous_candidate"] = self._draft["candidate"]
            self._draft["candidate"] = value
            self._revision += 1
            self._drafts[key] = normalize_builder(self._draft)
            self._dirty = True
            self._timer.start()
            self._message = "Draft ready. Review it, then Apply to Persona."
        self.changed.emit()

    @QtCore.Slot()
    def flush(self) -> None:
        if not self._key or not self._dirty:
            return
        self._timer.stop()
        self._dirty = False
        self._queue_save(self._key, normalize_builder(self._draft), False)

    def _queue_save(self, key: str, draft: dict[str, Any], apply: bool) -> None:
        self._pending_writes += 1
        if not apply:
            self._drafts[key] = normalize_builder(draft)
        def work() -> None:
            try:
                self._save(key, draft, apply)
                if not self._closing:
                    self._saved.emit(key, draft, apply, "")
            except Exception as error:
                if not self._closing:
                    self._saved.emit(key, draft, apply, str(error))
        self._writer.submit(work)
        self.changed.emit()

    @QtCore.Slot()
    def apply(self) -> None:
        if not self.state["canApply"]:
            return
        self._timer.stop()
        self._dirty = False
        draft = normalize_builder(self._draft)
        draft["previous_applied_prompt"] = self._applied_prompt
        draft["previous_applied_type"] = self._applied_type
        draft["prompt_version"] += 1
        self._applying = True
        self._error = ""
        self._queue_save(self._key, draft, True)
        self.changed.emit()

    @QtCore.Slot()
    def applyDescription(self) -> None:
        if not self.state["canApplyDescription"]:
            return
        self._timer.stop()
        self._dirty = False
        draft = normalize_builder(self._draft)
        draft["previous_applied_prompt"] = self._applied_prompt
        draft["previous_applied_type"] = self._applied_type
        draft["prompt_version"] += 1
        # Transient override: the persisted generated candidate stays editable.
        draft["_apply_text"] = draft["description"]
        self._applying = True
        self._error = ""
        self._queue_save(self._key, draft, True)
        self.changed.emit()

    @QtCore.Slot()
    def applyActiveEdit(self) -> None:
        if not self.state["canApplyActiveEdit"]:
            return
        self._timer.stop()
        self._dirty = False
        draft = normalize_builder(self._draft)
        draft["previous_applied_prompt"] = self._applied_prompt
        draft["previous_applied_type"] = self._applied_type
        draft["prompt_version"] += 1
        draft["_apply_text"] = self._active_edit
        draft["_apply_type"] = self._applied_type
        self._applying = True
        self._error = ""
        self._queue_save(self._key, draft, True)
        self.changed.emit()

    @QtCore.Slot(str, object, bool, str)
    def _on_saved(self, key: str, draft: Mapping[str, Any], apply: bool, error: str) -> None:
        self._pending_writes = max(0, self._pending_writes - 1)
        if self._closing:
            return
        if apply:
            self._applying = False
        if error:
            self._error = "Prompt was not saved: " + error
        elif apply:
            try:
                self._applied_callback(key, draft)
            except Exception as exc:
                self._error = "Prompt was saved but could not be activated: " + str(exc)
            else:
                if key == self._key:
                    previous_applied = self._applied_prompt
                    self._draft = normalize_builder(draft)
                    self._drafts[key] = normalize_builder(draft)
                    self._applied_prompt = str(draft.get("_apply_text") or self._draft["candidate"])
                    self._applied_type = normalize_type(draft.get("_apply_type", self._draft["prompt_type"]))
                    if self._active_edit == previous_applied:
                        self._active_edit = self._applied_prompt
                    self._active_edits[key] = self._active_edit
                    self._message = "Prompt applied to persona."
        self.changed.emit()

    @QtCore.Slot()
    def useApplied(self) -> None:
        if self._applying or self._in_flight or not self._applied_prompt:
            return
        self.setField("candidate", self._applied_prompt)
        self.setField("prompt_type", self._applied_type or "custom")

    @QtCore.Slot()
    def copyCandidate(self) -> None:
        clipboard = QtGui.QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._draft["candidate"])

    def close(self) -> None:
        if self._closing:
            return
        self.flush()
        self._closing = True
        if self._cancel_token is not None:
            self._cancel_token.cancel("application_closing")
        self._timer.stop()
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
        if self._owns_writer:
            self._writer.shutdown(wait=False, cancel_futures=False)
