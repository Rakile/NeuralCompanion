from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping

from PySide6 import QtCore, QtWidgets

from addons.audio_story_mode import novel_models


class NovelProjectDialog(QtWidgets.QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Novel Workshop Project")
        self.setModal(True)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("Project name")
        self.source_kind_combo = QtWidgets.QComboBox()
        self.source_kind_combo.addItem(
            "Chatlog JSON", novel_models.SOURCE_KIND_CHATLOG_JSON
        )
        self.source_kind_combo.addItem(
            "Markdown document", novel_models.SOURCE_KIND_MARKDOWN
        )
        form.addRow("Project name", self.name_edit)
        form.addRow("Source type", self.source_kind_combo)
        layout.addLayout(form)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selection(self) -> tuple[str, str]:
        return (
            self.name_edit.text().strip(),
            novel_models.normalize_source_kind(self.source_kind_combo.currentData()),
        )

    def _accept_if_valid(self) -> None:
        if not self.name_edit.text().strip():
            self.name_edit.setFocus()
            return
        self.accept()


class NovelWorkshopPanel(QtWidgets.QWidget):
    newProjectRequested = QtCore.Signal()
    chooseSourceRequested = QtCore.Signal(str)
    inspectRequested = QtCore.Signal(str, object)
    importRequested = QtCore.Signal(object)
    storyMapRequested = QtCore.Signal()
    outlineRequested = QtCore.Signal()
    outlineSaveRequested = QtCore.Signal(object)
    generateRequested = QtCore.Signal(object)
    retrySceneRequested = QtCore.Signal(str)
    assembleRequested = QtCore.Signal(bool)
    cancelRequested = QtCore.Signal()
    narrateRequested = QtCore.Signal(str)
    storyHandoffRequested = QtCore.Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("audio_story_novel_workshop")
        self._preview: novel_models.SourcePreview | None = None
        self._outline: dict = {}
        self._current_project_id = ""
        self._source_kind = ""
        self._state: novel_models.NovelProjectState | None = None
        self._busy = False
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 8)
        root.setSpacing(10)

        title = QtWidgets.QLabel("Novel Workshop")
        title.setObjectName("audio_story_novel_title")
        title.setStyleSheet("font-size: 18px; font-weight: 800; color: #f97316;")
        description = QtWidgets.QLabel(
            "Turn a chatlog into reviewed chapters and prose, or import Markdown "
            "for direct narration. Work is saved after every completed stage."
        )
        description.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(description)

        status_frame = QtWidgets.QFrame()
        status_frame.setObjectName("audio_story_novel_status_frame")
        status_layout = QtWidgets.QHBoxLayout(status_frame)
        status_layout.setContentsMargins(10, 7, 10, 7)
        self.status_label = QtWidgets.QLabel("No novel project open")
        self.status_label.setObjectName("audio_story_novel_status_label")
        self.status_label.setWordWrap(True)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumWidth(190)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancelRequested)
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress_bar)
        status_layout.addWidget(self.cancel_button)
        root.addWidget(status_frame)

        project_group = QtWidgets.QGroupBox("Project and source")
        project_layout = QtWidgets.QVBoxLayout(project_group)
        project_row = QtWidgets.QHBoxLayout()
        self.new_project_button = QtWidgets.QPushButton("New Novel Project")
        self.new_project_button.clicked.connect(self.newProjectRequested)
        self.project_label = QtWidgets.QLabel("No Novel Workshop project selected")
        self.project_label.setWordWrap(True)
        project_row.addWidget(self.new_project_button)
        project_row.addWidget(self.project_label, 1)
        project_layout.addLayout(project_row)
        choose_row = QtWidgets.QHBoxLayout()
        self.choose_chatlog_button = QtWidgets.QPushButton("Choose Chatlog JSON")
        self.choose_markdown_button = QtWidgets.QPushButton("Choose Markdown")
        self.choose_chatlog_button.clicked.connect(
            lambda: self.chooseSourceRequested.emit(
                novel_models.SOURCE_KIND_CHATLOG_JSON
            )
        )
        self.choose_markdown_button.clicked.connect(
            lambda: self.chooseSourceRequested.emit(novel_models.SOURCE_KIND_MARKDOWN)
        )
        choose_row.addWidget(self.choose_chatlog_button)
        choose_row.addWidget(self.choose_markdown_button)
        choose_row.addStretch(1)
        project_layout.addLayout(choose_row)
        self.source_path_edit = QtWidgets.QLineEdit()
        self.source_path_edit.setReadOnly(True)
        self.source_path_edit.setPlaceholderText("Choose a JSON or Markdown source file")
        project_layout.addWidget(self.source_path_edit)
        self.preview_label = QtWidgets.QLabel("No source inspected")
        self.preview_label.setWordWrap(True)
        project_layout.addWidget(self.preview_label)

        self.mapping_group = QtWidgets.QGroupBox("Chatlog field mapping")
        mapping_form = QtWidgets.QFormLayout(self.mapping_group)
        self.collection_path_edit = QtWidgets.QLineEdit()
        self.collection_path_edit.setPlaceholderText("data.messages")
        self.speaker_field_edit = QtWidgets.QLineEdit()
        self.text_field_edit = QtWidgets.QLineEdit()
        self.role_field_edit = QtWidgets.QLineEdit()
        self.timestamp_field_edit = QtWidgets.QLineEdit()
        self.thread_field_edit = QtWidgets.QLineEdit()
        mapping_form.addRow("Message collection", self.collection_path_edit)
        mapping_form.addRow("Speaker field", self.speaker_field_edit)
        mapping_form.addRow("Text field", self.text_field_edit)
        mapping_form.addRow("Role field", self.role_field_edit)
        mapping_form.addRow("Timestamp field", self.timestamp_field_edit)
        mapping_form.addRow("Thread field", self.thread_field_edit)
        self.reinspect_button = QtWidgets.QPushButton("Inspect with this mapping")
        self.reinspect_button.clicked.connect(self._emit_reinspect)
        mapping_form.addRow("", self.reinspect_button)
        self.mapping_group.setVisible(False)
        project_layout.addWidget(self.mapping_group)
        self.import_button = QtWidgets.QPushButton("Import Confirmed Source")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._emit_import)
        project_layout.addWidget(self.import_button)
        root.addWidget(project_group)

        settings_group = QtWidgets.QGroupBox("Novel settings")
        settings_layout = QtWidgets.QFormLayout(settings_group)
        self.adaptation_style_combo = QtWidgets.QComboBox()
        self.adaptation_style_combo.addItem(
            "Faithful account", novel_models.ADAPTATION_STYLE_FAITHFUL
        )
        self.adaptation_style_combo.addItem(
            "Lightly novelized", novel_models.ADAPTATION_STYLE_LIGHTLY_NOVELIZED
        )
        self.adaptation_style_combo.addItem(
            "Creative fiction", novel_models.ADAPTATION_STYLE_CREATIVE_FICTION
        )
        self.novel_instructions_edit = QtWidgets.QPlainTextEdit()
        self.novel_instructions_edit.setPlaceholderText(
            "Optional overall writing and adaptation guidance"
        )
        self.novel_instructions_edit.setMaximumHeight(90)
        settings_layout.addRow("Adaptation style", self.adaptation_style_combo)
        settings_layout.addRow("Novel instructions", self.novel_instructions_edit)
        self.advanced_group = QtWidgets.QGroupBox("Advanced prompt additions")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        advanced_layout = QtWidgets.QFormLayout(self.advanced_group)
        self.story_map_prompt_edit = QtWidgets.QPlainTextEdit()
        self.outline_prompt_edit = QtWidgets.QPlainTextEdit()
        self.scene_plan_prompt_edit = QtWidgets.QPlainTextEdit()
        self.prose_prompt_edit = QtWidgets.QPlainTextEdit()
        for editor in (
            self.story_map_prompt_edit,
            self.outline_prompt_edit,
            self.scene_plan_prompt_edit,
            self.prose_prompt_edit,
        ):
            editor.setMaximumHeight(70)
        advanced_layout.addRow("Story map", self.story_map_prompt_edit)
        advanced_layout.addRow("Outline", self.outline_prompt_edit)
        advanced_layout.addRow("Scene plans", self.scene_plan_prompt_edit)
        advanced_layout.addRow("Prose", self.prose_prompt_edit)
        self.reset_prompts_button = QtWidgets.QPushButton("Reset to defaults")
        self.reset_prompts_button.clicked.connect(self.reset_prompt_additions)
        advanced_layout.addRow("", self.reset_prompts_button)
        settings_layout.addRow(self.advanced_group)
        root.addWidget(settings_group)

        stages_group = QtWidgets.QGroupBox("Generation stages")
        stages_layout = QtWidgets.QVBoxLayout(stages_group)
        stage_row = QtWidgets.QHBoxLayout()
        self.story_map_button = QtWidgets.QPushButton("Build Story Map")
        self.outline_button = QtWidgets.QPushButton("Build Outline")
        self.save_outline_button = QtWidgets.QPushButton("Save Outline")
        self.generate_button = QtWidgets.QPushButton("Approve and Generate")
        self.story_map_button.clicked.connect(self.storyMapRequested)
        self.outline_button.clicked.connect(self.outlineRequested)
        self.save_outline_button.clicked.connect(self._emit_outline_save)
        self.generate_button.clicked.connect(self._emit_generate)
        for button in (
            self.story_map_button,
            self.outline_button,
            self.save_outline_button,
            self.generate_button,
        ):
            stage_row.addWidget(button)
        stages_layout.addLayout(stage_row)
        self.story_map_summary_label = QtWidgets.QLabel("Story map not built")
        self.story_map_summary_label.setWordWrap(True)
        stages_layout.addWidget(self.story_map_summary_label)
        self.outline_tree = QtWidgets.QTreeWidget()
        self.outline_tree.setObjectName("audio_story_novel_outline_tree")
        self.outline_tree.setColumnCount(4)
        self.outline_tree.setHeaderLabels(
            ("Chapter / Scene", "Summary", "Point of view", "Tense")
        )
        self.outline_tree.setMinimumHeight(220)
        stages_layout.addWidget(self.outline_tree)
        outline_action_row = QtWidgets.QHBoxLayout()
        self.outline_move_up_button = QtWidgets.QPushButton("Move Up")
        self.outline_move_down_button = QtWidgets.QPushButton("Move Down")
        self.outline_split_button = QtWidgets.QPushButton("Split Selected")
        self.outline_merge_button = QtWidgets.QPushButton("Merge with Next")
        self.outline_move_up_button.clicked.connect(lambda: self._move_selected(-1))
        self.outline_move_down_button.clicked.connect(lambda: self._move_selected(1))
        self.outline_split_button.clicked.connect(self._split_selected)
        self.outline_merge_button.clicked.connect(self._merge_selected_with_next)
        for button in (
            self.outline_move_up_button,
            self.outline_move_down_button,
            self.outline_split_button,
            self.outline_merge_button,
        ):
            outline_action_row.addWidget(button)
        outline_action_row.addStretch(1)
        stages_layout.addLayout(outline_action_row)
        action_row = QtWidgets.QHBoxLayout()
        self.assemble_button = QtWidgets.QPushButton("Assemble Novel")
        self.partial_button = QtWidgets.QPushButton("Assemble Partial Preview")
        self.retry_scene_button = QtWidgets.QPushButton("Retry Selected Scene")
        self.narrate_button = QtWidgets.QPushButton("Narrate Selected Chapter")
        self.story_handoff_button = QtWidgets.QPushButton("Use in Story / Images")
        self.assemble_button.clicked.connect(
            lambda: self.assembleRequested.emit(False)
        )
        self.partial_button.clicked.connect(lambda: self.assembleRequested.emit(True))
        self.retry_scene_button.clicked.connect(
            lambda: self.retrySceneRequested.emit(self.selected_scene_id())
        )
        self.narrate_button.clicked.connect(
            lambda: self.narrateRequested.emit(self.selected_chapter_id())
        )
        self.story_handoff_button.clicked.connect(
            lambda: self.storyHandoffRequested.emit(self.selected_chapter_id())
        )
        for button in (
            self.assemble_button,
            self.partial_button,
            self.retry_scene_button,
            self.narrate_button,
            self.story_handoff_button,
        ):
            action_row.addWidget(button)
        stages_layout.addLayout(action_row)
        root.addWidget(stages_group)
        root.addStretch(1)
        self._refresh_enabled_controls()

    @property
    def current_project_id(self) -> str:
        return self._current_project_id

    def set_project(
        self,
        project_id: str,
        project_name: str,
        source_kind: str,
        state: novel_models.NovelProjectState | None = None,
    ) -> None:
        previous_project_id = self._current_project_id
        self._current_project_id = str(project_id or "")
        self._source_kind = novel_models.normalize_source_kind(source_kind)
        if previous_project_id != self._current_project_id:
            self._state = None
            self._preview = None
            self._outline = {}
            self.outline_tree.clear()
            self.source_path_edit.clear()
            self.preview_label.setText("No source inspected")
            self.mapping_group.setVisible(False)
        if state is not None:
            self._state = state
        if self._current_project_id:
            self.project_label.setText(
                f"Project: {project_name or 'Untitled'} — {self._source_kind.replace('_', ' ').title()}"
            )
        else:
            self.project_label.setText("No Novel Workshop project selected")
        if self._state is not None:
            self.set_status(
                f"Import: {self._state.import_status}; Story map: {self._state.story_map_status}; "
                f"Outline: {self._state.outline_status}; Novel: {self._state.assembly_status}",
                state="saved",
            )
        self._refresh_enabled_controls()

    def set_preview(self, preview: novel_models.SourcePreview | None) -> None:
        self._preview = preview
        if preview is None:
            self.source_path_edit.clear()
            self.preview_label.setText("No source inspected")
            self.mapping_group.setVisible(False)
        else:
            self.source_path_edit.setText(preview.source_path)
            details = [f"{preview.record_count} messages"]
            if preview.source_kind == novel_models.SOURCE_KIND_MARKDOWN:
                details = [f"{preview.record_count} chapters"]
            if preview.participant_count:
                details.append(
                    f"{preview.participant_count}"
                    f"{'+' if preview.participants_truncated else ''} participants"
                )
            if preview.source_size_bytes:
                size_mb = preview.source_size_bytes / (1024 * 1024)
                details.append(
                    f"{size_mb:.1f} MB"
                    if size_mb >= 0.1
                    else f"{preview.source_size_bytes} bytes"
                )
            if preview.date_start or preview.date_end:
                details.append(
                    "dates "
                    f"{preview.date_start or 'unknown'} to "
                    f"{preview.date_end or 'unknown'}"
                )
            if preview.skipped_count:
                details.append(f"{preview.skipped_count} skipped")
            if preview.estimated_chunks:
                details.append(f"about {preview.estimated_chunks} chunks")
            if preview.ambiguities:
                details.extend(preview.ambiguities)
            self.preview_label.setText("; ".join(details))
            field_map = preview.field_map
            self.collection_path_edit.setText(".".join(field_map.collection_path))
            self.speaker_field_edit.setText(field_map.speaker_field)
            self.text_field_edit.setText(field_map.text_field)
            self.role_field_edit.setText(field_map.role_field)
            self.timestamp_field_edit.setText(field_map.timestamp_field)
            self.thread_field_edit.setText(field_map.thread_field)
            self.mapping_group.setVisible(
                preview.source_kind == novel_models.SOURCE_KIND_CHATLOG_JSON
                and bool(preview.ambiguities)
            )
        self._refresh_enabled_controls()

    def preview(self) -> novel_models.SourcePreview | None:
        return self._preview

    def field_map(self) -> novel_models.ChatlogFieldMap:
        path = tuple(
            part.strip()
            for part in self.collection_path_edit.text().split(".")
            if part.strip()
        )
        return novel_models.ChatlogFieldMap(
            collection_path=path,
            speaker_field=self.speaker_field_edit.text().strip(),
            text_field=self.text_field_edit.text().strip(),
            role_field=self.role_field_edit.text().strip(),
            timestamp_field=self.timestamp_field_edit.text().strip(),
            thread_field=self.thread_field_edit.text().strip(),
        )

    def set_story_map(self, story_map: Mapping | None) -> None:
        source = dict(story_map or {})
        self.story_map_summary_label.setText(
            "Story map: "
            f"{len(source.get('characters') or ())} characters, "
            f"{len(source.get('events') or ())} events, "
            f"{len(source.get('candidate_scenes') or ())} candidate scenes"
            if source
            else "Story map not built"
        )

    def set_outline(self, outline: Mapping | None) -> None:
        self._outline = copy.deepcopy(dict(outline or {}))
        self.outline_tree.clear()
        for chapter in self._outline.get("chapters") or ():
            chapter_item = QtWidgets.QTreeWidgetItem(
                [
                    str(chapter.get("title") or "Untitled Chapter"),
                    str(chapter.get("summary") or ""),
                    "",
                    "",
                ]
            )
            chapter_item.setData(0, QtCore.Qt.UserRole, ("chapter", str(chapter.get("chapter_id") or "")))
            chapter_item.setFlags(chapter_item.flags() | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsUserCheckable)
            chapter_item.setCheckState(0, QtCore.Qt.Checked if chapter.get("enabled", True) else QtCore.Qt.Unchecked)
            self.outline_tree.addTopLevelItem(chapter_item)
            for scene in chapter.get("scenes") or ():
                scene_item = QtWidgets.QTreeWidgetItem(
                    [
                        str(scene.get("title") or "Untitled Scene"),
                        str(scene.get("summary") or ""),
                        str(scene.get("pov") or ""),
                        str(scene.get("tense") or ""),
                    ]
                )
                scene_item.setData(0, QtCore.Qt.UserRole, ("scene", str(scene.get("scene_id") or "")))
                scene_item.setFlags(scene_item.flags() | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsUserCheckable)
                scene_item.setCheckState(0, QtCore.Qt.Checked if scene.get("enabled", True) else QtCore.Qt.Unchecked)
                chapter_item.addChild(scene_item)
            chapter_item.setExpanded(True)
        self._refresh_enabled_controls()

    def outline_mapping(self) -> dict:
        result = copy.deepcopy(self._outline)
        chapters_by_id = {
            str(chapter.get("chapter_id") or ""): chapter
            for chapter in result.get("chapters") or ()
        }
        scenes_by_id = {
            str(scene.get("scene_id") or ""): scene
            for chapter in result.get("chapters") or ()
            for scene in chapter.get("scenes") or ()
        }
        ordered_chapters = []
        for row in range(self.outline_tree.topLevelItemCount()):
            chapter_item = self.outline_tree.topLevelItem(row)
            _kind, chapter_id = chapter_item.data(0, QtCore.Qt.UserRole) or ("", "")
            chapter = chapters_by_id.get(str(chapter_id))
            if chapter is None:
                continue
            chapter["title"] = chapter_item.text(0).strip()
            chapter["summary"] = chapter_item.text(1).strip()
            chapter["enabled"] = chapter_item.checkState(0) == QtCore.Qt.Checked
            ordered_scenes = []
            for child_row in range(chapter_item.childCount()):
                scene_item = chapter_item.child(child_row)
                _scene_kind, scene_id = scene_item.data(0, QtCore.Qt.UserRole) or ("", "")
                scene = scenes_by_id.get(str(scene_id))
                if scene is None:
                    continue
                scene["title"] = scene_item.text(0).strip()
                scene["summary"] = scene_item.text(1).strip()
                scene["pov"] = scene_item.text(2).strip()
                scene["tense"] = scene_item.text(3).strip()
                scene["enabled"] = scene_item.checkState(0) == QtCore.Qt.Checked
                ordered_scenes.append(scene)
            chapter["scenes"] = ordered_scenes
            ordered_chapters.append(chapter)
        result["chapters"] = ordered_chapters
        return result

    def _move_selected(self, direction: int) -> None:
        item = self.outline_tree.currentItem()
        if item is None:
            return
        step = -1 if int(direction) < 0 else 1
        parent = item.parent()
        if parent is None:
            index = self.outline_tree.indexOfTopLevelItem(item)
            target = index + step
            if index < 0 or target < 0 or target >= self.outline_tree.topLevelItemCount():
                return
            moved = self.outline_tree.takeTopLevelItem(index)
            self.outline_tree.insertTopLevelItem(target, moved)
        else:
            index = parent.indexOfChild(item)
            target = index + step
            if index < 0 or target < 0 or target >= parent.childCount():
                return
            moved = parent.takeChild(index)
            parent.insertChild(target, moved)
        self.outline_tree.setCurrentItem(moved)

    def _split_selected(self) -> None:
        item = self.outline_tree.currentItem()
        if item is None:
            return
        outline = self.outline_mapping()
        kind, identifier = item.data(0, QtCore.Qt.UserRole) or ("", "")
        if kind == "chapter":
            chapters = list(outline.get("chapters") or ())
            for index, chapter in enumerate(chapters):
                if str(chapter.get("chapter_id") or "") != str(identifier):
                    continue
                duplicate = copy.deepcopy(chapter)
                duplicate["chapter_id"] = f"chapter-manual-{uuid.uuid4().hex[:12]}"
                duplicate["title"] = f"{chapter.get('title') or 'Chapter'} - Part 2"
                scenes = list(chapter.get("scenes") or ())
                split_at = max(1, len(scenes) // 2) if scenes else 0
                chapter["scenes"] = scenes[:split_at]
                duplicate["scenes"] = scenes[split_at:]
                chapters.insert(index + 1, duplicate)
                outline["chapters"] = chapters
                self.set_outline(outline)
                return
        if kind == "scene":
            for chapter in outline.get("chapters") or ():
                scenes = list(chapter.get("scenes") or ())
                for index, scene in enumerate(scenes):
                    if str(scene.get("scene_id") or "") != str(identifier):
                        continue
                    duplicate = copy.deepcopy(scene)
                    duplicate["scene_id"] = f"scene-manual-{uuid.uuid4().hex[:12]}"
                    duplicate["title"] = f"{scene.get('title') or 'Scene'} - Part 2"
                    summary = str(scene.get("summary") or "")
                    words = summary.split()
                    split_at = max(1, len(words) // 2) if words else 0
                    if split_at:
                        scene["summary"] = " ".join(words[:split_at])
                        duplicate["summary"] = " ".join(words[split_at:])
                    scenes.insert(index + 1, duplicate)
                    chapter["scenes"] = scenes
                    self.set_outline(outline)
                    return

    def _merge_selected_with_next(self) -> None:
        item = self.outline_tree.currentItem()
        if item is None:
            return
        outline = self.outline_mapping()
        kind, identifier = item.data(0, QtCore.Qt.UserRole) or ("", "")
        if kind == "chapter":
            chapters = list(outline.get("chapters") or ())
            for index in range(len(chapters) - 1):
                current = chapters[index]
                if str(current.get("chapter_id") or "") != str(identifier):
                    continue
                following = chapters.pop(index + 1)
                current["summary"] = " ".join(
                    part
                    for part in (
                        str(current.get("summary") or "").strip(),
                        str(following.get("summary") or "").strip(),
                    )
                    if part
                )
                current["scenes"] = list(current.get("scenes") or ()) + list(
                    following.get("scenes") or ()
                )
                outline["chapters"] = chapters
                self.set_outline(outline)
                return
        if kind == "scene":
            for chapter in outline.get("chapters") or ():
                scenes = list(chapter.get("scenes") or ())
                for index in range(len(scenes) - 1):
                    current = scenes[index]
                    if str(current.get("scene_id") or "") != str(identifier):
                        continue
                    following = scenes.pop(index + 1)
                    for field in ("summary", "purpose", "continuity_notes"):
                        current[field] = " ".join(
                            part
                            for part in (
                                str(current.get(field) or "").strip(),
                                str(following.get(field) or "").strip(),
                            )
                            if part
                        )
                    for field in ("characters", "source_record_ids"):
                        current[field] = list(
                            dict.fromkeys(
                                list(current.get(field) or ())
                                + list(following.get(field) or ())
                            )
                        )
                    chapter["scenes"] = scenes
                    self.set_outline(outline)
                    return

    def selected_chapter_id(self) -> str:
        item = self.outline_tree.currentItem()
        if item is None:
            item = self.outline_tree.topLevelItem(0)
        if item is None:
            return ""
        if item.parent() is not None:
            item = item.parent()
        data = item.data(0, QtCore.Qt.UserRole) or ("", "")
        return str(data[1] if len(data) > 1 else "")

    def selected_scene_id(self) -> str:
        item = self.outline_tree.currentItem()
        if item is None:
            chapter = self.outline_tree.topLevelItem(0)
            item = chapter.child(0) if chapter is not None else None
        if item is None:
            return ""
        kind, identifier = item.data(0, QtCore.Qt.UserRole) or ("", "")
        if kind == "chapter":
            item = item.child(0)
            if item is None:
                return ""
            kind, identifier = item.data(0, QtCore.Qt.UserRole) or ("", "")
        return str(identifier) if kind == "scene" else ""

    def settings_values(self) -> dict:
        return {
            "adaptation_style": self.adaptation_style_combo.currentData(),
            "novel_instructions": self.novel_instructions_edit.toPlainText().strip(),
            "prompt_additions": {
                "story_map": self.story_map_prompt_edit.toPlainText().strip(),
                "outline": self.outline_prompt_edit.toPlainText().strip(),
                "scene_plan": self.scene_plan_prompt_edit.toPlainText().strip(),
                "prose": self.prose_prompt_edit.toPlainText().strip(),
            },
        }

    def reset_prompt_additions(self) -> None:
        for editor in (
            self.story_map_prompt_edit,
            self.outline_prompt_edit,
            self.scene_plan_prompt_edit,
            self.prose_prompt_edit,
        ):
            editor.clear()

    def set_busy(self, busy: bool, message: str = "", percent: int = 0) -> None:
        self._busy = bool(busy)
        self.progress_bar.setValue(max(0, min(100, int(percent))))
        self.cancel_button.setEnabled(self._busy)
        if message:
            self.set_status(message, state="working" if busy else "saved")
        self._refresh_enabled_controls()

    def set_status(self, message: str, *, state: str = "saved") -> None:
        colors = {
            "working": "#f59e0b",
            "error": "#ef4444",
            "saved": "#22c55e",
        }
        color = colors.get(str(state), "#d7e3f4")
        self.status_label.setText(str(message or ""))
        self.status_label.setStyleSheet(f"font-weight: 700; color: {color};")

    def _emit_reinspect(self) -> None:
        if self._preview is not None:
            self.inspectRequested.emit(self._preview.source_path, self.field_map())

    def _emit_import(self) -> None:
        if self._preview is not None:
            self.importRequested.emit(self._preview)

    def _emit_outline_save(self) -> None:
        self.outlineSaveRequested.emit(self.outline_mapping())

    def _emit_generate(self) -> None:
        self.generateRequested.emit(self.outline_mapping())

    def _refresh_enabled_controls(self) -> None:
        has_project = bool(self._current_project_id)
        chatlog_project = (
            self._source_kind == novel_models.SOURCE_KIND_CHATLOG_JSON
        )
        markdown_project = self._source_kind == novel_models.SOURCE_KIND_MARKDOWN
        imported = bool(
            self._state is not None and self._state.import_status == "complete"
        )
        has_preview = self._preview is not None and not self._preview.ambiguities
        has_outline = bool(self._outline.get("chapters"))
        self.choose_chatlog_button.setEnabled(
            has_project and chatlog_project and not self._busy
        )
        self.choose_markdown_button.setEnabled(
            has_project and markdown_project and not self._busy
        )
        self.reinspect_button.setEnabled(has_project and not self._busy)
        self.import_button.setEnabled(has_project and has_preview and not self._busy)
        self.story_map_button.setEnabled(
            chatlog_project and imported and not self._busy
        )
        self.outline_button.setEnabled(
            chatlog_project
            and self._state is not None
            and self._state.story_map_status == "complete"
            and not self._busy
        )
        self.save_outline_button.setEnabled(
            chatlog_project and has_outline and not self._busy
        )
        self.generate_button.setEnabled(
            chatlog_project and has_outline and not self._busy
        )
        self.assemble_button.setEnabled(
            chatlog_project and has_outline and not self._busy
        )
        self.partial_button.setEnabled(
            chatlog_project and has_outline and not self._busy
        )
        self.retry_scene_button.setEnabled(
            chatlog_project and has_outline and not self._busy
        )
        for button in (
            self.outline_move_up_button,
            self.outline_move_down_button,
            self.outline_split_button,
            self.outline_merge_button,
        ):
            button.setEnabled(chatlog_project and has_outline and not self._busy)
        can_use_chapter = bool(
            (markdown_project and imported) or (chatlog_project and has_outline)
        )
        self.narrate_button.setEnabled(can_use_chapter and not self._busy)
        self.story_handoff_button.setEnabled(can_use_chapter and not self._busy)
