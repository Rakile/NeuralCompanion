"""Headless MuseTalk avatar-provider service for native QML."""

from __future__ import annotations
import threading
import weakref
from pathlib import Path

from core.avatar_runtime_context import MuseTalkAdapterInputs

from addons.musetalk_avatar.adapter import MUSE_AVATAR_TRANSITIONS, MUSE_EMOTION_AVATAR_MAP
from addons.musetalk_avatar import state as musetalk_state
from addons.musetalk_avatar.text_policy import normalize_vram_mode
from addons.musetalk_avatar.progressive_settings import KEY as PROGRESSIVE_BUFFER_KEY, normalize_buffer_seconds


class NativeMuseTalkService:
    construction_input_type = MuseTalkAdapterInputs
    _STATE_KEYS = (
        "musetalk_avatar_pack_id",
        "musetalk_vram_mode",
        PROGRESSIVE_BUFFER_KEY,
        "musetalk_loop_fade_ms",
        "musetalk_use_frame_cache",
        "ua_companion_orb_send_musetalk_face_mask",
    )

    def __init__(self, context) -> None:
        app_root = getattr(context, "app_root", None)
        root = Path(app_root) if app_root is not None else Path(__file__).resolve().parents[2]
        self._musetalk_root = root / "MuseTalk"
        self._packs_root = Path(app_root) / "avatar_packs" if app_root is not None else None
        self._runtime_config = context.capabilities.runtime_config
        self._resource_adapters = weakref.WeakSet()
        self._resource_lock = threading.RLock()

    def resources_snapshot(self):
        with self._resource_lock:
            adapters = tuple(self._resource_adapters)
        rows = []
        for adapter in adapters:
            process = getattr(adapter.bridge, 'process', None)
            if process is not None and process.poll() is None:
                rows.append({'id': str(process.pid), 'name': 'MuseTalk', 'model': 'Avatar engine',
                             'owner': 'NC · avatar worker', 'device': 'GPU · MuseTalk worker',
                             'processId': process.pid, 'processLabel': 'MuseTalk worker',
                             'users': ['Avatar rendering'] if getattr(adapter, 'is_speaking', False) else [],
                             'canUnload': True})
        return rows

    def unload_resource(self, instance_id):
        with self._resource_lock:
            adapters = tuple(self._resource_adapters)
        for adapter in adapters:
            process = getattr(adapter.bridge, 'process', None)
            if process is not None and str(process.pid) == str(instance_id) and process.poll() is None:
                adapter.stop_strict()
                return True
        return False

    def delete_package(self, payload):
        from addons.musetalk_avatar.avatar_packs import discover_avatar_packs
        from addons.musetalk_avatar.package_files import delete_package_files, package_deletion_info

        payload = dict(payload or {})
        pack_id = str(payload.get("pack_id") or "").strip()
        token = str(payload.get("token") or "")
        if payload.get("confirmed") is not True or not pack_id or not token:
            raise ValueError("Confirm the selected MuseTalk package before deleting it.")
        if self._packs_root is None:
            raise RuntimeError("The managed avatar package directory is unavailable.")
        with self._resource_lock:
            for adapter in tuple(self._resource_adapters):
                process = getattr(getattr(adapter, "bridge", None), "process", None)
                if not getattr(adapter, "_stopped", False) or (process is not None and process.poll() is None):
                    raise RuntimeError("Unload the MuseTalk worker before deleting an avatar package.")
            runtime = dict(self._runtime_config.snapshot() or {})
            if str(runtime.get("musetalk_avatar_pack_id") or "").strip() != pack_id:
                raise ValueError("The selected MuseTalk package changed; confirm it again.")
            packs = discover_avatar_packs(
                default_avatar_id=str(runtime.get("musetalk_avatar_id") or "default_avatar"),
                packs_dir=self._packs_root, include_legacy=False, include_standalone=False,
            )
            pack = packs.get(pack_id)
            if pack is None or not pack.manifest_path:
                raise ValueError("The selected MuseTalk package is unavailable.")
            info = package_deletion_info(self._packs_root, pack.manifest_path, pack_id, "musetalk")
            if info["token"] != token:
                raise ValueError("The MuseTalk package changed; confirm it again.")
            emotions = dict(runtime.get("musetalk_enabled_pack_emotions") or {})
            emotions.pop(pack_id, None)
            updates = {"musetalk_avatar_pack_id": "", "musetalk_avatar_id": "",
                       "musetalk_enabled_pack_emotions": emotions}
            applied = []
            try:
                for key, value in updates.items():
                    result = self._runtime_config.update(key, value)
                    if result is False or (hasattr(result, "accepted") and not result.accepted):
                        raise RuntimeError("Could not clear MuseTalk package settings.")
                    applied.append(key)
                delete_package_files(self._packs_root, pack.manifest_path, pack_id, "musetalk", token)
            except BaseException:
                rollback_failed = []
                for key in reversed(applied):
                    try:
                        result = self._runtime_config.update(key, runtime.get(key))
                        if result is False or (hasattr(result, "accepted") and not result.accepted):
                            rollback_failed.append(key)
                    except BaseException:
                        rollback_failed.append(key)
                if rollback_failed:
                    raise RuntimeError("Could not restore MuseTalk settings after deletion failed: " + ", ".join(rollback_failed))
                raise
        return {"pack_id": pack_id, "deleted": True}

    def export_avatar_runtime_settings(self) -> dict:
        runtime = dict(self._runtime_config.snapshot() or {})
        return {
            "musetalk_avatar_pack_id": str(runtime.get("musetalk_avatar_pack_id", "") or ""),
            "musetalk_vram_mode": normalize_vram_mode(runtime.get("musetalk_vram_mode", "quality")),
            "musetalk_loop_fade_ms": max(0, int(runtime.get("musetalk_loop_fade_ms", 180) or 0)),
            "musetalk_use_frame_cache": bool(runtime.get("musetalk_use_frame_cache", True)),
            PROGRESSIVE_BUFFER_KEY: normalize_buffer_seconds(runtime.get(PROGRESSIVE_BUFFER_KEY, 2.0)),
            "ua_companion_orb_send_musetalk_face_mask": bool(runtime.get("ua_companion_orb_send_musetalk_face_mask", False)),
        }

    def import_avatar_runtime_settings(self, payload) -> None:
        data = dict(payload or {})
        for key in self._STATE_KEYS:
            if key not in data:
                continue
            value = data[key]
            if key == "musetalk_vram_mode":
                value = normalize_vram_mode(value)
            elif key == PROGRESSIVE_BUFFER_KEY:
                value = normalize_buffer_seconds(value)
            elif key == "musetalk_loop_fade_ms":
                value = max(0, int(value or 0))
            elif key in {"musetalk_use_frame_cache", "ua_companion_orb_send_musetalk_face_mask"}:
                value = bool(value)
            else:
                value = str(value or "").strip()
            self._runtime_config.update(key, value)

    def create_adapter(self, construction_input: MuseTalkAdapterInputs):
        from addons.musetalk_avatar.adapter import MuseTalkAdapter

        actions = construction_input.runtime_actions
        adapter = MuseTalkAdapter(
            root_dir=str(self._musetalk_root),
            runtime_config=dict(construction_input.runtime_config),
            invalidate_available_emotion_names_fn=actions.invalidate_available_emotion_names,
            musetalk_state_module=musetalk_state,
            log_memory_checkpoint_fn=actions.log_memory_checkpoint,
            stop_flag_event=construction_input.stop_requested,
            stop_playback_event=construction_input.playback_stop_requested,
            dry_run_module=actions,
            worker_supervisor=construction_input.worker_supervisor,
            worker_lease_factory=(
                construction_input.work_lease_source.current
                if construction_input.work_lease_source is not None
                else None
            ),
            phone_presentation_getter=construction_input.phone_presentation_getter,
            progressive_settings_getter=self._runtime_config.snapshot,
        )
        with self._resource_lock:
            self._resource_adapters.add(adapter)
        return adapter

    @staticmethod
    def legacy_emotion_avatar_map() -> dict:
        return dict(MUSE_EMOTION_AVATAR_MAP or {})

    @staticmethod
    def legacy_avatar_transitions() -> dict:
        return dict(MUSE_AVATAR_TRANSITIONS or {})

    @staticmethod
    def reset_preview_zoom() -> bool:
        # The Qt Quick viewer owns its zoom transform; the shell handles the
        # visual reset without reaching into a QWidget preview.
        return True

    @staticmethod
    def toggle_avatar_focus() -> bool:
        # Native QML emits the external focus-window request itself.
        return True

    @staticmethod
    def preview_panel_exports() -> dict:
        return {
            "QT_MUSETALK_LOOP_FADE_MS": 180,
            "QT_PREVIEW_AHEAD_PRELOAD": 24,
            "QT_PREVIEW_CACHE_LIMIT": 240,
            "QT_PREVIEW_INITIAL_PRELOAD": 12,
        }
