"""Native Document Memory (RAG) surface."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from PySide6 import QtCore

from ui.qml_bridge.adapters.addon_session import AddonSessionNativeAdapter
from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_commands import NativeCommandRunner
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
)


def _local_paths(values: object) -> list[str]:
    paths = []
    for value in list(values or []):
        text = str(value or "").strip()
        if not text:
            continue
        url = QtCore.QUrl(text)
        path = url.toLocalFile() if url.isLocalFile() else text
        if path and path not in paths:
            paths.append(path)
    return paths


class RagContextNativeAdapter(AddonSessionNativeAdapter):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._selected_file = ""
        self._test_query = ""
        self._test_result = ""
        self._status = ""
        self._document = {}
        self._mutation_error = ""
        self._mutations = NativeCommandRunner(self, max_workers=1)
        self._mutations.completed.connect(self._mutation_completed)

    def document_snapshot(self):
        return {**self._document, "error": self._mutation_error or self._document.get("error", ""), "test_query": self._test_query, "test_result": self._test_result}

    def refresh_document_status(self):
        try:
            value = self._invoke("runtime.rag.status")
        except RuntimeError as exc:
            value = {"error": str(exc), "packages": [], "sources": [], "settings": {}}
        value = dict(value) if isinstance(value, dict) else {}
        if value != self._document:
            self._document = value
            self._revision += 1
            self.changed.emit()
            return True
        return False

    @QtCore.Slot(str, bool, object, str)
    def _mutation_completed(self, _key, accepted, result, error):
        if not accepted:
            self._status = str(error)
        elif isinstance(result, dict) and result.get("accepted") is False:
            self._status = str(result.get("error") or "Document Memory setting was rejected.")
        self._mutation_error = self._status if not accepted or (isinstance(result, dict) and result.get("accepted") is False) else ""
        self.refresh_document_status()
        if callable(self._persist):
            self._persist()
        self.changed.emit()

    def close(self):
        self._mutations.close()

    def _settings(self) -> dict[str, object]:
        if self._document.get("settings"):
            return dict(self._document["settings"])
        try:
            payload = self._state()
        except RuntimeError:
            return {}
        return dict(payload.get("rag_context") or {})

    def snapshot(self) -> NativeSurface:
        settings = self._settings()
        status_result = self._document
        if isinstance(status_result, dict):
            self._status = str(status_result.get("status") or self._status)
        files = [str(path) for path in settings.get("files") or []]
        if self._selected_file not in files:
            self._selected_file = files[0] if files else ""
        controls = []
        for control in self._surface.controls:
            if control.id == "rag_context_files":
                control = replace(
                    control,
                    value=self._selected_file,
                    choices=tuple(
                        NativeChoice(value=path, label=path) for path in files
                    ),
                )
            elif control.id == "rag_context_test_query":
                control = replace(control, value=self._test_query)
            elif control.id == "rag_context_result_preview":
                control = replace(control, value=self._test_result)
            elif control.id == "rag_context_status":
                control = replace(control, value=self._status)
            elif control.id == "model":
                choices = tuple(NativeChoice(str(item.get("key") or item.get("id")), str(item.get("display_name") or item.get("key") or item.get("id"))) for item in self._document.get("models", ()))
                if not any(c.value == settings.get("model") for c in choices):
                    choices = (NativeChoice(settings.get("model", "text-embedding-bge-m3"), str(settings.get("model", "text-embedding-bge-m3"))),) + choices
                control = replace(control, value=settings.get("model", control.default_value), choices=choices)
            else:
                control = replace(
                    control,
                    value=settings.get(control.id, control.default_value),
                )
            controls.append(control)
        return replace(
            self._surface,
            controls=apply_card_layout(controls),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key == "rag_context_files":
            self._selected_file = str(value or "").strip()
        elif key == "rag_context_test_query":
            self._test_query = str(value or "").strip()
        else:
            # The displayed model choices come from the refreshed local catalog.
            control = (next((item for item in self.snapshot().controls if item.id == key), None)
                       if key == "model" else self._controls.get(key))
            if control is None or control.kind in {
                NativeControlKind.ACTION,
                NativeControlKind.DISPLAY,
                NativeControlKind.LIST,
            }:
                raise KeyError(f"Unknown Document Memory setting '{control_id}'.")
            changes = {key: RuntimeConfigNativeAdapter._normalize(control, value)}
            request = {"changes": changes, "package_id": self._document.get("activePackageId"),
                       "expected_revision": self._document.get("package_revision"),
                       "_expected_package_id": self._document.get("activePackageId"),
                       "_expected_activation_revision": self._document.get("revision")}
            if not self._mutations.submit("document-setting", lambda: self._invoke("runtime.rag.settings.update", request)):
                raise RuntimeError("A Document Memory setting is still being saved.")
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        action = str(control_id or "").strip()
        scope_request = {k: v for k, v in dict(payload or {}).items() if k.startswith("_expected_")} if isinstance(payload, dict) else {}
        if action == "rag_context_command":
            request = dict(payload or {})
            capability = str(request.pop("capability", ""))
            if not capability.startswith("runtime.rag."):
                raise ValueError("Invalid Document Memory command.")
            result = self._invoke(capability, request)
        elif action == "rag_context_add_files":
            supplied = dict(payload) if isinstance(payload, dict) else {}
            paths = _local_paths(supplied.get("paths", ()) if supplied else payload)
            if paths:
                result = self._invoke("runtime.rag.add_files", {**supplied, "paths": paths})
            else:
                result = None
        elif action == "rag_context_remove_files":
            result = self._invoke(
                "runtime.rag.remove_files",
                {**scope_request, "paths": [self._selected_file] if self._selected_file else []},
            )
        elif action == "rag_context_clear_files":
            result = self._invoke("runtime.rag.clear_files", scope_request)
        elif action == "rag_context_build_index":
            result = self._invoke("runtime.rag.build_index", scope_request)
        elif action == "rag_context_reload":
            result = self._invoke("runtime.rag.status")
        elif action == "rag_context_models":
            result = self._invoke("runtime.rag.models.refresh", scope_request)
        elif action == "rag_context_test":
            result = self._invoke(
                "runtime.rag.test_query",
                {"query": self._test_query},
            )
            if isinstance(result, dict):
                self._test_result = str(
                    result.get("context") or "No matching chunks."
                )
                debug = result.get("debug") or {}
                if debug:
                    details = f"Mode: {debug.get('mode', 'none')} · {float(debug.get('duration_ms', 0)):.0f} ms"
                    if debug.get("sources"):
                        details += "\nSources: " + ", ".join(dict.fromkeys(str(source) for source in debug["sources"]))
                    if debug.get("fallback_reason"):
                        details += "\n" + str(debug["fallback_reason"])
                    self._test_result = details + "\n\n" + self._test_result
        else:
            raise KeyError(f"Unknown Document Memory action '{control_id}'.")
        if isinstance(result, dict):
            if result.get("accepted") is False:
                raise RuntimeError(str(result.get("error") or "Document Memory action failed."))
            self._status = str(result.get("status") or self._status)
        self._revision += 1
        if callable(self._persist):
            self._persist()
        self.changed.emit()


def build_rag_context_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> RagContextNativeAdapter:
    surface = NativeSurface(
        id="rag_context_tab",
        title="Document Memory",
        addon_id="nc.rag_context",
        sections=("Sources", "Usage", "Retrieval", "Index", "Test search"),
        description="Index local documents and retrieve relevant notes for chat.",
        controls=(
            NativeControl(
                id="enabled",
                label="Use Document Memory in chat",
                kind=NativeControlKind.BOOLEAN,
                section="Sources",
                default_value=False,
            ),
            NativeControl(
                id="rag_context_files",
                label="Selected files",
                kind=NativeControlKind.LIST,
                section="Sources",
                choices=(NativeChoice(value="", label="No files"),),
            ),
            NativeControl(
                id="rag_context_add_files",
                label="Add files",
                kind=NativeControlKind.ACTION,
                section="Sources",
                metadata={
                    "filePicker": True,
                    "multiple": True,
                    "dialogTitle": "Select Document Memory files",
                    "nameFilters": [
                        "Document Memory files (*.txt *.md *.markdown *.json *.log *.pdf)",
                        "All files (*)",
                    ],
                },
            ),
            NativeControl(
                id="rag_context_remove_files",
                label="Remove selected file",
                kind=NativeControlKind.ACTION,
                section="Sources",
            ),
            NativeControl(
                id="rag_context_clear_files",
                label="Clear files",
                kind=NativeControlKind.ACTION,
                section="Sources",
                metadata={"destructive": True},
            ),
            NativeControl(
                id="base_url", label="Local embedding server", kind=NativeControlKind.TEXT,
                section="Retrieval", default_value="http://127.0.0.1:1234/v1",
                description="Only loopback endpoints are supported."),
            NativeControl(
                id="model", label="Semantic search model", kind=NativeControlKind.CHOICE,
                section="Retrieval", default_value="text-embedding-bge-m3",
                choices=(NativeChoice("text-embedding-bge-m3", "text-embedding-bge-m3"),)),
            NativeControl(
                id="rag_context_models", label="Refresh embedding models", kind=NativeControlKind.ACTION,
                section="Retrieval"),
            NativeControl(
                id="prefix_scheme", label="Model preprocessing", kind=NativeControlKind.CHOICE,
                section="Retrieval", default_value="bge-m3", choices=(NativeChoice("bge-m3", "Plain text / BGE-M3"),NativeChoice("nomic", "Nomic prefixes"),NativeChoice("qwen3", "Qwen3 query instruction"),NativeChoice("custom", "Custom prefixes"))),
            NativeControl(
                id="context_tokens", label="Embedding model context", kind=NativeControlKind.INTEGER,
                section="Retrieval", default_value=8192, minimum=256, maximum=32768, step=256),
            NativeControl(
                id="semantic_min_score", label="Minimum semantic similarity", kind=NativeControlKind.NUMBER,
                section="Retrieval", default_value=.25, minimum=-1, maximum=1, step=.05),
            NativeControl(
                id="deadline_ms", label="Retrieval deadline (milliseconds)", kind=NativeControlKind.INTEGER,
                section="Retrieval", default_value=1500, minimum=100, maximum=5000, step=100),
            NativeControl(
                id="top_k",
                label="Maximum matching notes",
                kind=NativeControlKind.INTEGER,
                section="Retrieval",
                default_value=4,
                minimum=1,
                maximum=12,
            ),
            NativeControl(
                id="min_score",
                label="Minimum matching keywords",
                kind=NativeControlKind.INTEGER,
                section="Retrieval",
                default_value=2,
                minimum=0,
                maximum=20,
            ),
            NativeControl(
                id="max_context_chars",
                label="Maximum context characters",
                kind=NativeControlKind.INTEGER,
                section="Retrieval",
                default_value=4000,
                minimum=1000,
                maximum=16000,
                step=250,
            ),
            NativeControl(
                id="rag_context_status",
                label="Index status",
                kind=NativeControlKind.DISPLAY,
                section="Index",
            ),
            NativeControl(
                id="rag_context_build_index",
                label="Build index",
                kind=NativeControlKind.ACTION,
                section="Index",
            ),
            NativeControl(
                id="rag_context_reload",
                label="Reload status",
                kind=NativeControlKind.ACTION,
                section="Index",
            ),
            NativeControl(
                id="rag_context_test_query",
                label="Test query",
                kind=NativeControlKind.TEXT,
                section="Test search",
            ),
            NativeControl(
                id="rag_context_test",
                label="Run test search",
                kind=NativeControlKind.ACTION,
                section="Test search",
            ),
            NativeControl(
                id="rag_context_result_preview",
                label="Result preview",
                kind=NativeControlKind.MULTILINE,
                section="Test search",
                metadata={"readOnly": True, "scrollable": True, "editorPreferredHeight": 240},
            ),
        ),
    )
    return RagContextNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["RagContextNativeAdapter", "build_rag_context_adapter"]
