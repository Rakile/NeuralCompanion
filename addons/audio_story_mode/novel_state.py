"""Widget-free state owner for the Audio Story Novel Workshop.

The former NovelWorkshopPanel stored authoritative source-preview, outline,
selection, settings, progress, and status state inside a QWidget.  Native QML
must be able to drive the same pipeline without constructing that widget, so
this module owns the state in plain Python and exposes serializable snapshots.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from typing import Any

from addons.audio_story_mode import novel_models


class NovelWorkshopState:
    """Authoritative, serializable Novel Workshop interaction state."""

    def __init__(self) -> None:
        self._preview: novel_models.SourcePreview | None = None
        self._outline: dict[str, Any] = {}
        self._story_map: dict[str, Any] = {}
        self._current_project_id = ""
        self._project_name = ""
        self._source_kind = ""
        self._state: novel_models.NovelProjectState | None = None
        self._busy = False
        self._progress = 0
        self._status = "No novel project open"
        self._status_state = "saved"
        self._selected_chapter_id = ""
        self._selected_scene_id = ""
        self._settings: dict[str, Any] = {
            "adaptation_style": novel_models.ADAPTATION_STYLE_FAITHFUL,
            "novel_instructions": "",
            "prompt_additions": {
                "story_map": "",
                "outline": "",
                "scene_plan": "",
                "prose": "",
            },
        }

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
        self._project_name = str(project_name or "")
        self._source_kind = novel_models.normalize_source_kind(source_kind)
        if previous_project_id != self._current_project_id:
            self._state = None
            self._preview = None
            self._outline = {}
            self._story_map = {}
            self._selected_chapter_id = ""
            self._selected_scene_id = ""
        if state is not None:
            self._state = state
        if self._state is not None:
            self.set_status(
                f"Import: {self._state.import_status}; Story map: "
                f"{self._state.story_map_status}; Outline: "
                f"{self._state.outline_status}; Novel: "
                f"{self._state.assembly_status}",
                state="saved",
            )
        elif not self._current_project_id:
            self.set_status("No novel project open", state="saved")

    def set_preview(self, preview: novel_models.SourcePreview | None) -> None:
        self._preview = preview

    def preview(self) -> novel_models.SourcePreview | None:
        return self._preview

    def field_map(self) -> novel_models.ChatlogFieldMap:
        preview = self._preview
        return (
            preview.field_map
            if preview is not None
            else novel_models.ChatlogFieldMap()
        )

    def set_field_map(self, value: Mapping[str, Any]) -> None:
        field_map = novel_models.ChatlogFieldMap.from_mapping(value)
        preview = self._preview
        if preview is None:
            return
        preview_data = preview.to_dict()
        preview_data["field_map"] = field_map.to_dict()
        self._preview = novel_models.SourcePreview.from_mapping(preview_data)

    def set_story_map(self, story_map: Mapping | None) -> None:
        self._story_map = copy.deepcopy(dict(story_map or {}))

    def set_outline(self, outline: Mapping | None) -> None:
        self._outline = copy.deepcopy(dict(outline or {}))
        chapter_ids = {
            str(chapter.get("chapter_id") or "")
            for chapter in self._outline.get("chapters") or ()
            if isinstance(chapter, Mapping)
        }
        scene_ids = {
            str(scene.get("scene_id") or "")
            for chapter in self._outline.get("chapters") or ()
            if isinstance(chapter, Mapping)
            for scene in chapter.get("scenes") or ()
            if isinstance(scene, Mapping)
        }
        if self._selected_chapter_id not in chapter_ids:
            self._selected_chapter_id = next(iter(chapter_ids), "")
        if self._selected_scene_id not in scene_ids:
            self._selected_scene_id = next(iter(scene_ids), "")

    def outline_mapping(self) -> dict[str, Any]:
        return copy.deepcopy(self._outline)

    def select(self, *, chapter_id: str = "", scene_id: str = "") -> None:
        chapter_value = str(chapter_id or "")
        scene_value = str(scene_id or "")
        if chapter_value:
            self._selected_chapter_id = chapter_value
        if scene_value:
            self._selected_scene_id = scene_value
            for chapter in self._outline.get("chapters") or ():
                if not isinstance(chapter, Mapping):
                    continue
                if any(
                    str(scene.get("scene_id") or "") == scene_value
                    for scene in chapter.get("scenes") or ()
                    if isinstance(scene, Mapping)
                ):
                    self._selected_chapter_id = str(
                        chapter.get("chapter_id") or self._selected_chapter_id
                    )
                    break

    def selected_chapter_id(self) -> str:
        if self._selected_chapter_id:
            return self._selected_chapter_id
        chapters = self._outline.get("chapters") or ()
        return (
            str(chapters[0].get("chapter_id") or "")
            if chapters and isinstance(chapters[0], Mapping)
            else ""
        )

    def selected_scene_id(self) -> str:
        if self._selected_scene_id:
            return self._selected_scene_id
        for chapter in self._outline.get("chapters") or ():
            if not isinstance(chapter, Mapping):
                continue
            scenes = chapter.get("scenes") or ()
            if scenes and isinstance(scenes[0], Mapping):
                return str(scenes[0].get("scene_id") or "")
        return ""

    def settings_values(self) -> dict[str, Any]:
        return copy.deepcopy(self._settings)

    def update_settings(self, values: Mapping[str, Any]) -> None:
        source = dict(values or {})
        if "adaptation_style" in source:
            self._settings["adaptation_style"] = (
                novel_models.normalize_adaptation_style(
                    source.get("adaptation_style")
                )
            )
        if "novel_instructions" in source:
            self._settings["novel_instructions"] = str(
                source.get("novel_instructions") or ""
            ).strip()
        if isinstance(source.get("prompt_additions"), Mapping):
            additions = self._settings["prompt_additions"]
            for key in ("story_map", "outline", "scene_plan", "prose"):
                if key in source["prompt_additions"]:
                    additions[key] = str(
                        source["prompt_additions"].get(key) or ""
                    ).strip()

    def reset_prompt_additions(self) -> None:
        self._settings["prompt_additions"] = {
            "story_map": "",
            "outline": "",
            "scene_plan": "",
            "prose": "",
        }

    def set_busy(self, busy: bool, message: str = "", percent: int = 0) -> None:
        self._busy = bool(busy)
        self._progress = max(0, min(100, int(percent or 0)))
        if message:
            self.set_status(message, state="working" if busy else "saved")

    def set_status(self, message: str, *, state: str = "saved") -> None:
        self._status = str(message or "")
        self._status_state = str(state or "saved")

    def move_selected(self, direction: int, *, kind: str, identifier: str) -> None:
        step = -1 if int(direction) < 0 else 1
        outline = self.outline_mapping()
        if kind == "chapter":
            items = list(outline.get("chapters") or ())
        else:
            items = []
            for chapter in outline.get("chapters") or ():
                candidate = list(chapter.get("scenes") or ())
                if any(str(item.get("scene_id") or "") == identifier for item in candidate):
                    items = candidate
                    chapter["scenes"] = items
                    break
        key = "chapter_id" if kind == "chapter" else "scene_id"
        index = next(
            (i for i, item in enumerate(items) if str(item.get(key) or "") == identifier),
            -1,
        )
        target = index + step
        if index >= 0 and 0 <= target < len(items):
            items[index], items[target] = items[target], items[index]
            if kind == "chapter":
                outline["chapters"] = items
            self.set_outline(outline)

    def split_selected(self, *, kind: str, identifier: str) -> None:
        outline = self.outline_mapping()
        if kind == "chapter":
            chapters = list(outline.get("chapters") or ())
            for index, chapter in enumerate(chapters):
                if str(chapter.get("chapter_id") or "") != identifier:
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
                break
        elif kind == "scene":
            for chapter in outline.get("chapters") or ():
                scenes = list(chapter.get("scenes") or ())
                for index, scene in enumerate(scenes):
                    if str(scene.get("scene_id") or "") != identifier:
                        continue
                    duplicate = copy.deepcopy(scene)
                    duplicate["scene_id"] = f"scene-manual-{uuid.uuid4().hex[:12]}"
                    duplicate["title"] = f"{scene.get('title') or 'Scene'} - Part 2"
                    words = str(scene.get("summary") or "").split()
                    split_at = max(1, len(words) // 2) if words else 0
                    if split_at:
                        scene["summary"] = " ".join(words[:split_at])
                        duplicate["summary"] = " ".join(words[split_at:])
                    scenes.insert(index + 1, duplicate)
                    chapter["scenes"] = scenes
                    break
        self.set_outline(outline)

    def merge_selected_with_next(self, *, kind: str, identifier: str) -> None:
        outline = self.outline_mapping()
        if kind == "chapter":
            chapters = list(outline.get("chapters") or ())
            for index in range(len(chapters) - 1):
                current = chapters[index]
                if str(current.get("chapter_id") or "") != identifier:
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
                break
        elif kind == "scene":
            for chapter in outline.get("chapters") or ():
                scenes = list(chapter.get("scenes") or ())
                for index in range(len(scenes) - 1):
                    current = scenes[index]
                    if str(current.get("scene_id") or "") != identifier:
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
                    break
        self.set_outline(outline)

    def snapshot(self) -> dict[str, Any]:
        preview = self._preview.to_dict() if self._preview is not None else {}
        state = (
            {
                "project_id": self._state.project_id,
                "source_fingerprint": self._state.source_fingerprint,
                "import_status": self._state.import_status,
                "completed_chunk_refs": list(self._state.completed_chunk_refs),
                "story_map_status": self._state.story_map_status,
                "outline_status": self._state.outline_status,
                "assembly_status": self._state.assembly_status,
            }
            if self._state is not None
            else {}
        )
        return {
            "project_id": self._current_project_id,
            "project_name": self._project_name,
            "source_kind": self._source_kind,
            "preview": preview,
            "story_map": copy.deepcopy(self._story_map),
            "outline": self.outline_mapping(),
            "state": state,
            "settings": self.settings_values(),
            "selected_chapter_id": self.selected_chapter_id(),
            "selected_scene_id": self.selected_scene_id(),
            "busy": self._busy,
            "progress": self._progress,
            "status": self._status,
            "status_state": self._status_state,
        }


__all__ = ["NovelWorkshopState"]
