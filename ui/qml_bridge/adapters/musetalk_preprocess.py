"""Typed native-QML surface for MuseTalk avatar preprocessing."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Callable, Mapping

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.native_contracts import (
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


_SETTING_IDS: dict[str, str] = {
    "musetalk_target_pack_combo": "musetalk_preprocess_target_pack_id",
    "musetalk_avatar_combo": "musetalk_selected_avatar_id",
    "musetalk_source_edit": "musetalk_source_path",
    "musetalk_avatar_id_edit": "musetalk_avatar_id",
    "musetalk_recreate_checkbox": "musetalk_recreate",
    "musetalk_create_frame_cache_checkbox": "musetalk_create_frame_cache",
    "musetalk_emotion_tags_edit": "musetalk_emotion_tags",
    "musetalk_bbox_shift_spin": "musetalk_bbox_shift",
    "musetalk_parsing_mode_combo": "musetalk_parsing_mode",
    "musetalk_extra_margin_spin": "musetalk_extra_margin",
    "musetalk_left_cheek_width_spin": "musetalk_left_cheek_width",
    "musetalk_right_cheek_width_spin": "musetalk_right_cheek_width",
    "musetalk_debug_show_mask_overlay_quick_checkbox": "musetalk_debug_show_mask_overlay",
    "musetalk_mask_range_start_spin": "musetalk_mask_range_start",
    "musetalk_mask_range_end_spin": "musetalk_mask_range_end",
    "musetalk_mask_range_passthrough_checkbox": "musetalk_mask_range_passthrough",
    "musetalk_debug_frame_index_spin": "musetalk_debug_frame_index",
    "musetalk_debug_show_mask_overlay_checkbox": "musetalk_debug_show_mask_overlay",
    "musetalk_debug_brush_size_spin": "musetalk_debug_brush_size",
    "musetalk_debug_brush_feather_spin": "musetalk_debug_brush_feather",
    "musetalk_debug_brush_transparency_spin": "musetalk_debug_brush_transparency",
    "musetalk_test_audio_edit": "musetalk_test_audio",
}


_ACTION_IDS: dict[str, str] = {
    **{f"btn_musetalk_variant_{action}": f"variant_{action}"
       for action in ("preview", "redo", "replace", "delete", "make_base")},
    "btn_musetalk_target_pack_refresh": "refresh_packs",
    "btn_musetalk_target_pack_new": "create_pack",
    "btn_musetalk_avatar_refresh": "refresh_avatars",
    "btn_musetalk_clear_frame_cache": "clear_frame_cache",
    "btn_musetalk_make_default_avatar": "make_default",
    "btn_musetalk_source_video": "set_source_path",
    "btn_musetalk_source_image": "set_source_path",
    "btn_musetalk_source_folder": "set_source_path",
    "btn_musetalk_prepare_avatar": "preprocess",
    "btn_musetalk_avatar_save_metadata": "save_metadata",
    "btn_musetalk_pack_emotions_all": "enable_all_emotions",
    "btn_musetalk_pack_emotions_none": "disable_optional_emotions",
    "btn_musetalk_debug_first_frame_quick": "debug_preview",
    "btn_musetalk_debug_first_frame_modified_quick": "debug_preview_modified",
    "btn_musetalk_mask_range_add": "add_mask_range",
    "btn_musetalk_mask_range_update": "update_mask_range",
    "btn_musetalk_mask_range_load": "load_mask_range",
    "btn_musetalk_mask_range_remove": "remove_mask_range",
    "btn_musetalk_mask_override_add": "add_mask_override",
    "btn_musetalk_mask_override_load": "load_mask_override",
    "btn_musetalk_mask_override_remove": "remove_mask_override",
    "btn_musetalk_debug_zoom_out": "zoom_out",
    "btn_musetalk_debug_zoom_reset": "zoom_reset",
    "btn_musetalk_debug_zoom_in": "zoom_in",
    "btn_musetalk_test_audio": "set_test_audio",
    "btn_musetalk_debug_first_frame": "debug_preview",
    "btn_musetalk_debug_first_frame_modified": "debug_preview_modified",
    "btn_musetalk_first_frame_test": "audio_frame_test",
    "btn_musetalk_retry_cleanup": "retry_cleanup",
}


_TRANSIENT_ACTIONS = {
    "refresh_packs",
    "refresh_avatars",
    "debug_preview",
    "debug_preview_modified",
    "audio_frame_test",
    "zoom_out",
    "zoom_reset",
    "zoom_in",
    "save_edited_mask",
    "retry_cleanup",
    "release_worker",
}


def _action(
    control_id: str,
    label: str,
    section: str,
    *,
    description: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> NativeControl:
    return NativeControl(
        control_id,
        label,
        NativeControlKind.ACTION,
        section,
        description=description,
        metadata=dict(metadata or {}),
    )


class MuseTalkPreprocessNativeAdapter(NativeSurfaceAdapter):
    def __init__(
        self,
        application_facade: Any,
        *,
        persist: Callable[[], Any] | None = None,
        parent=None,
    ) -> None:
        super().__init__("musetalk_preprocess_tab", "nc.musetalk_preprocess", parent)
        self._application = application_facade
        self._persist = persist
        self._revision = 0
        self._emotion_bindings: dict[str, dict[str, str]] = {}

    def _invoke(self, capability: str, payload: Mapping[str, Any] | None = None) -> Any:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "MuseTalk Preprocess is unavailable."))
            )
        value = result.value
        if isinstance(value, Mapping) and value.get("ok") is False:
            raise RuntimeError(
                str(value.get("error") or "MuseTalk creator action failed.")
            )
        return value

    def creator_snapshot(self) -> dict[str, Any]:
        """Return the authoritative raw state needed by the dedicated creator model."""

        value = self._invoke("runtime.musetalk_preprocess.native_snapshot") or {}
        if not isinstance(value, Mapping):
            raise RuntimeError("MuseTalk Preprocess native state is unavailable.")
        state = dict(value)
        pack_id = str(state.get("musetalk_preprocess_target_pack_id") or "")
        bindings: dict[str, dict[str, str]] = {}
        if "musetalk_native_pack_emotions" in state:
            emotion_rows: list[dict[str, Any]] = []
            for raw in list(state.get("musetalk_native_pack_emotions") or []):
                row = dict(raw or {})
                emotion = str(row.get("tag") or "").strip()
                if emotion:
                    control_id = self._emotion_control_id(pack_id, emotion)
                    row["control_id"] = control_id
                    bindings[control_id] = {"pack_id": pack_id, "emotion": emotion}
                emotion_rows.append(row)
            state["musetalk_native_pack_emotions"] = emotion_rows
        self._emotion_bindings = bindings
        return state

    def creator_activity_snapshot(self) -> dict[str, Any]:
        """Return the service's cheap live ownership/job projection."""

        value = self._invoke("runtime.musetalk_preprocess.creator_activity") or {}
        if not isinstance(value, Mapping):
            raise RuntimeError("MuseTalk creator activity is unavailable.")
        return dict(value)

    def invoke_creator_action(self, action: str, payload: Any = None) -> Any:
        """Invoke one addon action while preserving adapter persistence/change semantics."""

        normalized = str(action or "").strip()
        if not normalized:
            raise ValueError("A MuseTalk creator action is required.")
        result = self._invoke(
            "runtime.musetalk_preprocess.native_action",
            {"action": normalized, "payload": payload},
        )
        if self._persist is not None and normalized not in _TRANSIENT_ACTIONS:
            self._persist()
        self._revision += 1
        self.changed.emit()
        return result

    def release_worker(self) -> Any:
        return self.invoke_creator_action("release_worker")

    def prepare_shutdown(self) -> None:
        if not self.creator_activity_snapshot():
            return
        result = self._invoke("runtime.musetalk_preprocess.prepare_shutdown")
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            raise RuntimeError("MuseTalk creator shutdown was not confirmed.")

    @contextmanager
    def chat_startup_handoff(self):
        """Keep creator submissions barred until the caller reserves chat."""
        # Disabled/uninstalled addons return no capability value. The host gate
        # still rejects any outstanding reservation from an older generation.
        if not self.creator_activity_snapshot():
            yield
            return
        ticket = self._invoke("runtime.musetalk_preprocess.begin_chat_handoff")
        if not isinstance(ticket, str) or not ticket:
            raise RuntimeError("MuseTalk creator handoff did not return a ticket.")
        try:
            yield
        finally:
            self._invoke("runtime.musetalk_preprocess.end_chat_handoff", {"ticket": ticket})
            self.changed.emit()

    @staticmethod
    def _choice_rows(raw: Any, fallback: tuple[tuple[Any, str], ...]) -> tuple:
        rows: list[tuple[Any, str]] = []
        for item in list(raw or []):
            if isinstance(item, Mapping):
                rows.append((item.get("value"), str(item.get("label") or item.get("value") or "")))
        return choices(rows or fallback)

    @staticmethod
    def _mask_range_choices(raw: Any) -> tuple:
        rows: list[tuple[int, str]] = []
        for index, item in enumerate(list(raw or [])):
            entry = dict(item or {})
            mode = "Passthrough" if entry.get("passthrough") else str(entry.get("parsing_mode") or "Mask")
            rows.append(
                (
                    index,
                    f"{entry.get('start_frame', 0)}-{entry.get('end_frame', 0)} · {mode} · shift {entry.get('bbox_shift', 0)}",
                )
            )
        return choices(rows or ((-1, "No mask ranges"),))

    @staticmethod
    def _mask_override_choices(raw: Any) -> tuple:
        rows: list[tuple[int, str]] = []
        for index, item in enumerate(list(raw or [])):
            entry = dict(item or {})
            rows.append(
                (
                    index,
                    f"Frame {entry.get('frame_index', 0)} · {entry.get('range_label', 'Global')} · {entry.get('status', '')}",
                )
            )
        return choices(rows or ((-1, "No mask overrides"),))

    @staticmethod
    def _emotion_control_id(pack_id: str, emotion: str) -> str:
        readable = re.sub(r"[^a-z0-9_]+", "_", emotion.lower()).strip("_") or "emotion"
        identity = f"{pack_id}\0{emotion}".encode("utf-8")
        return f"musetalk_pack_emotion_{readable}_{hashlib.sha256(identity).hexdigest()[:10]}"

    def _emotion_controls(self, state: Mapping[str, Any]) -> tuple[NativeControl, ...]:
        pack_id = str(state.get("musetalk_preprocess_target_pack_id") or "")
        bindings: dict[str, dict[str, str]] = {}
        controls: list[NativeControl] = []
        for raw in list(state.get("musetalk_native_pack_emotions") or []):
            row = dict(raw or {})
            emotion = str(row.get("tag") or "").strip()
            if not emotion:
                continue
            control_id = self._emotion_control_id(pack_id, emotion)
            bindings[control_id] = {"pack_id": pack_id, "emotion": emotion}
            locked = bool(row.get("locked"))
            controls.append(
                NativeControl(
                    control_id,
                    emotion,
                    NativeControlKind.BOOLEAN,
                    "Metadata",
                    description=f"Avatar: {row.get('avatar_id', '')}",
                    value=bool(row.get("enabled")),
                    enabled=not locked,
                    metadata={
                        "creatorRowKind": "emotion",
                        "packId": pack_id,
                        "emotion": emotion,
                        "avatarId": str(row.get("avatar_id") or ""),
                        "locked": locked,
                    },
                )
            )
        self._emotion_bindings = bindings
        return tuple(controls)

    def snapshot(self) -> NativeSurface:
        state = self.creator_snapshot()
        pack_choices = self._choice_rows(
            state.get("musetalk_native_pack_choices"),
            (("__standalone__", "Standalone Avatars"),),
        )
        avatar_choices = self._choice_rows(
            state.get("musetalk_native_avatar_choices"),
            (("", "No Prepared Avatars"),),
        )
        emotion_controls = self._emotion_controls(state)
        frame_max_raw = state.get("musetalk_native_source_frame_max")
        frame_max = int(frame_max_raw) if isinstance(frame_max_raw, int) else None
        confirmations = dict(state.get("musetalk_native_confirmation_targets") or {})
        preprocess_confirmation = dict(confirmations.get("preprocess") or {})
        cache_confirmation = dict(confirmations.get("clear_frame_cache") or {})
        controls = (
            NativeControl(
                "musetalk_intro_label",
                "MuseTalk Preprocess",
                NativeControlKind.DISPLAY,
                "Overview",
                value="Prepare a video, still image, or frame folder as a MuseTalk avatar. Packs keep related looks and emotion variants together.",
            ),
            NativeControl(
                "musetalk_source_description",
                "Source and prepared avatar",
                NativeControlKind.DISPLAY,
                "Overview",
                value="Choose an existing prepared avatar to inspect or choose source media to preprocess.",
            ),
            NativeControl(
                "musetalk_target_pack_combo",
                "Target avatar pack",
                NativeControlKind.CHOICE,
                "Overview",
                value=state.get("musetalk_preprocess_target_pack_id"),
                choices=pack_choices,
            ),
            _action("btn_musetalk_target_pack_refresh", "Refresh packs", "Overview"),
            _action(
                "btn_musetalk_target_pack_new",
                "New pack",
                "Overview",
                metadata={
                    "execution": "ui",
                    "inputPrompt": True,
                    "dialogTitle": "Create avatar pack",
                    "inputLabel": "Pack name",
                },
            ),
            NativeControl(
                "musetalk_avatar_combo",
                "Prepared avatar",
                NativeControlKind.CHOICE,
                "Overview",
                value=state.get("musetalk_selected_avatar_id", ""),
                choices=avatar_choices,
            ),
            _action("btn_musetalk_avatar_refresh", "Refresh avatars", "Overview"),
            _action(
                "btn_musetalk_clear_frame_cache",
                "Clear startup cache",
                "Overview",
                metadata={
                    "destructive": True,
                    "creatorConfirmation": cache_confirmation,
                    "confirmationRequired": bool(cache_confirmation.get("required", True)),
                },
            ),
            _action("btn_musetalk_make_default_avatar", "Make default", "Overview"),
            NativeControl("musetalk_source_edit", "Source path", NativeControlKind.TEXT, "Source", value=state.get("musetalk_source_path", "")),
            _action("btn_musetalk_source_video", "Choose video", "Source", metadata={"execution": "ui", "filePicker": True, "dialogTitle": "Select MuseTalk source video", "nameFilters": ["Video files (*.mp4 *.mov *.mkv *.avi *.webm)", "All files (*)"]}),
            _action("btn_musetalk_source_image", "Choose image", "Source", metadata={"execution": "ui", "filePicker": True, "dialogTitle": "Select MuseTalk source image", "nameFilters": ["Image files (*.png *.jpg *.jpeg *.webp *.bmp)", "All files (*)"]}),
            _action("btn_musetalk_source_folder", "Choose frame folder", "Source", metadata={"execution": "ui", "folderPicker": True, "dialogTitle": "Select MuseTalk frame folder"}),
            NativeControl("musetalk_avatar_id_edit", "Avatar ID", NativeControlKind.TEXT, "Source", value=state.get("musetalk_avatar_id", "default_avatar")),
            NativeControl("musetalk_recreate_checkbox", "Recreate existing folder", NativeControlKind.BOOLEAN, "Source", value=bool(state.get("musetalk_recreate", False))),
            NativeControl("musetalk_avatar_destination_label", "Avatar destination", NativeControlKind.DISPLAY, "Source", value=state.get("musetalk_native_destination", "")),
            _action(
                "btn_musetalk_prepare_avatar",
                "Preprocess avatar",
                "Source",
                metadata={
                    "destructive": bool(preprocess_confirmation.get("required")),
                    "creatorConfirmation": preprocess_confirmation,
                    "confirmationRequired": bool(preprocess_confirmation.get("required")),
                },
            ),
            NativeControl("musetalk_create_frame_cache_checkbox", "Faster avatar startup cache", NativeControlKind.BOOLEAN, "Source", value=bool(state.get("musetalk_create_frame_cache", True))),
            NativeControl("musetalk_emotion_tags_edit", "Emotion tags", NativeControlKind.TEXT, "Metadata", value=state.get("musetalk_emotion_tags", "")),
            _action("btn_musetalk_avatar_save_metadata", "Save tag mapping and mask metadata", "Metadata"),
            NativeControl("musetalk_emotions_description", "Emotion mapping", NativeControlKind.DISPLAY, "Metadata", value="Comma-separated tags select this prepared avatar for matching model emotions."),
            NativeControl("musetalk_pack_emotions_summary_label", "Pack emotion summary", NativeControlKind.DISPLAY, "Metadata", value=state.get("musetalk_native_pack_emotion_summary", "")),
            _action("btn_musetalk_pack_emotions_all", "Enable all emotion variants", "Metadata"),
            _action("btn_musetalk_pack_emotions_none", "Disable optional variants", "Metadata"),
            *emotion_controls,
            NativeControl("unnamed_qlabel_qlabel", "Emotion variants", NativeControlKind.MULTILINE, "Metadata", value=json.dumps(state.get("musetalk_native_pack_emotions", []), ensure_ascii=False, indent=2), metadata={"readOnly": True, "rows": 7}),
            NativeControl("unnamed_qlabel_qlabel#2", "Mask profile", NativeControlKind.DISPLAY, "Mask", value="Global mouth-area settings are used unless a matching frame range overrides them."),
            NativeControl("unnamed_qlabel_qlabel#3", "Mask ranges", NativeControlKind.DISPLAY, "Ranges", value="Frame-specific ranges are validated and saved with avatar metadata."),
            NativeControl("unnamed_qlabel_qlabel#4", "Debug tools", NativeControlKind.DISPLAY, "Debug", value="Preview a frame before preprocessing and inspect the generated mask."),
            NativeControl("musetalk_mask_description", "Mouth mask profile", NativeControlKind.DISPLAY, "Mask", value="Tune detected mouth crop and parsed-mask shape."),
            NativeControl("musetalk_bbox_shift_spin", "BBox shift", NativeControlKind.INTEGER, "Mask", value=int(state.get("musetalk_bbox_shift", 0)), minimum=-100, maximum=100),
            NativeControl("musetalk_parsing_mode_combo", "Parsing mode", NativeControlKind.CHOICE, "Mask", value=state.get("musetalk_parsing_mode", "jaw"), choices=choices((("jaw", "Jaw (recommended)"), ("raw", "Raw parsed mask")))),
            NativeControl("musetalk_extra_margin_spin", "Extra margin", NativeControlKind.INTEGER, "Mask", value=int(state.get("musetalk_extra_margin", 10)), minimum=0, maximum=200),
            NativeControl("musetalk_left_cheek_width_spin", "Left cheek width", NativeControlKind.INTEGER, "Mask", value=int(state.get("musetalk_left_cheek_width", 90)), minimum=0, maximum=400),
            NativeControl("musetalk_right_cheek_width_spin", "Right cheek width", NativeControlKind.INTEGER, "Mask", value=int(state.get("musetalk_right_cheek_width", 90)), minimum=0, maximum=400),
            _action("btn_musetalk_debug_first_frame_quick", "Preview first frame", "Mask"),
            _action("btn_musetalk_debug_first_frame_modified_quick", "Preview with edited mask", "Mask"),
            NativeControl("musetalk_debug_show_mask_overlay_quick_checkbox", "Show mask overlay", NativeControlKind.BOOLEAN, "Mask", value=bool(state.get("musetalk_debug_show_mask_overlay", True))),
            NativeControl("musetalk_mask_ranges_description", "Frame-specific mask ranges", NativeControlKind.DISPLAY, "Ranges", value="Override the mask profile or use passthrough for selected frame intervals."),
            NativeControl("musetalk_mask_range_start_spin", "Range start", NativeControlKind.INTEGER, "Ranges", value=int(state.get("musetalk_mask_range_start", 0)), minimum=0, maximum=frame_max, metadata={"sourceFrameCount": state.get("musetalk_native_source_frame_count"), "sourceFrameMaximumKnown": frame_max is not None}),
            NativeControl("musetalk_mask_range_end_spin", "Range end", NativeControlKind.INTEGER, "Ranges", value=int(state.get("musetalk_mask_range_end", 0)), minimum=0, maximum=frame_max, metadata={"sourceFrameCount": state.get("musetalk_native_source_frame_count"), "sourceFrameMaximumKnown": frame_max is not None}),
            NativeControl("musetalk_mask_range_passthrough_checkbox", "Passthrough / no mask", NativeControlKind.BOOLEAN, "Ranges", value=bool(state.get("musetalk_mask_range_passthrough", False))),
            _action("btn_musetalk_mask_range_add", "Add range from current settings", "Ranges"),
            _action("btn_musetalk_mask_range_update", "Update selected range", "Ranges"),
            _action("btn_musetalk_mask_range_load", "Load selected into mask settings", "Ranges"),
            _action("btn_musetalk_mask_range_remove", "Remove selected range", "Ranges"),
            NativeControl("musetalk_mask_ranges_table", "Mask ranges", NativeControlKind.LIST, "Ranges", value=int(state.get("musetalk_mask_range_selected_index", -1)), choices=self._mask_range_choices(state.get("musetalk_mask_ranges")), metadata={"creatorRows": list(state.get("musetalk_mask_ranges") or []), "rowActions": ["load_mask_range", "update_mask_range", "remove_mask_range"]}),
            NativeControl("musetalk_mask_override_description", "Edited mask overrides", NativeControlKind.DISPLAY, "Overrides", value="Save the current edited debug mask for one exact source frame."),
            _action("btn_musetalk_mask_override_add", "Add current edited mask", "Overrides"),
            _action("btn_musetalk_mask_override_load", "Load selected frame", "Overrides"),
            _action("btn_musetalk_mask_override_remove", "Remove selected override", "Overrides"),
            NativeControl("musetalk_mask_overrides_table", "Mask overrides", NativeControlKind.LIST, "Overrides", value=int(state.get("musetalk_mask_override_selected_index", -1)), choices=self._mask_override_choices(state.get("musetalk_mask_overrides")), metadata={"creatorRows": list(state.get("musetalk_mask_overrides") or []), "rowActions": ["load_mask_override", "remove_mask_override"]}),
            NativeControl("musetalk_debug_description", "First-frame debug", NativeControlKind.DISPLAY, "Debug", value="Debug generation runs on the bounded command worker and publishes the resulting image here."),
            NativeControl("musetalk_debug_frame_index_spin", "Debug frame index", NativeControlKind.INTEGER, "Debug", value=int(state.get("musetalk_debug_frame_index", 0)), minimum=0, maximum=frame_max, metadata={"sourceFrameCount": state.get("musetalk_native_source_frame_count"), "sourceFrameMaximumKnown": frame_max is not None}),
            NativeControl("musetalk_debug_frame_note", "Frame indexing", NativeControlKind.DISPLAY, "Debug", value="Frame 0 is the first source frame."),
            NativeControl("musetalk_debug_show_mask_overlay_checkbox", "Show mask overlay", NativeControlKind.BOOLEAN, "Debug", value=bool(state.get("musetalk_debug_show_mask_overlay", True))),
            NativeControl("musetalk_source_frame_info_label", "Source frame info", NativeControlKind.DISPLAY, "Debug", value=state.get("musetalk_native_source_frame_info", "")),
            NativeControl("musetalk_debug_brush_size_spin", "Brush size", NativeControlKind.INTEGER, "Debug", value=int(state.get("musetalk_debug_brush_size", 12)), minimum=1, maximum=200),
            NativeControl("musetalk_debug_brush_feather_spin", "Brush feather", NativeControlKind.INTEGER, "Debug", value=int(state.get("musetalk_debug_brush_feather", 6)), minimum=0, maximum=100),
            NativeControl("musetalk_debug_brush_transparency_spin", "Brush transparency", NativeControlKind.INTEGER, "Debug", value=int(state.get("musetalk_debug_brush_transparency", 0)), minimum=0, maximum=100),
            NativeControl("musetalk_preview_zoom_label", "Preview zoom", NativeControlKind.DISPLAY, "Debug", value=f"{float(state.get('musetalk_debug_zoom', 1.0)):.2f}×"),
            _action("btn_musetalk_debug_zoom_out", "Zoom out", "Debug"),
            _action("btn_musetalk_debug_zoom_reset", "Fit preview", "Debug"),
            _action("btn_musetalk_debug_zoom_in", "Zoom in", "Debug"),
            NativeControl("musetalk_test_audio_edit", "Test audio", NativeControlKind.TEXT, "Debug", value=state.get("musetalk_test_audio", "")),
            _action("btn_musetalk_test_audio", "Choose audio", "Debug", metadata={"execution": "ui", "filePicker": True, "dialogTitle": "Select MuseTalk first-frame test audio", "nameFilters": ["Audio files (*.wav *.mp3 *.flac *.m4a *.ogg)", "All files (*)"]}),
            NativeControl("musetalk_debug_hint", "Debug hint", NativeControlKind.DISPLAY, "Debug", value="Render a normal preview first. Edited-mask preview requires a modified mask generated by the preview editor."),
            _action("btn_musetalk_debug_first_frame", "Preview first frame", "Debug"),
            _action("btn_musetalk_debug_first_frame_modified", "Preview with edited mask", "Debug"),
            _action("btn_musetalk_first_frame_test", "Audio frame test", "Debug"),
            NativeControl("musetalk_native_preview", "Debug preview", NativeControlKind.IMAGE, "Debug", value=state.get("musetalk_native_preview_path", ""), metadata={"zoom": float(state.get("musetalk_debug_zoom", 1.0))}),
            NativeControl("musetalk_native_preview_details", "Preview details", NativeControlKind.MULTILINE, "Debug", value=json.dumps(state.get("musetalk_native_preview_details", {}), ensure_ascii=False, indent=2), metadata={"readOnly": True, "rows": 8}),
            NativeControl("musetalk_native_progress", "Operation progress", NativeControlKind.PROGRESS, "Status", value=int(state.get("musetalk_native_progress", 0)), minimum=0, maximum=100),
            NativeControl("musetalk_avatar_status_label", "MuseTalk status", NativeControlKind.DISPLAY, "Status", value=state.get("musetalk_native_status", "")),
        )
        return NativeSurface(
            id=self.surface_id,
            title="MuseTalk Preprocess",
            addon_id=self.addon_id,
            sections=("Overview", "Source", "Metadata", "Mask", "Ranges", "Overrides", "Debug", "Status"),
            description="Headless avatar-pack preparation, mask profiles, metadata, previews, and audio-frame tests.",
            controls=apply_card_layout(controls),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        emotion = self._emotion_bindings.get(key)
        if emotion is not None:
            if not isinstance(value, bool):
                self.changed.emit()
                raise TypeError("MuseTalk emotion controls require a boolean value.")
            try:
                self._invoke(
                    "runtime.musetalk_preprocess.native_action",
                    {
                        "action": "set_emotion_enabled",
                        "payload": {**emotion, "enabled": value},
                    },
                )
            except (KeyError, RuntimeError, TypeError, ValueError):
                self.changed.emit()
                raise
            if self._persist is not None:
                self._persist()
            self._revision += 1
            self.changed.emit()
            return
        if key == "musetalk_mask_ranges_table":
            setting = "musetalk_mask_range_selected_index"
        elif key == "musetalk_mask_overrides_table":
            setting = "musetalk_mask_override_selected_index"
        else:
            setting = _SETTING_IDS.get(key, "")
        if not setting:
            self.changed.emit()
            raise KeyError(f"Unknown MuseTalk preprocess field {control_id!r}.")
        try:
            self._invoke(
                "runtime.musetalk_preprocess.native_update",
                {"key": setting, "value": value},
            )
        except (KeyError, RuntimeError, TypeError, ValueError):
            self.changed.emit()
            raise
        if self._persist is not None:
            self._persist()
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        key = str(control_id or "").strip()
        action = _ACTION_IDS.get(key)
        if action is None:
            raise KeyError(f"Unknown MuseTalk preprocess action {control_id!r}.")
        action_payload: Any = payload
        row_setting = ""
        if isinstance(payload, Mapping) and "selected_index" in payload:
            if action in {"load_mask_range", "update_mask_range", "remove_mask_range"}:
                row_setting = "musetalk_mask_range_selected_index"
            elif action in {"load_mask_override", "remove_mask_override"}:
                row_setting = "musetalk_mask_override_selected_index"
        if row_setting:
            self._invoke(
                "runtime.musetalk_preprocess.native_update",
                {"key": row_setting, "value": int(payload["selected_index"])},
            )
            action_payload = None
        if action == "create_pack" and not isinstance(payload, Mapping):
            action_payload = {"name": str(payload or "")}
        self.invoke_creator_action(action, action_payload)


def build_musetalk_preprocess_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], Any] | None = None,
) -> MuseTalkPreprocessNativeAdapter:
    """Register UI without requiring the optional addon to be loaded."""
    return MuseTalkPreprocessNativeAdapter(application_facade, persist=persist)


__all__ = ["MuseTalkPreprocessNativeAdapter", "build_musetalk_preprocess_adapter"]
