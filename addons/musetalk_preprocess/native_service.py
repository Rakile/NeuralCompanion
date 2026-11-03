"""Addon-owned MuseTalk preprocessing state and command service.

The original preprocess controller combined MuseTalk domain operations with a
large QWidget form.  The native QML shell uses this service instead: all state
is plain Python data and every potentially expensive command is invoked by the
bounded native command runner.
"""

from __future__ import annotations

import base64
import binascii
import copy
import importlib
import json
import os
import re
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from PySide6.QtCore import QUrl

from addons.musetalk_preprocess.variant_management import MuseTalkVariantManagement
from addons.musetalk_preprocess.creator_jobs import CreatorInputError, CreatorJob, CreatorJobRunner

from addons.musetalk_avatar.avatar_packs import (
    MUSE_AVATAR_PACKS_DIR,
    MuseTalkAvatarPack,
    MuseTalkAvatarVariant,
    avatar_pack_search_dirs,
    discover_avatar_packs,
    save_avatar_pack_manifest,
)


MUSE_AVATAR_RESULTS_DIR = Path("MuseTalk") / "results" / "v15" / "avatars"
MUSE_MASK_OVERRIDE_STAGING_DIR = Path("MuseTalk") / "runtime" / "mask_override_staging"
MUSE_STANDALONE_TARGET_PACK_ID = "__standalone__"
MUSE_STANDALONE_STORAGE_PACK_ID = "stand_alone"
_IMAGE_SOURCE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp"})


DEFAULT_STATE: dict[str, Any] = {
    "musetalk_source_path": "",
    "musetalk_preprocess_target_pack_id": MUSE_STANDALONE_TARGET_PACK_ID,
    "musetalk_selected_avatar_id": "",
    "musetalk_avatar_id": "default_avatar",
    "musetalk_recreate": False,
    "musetalk_create_frame_cache": True,
    "musetalk_emotion_tags": "",
    "musetalk_bbox_shift": 0,
    "musetalk_parsing_mode": "jaw",
    "musetalk_extra_margin": 10,
    "musetalk_left_cheek_width": 90,
    "musetalk_right_cheek_width": 90,
    "musetalk_debug_show_mask_overlay": True,
    "musetalk_mask_range_start": 0,
    "musetalk_mask_range_end": 0,
    "musetalk_mask_range_passthrough": False,
    "musetalk_mask_range_selected_index": -1,
    "musetalk_mask_ranges": [],
    "musetalk_mask_override_selected_index": -1,
    "musetalk_mask_overrides": [],
    "musetalk_debug_frame_index": 0,
    "musetalk_debug_brush_size": 12,
    "musetalk_debug_brush_feather": 6,
    "musetalk_debug_brush_transparency": 0,
    "musetalk_debug_zoom": 1.0,
    "musetalk_test_audio": "",
    "musetalk_enabled_pack_emotions": {},
}


_INTEGER_RANGES: dict[str, tuple[int, int]] = {
    "musetalk_bbox_shift": (-100, 100),
    "musetalk_extra_margin": (0, 200),
    "musetalk_left_cheek_width": (0, 400),
    "musetalk_right_cheek_width": (0, 400),
    "musetalk_mask_range_start": (0, 50000),
    "musetalk_mask_range_end": (0, 50000),
    "musetalk_mask_range_selected_index": (-1, 50000),
    "musetalk_mask_override_selected_index": (-1, 50000),
    "musetalk_debug_frame_index": (0, 50000),
    "musetalk_debug_brush_size": (1, 200),
    "musetalk_debug_brush_feather": (0, 100),
    "musetalk_debug_brush_transparency": (0, 100),
}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(child) for child in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _int_or_default(value: Any, default: int) -> int:
    return int(default if value is None else value)


@dataclass
class _UpdateEffectsCompletion:
    """One waiting update owns all effects submitted by its callback chain."""

    done: threading.Event = field(default_factory=threading.Event)
    errors: list[BaseException] = field(default_factory=list)
    pending: int = 0


