from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6 import QtWidgets

from addons.rag_context import indexer


class RagContextController:
    def __init__(self, context):
        self.context = context
        self.settings = indexer.load_settings(context.storage)
        self.widget = None
        self.enable_checkbox = None
        self.file_list = None
        self.top_k_spin = None
        self.min_score_spin = None
        self.max_chars_spin = None
        self.status_label = None
        self.test_query_edit = None
        self.result_preview = None

    def bind_designer_tab(self, widget):
        if widget is None:
            raise RuntimeError("RAG Context Designer UI did not provide a widget.")

        self.widget = widget
        self.enable_checkbox = self._ui_child(widget, "rag_context_enable_checkbox", QtWidgets.QCheckBox)
        self.file_list = self._ui_child(widget, "rag_context_file_list", QtWidgets.QListWidget)
        self.top_k_spin = self._ui_child(widget, "rag_context_top_k_spin", QtWidgets.QSpinBox)
        self.min_score_spin = self._ui_child(widget, "rag_context_min_score_spin", QtWidgets.QSpinBox)
        self.max_chars_spin = self._ui_child(widget, "rag_context_max_chars_spin", QtWidgets.QSpinBox)
        self.status_label = self._ui_child(widget, "rag_context_status_label", QtWidgets.QLabel)
        self.test_query_edit = self._ui_child(widget, "rag_context_test_query_edit", QtWidgets.QLineEdit)
        self.result_preview = self._ui_child(widget, "rag_context_result_preview", QtWidgets.QPlainTextEdit)

        add_files = self._ui_child(widget, "rag_context_add_files_button", QtWidgets.QPushButton)
        remove_files = self._ui_child(widget, "rag_context_remove_files_button", QtWidgets.QPushButton)
        clear_files = self._ui_child(widget, "rag_context_clear_files_button", QtWidgets.QPushButton)
        build_button = self._ui_child(widget, "rag_context_build_button", QtWidgets.QPushButton)
        reload_button = self._ui_child(widget, "rag_context_reload_button", QtWidgets.QPushButton)
        test_button = self._ui_child(widget, "rag_context_test_button", QtWidgets.QPushButton)

        required = (
            self.enable_checkbox,
            self.file_list,
            self.top_k_spin,
            self.min_score_spin,
            self.max_chars_spin,
            self.status_label,
            self.test_query_edit,
            self.result_preview,
            add_files,
            remove_files,
            clear_files,
            build_button,
            reload_button,
            test_button,
        )
        if any(item is None for item in required):
            raise RuntimeError("RAG Context Designer UI is missing one or more required controls.")

        self.file_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.enable_checkbox.toggled.connect(self._on_enabled_changed)
        self.top_k_spin.valueChanged.connect(self._on_numeric_changed)
        self.min_score_spin.valueChanged.connect(self._on_numeric_changed)
        self.max_chars_spin.valueChanged.connect(self._on_numeric_changed)
        add_files.clicked.connect(self._add_files)
        remove_files.clicked.connect(self._remove_selected_files)
        clear_files.clicked.connect(self._clear_files)
        build_button.clicked.connect(self._build_index)
        reload_button.clicked.connect(self._refresh_status)
        test_button.clicked.connect(self._test_query)

        self._sync_widgets()
        self._refresh_status()
        return widget

    def _ui_child(self, root, name, cls):
        try:
            return root.findChild(cls, name)
        except Exception:
            return None

    def collect_chat_context(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        settings = self._current_settings()
        if not settings.get("enabled"):
            return None
        query = _latest_user_text(payload.get("messages") or payload.get("history") or [])
        if not query:
            query = str(payload.get("query") or "").strip()
        if not query:
            return None
        db = indexer.load_index(self.context.storage)
        results = indexer.search_index(
            db,
            query,
            top_k=int(settings.get("top_k") or 4),
            min_score=int(settings.get("min_score") or 0),
        )
        context_text = indexer.build_context(results, max_chars=int(settings.get("max_context_chars") or 4000))
        if not context_text:
            return {
                "context": "",
                "debug": {"addon": "nc.rag_context", "query": query, "matches": 0},
            }
        return {
            "context": context_text,
            "debug": {
                "addon": "nc.rag_context",
                "query": query,
                "matches": len(results),
                "sources": [Path(item.source).name for item in results],
            },
        }

    def export_state(self) -> dict[str, Any]:
        return self._current_settings()

    def import_state(self, payload: dict[str, Any]) -> None:
        self.settings = indexer.normalize_settings(payload)
        self._save_settings()
        self._sync_widgets()
        self._refresh_status()

    def _add_files(self):
        paths, _selected_filter = QtWidgets.QFileDialog.getOpenFileNames(
            self.widget,
            "Select RAG text files",
            "",
            "Text files (*.txt *.md *.markdown *.json *.log);;All files (*)",
        )
        if not paths:
            return
        files = list(self.settings.get("files") or [])
        seen = {str(item).lower() for item in files}
        for path in paths:
            path = str(path or "").strip()
            if not path or path.lower() in seen:
                continue
            files.append(path)
            seen.add(path.lower())
        self.settings["files"] = files
        self._save_settings()
        self._sync_file_list()
        self._refresh_status()

    def _remove_selected_files(self):
        selected = {item.text() for item in self.file_list.selectedItems()} if self.file_list is not None else set()
        if not selected:
            return
        self.settings["files"] = [path for path in self.settings.get("files") or [] if path not in selected]
        self._save_settings()
        self._sync_file_list()
        self._refresh_status()

    def _clear_files(self):
        self.settings["files"] = []
        self._save_settings()
        self._sync_file_list()
        self._refresh_status()

    def _build_index(self):
        settings = self._current_settings()
        db = indexer.build_index(list(settings.get("files") or []))
        indexer.save_index(self.context.storage, db)
        self._set_status(
            f"Built RAG DB with {len(db.get('chunks') or [])} chunk(s) from {len(db.get('files') or [])} selected file(s)."
        )

    def _test_query(self):
        query = str(self.test_query_edit.text() if self.test_query_edit is not None else "").strip()
        db = indexer.load_index(self.context.storage)
        settings = self._current_settings()
        results = indexer.search_index(
            db,
            query,
            top_k=int(settings.get("top_k") or 4),
            min_score=int(settings.get("min_score") or 0),
        )
        context_text = indexer.build_context(results, max_chars=int(settings.get("max_context_chars") or 4000))
        if self.result_preview is not None:
            self.result_preview.setPlainText(context_text or "No matching chunks.")
        self._set_status(f"Test query returned {len(results)} matching chunk(s).")

    def _refresh_status(self):
        db = indexer.load_index(self.context.storage)
        file_count = len(self.settings.get("files") or [])
        chunk_count = len(db.get("chunks") or [])
        built_at = str(db.get("built_at") or "not built")
        self._set_status(f"Selected files: {file_count}. RAG DB chunks: {chunk_count}. Last build: {built_at}.")

    def _on_enabled_changed(self, checked):
        self.settings["enabled"] = bool(checked)
        self._save_settings()

    def _on_numeric_changed(self, _value):
        self.settings = self._current_settings()
        self._save_settings()

    def _current_settings(self) -> dict[str, Any]:
        settings = dict(self.settings or {})
        if self.enable_checkbox is not None:
            settings["enabled"] = bool(self.enable_checkbox.isChecked())
        if self.top_k_spin is not None:
            settings["top_k"] = int(self.top_k_spin.value())
        if self.min_score_spin is not None:
            settings["min_score"] = int(self.min_score_spin.value())
        if self.max_chars_spin is not None:
            settings["max_context_chars"] = int(self.max_chars_spin.value())
        settings["files"] = list(settings.get("files") or [])
        self.settings = indexer.normalize_settings(settings)
        return dict(self.settings)

    def _save_settings(self):
        self.settings = indexer.normalize_settings(self.settings)
        indexer.save_settings(self.context.storage, self.settings)

    def _sync_widgets(self):
        if self.widget is None:
            return
        settings = indexer.normalize_settings(self.settings)
        if self.enable_checkbox is not None:
            self.enable_checkbox.setChecked(bool(settings.get("enabled")))
        if self.top_k_spin is not None:
            self.top_k_spin.setValue(int(settings.get("top_k") or 4))
        if self.min_score_spin is not None:
            self.min_score_spin.setValue(int(settings.get("min_score") or 0))
        if self.max_chars_spin is not None:
            self.max_chars_spin.setValue(int(settings.get("max_context_chars") or 4000))
        self._sync_file_list()

    def _sync_file_list(self):
        if self.file_list is None:
            return
        self.file_list.clear()
        for path in self.settings.get("files") or []:
            self.file_list.addItem(str(path))

    def _set_status(self, text: str):
        if self.status_label is not None:
            self.status_label.setText(str(text or ""))


def _latest_user_text(messages) -> str:
    for item in reversed(list(messages or [])):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("speaker") or "").strip().lower()
        if role not in {"user", "human"}:
            continue
        content = item.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if text:
                        parts.append(str(text))
                elif part:
                    parts.append(str(part))
            return "\n".join(parts).strip()
        return str(content or item.get("text") or "").strip()
    return ""