class MuseTalkPreprocessHeadlessService(MuseTalkVariantManagement):
    """Widget-independent owner for the native MuseTalk preprocess surface."""

    _SELECTION_KEYS = frozenset(
        {
            "musetalk_source_path",
            "musetalk_preprocess_target_pack_id",
            "musetalk_selected_avatar_id",
            "musetalk_avatar_id",
            "musetalk_debug_frame_index",
        }
    )
    _MASK_IDENTITY_KEYS = frozenset(
        {
            "musetalk_source_path",
            "musetalk_preprocess_target_pack_id",
            "musetalk_selected_avatar_id",
            "musetalk_avatar_id",
            "musetalk_debug_frame_index",
            "musetalk_bbox_shift",
            "musetalk_parsing_mode",
            "musetalk_extra_margin",
            "musetalk_left_cheek_width",
            "musetalk_right_cheek_width",
            "musetalk_mask_ranges",
        }
    )
    _ADMITTED_ACTIONS = frozenset(
        {
            "variant_preview", "variant_redo", "variant_replace", "variant_delete", "variant_make_base",
            "preprocess",
            "debug_preview",
            "debug_preview_modified",
            "audio_frame_test",
            "create_pack",
            "clear_frame_cache",
            "make_default",
            "save_metadata",
            "enable_all_emotions",
            "disable_optional_emotions",
            "set_emotion_enabled",
            "save_edited_mask",
            "add_mask_override",
            "remove_mask_override",
        }
    )
    _MASK_IDENTITY_ACTIONS = frozenset(
        {"debug_preview", "debug_preview_modified", "save_edited_mask", "add_mask_override"}
    )

    def __init__(self, projection: Any, *, bridge_factory=None) -> None:
        app_root = getattr(projection, "app_root", None)
        root = Path(app_root) if app_root is not None else Path(__file__).resolve().parents[2]
        self._musetalk_root = root / "MuseTalk"
        self._logger = getattr(projection, "logger", None)
        self._events = getattr(projection, "events", None)
        capabilities = getattr(projection, "capabilities", None)
        self._shell = getattr(capabilities, "shell_session", None)
        self._runtime_config = getattr(capabilities, "runtime_config", None)
        self._musetalk = getattr(capabilities, "musetalk", None)
        self._avatar = getattr(capabilities, "avatar", None)
        self._state_lock = threading.RLock()
        self._update_effect_lock = threading.RLock()
        self._update_effect_queue: deque[
            tuple[dict[str, Any], _UpdateEffectsCompletion]
        ] = deque()
        self._dispatching_update_effects = False
        self._update_effect_thread_id: int | None = None
        self._active_update_completion: _UpdateEffectsCompletion | None = None
        self._job_local = threading.local()
        self._live_state = _plain(DEFAULT_STATE)
        self._live_status = "MuseTalk Preprocess is ready."
        self._live_progress = 0
        self._live_last_preview: dict[str, Any] = {}
        self._live_preview_identity: dict[str, Any] = {}
        self._live_saved_mask: dict[str, Any] = {}
        self._pending_mask_override: dict[str, Any] = {}
        self._mask_identity_revision = 0
        self._selection_revision = 0
        self._active_job: dict[str, Any] = {}
        self._completed_job: dict[str, Any] = {}
        self._source_frame_count: int | None = None
        self._source_frame_count_reason = "Source path has not been inspected."
        access = getattr(capabilities, "avatar_creation", None)
        self._creator_access = access
        self._preview_revision = 0
        self._job_runner = CreatorJobRunner(
            access=access,
            bridge_factory=bridge_factory or self._create_bridge,
            on_stage=self._on_job_stage,
        )
        self._hydrate_runtime_defaults()

    @property
    def _state(self) -> dict[str, Any]:
        return getattr(self._job_local, "state", self._live_state)

    @property
    def _status(self) -> str:
        return getattr(self._job_local, "status", self._live_status)

    @_status.setter
    def _status(self, value: Any) -> None:
        if hasattr(self._job_local, "state"):
            self._job_local.status = str(value)
        else:
            self._live_status = str(value)

    @property
    def _progress(self) -> int:
        return int(getattr(self._job_local, "progress", self._live_progress))

    @_progress.setter
    def _progress(self, value: Any) -> None:
        if hasattr(self._job_local, "state"):
            self._job_local.progress = int(value)
        else:
            self._live_progress = int(value)

    @property
    def _last_preview(self) -> dict[str, Any]:
        return getattr(self._job_local, "last_preview", self._live_last_preview)

    @_last_preview.setter
    def _last_preview(self, value: Mapping[str, Any]) -> None:
        plain = _plain(value)
        if hasattr(self._job_local, "state"):
            self._job_local.last_preview = plain
            self._job_local.preview_written = True
        else:
            self._live_last_preview = plain
            self._preview_revision += 1

    @property
    def _preview_identity(self) -> dict[str, Any]:
        return getattr(self._job_local, "preview_identity", self._live_preview_identity)

    @_preview_identity.setter
    def _preview_identity(self, value: Mapping[str, Any]) -> None:
        plain = _plain(value)
        if hasattr(self._job_local, "state"):
            self._job_local.preview_identity = plain
        else:
            self._live_preview_identity = plain

    @property
    def _saved_mask(self) -> dict[str, Any]:
        return getattr(self._job_local, "saved_mask", self._live_saved_mask)

    @_saved_mask.setter
    def _saved_mask(self, value: Mapping[str, Any]) -> None:
        plain = _plain(value)
        if hasattr(self._job_local, "state"):
            self._job_local.saved_mask = plain
        else:
            self._live_saved_mask = plain

    @property
    def _pending_override(self) -> dict[str, Any]:
        return getattr(self._job_local, "pending_mask_override", self._pending_mask_override)

    @_pending_override.setter
    def _pending_override(self, value: Mapping[str, Any]) -> None:
        plain = _plain(value)
        if hasattr(self._job_local, "state"):
            self._job_local.pending_mask_override = plain
        else:
            self._pending_mask_override = plain

    def _invalidate_mask_ownership(self) -> None:
        if hasattr(self._job_local, "state"):
            self._preview_identity = {}
            self._saved_mask = {}
            self._pending_override = {}
            if isinstance(self._job_local.last_preview, dict):
                self._job_local.last_preview["modified_mask_path"] = ""
            return
        self._live_preview_identity = {}
        self._live_saved_mask = {}
        self._pending_mask_override = {}
        if isinstance(self._live_last_preview, dict):
            self._live_last_preview["modified_mask_path"] = ""
        self._mask_identity_revision += 1

    def _create_bridge(self):
        module = importlib.import_module("musetalk_bridge")
        return module.MuseTalkBridge(
            root_dir=str(self._musetalk_root),
            worker_options={"vram_mode": self._state.get("_creator_worker_configuration", self._vram_mode())},
        )

    def _on_job_stage(self, job: CreatorJob, stage: str) -> None:
        with self._state_lock:
            self._active_job = {
                "job_id": job.job_id,
                "action": job.action,
                "selection_revision": job.selection_revision,
                "stage": str(stage),
            }
            if stage == "cleanup_failed":
                self._live_status = "MuseTalk creator cleanup is incomplete; runtime access remains reserved."

    def _hydrate_runtime_defaults(self) -> None:
        pack_id = self._runtime_value("musetalk_avatar_pack_id", "")
        if str(pack_id or "").strip():
            self._state["musetalk_preprocess_target_pack_id"] = self._normalize_pack_id(pack_id)
        avatar_id = self._runtime_value("musetalk_avatar_id", "default_avatar")
        self._state["musetalk_avatar_id"] = self._sanitize_avatar_id(avatar_id)
        enabled = self._runtime_value("musetalk_enabled_pack_emotions", {})
        self._state["musetalk_enabled_pack_emotions"] = self._normalize_enabled_emotions(enabled)

    def _runtime_value(self, key: str, default: Any = None) -> Any:
        try:
            getter = getattr(self._runtime_config, "get", None)
            return getter(str(key), default) if callable(getter) else default
        except Exception:
            return default

    def _update_runtime_value(self, key: str, value: Any) -> None:
        try:
            updater = getattr(self._runtime_config, "update", None)
            if callable(updater):
                updater(str(key), _plain(value))
        except Exception:
            return

    def _notify_settings_changed(self) -> None:
        if bool(getattr(self._job_local, "suppress_notifications", False)):
            return
        try:
            callback = getattr(self._shell, "notify_settings_changed", None)
            if callable(callback):
                callback()
        except Exception:
            pass

    @staticmethod
    def _sanitize_avatar_id(value: Any) -> str:
        text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
        return re.sub(r"_+", "_", text).strip("_") or "default_avatar"

    @staticmethod
    def _normalize_pack_id(value: Any) -> str:
        text = str(value or "").strip()
        if not text or text == MUSE_STANDALONE_STORAGE_PACK_ID:
            return MUSE_STANDALONE_TARGET_PACK_ID
        return text

    @staticmethod
    def _parse_emotion_tags(value: Any) -> list[str]:
        chunks = value if isinstance(value, (list, tuple, set)) else str(value or "").split(",")
        tags: list[str] = []
        for raw in chunks:
            tag = str(raw or "").strip().strip("[]").strip().lower()
            if tag and tag not in tags:
                tags.append(tag)
        return tags

    def _normalize_enabled_emotions(self, value: Any) -> dict[str, list[str]]:
        if not isinstance(value, Mapping):
            return {}
        normalized: dict[str, list[str]] = {}
        for raw_pack_id, raw_tags in value.items():
            pack_id = str(raw_pack_id or "").strip()
            if pack_id:
                normalized[pack_id] = self._parse_emotion_tags(raw_tags)
        return normalized

    def _current_enabled_emotions(self) -> dict[str, list[str]]:
        # The runtime page and Creator edit the same setting. Do not reapply the
        # Creator's startup copy after another surface has saved newer choices.
        key = "musetalk_enabled_pack_emotions"
        return self._normalize_enabled_emotions(self._runtime_value(key, self._state[key]))

    def _pack_root(self, pack_id: Any = None) -> Path:
        normalized = self._normalize_pack_id(
            pack_id if pack_id is not None else self._state["musetalk_preprocess_target_pack_id"]
        )
        if normalized == MUSE_STANDALONE_TARGET_PACK_ID:
            return MUSE_AVATAR_PACKS_DIR / MUSE_STANDALONE_STORAGE_PACK_ID
        root = MUSE_AVATAR_PACKS_DIR / normalized
        manifest = root / 'manifest.json'
        if manifest.is_file():
            payload = json.loads(manifest.read_text(encoding='utf-8'))
            if str(payload.get('avatar_engine') or 'musetalk').strip().lower() != 'musetalk':
                raise ValueError('This package belongs to another avatar engine; select a MuseTalk package.')
        return root

    def _avatar_root(self, avatar_id: Any = None, pack_id: Any = None) -> Path:
        return self._pack_root(pack_id) / self._sanitize_avatar_id(
            avatar_id if avatar_id is not None else self._state["musetalk_avatar_id"]
        )

    def _pack_catalog(self) -> dict[str, MuseTalkAvatarPack]:
        legacy_map: dict[str, Any] = {}
        legacy_transitions: dict[str, Any] = {}
        for method_name, target in (
            ("legacy_emotion_avatar_map", legacy_map),
            ("legacy_avatar_transitions", legacy_transitions),
        ):
            try:
                callback = getattr(self._musetalk, method_name, None)
                if callable(callback):
                    target.update(dict(callback() or {}))
            except Exception:
                pass
        try:
            return discover_avatar_packs(
                default_avatar_id=str(self._runtime_value("musetalk_avatar_id", "default_avatar") or "default_avatar"),
                legacy_map=legacy_map,
                legacy_transitions=legacy_transitions,
                avatars_dir=MUSE_AVATAR_RESULTS_DIR,
                include_legacy=False,
                include_standalone=False,
            )
        except Exception:
            return {}

    def _pack_choices(self) -> list[dict[str, str]]:
        values = [{"value": MUSE_STANDALONE_TARGET_PACK_ID, "label": "Standalone Avatars"}]
        seen = {MUSE_STANDALONE_TARGET_PACK_ID, MUSE_STANDALONE_STORAGE_PACK_ID}
        for root in avatar_pack_search_dirs():
            root_path = Path(root)
            if not root_path.is_dir():
                continue
            for child in sorted(root_path.iterdir(), key=lambda item: item.name.lower()):
                if not child.is_dir() or child.name in seen:
                    continue
                manifest = child / 'manifest.json'
                if manifest.is_file():
                    try:
                        payload = json.loads(manifest.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        continue
                    if not isinstance(payload, dict):
                        continue
                    if str(payload.get('avatar_engine') or 'musetalk').strip().lower() != 'musetalk':
                        continue
                # Unfinished MuseTalk folders can contain caches before their
                # manifest is saved; preserve their selection/cleanup workflow.
                seen.add(child.name)
                values.append({'value': child.name, 'label': child.name})
        current = self._normalize_pack_id(self._state["musetalk_preprocess_target_pack_id"])
        if current not in {str(item["value"]) for item in values}:
            if self._state["musetalk_preprocess_target_pack_id"] != MUSE_STANDALONE_TARGET_PACK_ID:
                self._state["musetalk_preprocess_target_pack_id"] = MUSE_STANDALONE_TARGET_PACK_ID
                if not hasattr(self._job_local, "state"):
                    self._selection_revision += 1
                    self._invalidate_mask_ownership()
        return values

    def _avatar_choices(self) -> list[dict[str, str]]:
        values: list[dict[str, str]] = []
        root = self._pack_root()
        if root.is_dir():
            for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
                if child.name.startswith((".prepare-", ".previous-", ".deleted-")):
                    continue
                if child.is_dir() and ((child / "avator_info.json").is_file() or (child / "full_imgs").is_dir()):
                    values.append({"value": child.name, "label": child.name})
        selected = str(self._state.get("musetalk_selected_avatar_id") or "")
        if values and selected not in {str(item["value"]) for item in values}:
            selected = str(values[0]["value"])
            self._state["musetalk_selected_avatar_id"] = selected
            if not hasattr(self._job_local, "state"):
                self._selection_revision += 1
                self._invalidate_mask_ownership()
        if not values:
            if self._state["musetalk_selected_avatar_id"]:
                self._state["musetalk_selected_avatar_id"] = ""
                if not hasattr(self._job_local, "state"):
                    self._selection_revision += 1
                    self._invalidate_mask_ownership()
            values.append({"value": "", "label": "No Prepared Avatars"})
        return values

    def _pack_emotion_summary(self) -> tuple[str, list[dict[str, Any]]]:
        pack_id = self._normalize_pack_id(self._state["musetalk_preprocess_target_pack_id"])
        if pack_id == MUSE_STANDALONE_TARGET_PACK_ID:
            return (
                "Standalone avatars use their own saved emotion tags; pack-level toggles do not apply.",
                [],
            )
        pack = self._pack_catalog().get(pack_id)
        if pack is None:
            return (f"Avatar pack '{pack_id}' could not be loaded.", [])
        mapping = {
            str(tag): str(avatar_id)
            for tag, avatar_id in (pack.emotion_avatar_map() or {}).items()
        }
        locked = {
            tag for tag, avatar_id in mapping.items()
            if avatar_id == str(pack.default_avatar_id or "")
        }
        stored = self._current_enabled_emotions()
        enabled = set(stored.get(pack_id, mapping.keys())) | locked
        rows = [
            {
                "tag": tag,
                "avatar_id": mapping[tag],
                "enabled": tag in enabled,
                "locked": tag in locked,
            }
            for tag in sorted(mapping)
        ]
        optional = max(0, len(rows) - len(locked))
        enabled_optional = sum(1 for row in rows if row["enabled"] and not row["locked"])
        return (
            f"Pack '{pack.display_name or pack.pack_id}' uses '{pack.default_avatar_id}' as its locked base avatar. "
            f"Enabled optional emotion tags: {enabled_optional} / {optional}.",
            rows,
        )

    def _destination(self) -> str:
        return str(self._avatar_root().resolve())

    def _source_frame_info(self) -> str:
        if self._source_frame_count is None:
            return f"Source frames: unknown. {self._source_frame_count_reason}"
        if self._source_frame_count <= 0:
            return "Source frames: unavailable for the current source."
        maximum = self._source_frame_count - 1
        return (
            f"Source frames: {self._source_frame_count} (valid indices 0-{maximum}; "
            f"prepared ping-pong cycle: {self._source_frame_count * 2})."
        )

    def _creator_access_snapshot(self) -> dict[str, str]:
        if self._creator_access is None:
            return {
                "owner": "",
                "phase": "unavailable",
                "reason": "Avatar creation access is unavailable.",
            }
        try:
            return {
                str(key): str(value or "")
                for key, value in dict(self._creator_access.snapshot() or {}).items()
            }
        except Exception as error:
            return {"owner": "", "phase": "unavailable", "reason": str(error)}

    def _confirmation_targets(self) -> dict[str, dict[str, Any]]:
        selection_revision = int(self._selection_revision)
        return {
            "preprocess": {
                "action": "preprocess",
                "target": self._destination(),
                "selection_revision": selection_revision,
                "required": bool(self._state["musetalk_recreate"]),
            },
            "clear_frame_cache": {
                "action": "clear_frame_cache",
                "target": str(self._frame_cache_root().resolve()),
                "selection_revision": selection_revision,
                "required": True,
            },
        }

    def creator_activity_snapshot(self) -> dict[str, Any]:
        """Return only cheap live ownership/job fields for the creator UI."""

        with self._state_lock:
            active_job = _plain(self._active_job)
            completed_job = _plain(self._completed_job)
            status = str(self._live_status)
        cleanup_pending = self._job_runner.cleanup_pending
        residency = self._job_runner.residency_snapshot()
        access = self._creator_access_snapshot()
        active_job_id = str(active_job.get("job_id") or "")
        if not active_job_id and cleanup_pending:
            active_job_id = str(completed_job.get("job_id") or "")
        return {
            "musetalk_native_status": status,
            "musetalk_native_active_job": active_job,
            "musetalk_native_cleanup_pending": cleanup_pending,
            "creator_access": access,
            "creator_residency": residency,
            "creator_busy": bool(active_job or cleanup_pending or residency["busy"] or residency["release_requested"]),
            "creator_job_id": active_job_id,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            pack_summary, emotion_rows = self._pack_emotion_summary()
            access = self._creator_access_snapshot()
            cleanup_pending = self._job_runner.cleanup_pending
            residency = self._job_runner.residency_snapshot()
            active_job_id = str(self._active_job.get("job_id") or "")
            if not active_job_id and cleanup_pending:
                active_job_id = str(self._completed_job.get("job_id") or "")
            payload = _plain(self._state)
            payload["musetalk_enabled_pack_emotions"] = self._current_enabled_emotions()
            payload.update(
                {
                    "musetalk_native_status": self._status,
                    "musetalk_native_progress": int(self._progress),
                    "musetalk_native_pack_choices": self._pack_choices(),
                    "musetalk_native_avatar_choices": self._avatar_choices(),
                    "musetalk_native_destination": self._destination(),
                    "musetalk_native_pack_emotion_summary": pack_summary,
                    "musetalk_native_pack_emotions": emotion_rows,
                    "musetalk_native_variant_entries": self._variant_entries(),
                    "musetalk_native_source_frame_info": self._source_frame_info(),
                    "musetalk_native_source_frame_count": self._source_frame_count,
                    "musetalk_native_source_frame_reason": self._source_frame_count_reason,
                    "musetalk_native_source_frame_max": (
                        self._source_frame_count - 1
                        if self._source_frame_count is not None and self._source_frame_count > 0
                        else None
                    ),
                    "musetalk_native_preview_path": str(self._last_preview.get("frame_path") or ""),
                    "musetalk_native_preview_details": _plain(self._last_preview),
                    "musetalk_native_selection_revision": int(self._selection_revision),
                    "musetalk_native_active_job": _plain(self._active_job),
                    "musetalk_native_completed_job": _plain(self._completed_job),
                    "musetalk_native_cleanup_pending": cleanup_pending,
                    "musetalk_native_confirmation_targets": self._confirmation_targets(),
                    "creator_access": access,
                    "creator_residency": residency,
                    "creator_busy": bool(self._active_job or cleanup_pending or residency["busy"] or residency["release_requested"]),
                    "creator_job_id": active_job_id,
                    "creator_selection_revision": int(self._selection_revision),
                    "creator_preview_revision": int(self._preview_revision),
                    "creator_preview_identity": _plain(self._preview_identity),
                    "creator_edited_mask_path": str(self._saved_mask.get("path") or ""),
                }
            )
            return payload

    def export_session_state(self) -> dict[str, Any]:
        with self._state_lock:
            payload = _plain(self._state)
            payload["musetalk_enabled_pack_emotions"] = self._current_enabled_emotions()
            return payload

    def import_session_state(self, payload: Any) -> None:
        if not isinstance(payload, Mapping):
            return
        enabled_key = "musetalk_enabled_pack_emotions"
        if enabled_key in payload:
            self.update(enabled_key, payload[enabled_key], notify=False)
        for key, value in payload.items():
            if str(key) in DEFAULT_STATE and str(key) != enabled_key:
                self.update(str(key), value, notify=False)
        self._status = "MuseTalk preprocess settings restored."

    def update(self, key: str, value: Any, *, notify: bool = True) -> dict[str, Any]:
        normalized_key = str(key or "").strip()
        if (
            normalized_key == "musetalk_enabled_pack_emotions"
            and not hasattr(self._job_local, "state")
        ):
            self._execute_job(
                "update_enabled_pack_emotions",
                lambda: self._update_for_job(normalized_key, copy.deepcopy(value), notify=notify),
            )
            return self.snapshot()
        job_local_update = hasattr(self._job_local, "state")
        with self._state_lock:
            effects = self._update_locked(normalized_key, value, notify=notify)
            if not job_local_update:
                with self._update_effect_lock:
                    reentrant_dispatch = (
                        self._dispatching_update_effects
                        and self._update_effect_thread_id == threading.get_ident()
                    )
                    # Attribute descendants to the bundle being dispatched, even
                    # when a different caller's thread is draining that bundle.
                    completion = (
                        self._active_update_completion
                        if reentrant_dispatch else _UpdateEffectsCompletion()
                    )
                    assert completion is not None
                    completion.pending += 1
                    self._update_effect_queue.append((effects, completion))
        if job_local_update:
            self._run_update_effects(effects)
            return self.snapshot()
        self._drain_update_effects()
        if not reentrant_dispatch:
            completion.done.wait()
            if completion.errors:
                first_error = completion.errors[0]
                for error in completion.errors[1:]:
                    BaseException.add_note(first_error, f"Additional update callback failure: {error!r}")
                raise first_error
        return self.snapshot()

    def _update_locked(self, normalized_key: str, value: Any, *, notify: bool) -> dict[str, Any]:
        if normalized_key not in DEFAULT_STATE:
            raise KeyError(f"Unknown MuseTalk preprocess setting '{normalized_key}'.")
        previous = _plain(self._state.get(normalized_key))
        default = DEFAULT_STATE[normalized_key]
        if normalized_key in {
            "musetalk_mask_range_start",
            "musetalk_mask_range_end",
            "musetalk_debug_frame_index",
        }:
            value = max(0, int(value))
        elif normalized_key in _INTEGER_RANGES:
            minimum, maximum = _INTEGER_RANGES[normalized_key]
            value = max(minimum, min(maximum, int(value)))
        elif normalized_key == "musetalk_debug_zoom":
            value = max(0.25, min(4.0, float(value)))
        elif isinstance(default, bool):
            value = bool(value)
        elif normalized_key == "musetalk_parsing_mode":
            value = str(value or "jaw").strip().lower()
            if value not in {"jaw", "raw"}:
                raise ValueError("MuseTalk parsing mode must be 'jaw' or 'raw'.")
        elif normalized_key == "musetalk_preprocess_target_pack_id":
            value = self._normalize_pack_id(value)
            self._state["musetalk_selected_avatar_id"] = ""
        elif normalized_key == "musetalk_avatar_id":
            value = self._sanitize_avatar_id(value)
        elif normalized_key == "musetalk_selected_avatar_id":
            value = str(value or "").strip()
        elif normalized_key == "musetalk_source_path":
            value = self._local_path(value)
        elif normalized_key == "musetalk_enabled_pack_emotions":
            value = self._normalize_enabled_emotions(value)
        elif normalized_key in {"musetalk_mask_ranges", "musetalk_mask_overrides"}:
            if not isinstance(value, list):
                raise ValueError(f"{normalized_key} must be a list.")
            normalizer = self._normalize_mask_range if normalized_key.endswith("ranges") else self._normalize_mask_override
            value = [normalizer(item) for item in value]
        else:
            value = str(value or "") if isinstance(default, str) else value
        self._state[normalized_key] = _plain(value)
        if previous != self._state[normalized_key] and normalized_key in self._MASK_IDENTITY_KEYS:
            self._invalidate_mask_ownership()
        if normalized_key == "musetalk_source_path":
            (
                self._source_frame_count,
                self._source_frame_count_reason,
            ) = self._inspect_source_frame_metadata(str(value))
        if normalized_key in self._SELECTION_KEYS and previous != self._state[normalized_key]:
            self._selection_revision += 1
        if normalized_key == "musetalk_selected_avatar_id" and value:
            self._load_selected_avatar(str(value))
        runtime_update = (
            (normalized_key, _plain(value))
            if normalized_key == "musetalk_enabled_pack_emotions"
            else None
        )
        brush_settings = None
        if normalized_key in {
            "musetalk_debug_brush_size",
            "musetalk_debug_brush_feather",
            "musetalk_debug_brush_transparency",
        }:
            brush_settings = {
                "radius": int(self._state["musetalk_debug_brush_size"]),
                "feather": int(self._state["musetalk_debug_brush_feather"]),
                "transparency": int(self._state["musetalk_debug_brush_transparency"]),
            }
        return {
            "runtime_update": runtime_update,
            "brush_settings": brush_settings,
            "notify": bool(notify),
        }

    def _run_update_effects(self, effects: Mapping[str, Any]) -> None:
        runtime_update = effects.get("runtime_update")
        if runtime_update is not None:
            key, value = runtime_update
            self._update_runtime_value(str(key), value)
        brush_settings = effects.get("brush_settings")
        if isinstance(brush_settings, Mapping):
            self._apply_debug_brush(brush_settings)
        if bool(effects.get("notify")):
            self._notify_settings_changed()

    def _drain_update_effects(self) -> None:
        with self._update_effect_lock:
            if self._dispatching_update_effects:
                return
            self._dispatching_update_effects = True
            self._update_effect_thread_id = threading.get_ident()
        while True:
            with self._update_effect_lock:
                if not self._update_effect_queue:
                    self._dispatching_update_effects = False
                    self._update_effect_thread_id = None
                    return
                effects, completion = self._update_effect_queue.popleft()
                self._active_update_completion = completion
            try:
                self._run_update_effects(effects)
            except BaseException as error:
                completion.errors.append(error)
            finally:
                with self._update_effect_lock:
                    self._active_update_completion = None
                    completion.pending -= 1
                    if not completion.pending:
                        completion.done.set()

    def _update_for_job(self, key: str, value: Any, *, notify: bool) -> dict[str, Any]:
        self.update(key, value, notify=notify)
        return {"key": key}

    def _load_selected_avatar(self, avatar_id: str) -> None:
        clean = self._sanitize_avatar_id(avatar_id)
        metadata = self._read_avatar_metadata(clean)
        self._state["musetalk_avatar_id"] = clean
        self._state["musetalk_emotion_tags"] = ", ".join(
            self._parse_emotion_tags(metadata.get("emotion_tags", []))
        )
        for key, default in (
            ("musetalk_bbox_shift", 0),
            ("musetalk_parsing_mode", "jaw"),
            ("musetalk_extra_margin", 10),
            ("musetalk_left_cheek_width", 90),
            ("musetalk_right_cheek_width", 90),
        ):
            metadata_key = key.removeprefix("musetalk_")
            self._state[key] = metadata.get(metadata_key, default)
        self._state["musetalk_mask_ranges"] = [
            self._normalize_mask_range(item) for item in list(metadata.get("mask_ranges") or [])
        ]
        self._state["musetalk_mask_overrides"] = [
            self._normalize_mask_override(item) for item in list(metadata.get("mask_overrides") or [])
        ]
        source = str(metadata.get("video_path") or "").strip()
        if source and not self._state["musetalk_source_path"]:
            self._state["musetalk_source_path"] = source

    def _mask_settings(self) -> dict[str, Any]:
        return {
            "parsing_mode": self._state["musetalk_parsing_mode"],
            "extra_margin": int(self._state["musetalk_extra_margin"]),
            "left_cheek_width": int(self._state["musetalk_left_cheek_width"]),
            "right_cheek_width": int(self._state["musetalk_right_cheek_width"]),
        }

    def _current_mask_profile(self) -> dict[str, Any]:
        return {"bbox_shift": int(self._state["musetalk_bbox_shift"]), **self._mask_settings()}

    def _normalize_mask_range(self, value: Any) -> dict[str, Any]:
        payload = dict(value or {}) if isinstance(value, Mapping) else {}
        start = max(0, int(payload.get("start_frame", 0) or 0))
        end = max(start, int(payload.get("end_frame", start) or start))
        parsing_mode = str(payload.get("parsing_mode", "jaw") or "jaw").lower()
        if parsing_mode not in {"jaw", "raw"}:
            parsing_mode = "jaw"
        return {
            "start_frame": start,
            "end_frame": end,
            "bbox_shift": int(payload.get("bbox_shift", 0) or 0),
            "passthrough": bool(payload.get("passthrough", False)),
            "parsing_mode": parsing_mode,
            "extra_margin": _int_or_default(payload.get("extra_margin"), 10),
            "left_cheek_width": _int_or_default(payload.get("left_cheek_width"), 90),
            "right_cheek_width": _int_or_default(payload.get("right_cheek_width"), 90),
        }

    def _current_mask_range(self) -> dict[str, Any]:
        return self._normalize_mask_range(
            {
                "start_frame": self._state["musetalk_mask_range_start"],
                "end_frame": self._state["musetalk_mask_range_end"],
                "passthrough": self._state["musetalk_mask_range_passthrough"],
                **self._current_mask_profile(),
            }
        )

    @staticmethod
    def _normalize_mask_override(value: Any) -> dict[str, Any]:
        payload = dict(value or {}) if isinstance(value, Mapping) else {}
        bbox = [int(item) for item in list(payload.get("bbox") or [])[:4]]
        crop = [int(item) for item in list(payload.get("crop_box") or [])[:4]]
        path = str(payload.get("override_mask_path") or "").strip()
        source_signature = (
            _plain(payload.get("source_signature"))
            if isinstance(payload.get("source_signature"), Mapping)
            else {}
        )
        return {
            "frame_index": max(0, int(payload.get("frame_index", 0) or 0)),
            "override_mask_path": path,
            "source_path": str(payload.get("source_path") or "").strip(),
            "source_signature": source_signature,
            "range_label": str(payload.get("range_label", "Global") or "Global"),
            "passthrough": bool(payload.get("passthrough", False)),
            "bbox_shift": int(payload.get("bbox_shift", 0) or 0),
            "parsing_mode": str(payload.get("parsing_mode", "jaw") or "jaw"),
            "extra_margin": _int_or_default(payload.get("extra_margin"), 10),
            "left_cheek_width": _int_or_default(payload.get("left_cheek_width"), 90),
            "right_cheek_width": _int_or_default(payload.get("right_cheek_width"), 90),
            "bbox": bbox if len(bbox) == 4 else [],
            "crop_box": crop if len(crop) == 4 else [],
            "mask_width": int(payload.get("mask_width", max(0, crop[2] - crop[0]) if len(crop) == 4 else 0) or 0),
            "mask_height": int(payload.get("mask_height", max(0, crop[3] - crop[1]) if len(crop) == 4 else 0) or 0),
            "status": "OK" if path and Path(path).is_file() else "Missing file",
        }

    def _read_avatar_metadata(self, avatar_id: str) -> dict[str, Any]:
        root = self._avatar_root(avatar_id)
        payload: dict[str, Any] = {"avatar_id": avatar_id, "emotion_tags": []}
        for file_name in ("avatar_pose.json", "avator_info.json"):
            path = root / file_name
            if not path.is_file():
                continue
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(stored, Mapping):
                for key, value in stored.items():
                    if key not in payload or file_name == "avatar_pose.json":
                        payload[str(key)] = _plain(value)
        return payload

    def _write_avatar_metadata(self, avatar_path: Path | None = None) -> Path:
        avatar_id = self._sanitize_avatar_id(self._state["musetalk_avatar_id"])
        root = Path(avatar_path) if avatar_path is not None else self._avatar_root(avatar_id)
        root.mkdir(parents=True, exist_ok=True)
        stored = self._read_avatar_metadata(avatar_id) if avatar_path is None else {}
        payload = {
            "avatar_id": avatar_id,
            "emotion_tags": self._parse_emotion_tags(self._state["musetalk_emotion_tags"]),
            "bbox_shift": int(self._state["musetalk_bbox_shift"]),
            **self._mask_settings(),
            "mask_ranges": _plain(self._state["musetalk_mask_ranges"]),
            "mask_overrides": _plain(self._state["musetalk_mask_overrides"]),
            "source_path": str(stored.get("source_path") or stored.get("video_path") or self._state["musetalk_source_path"] or ""),
            "updated_at": round(time.time(), 3),
        }
        target = root / "avatar_pose.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, target)
        return target

    def _ensure_pack_manifest(self, pack_id: str) -> None:
        if pack_id == MUSE_STANDALONE_TARGET_PACK_ID:
            return
        root = MUSE_AVATAR_PACKS_DIR / pack_id
        root.mkdir(parents=True, exist_ok=True)
        pack = self._pack_catalog().get(pack_id)
        if pack is None:
            pack = MuseTalkAvatarPack(
                pack_id=pack_id,
                display_name=pack_id,
                default_variant="default",
                variants={},
                transitions=[],
                source="nc_pack",
            )
        save_avatar_pack_manifest(pack, packs_dir=MUSE_AVATAR_PACKS_DIR)

    def _record_pack_variant(self, avatar_path: str, *, source_path: str | None = None) -> None:
        pack_id = self._normalize_pack_id(self._state["musetalk_preprocess_target_pack_id"])
        if pack_id == MUSE_STANDALONE_TARGET_PACK_ID:
            return
        avatar_id = self._sanitize_avatar_id(self._state["musetalk_avatar_id"])
        self._ensure_pack_manifest(pack_id)
        pack = self._pack_catalog().get(pack_id)
        if pack is None:
            pack = MuseTalkAvatarPack(pack_id, pack_id, avatar_id, {}, source="nc_pack")
        pack.variants[avatar_id] = MuseTalkAvatarVariant(
            variant_id=avatar_id,
            avatar_id=avatar_id,
            avatar_path=str(Path(avatar_path).resolve()) if avatar_path else "",
            tags=self._parse_emotion_tags(self._state["musetalk_emotion_tags"]),
            display_name=(pack.variants[avatar_id].display_name if avatar_id in pack.variants else avatar_id),
            metadata={**(pack.variants[avatar_id].metadata if avatar_id in pack.variants else {}),
                      "source_path": (str(source_path) if source_path is not None else
                                      str((pack.variants[avatar_id].metadata.get("source_path") if avatar_id in pack.variants else "")
                                          or self._state["musetalk_source_path"] or ""))},
        )
        if not pack.default_variant or pack.default_variant not in pack.variants:
            pack.default_variant = avatar_id
        save_avatar_pack_manifest(pack, packs_dir=MUSE_AVATAR_PACKS_DIR)

    def _vram_mode(self) -> str:
        try:
            snapshot = getattr(self._avatar, "snapshot", None)
            if callable(snapshot):
                return str((snapshot() or {}).get("musetalk_vram_mode_key") or "quality")
        except Exception:
            pass
        return "quality"

    def _bridge_request(self, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
        return self._job_runner.request(payload, timeout=int(timeout))

    def _validate_source(self) -> Path:
        raw = str(self._state["musetalk_source_path"] or "").strip()
        if not raw:
            raise ValueError("Choose a source video, still image, or frame folder first.")
        source = Path(raw)
        if not source.exists():
            raise FileNotFoundError(f"MuseTalk source was not found: {source}")
        return source

    def _validate_overrides(self, source: Path) -> list[dict[str, Any]]:
        values = [self._normalize_mask_override(item) for item in self._state["musetalk_mask_overrides"]]
        missing = [item for item in values if item["status"] != "OK"]
        if missing:
            frames = ", ".join(str(item["frame_index"]) for item in missing[:10])
            raise FileNotFoundError(f"Modified mask files are missing for frame(s): {frames}.")
        resolved_source = source.resolve()
        for item in values:
            stored_source = str(item.get("source_path") or "").strip()
            stored_signature = dict(item.get("source_signature") or {})
            if not stored_source and not stored_signature:
                continue
            frame_index = int(item["frame_index"])
            try:
                matches_source = (
                    not stored_source or Path(stored_source).resolve() == resolved_source
                )
            except OSError:
                matches_source = False
            matches_signature = True
            if stored_signature:
                try:
                    actual_frame_index = self._expected_source_frame_index(
                        resolved_source, frame_index
                    )
                    matches_signature = (
                        self._source_signature(resolved_source, actual_frame_index)
                        == stored_signature
                    )
                except (OSError, RuntimeError):
                    matches_signature = False
            if not matches_source or not matches_signature:
                raise RuntimeError(
                    f"Modified mask override for frame {frame_index} does not match the "
                    "selected source or source frame. Render that frame again and save a "
                    "new override before preprocessing."
                )
        return values

    def _preprocess(self, confirmation: Any = None) -> dict[str, Any]:
        source = self._validate_source()
        avatar_id = self._sanitize_avatar_id(self._state["musetalk_avatar_id"])
        pack_id = self._normalize_pack_id(self._state["musetalk_preprocess_target_pack_id"])
        overrides = self._validate_overrides(source)
        target_root = self._avatar_root(avatar_id, pack_id).resolve()
        self._require_confirmation(
            "preprocess",
            target_root,
            confirmation,
            required=bool(self._state["musetalk_recreate"]),
        )
        self._ensure_pack_manifest(pack_id)
        self._status = f"Preprocessing MuseTalk avatar '{avatar_id}'..."
        self._progress = 5
        response = self._bridge_request(
            {
                "action": "prepare_avatar",
                "avatar_id": avatar_id,
                "avatar_path_override": str(target_root),
                "video_path": str(source),
                "bbox_shift": int(self._state["musetalk_bbox_shift"]),
                "recreate": bool(self._state["musetalk_recreate"]),
                "mask_ranges": _plain(self._state["musetalk_mask_ranges"]),
                "mask_overrides": overrides,
                "create_frame_cache": bool(self._state["musetalk_create_frame_cache"]),
                **self._mask_settings(),
            },
            timeout=1800,
        )
        avatar_path = str(response.get("avatar_path") or "")
        if not avatar_path:
            raise RuntimeError("MuseTalk preprocessing completed without an avatar path.")
        resolved_avatar_path = Path(avatar_path).resolve()
        if resolved_avatar_path != target_root:
            raise RuntimeError("MuseTalk preprocessing returned an unexpected avatar destination.")
        self._write_avatar_metadata(resolved_avatar_path)
        self._record_pack_variant(str(resolved_avatar_path), source_path=str(source.resolve()))
        self._state["musetalk_selected_avatar_id"] = avatar_id
        self._status = f"MuseTalk avatar '{avatar_id}' is ready."
        self._progress = 100
        self._notify_settings_changed()
        return {"avatar_id": avatar_id, "avatar_path": str(resolved_avatar_path)}

    def _resolve_mask_profile(self, frame_index: int) -> dict[str, Any]:
        base = {**self._current_mask_profile(), "passthrough": False, "range_label": "Global"}
        for raw in self._state["musetalk_mask_ranges"]:
            entry = self._normalize_mask_range(raw)
            if entry["start_frame"] <= frame_index <= entry["end_frame"]:
                entry["range_label"] = f"{entry['start_frame']}-{entry['end_frame']}"
                return entry
        return base

    @classmethod
    def _folder_source_candidates(cls, source: Path) -> list[Path]:
        # MuseTalk's worker sorts full path strings with Python's literal,
        # case-sensitive ordering.  Match that exact indexing contract.
        return [
            Path(value)
            for value in sorted(
                str(child)
                for child in source.iterdir()
                if child.is_file() and child.suffix.lower() in _IMAGE_SOURCE_EXTENSIONS
            )
        ]

    @classmethod
    def _expected_source_frame_index(cls, source: Path, requested_frame_index: int) -> int:
        resolved = source.resolve()
        requested = max(0, int(requested_frame_index))
        if resolved.is_dir():
            candidates = cls._folder_source_candidates(resolved)
            if not candidates:
                raise RuntimeError("The selected source folder has no image frames.")
            return min(requested, len(candidates) - 1)
        if resolved.suffix.lower() in _IMAGE_SOURCE_EXTENSIONS:
            return 0
        return requested

    @classmethod
    def _source_signature(cls, source: Path, actual_frame_index: int) -> dict[str, Any]:
        resolved = source.resolve()
        if resolved.is_dir():
            candidates = cls._folder_source_candidates(resolved)
            if not candidates:
                raise RuntimeError("The selected source folder has no image frames.")
            index = int(actual_frame_index)
            if not 0 <= index < len(candidates):
                raise RuntimeError("The selected source folder frame is no longer available.")
            selected = candidates[index].resolve()
            stat = selected.stat()
            return {
                "kind": "folder_frame",
                "source_path": str(resolved),
                "frame_index": index,
                "frame_path": str(selected),
                "candidate_count": len(candidates),
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        stat = resolved.stat()
        return {
            "kind": "file",
            "source_path": str(resolved),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }

    def _make_preview_identity(
        self,
        *,
        source: Path,
        response: Mapping[str, Any],
        profile: Mapping[str, Any],
        source_signature: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            bbox = [int(value) for value in list(response.get("bbox") or [])]
            crop = [int(value) for value in list(response.get("crop_box") or [])]
            actual_frame_index = int(response.get("actual_frame_index", 0) or 0)
        except (TypeError, ValueError):
            return {}
        if len(bbox) != 4 or len(crop) != 4:
            return {}
        width = max(1, crop[2] - crop[0])
        height = max(1, crop[3] - crop[1])
        resolved_source = source.resolve()

        def profile_int(key: str, default: int) -> int:
            raw = response.get(key, profile.get(key, default))
            return int(default if raw is None else raw)

        return {
            "source_path": str(resolved_source),
            "source_signature": _plain(source_signature),
            "actual_frame_index": actual_frame_index,
            "profile": {
                "bbox_shift": profile_int("bbox_shift", 0),
                "parsing_mode": str(response.get("parsing_mode", profile.get("parsing_mode", "jaw")) or "jaw"),
                "extra_margin": profile_int("extra_margin", 10),
                "left_cheek_width": profile_int("left_cheek_width", 90),
                "right_cheek_width": profile_int("right_cheek_width", 90),
                "range_label": str(profile.get("range_label", "Global") or "Global"),
                "passthrough": bool(profile.get("passthrough", False)),
            },
            "bbox": bbox,
            "crop_box": crop,
            "crop_width": width,
            "crop_height": height,
        }

    @staticmethod
    def _identity_base(value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            str(key): _plain(child)
            for key, child in dict(value or {}).items()
            if str(key) != "preview_revision"
        }

    @classmethod
    def _same_preview_identity(cls, first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
        return bool(first) and cls._identity_base(first) == cls._identity_base(second)

    @classmethod
    def _override_matches_identity(cls, entry: Mapping[str, Any], identity: Mapping[str, Any]) -> bool:
        if not identity:
            return False
        profile = dict(identity.get("profile") or {})
        try:
            return (
                int(entry.get("frame_index", -1)) == int(identity["actual_frame_index"])
                and str(entry.get("source_path") or "") == str(identity["source_path"])
                and dict(entry.get("source_signature") or {}) == dict(identity["source_signature"])
                and [int(value) for value in list(entry.get("bbox") or [])] == list(identity["bbox"])
                and [int(value) for value in list(entry.get("crop_box") or [])] == list(identity["crop_box"])
                and int(entry.get("bbox_shift", 0) or 0) == int(profile["bbox_shift"])
                and str(entry.get("parsing_mode", "jaw") or "jaw") == str(profile["parsing_mode"])
                and _int_or_default(entry.get("extra_margin"), 10) == int(profile["extra_margin"])
                and _int_or_default(entry.get("left_cheek_width"), 90) == int(profile["left_cheek_width"])
                and _int_or_default(entry.get("right_cheek_width"), 90) == int(profile["right_cheek_width"])
                and str(entry.get("range_label", "Global") or "Global") == str(profile["range_label"])
                and bool(entry.get("passthrough", False)) == bool(profile["passthrough"])
            )
        except (KeyError, TypeError, ValueError):
            return False

    @staticmethod
    def _mask_file_matches(path: Path, *, width: int, height: int) -> bool:
        try:
            import cv2

            image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        except Exception:
            return False
        return bool(
            image is not None
            and image.dtype.name == "uint8"
            and image.ndim == 2
            and tuple(image.shape) == (int(height), int(width))
        )

    def _validated_saved_mask_path(self) -> Path:
        saved = dict(self._saved_mask or {})
        identity = dict(self._preview_identity or {})
        saved_identity = dict(saved.get("identity") or {})
        if not self._same_preview_identity(saved_identity, identity):
            raise RuntimeError("The edited mask is stale for the current preview identity.")
        source = Path(str(identity.get("source_path") or ""))
        current_signature = self._source_signature(source, int(identity["actual_frame_index"]))
        if current_signature != dict(identity.get("source_signature") or {}):
            raise RuntimeError("The preview source changed; render a fresh preview before saving or reusing a mask.")
        path = Path(str(saved.get("path") or ""))
        if not path.is_file() or not self._mask_file_matches(
            path,
            width=int(identity["crop_width"]),
            height=int(identity["crop_height"]),
        ):
            raise FileNotFoundError("The edited mask file is missing or does not match the preview crop.")
        return path.resolve()

    @staticmethod
    def _decode_mask_png(encoded_value: Any, *, width: int, height: int):
        if not isinstance(encoded_value, str):
            raise ValueError("mask_png_base64 must be a base64 string.")
        try:
            encoded = encoded_value.encode("ascii")
        except UnicodeEncodeError as error:
            raise ValueError("mask_png_base64 must contain ASCII base64 data.") from error
        maximum = 2 * int(width) * int(height) + 65536
        if len(encoded) > maximum:
            raise ValueError("The encoded mask PNG is too large for the preview crop.")
        try:
            png = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("mask_png_base64 is not valid base64.") from error
        if (
            len(png) < 33
            or png[:8] != b"\x89PNG\r\n\x1a\n"
            or int.from_bytes(png[8:12], "big") != 13
            or png[12:16] != b"IHDR"
        ):
            raise ValueError("The edited mask must be a PNG image.")
        png_width = int.from_bytes(png[16:20], "big")
        png_height = int.from_bytes(png[20:24], "big")
        if (png_width, png_height) != (int(width), int(height)):
            raise ValueError("The edited mask PNG dimensions do not match the authoritative preview crop.")
        if png[24] != 8 or png[25] != 0:
            raise ValueError("The edited mask PNG must be 8-bit grayscale.")
        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if (
            image is None
            or image.dtype != np.uint8
            or image.ndim != 2
            or tuple(image.shape) != (int(height), int(width))
        ):
            raise ValueError("The edited mask PNG could not be decoded as 8-bit grayscale.")
        return image

    def _save_edited_mask(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("save_edited_mask requires a preview revision and grayscale PNG data.")
        identity = dict(self._preview_identity or {})
        if not identity:
            raise RuntimeError("Render an editable debug preview before saving a mask.")
        try:
            supplied_revision = int(payload.get("preview_revision", -1))
        except (TypeError, ValueError) as error:
            raise ValueError("preview_revision must be an integer.") from error
        expected_revision = int(identity.get("preview_revision", -1))
        if supplied_revision != expected_revision:
            raise RuntimeError("The edited mask is stale for the current preview revision.")
        current_signature = self._source_signature(
            Path(str(identity["source_path"])), int(identity["actual_frame_index"])
        )
        if current_signature != dict(identity.get("source_signature") or {}):
            raise RuntimeError("The preview source changed; render a fresh preview before saving the mask.")
        image = self._decode_mask_png(
            payload.get("mask_png_base64"),
            width=int(identity["crop_width"]),
            height=int(identity["crop_height"]),
        )
        with self._state_lock:
            if self._live_preview_identity != identity:
                raise RuntimeError("The edited mask is stale for the current preview identity.")
        debug_dir_text = str(self._last_preview.get("debug_dir") or "").strip()
        if not debug_dir_text:
            raise RuntimeError("The authoritative preview has no scratch directory.")
        debug_dir = Path(debug_dir_text)
        target = (debug_dir.resolve() / "debug_mask_modified.png").resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp.png")
        import cv2

        try:
            if not cv2.imwrite(str(temporary), image):
                raise RuntimeError("Could not write the edited mask PNG.")
            os.replace(temporary, target)
        finally:
            if temporary.is_file():
                temporary.unlink()
        self._saved_mask = {"path": str(target), "identity": identity}
        self._status = "MuseTalk edited mask saved to creator scratch storage."
        return {
            "modified_mask_path": str(target),
            "preview_revision": expected_revision,
            "crop_width": int(identity["crop_width"]),
            "crop_height": int(identity["crop_height"]),
        }

    def _debug_preview(self, *, modified: bool, mask_payload: Any = None) -> dict[str, Any]:
        try:
            if modified and mask_payload:
                # The worker consumes a path: stage current UI pixels in derived
                # scratch storage, never in the persistent mask override list.
                self._save_edited_mask(mask_payload)
            source = self._validate_source()
            frame_index = int(self._state["musetalk_debug_frame_index"])
            profile = self._resolve_mask_profile(frame_index)
            expected_frame_index = self._expected_source_frame_index(source, frame_index)
            source_signature_before = self._source_signature(source, expected_frame_index)
            saved_path = self._validated_saved_mask_path() if modified else None
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            if modified:
                raise CreatorInputError(str(error)) from error
            raise
        payload = {
            "action": "debug_first_frame",
            "source_path": str(source),
            "bbox_shift": int(profile["bbox_shift"]),
            "frame_index": frame_index,
            "output_root": os.path.join("runtime", "first_frame_debug"),
            "parsing_mode": profile["parsing_mode"],
            "extra_margin": int(profile["extra_margin"]),
            "left_cheek_width": int(profile["left_cheek_width"]),
            "right_cheek_width": int(profile["right_cheek_width"]),
        }
        if saved_path is not None:
            payload["modified_mask_path"] = str(saved_path)
        self._status = f"Rendering MuseTalk frame {frame_index} preview..."
        self._progress = 10
        response = self._bridge_request(payload, timeout=1800)
        frame_path = str(response.get("frame_path") or "")
        if not frame_path or not Path(frame_path).is_file():
            raise RuntimeError("MuseTalk did not produce a debug preview image.")
        debug_dir = str(response.get("debug_dir") or Path(frame_path).parent)
        actual_frame_index = int(response.get("actual_frame_index", 0) or 0)
        source_signature_after = self._source_signature(source, actual_frame_index)
        if source_signature_after != source_signature_before:
            raise RuntimeError("The preview source changed during the worker render; render it again.")
        preview_identity = self._make_preview_identity(
            source=source,
            response=response,
            profile=profile,
            source_signature=source_signature_before,
        )
        edited_path = ""
        if modified:
            if not self._same_preview_identity(self._preview_identity, preview_identity):
                raise RuntimeError("The edited mask no longer matches the rendered preview identity.")
            edited_path = str(saved_path or "")
            self._saved_mask = {"path": edited_path, "identity": preview_identity}
        else:
            pending = dict(self._pending_override or {})
            pending_path = Path(str(pending.get("override_mask_path") or ""))
            if (
                pending
                and self._override_matches_identity(pending, preview_identity)
                and self._mask_file_matches(
                    pending_path,
                    width=int(preview_identity.get("crop_width", 0)),
                    height=int(preview_identity.get("crop_height", 0)),
                )
            ):
                edited_path = str(pending_path.resolve())
                self._saved_mask = {"path": edited_path, "identity": preview_identity}
            else:
                self._saved_mask = {}
            self._pending_override = {}
        response.update(
            {
                "mode": "debug",
                "frame_path": frame_path,
                "debug_dir": debug_dir,
                "range_label": profile.get("range_label", "Global"),
                "modified_mask_path": edited_path,
            }
        )
        self._preview_identity = preview_identity
        self._last_preview = _plain(response)
        self._status = f"MuseTalk preview frame {response.get('actual_frame_index', frame_index)} is ready."
        self._progress = 100
        self._publish_preview()
        return _plain(response)

    def _publish_preview(self) -> None:
        if bool(getattr(self._job_local, "suppress_notifications", False)):
            return
        frame_path = str(self._last_preview.get("frame_path") or "")
        if not frame_path and self._last_preview.get("mode") != "cleared":
            return
        try:
            callback = getattr(self._musetalk, "publish_preview_path", None)
            if callable(callback):
                callback(frame_path)
        except Exception:
            pass

    def _apply_debug_brush(self, settings: Mapping[str, Any]) -> None:
        try:
            callback = getattr(self._musetalk, "set_debug_mask_brush", None)
            if callable(callback):
                callback(
                    radius=int(settings["radius"]),
                    feather=int(settings["feather"]),
                    transparency=int(settings["transparency"]),
                )
        except Exception:
            pass

    def _audio_frame_test(self) -> dict[str, Any]:
        audio = Path(str(self._state["musetalk_test_audio"] or "").strip())
        if not str(audio) or not audio.is_file():
            raise FileNotFoundError("Choose an existing short test audio file first.")
        source = self._validate_source()
        avatar_id = self._sanitize_avatar_id(self._state["musetalk_avatar_id"])
        scratch_id = f"scratch_{avatar_id}_{uuid4().hex}"
        scratch_root = MUSE_AVATAR_RESULTS_DIR.resolve()
        scratch_path = (scratch_root / scratch_id).resolve()
        if scratch_path.parent != scratch_root or not scratch_path.name.startswith("scratch_"):
            raise RuntimeError("Refusing an unsafe MuseTalk scratch location.")
        self._status = "Rendering MuseTalk audio first-frame test..."
        self._progress = 5
        primary_error: BaseException | None = None
        try:
            self._bridge_request(
                {
                    "action": "prepare_avatar",
                    "avatar_id": scratch_id,
                    "avatar_path_override": str(scratch_path),
                    "video_path": str(source),
                    "bbox_shift": int(self._state["musetalk_bbox_shift"]),
                    "recreate": True,
                    **self._mask_settings(),
                },
                timeout=1800,
            )
            response = self._bridge_request(
                {
                    "action": "render_audio",
                    "avatar_id": scratch_id,
                    "audio_path": str(audio),
                    "chunk_id": f"first_frame_{avatar_id}_{int(time.time())}",
                    "fps": 24,
                    "output_root": os.path.join("runtime", "first_frame_tests"),
                    "max_frames": 1,
                },
                timeout=600,
            )
        except BaseException as error:
            primary_error = error
            raise
        finally:
            try:
                if scratch_path.exists():
                    if scratch_path.parent != scratch_root or not scratch_path.name.startswith("scratch_"):
                        raise RuntimeError("Refusing cleanup outside the owned MuseTalk scratch root.")
                    shutil.rmtree(scratch_path)
            except BaseException as cleanup_error:
                if primary_error is not None:
                    primary_error.add_note(f"MuseTalk scratch cleanup also failed: {cleanup_error}")
                else:
                    raise
        frame_dir = Path(str(response.get("frame_dir") or ""))
        frames = sorted(frame_dir.glob("*.png")) if frame_dir.is_dir() else []
        if not frames:
            raise RuntimeError("MuseTalk audio test produced no PNG frame.")
        self._invalidate_mask_ownership()
        self._last_preview = {
            "mode": "audio",
            "frame_path": str(frames[0]),
            "frame_dir": str(frame_dir),
        }
        self._status = "MuseTalk audio first-frame test is ready."
        self._progress = 100
        self._publish_preview()
        return _plain(self._last_preview)

    def _create_pack(self, payload: Any) -> dict[str, Any]:
        raw = payload.get("name") if isinstance(payload, Mapping) else payload
        pack_id = self._sanitize_avatar_id(raw)
        if not str(raw or "").strip():
            raise ValueError("Enter an avatar pack name.")
        if pack_id == MUSE_STANDALONE_STORAGE_PACK_ID:
            raise ValueError(f"'{MUSE_STANDALONE_STORAGE_PACK_ID}' is reserved.")
        target = MUSE_AVATAR_PACKS_DIR / pack_id
        if target.exists() and not target.is_dir():
            raise FileExistsError(f"A non-folder entry exists at {target}.")
        target.mkdir(parents=True, exist_ok=True)
        self._state["musetalk_preprocess_target_pack_id"] = pack_id
        self._ensure_pack_manifest(pack_id)
        self._status = f"Avatar pack '{pack_id}' is ready."
        self._notify_settings_changed()
        return {"pack_id": pack_id, "path": str(target.resolve())}

    def _frame_cache_root(self) -> Path:
        avatar_id = str(
            self._state.get("musetalk_selected_avatar_id")
            or self._state["musetalk_avatar_id"]
        )
        return self._avatar_root(avatar_id)

    def _clear_frame_cache(self, confirmation: Any = None) -> dict[str, Any]:
        root = self._frame_cache_root().resolve()
        self._require_confirmation("clear_frame_cache", root, confirmation, required=True)
        avatar_id = root.name
        candidates = [root / "frame_cache", root / "frame_cache.npy", root / "full_imgs_cache.npy"]
        removed = 0
        for path in candidates:
            if path.is_dir():
                shutil.rmtree(path)
                removed += 1
            elif path.is_file():
                path.unlink()
                removed += 1
        self._status = f"Cleared {removed} startup cache item(s) for '{avatar_id}'."
        return {"removed": removed}

    def _require_confirmation(
        self,
        action: str,
        target: Path,
        payload: Any,
        *,
        required: bool,
    ) -> None:
        if not required:
            return
        if not isinstance(payload, Mapping) or payload.get("confirmed") is not True:
            raise PermissionError(f"MuseTalk {action} requires explicit target confirmation.")
        expected_revision = int(
            getattr(self._job_local, "selection_revision", self._selection_revision)
        )
        if int(payload.get("selection_revision", -1)) != expected_revision:
            raise RuntimeError(f"MuseTalk {action} confirmation is stale for the current selection.")
        if str(payload.get("action") or "") != action:
            raise RuntimeError(f"MuseTalk {action} confirmation names a different action.")
        try:
            confirmed_target = Path(str(payload.get("target") or "")).resolve()
        except Exception as error:
            raise RuntimeError(f"MuseTalk {action} confirmation has an invalid target.") from error
        if confirmed_target != Path(target).resolve():
            raise RuntimeError(f"MuseTalk {action} confirmation target is stale.")

    def _make_default(self) -> dict[str, Any]:
        pack_id = self._normalize_pack_id(self._state["musetalk_preprocess_target_pack_id"])
        if pack_id == MUSE_STANDALONE_TARGET_PACK_ID:
            raise ValueError("Choose an avatar pack before setting its default variant.")
        avatar_id = str(self._state.get("musetalk_selected_avatar_id") or self._state["musetalk_avatar_id"])
        pack = self._pack_catalog().get(pack_id)
        if pack is None:
            raise FileNotFoundError(f"Avatar pack '{pack_id}' could not be loaded.")
        target_variant = next(
            (
                variant_id for variant_id, variant in pack.variants.items()
                if str(variant_id) == avatar_id or str(variant.avatar_id) == avatar_id
            ),
            "",
        )
        if not target_variant:
            raise FileNotFoundError(f"Variant '{avatar_id}' is not in pack '{pack_id}'.")
        pack.default_variant = target_variant
        path = save_avatar_pack_manifest(pack, packs_dir=self._pack_root(pack_id).parent)
        self._status = f"Pack '{pack_id}' now uses '{avatar_id}' as default."
        return {"manifest": str(path)}

    def _set_all_pack_emotions(self, enabled: bool) -> dict[str, Any]:
        pack_id = self._normalize_pack_id(self._state["musetalk_preprocess_target_pack_id"])
        if pack_id == MUSE_STANDALONE_TARGET_PACK_ID:
            return {"enabled": []}
        pack = self._pack_catalog().get(pack_id)
        if pack is None:
            raise FileNotFoundError(f"Avatar pack '{pack_id}' could not be loaded.")
        mapping = pack.emotion_avatar_map() or {}
        locked = {
            tag for tag, avatar_id in mapping.items()
            if str(avatar_id) == str(pack.default_avatar_id)
        }
        selected = set(mapping) if enabled else locked
        stored = self._current_enabled_emotions()
        stored[pack_id] = sorted(selected)
        self._state["musetalk_enabled_pack_emotions"] = stored
        self._update_runtime_value("musetalk_enabled_pack_emotions", stored)
        self._notify_settings_changed()
        return {"enabled": sorted(selected)}

    def _set_emotion_enabled(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise TypeError("MuseTalk emotion update requires a payload mapping.")
        raw_pack_id = payload.get("pack_id")
        raw_emotion = payload.get("emotion")
        enabled = payload.get("enabled")
        if not isinstance(raw_pack_id, str) or not raw_pack_id.strip():
            raise ValueError("MuseTalk emotion update requires a pack_id string.")
        if not isinstance(raw_emotion, str) or not raw_emotion.strip():
            raise ValueError("MuseTalk emotion update requires an emotion string.")
        if not isinstance(enabled, bool):
            raise TypeError("MuseTalk emotion update enabled value must be boolean.")
        pack_id = self._normalize_pack_id(raw_pack_id)
        pack = self._pack_catalog().get(pack_id)
        if pack is None:
            raise FileNotFoundError(f"Avatar pack '{pack_id}' could not be loaded.")
        parsed_emotions = self._parse_emotion_tags([raw_emotion])
        if not parsed_emotions:
            raise ValueError("MuseTalk emotion update requires a valid emotion tag.")
        emotion = parsed_emotions[0]
        mapping = {
            str(tag): str(avatar_id)
            for tag, avatar_id in (pack.emotion_avatar_map() or {}).items()
        }
        if emotion not in mapping:
            raise KeyError(f"Emotion tag '{emotion}' is not in pack '{pack_id}'.")
        locked = {
            tag
            for tag, avatar_id in mapping.items()
            if avatar_id == str(pack.default_avatar_id or "")
        }
        if not enabled and emotion in locked:
            raise ValueError(f"Emotion tag '{emotion}' is locked to the pack default.")
        stored = self._current_enabled_emotions()
        selected = set(stored.get(pack_id, mapping)) | locked
        if enabled:
            selected.add(emotion)
        else:
            selected.discard(emotion)
        stored[pack_id] = sorted(selected)
        self.update("musetalk_enabled_pack_emotions", stored)
        return {
            "pack_id": pack_id,
            "emotion": emotion,
            "enabled": enabled,
            "enabled_emotions": sorted(selected),
        }

    def _mask_range_action(self, action: str) -> dict[str, Any]:
        ranges = [self._normalize_mask_range(item) for item in self._state["musetalk_mask_ranges"]]
        index = int(self._state["musetalk_mask_range_selected_index"])
        if action == "add_mask_range":
            ranges.append(self._current_mask_range())
            ranges.sort(key=lambda item: (item["start_frame"], item["end_frame"]))
            index = ranges.index(self._current_mask_range()) if self._current_mask_range() in ranges else 0
        elif not (0 <= index < len(ranges)):
            raise IndexError("Select a mask range first.")
        elif action == "update_mask_range":
            ranges[index] = self._current_mask_range()
            ranges.sort(key=lambda item: (item["start_frame"], item["end_frame"]))
        elif action == "load_mask_range":
            entry = ranges[index]
            self._state.update(
                {
                    "musetalk_mask_range_start": entry["start_frame"],
                    "musetalk_mask_range_end": entry["end_frame"],
                    "musetalk_mask_range_passthrough": entry["passthrough"],
                    "musetalk_bbox_shift": entry["bbox_shift"],
                    "musetalk_parsing_mode": entry["parsing_mode"],
                    "musetalk_extra_margin": entry["extra_margin"],
                    "musetalk_left_cheek_width": entry["left_cheek_width"],
                    "musetalk_right_cheek_width": entry["right_cheek_width"],
                }
            )
        elif action == "remove_mask_range":
            del ranges[index]
            index = min(index, len(ranges) - 1)
        self._state["musetalk_mask_ranges"] = ranges
        self._state["musetalk_mask_range_selected_index"] = index
        self._invalidate_mask_ownership()
        self._notify_settings_changed()
        return {"ranges": _plain(ranges), "selected_index": index}

    def _add_mask_override(self) -> dict[str, Any]:
        result = dict(self._last_preview)
        if result.get("mode") != "debug":
            raise RuntimeError("Render a debug preview first.")
        identity = dict(self._preview_identity or {})
        source = self._validated_saved_mask_path()
        frame_index = int(identity["actual_frame_index"])
        staging = (
            MUSE_MASK_OVERRIDE_STAGING_DIR
            / self._sanitize_avatar_id(self._state["musetalk_preprocess_target_pack_id"])
            / self._sanitize_avatar_id(self._state["musetalk_avatar_id"])
        ).resolve()
        staging.mkdir(parents=True, exist_ok=True)
        target = staging / f"{frame_index:08d}.png"
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        profile = dict(identity.get("profile") or {})
        entry = self._normalize_mask_override(
            {
                **result,
                **profile,
                "frame_index": frame_index,
                "source_path": identity.get("source_path", ""),
                "source_signature": identity.get("source_signature", {}),
                "bbox": identity.get("bbox", []),
                "crop_box": identity.get("crop_box", []),
                "mask_width": identity.get("crop_width", 0),
                "mask_height": identity.get("crop_height", 0),
                "override_mask_path": str(target),
            }
        )
        overrides = [
            self._normalize_mask_override(item)
            for item in self._state["musetalk_mask_overrides"]
            if int(dict(item).get("frame_index", -1)) != frame_index
        ]
        overrides.append(entry)
        overrides.sort(key=lambda item: item["frame_index"])
        index = next(i for i, item in enumerate(overrides) if item["frame_index"] == frame_index)
        self._state["musetalk_mask_overrides"] = overrides
        self._state["musetalk_mask_override_selected_index"] = index
        self._notify_settings_changed()
        return {"overrides": _plain(overrides), "selected_index": index}

    def _mask_override_action(self, action: str) -> dict[str, Any]:
        overrides = [self._normalize_mask_override(item) for item in self._state["musetalk_mask_overrides"]]
        index = int(self._state["musetalk_mask_override_selected_index"])
        if not (0 <= index < len(overrides)):
            raise IndexError("Select a mask override first.")
        entry = overrides[index]
        if action == "load_mask_override":
            self.update("musetalk_debug_frame_index", entry["frame_index"])
            self._invalidate_mask_ownership()
            self._pending_override = entry
        elif action == "remove_mask_override":
            path = Path(str(entry.get("override_mask_path") or ""))
            if path.is_file():
                path.unlink()
            saved_path = Path(str(self._saved_mask.get("path") or ""))
            if str(saved_path) and saved_path.resolve() == path.resolve():
                self._saved_mask = {}
            del overrides[index]
            index = min(index, len(overrides) - 1)
            self._state["musetalk_mask_overrides"] = overrides
            self._state["musetalk_mask_override_selected_index"] = index
            self._notify_settings_changed()
        return {"overrides": _plain(overrides), "selected_index": index}

    def _perform_action(self, name: str, payload: Any = None) -> dict[str, Any]:
        if name.startswith("variant_"):
            return self._variant_action(name.removeprefix("variant_"), payload)
        if name in {"refresh_packs", "refresh_avatars"}:
            self._status = "MuseTalk avatar catalog refreshed."
            return {}
        if name == "retry_cleanup":
            if not self.retry_cleanup():
                raise RuntimeError("MuseTalk creator cleanup remains incomplete.")
            self._status = "MuseTalk creator cleanup completed."
            return {"cleanup_complete": True}
        if name == "create_pack":
            return self._create_pack(payload)
        if name == "set_source_path":
            value = payload[0] if isinstance(payload, list) and payload else payload
            return self.update("musetalk_source_path", self._local_path(value))
        if name == "set_test_audio":
            value = payload[0] if isinstance(payload, list) and payload else payload
            return self.update("musetalk_test_audio", self._local_path(value))
        if name == "clear_frame_cache":
            return self._clear_frame_cache(payload)
        if name == "make_default":
            return self._make_default()
        if name == "preprocess":
            return self._preprocess(payload)
        if name == "save_metadata":
            result = {"path": str(self._write_avatar_metadata())}
            self._record_pack_variant(str(self._avatar_root()))
            self._status = "MuseTalk avatar metadata saved."
            return result
        if name == "enable_all_emotions":
            return self._set_all_pack_emotions(True)
        if name == "disable_optional_emotions":
            return self._set_all_pack_emotions(False)
        if name == "set_emotion_enabled":
            return self._set_emotion_enabled(payload)
        if name == "save_edited_mask":
            return self._save_edited_mask(payload)
        if name in {"add_mask_range", "update_mask_range", "load_mask_range", "remove_mask_range"}:
            return self._mask_range_action(name)
        if name == "add_mask_override":
            return self._add_mask_override()
        if name in {"load_mask_override", "remove_mask_override"}:
            return self._mask_override_action(name)
        if name == "debug_preview":
            return self._debug_preview(modified=False)
        if name == "debug_preview_modified":
            return self._debug_preview(modified=True, mask_payload=payload)
        if name == "audio_frame_test":
            return self._audio_frame_test()
        if name == "zoom_out":
            return self.update("musetalk_debug_zoom", float(self._state["musetalk_debug_zoom"]) / 1.2)
        if name == "zoom_reset":
            return self.update("musetalk_debug_zoom", 1.0)
        if name == "zoom_in":
            return self.update("musetalk_debug_zoom", float(self._state["musetalk_debug_zoom"]) * 1.2)
        raise KeyError(f"Unknown MuseTalk preprocess action '{name}'.")

    def _execute_job(self, action: str, operation) -> dict[str, Any]:
        configuration = self._vram_mode()
        with self._state_lock:
            job = CreatorJob(
                job_id=uuid4().hex,
                action=str(action),
                selection_revision=self._selection_revision,
                state={**self._live_state, "_creator_worker_configuration": configuration},
            )
            initial_preview = _plain(self._live_last_preview)
            initial_preview_identity = _plain(self._live_preview_identity)
            initial_saved_mask = _plain(self._live_saved_mask)
            initial_pending_override = _plain(self._pending_mask_override)
            initial_mask_identity_revision = int(self._mask_identity_revision)
        captured: dict[str, Any] = {}

        def run_with_job_state() -> dict[str, Any]:
            self._job_local.state = copy.deepcopy(dict(job.state))
            self._job_local.status = self._live_status
            self._job_local.progress = 0
            self._job_local.last_preview = copy.deepcopy(initial_preview)
            self._job_local.preview_written = False
            self._job_local.preview_identity = copy.deepcopy(initial_preview_identity)
            self._job_local.saved_mask = copy.deepcopy(initial_saved_mask)
            self._job_local.pending_mask_override = copy.deepcopy(initial_pending_override)
            self._job_local.suppress_notifications = True
            self._job_local.selection_revision = job.selection_revision
            try:
                result = dict(operation() or {})
                captured["operation_ok"] = True
                return result
            finally:
                captured["state"] = _plain(self._job_local.state)
                captured["status"] = str(self._job_local.status)
                captured["progress"] = int(self._job_local.progress)
                captured["last_preview"] = _plain(self._job_local.last_preview)
                captured["preview_written"] = bool(self._job_local.preview_written)
                captured["preview_identity"] = _plain(self._job_local.preview_identity)
                captured["saved_mask"] = _plain(self._job_local.saved_mask)
                captured["pending_mask_override"] = _plain(self._job_local.pending_mask_override)
                for attribute in (
                    "state",
                    "status",
                    "progress",
                    "last_preview",
                    "preview_written",
                    "preview_identity",
                    "saved_mask",
                    "pending_mask_override",
                    "suppress_notifications",
                    "selection_revision",
                ):
                    delattr(self._job_local, attribute)

        error: BaseException | None = None
        result: dict[str, Any] = {}
        try:
            result = self._job_runner.execute(job, run_with_job_state)
        except BaseException as exc:
            error = exc

        operation_ok = bool(captured.get("operation_ok"))
        preview_committed = False
        state_committed = False
        with self._state_lock:
            stale_selection = self._selection_revision != job.selection_revision
            stale_preview_identity = (
                action in self._MASK_IDENTITY_ACTIONS
                and self._mask_identity_revision != initial_mask_identity_revision
            )
            cleanup_pending = self._job_runner.cleanup_pending
            if operation_ok and not stale_selection and not stale_preview_identity:
                ownership_current = self._live_preview_identity == initial_preview_identity
                final_state = dict(captured.get("state") or {})
                changed_selection = False
                for key, final_value in final_state.items():
                    original_value = job.state.get(key)
                    if final_value == original_value:
                        continue
                    if self._live_state.get(key) != original_value:
                        continue
                    self._live_state[key] = _plain(final_value)
                    state_committed = True
                    changed_selection = changed_selection or key in self._SELECTION_KEYS
                if changed_selection:
                    self._selection_revision += 1
                final_preview = dict(captured.get("last_preview") or {})
                if bool(captured.get("preview_written")) and self._live_last_preview == initial_preview:
                    next_preview_revision = self._preview_revision + 1
                    final_identity = dict(captured.get("preview_identity") or {})
                    if final_identity:
                        final_identity["preview_revision"] = next_preview_revision
                        final_preview["preview_revision"] = next_preview_revision
                    self._live_last_preview = _plain(final_preview)
                    self._live_preview_identity = _plain(final_identity)
                    final_saved = dict(captured.get("saved_mask") or {})
                    saved_identity = dict(final_saved.get("identity") or {})
                    if final_saved and self._same_preview_identity(saved_identity, final_identity):
                        final_saved["identity"] = _plain(final_identity)
                    else:
                        final_saved = {}
                    self._live_saved_mask = _plain(final_saved)
                    self._pending_mask_override = _plain(
                        captured.get("pending_mask_override") or {}
                    )
                    self._preview_revision = next_preview_revision
                    preview_committed = True
                elif ownership_current:
                    self._live_saved_mask = _plain(captured.get("saved_mask") or {})
                    self._pending_mask_override = _plain(
                        captured.get("pending_mask_override") or {}
                    )
                self._live_status = str(captured.get("status") or self._live_status)
                self._live_progress = int(captured.get("progress") or 0)
            elif operation_ok and (stale_selection or stale_preview_identity):
                self._live_status = (
                    f"MuseTalk {action} completed for an earlier selection or preview identity; "
                    "current selection was unchanged."
                )
                self._live_progress = 0
            if error is not None and not operation_ok:
                suffix = " Creator cleanup is incomplete; runtime access remains reserved." if cleanup_pending else ""
                self._live_status = f"MuseTalk action failed: {error}.{suffix}"
                self._live_progress = 0
            completed_status = (
                "cleanup_failed" if cleanup_pending else "complete" if error is None else "failed"
            )
            notes = list(getattr(error, "__notes__", [])) if error is not None else []
            self._completed_job = {
                "job_id": job.job_id,
                "action": job.action,
                "selection_revision": job.selection_revision,
                "status": completed_status,
                "stale_selection": stale_selection,
                "stale_preview_identity": stale_preview_identity,
                "error": str(error or ""),
                "notes": notes,
                "result": _plain(result),
            }
            self._active_job = {}

        if state_committed:
            self._notify_settings_changed()
        if preview_committed:
            self._publish_preview()
        if error is not None:
            raise error
        return result

    def action(self, action: str, payload: Any = None) -> dict[str, Any]:
        name = str(action or "").strip().lower()
        if name == "release_worker":
            if not self.release_worker():
                raise RuntimeError(self._job_runner.residency_snapshot()["reason"])
            return {"ok": True, "state": self.snapshot()}
        self._progress = 0
        try:
            if name in self._ADMITTED_ACTIONS:
                frozen_payload = copy.deepcopy(payload)
                result = self._execute_job(name, lambda: self._perform_action(name, frozen_payload))
            else:
                result = self._perform_action(name, payload)
            return {"ok": True, "result": _plain(result), "state": self.snapshot()}
        except Exception as exc:
            if name not in self._ADMITTED_ACTIONS:
                self._status = f"MuseTalk action failed: {exc}"
                self._progress = 0
            if self._logger is not None:
                try:
                    self._logger.warning("MuseTalk preprocess action '%s' failed: %s", name, exc)
                except Exception:
                    pass
            raise

    @staticmethod
    def _local_path(value: Any) -> str:
        if isinstance(value, QUrl):
            url = value
            text = url.toLocalFile() if url.isLocalFile() else url.toString()
        else:
            text = str(value or "").strip()
            url = QUrl(text)
            if url.isLocalFile():
                text = url.toLocalFile()
        return str(Path(text).resolve()) if text else ""

    @staticmethod
    def _inspect_source_frame_count(value: str) -> int | None:
        count, _reason = MuseTalkPreprocessHeadlessService._inspect_source_frame_metadata(value)
        return count

    @staticmethod
    def _inspect_source_frame_metadata(value: str) -> tuple[int | None, str]:
        text = str(value or "").strip()
        if not text:
            return None, "Source path is empty; frame bounds are unknown."
        source = Path(text)
        if source.is_dir():
            candidates = sorted(
                child
                for child in source.iterdir()
                if child.is_file() and child.suffix.lower() in _IMAGE_SOURCE_EXTENSIONS
            )
            if not candidates:
                return 0, "No supported image frames were found."
            try:
                import cv2

                if any(cv2.imread(str(child)) is None for child in candidates):
                    return (
                        None,
                        "Source folder contains unreadable image candidates; debug and "
                        "preprocess indexing may differ, so frame bounds are unknown.",
                    )
            except Exception:
                return None, "Source folder readability could not be inspected; frame bounds are unknown."
            return len(candidates), ""
        if not source.is_file():
            return None, "Source path does not exist; frame bounds are unknown."
        if source.suffix.lower() in _IMAGE_SOURCE_EXTENSIONS:
            try:
                import cv2

                if cv2.imread(str(source)) is None:
                    return None, "Source image is unreadable; frame bounds are unknown."
            except Exception:
                return None, "Source image readability could not be inspected; frame bounds are unknown."
            return 1, ""
        try:
            import cv2

            capture = cv2.VideoCapture(str(source))
            try:
                count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            finally:
                capture.release()
            if count > 0:
                return count, ""
            return None, "Video frame count is unavailable; frame bounds are unknown."
        except Exception:
            return None, "Video frame count could not be inspected; frame bounds are unknown."

    def retry_cleanup(self) -> bool:
        cleanup_ok = self._job_runner.retry_cleanup()
        if cleanup_ok:
            with self._state_lock:
                self._active_job = {}
        return cleanup_ok

    def resources_snapshot(self):
        state = self._job_runner.residency_snapshot()
        if not (state.get('loaded') or state.get('cleanup_failed') or state.get('loading')):
            return []
        return [{'id': str(state.get('pid') or 'creator-worker'), 'name': 'MuseTalk Creator',
                 'model': 'Avatar preprocessing and preview', 'owner': 'NC · creator worker',
                 'device': 'GPU · MuseTalk worker', 'canUnload': True,
                 'processId': state.get('pid'), 'processLabel': 'MuseTalk Creator worker',
                 'status': 'cleanup_failed' if state.get('cleanup_failed') else 'loading' if state.get('loading') else 'idle',
                 'error': str(state.get('reason') or ''),
                 'users': ['Avatar Creator'] if state.get('busy') or state.get('loading') else []}]

    def resource_maintenance(self):
        return self._job_runner.resource_maintenance()

    def resource_users(self):
        state = self._job_runner.residency_snapshot()
        return ['Avatar Creator'] if state.get('busy') or state.get('loading') else []

    def unload_resource(self, instance_id):
        if not any(r['id'] == str(instance_id) and not r['users'] for r in self.resources_snapshot()):
            return False
        return self.release_worker('Resources tab')

    def release_worker(self, reason: str = "user") -> bool:
        ok = self._job_runner.release(reason)
        with self._state_lock:
            self._live_status = (
                "MuseTalk unloaded; GPU memory released." if ok else
                "MuseTalk cleanup failed: " + self._job_runner.residency_snapshot()["reason"]
            )
        return ok

    def begin_chat_handoff(self) -> str:
        return self._job_runner.begin_chat_handoff()

    def end_chat_handoff(self, ticket: str) -> None:
        self._job_runner.end_chat_handoff(ticket)

    def prepare_shutdown(self) -> None:
        """Called on the tracked shutdown lane before GUI addon teardown."""
        ticket = self.begin_chat_handoff()
        try:
            self._job_runner.close()
        finally:
            self.end_chat_handoff(ticket)

    def shutdown(self) -> bool:
        self._job_runner.close()
        try:
            callback = getattr(self._musetalk, "clear_debug_mask_editor", None)
            if callable(callback):
                callback()
        except Exception:
            pass
        residency = self._job_runner.residency_snapshot()
        return not (residency["busy"] or residency["loaded"] or residency["cleanup_failed"])


__all__ = [
    "DEFAULT_STATE",
    "MUSE_STANDALONE_TARGET_PACK_ID",
    "MuseTalkPreprocessHeadlessService",
]
