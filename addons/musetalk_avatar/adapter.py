from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from pydub import AudioSegment

from addons.musetalk_avatar import pack_runtime, preview_runtime, state as musetalk_state
from addons.musetalk_avatar.avatar_packs import discover_avatar_packs, get_avatar_pack
from addons.musetalk_avatar.text_policy import normalize_vram_mode
from core import avatar_runtime, runtime_files, streaming_text
from core import expression_state
from musetalk_bridge import MuseTalkBridge


_RUNTIME_SYMBOLS_READY = False


class _DryRunNoop:
    def record_reply_metric(self, *args, **kwargs):
        return None


RUNTIME_CONFIG = {}
invalidate_available_emotion_names = lambda: None
log_musetalk_memory_checkpoint = lambda *args, **kwargs: None
stop_flag = threading.Event()
stop_playback = threading.Event()
dry_run = _DryRunNoop()


MUSE_MAX_INFLIGHT_RENDERS = 3
MUSE_FIRST_CHUNK_PREDICTED_DELAY_SECONDS = 2.0
MUSE_FIRST_CHUNK_DELAY_SAMPLE_LIMIT = 8
MUSE_RENDER_OVERLAP_MS = 150
STREAM_FIRST_CHUNK_PLAN_SECONDS = streaming_text.STREAM_FIRST_CHUNK_PLAN_SECONDS

MUSE_EMOTION_AVATAR_MAP = {
    "angry": "angry_avatar",
}
MUSE_AVATAR_TRANSITIONS = {
    ("angry_avatar", "default_avatar"): {
        "start_frame": 80,
        "end_frame": 7,
    },
}


def list_png_frames(frame_dir):
    return runtime_files.list_png_frames(frame_dir)


def safe_delete_with_retry(file_path, *, retries=5, delay=0.1):
    return runtime_files.safe_delete_with_retry(file_path, retries=retries, delay=delay)


def get_current_musetalk_source_index(state=None, advance_to_next_frame=False):
    return preview_runtime.get_current_musetalk_source_index(
        state,
        runtime_config=RUNTIME_CONFIG,
        musetalk_state_module=musetalk_state,
        advance_to_next_frame=advance_to_next_frame,
    )


def prime_musetalk_preview_frame(playback_state):
    return preview_runtime.prime_musetalk_preview_frame(
        playback_state,
        runtime_config=RUNTIME_CONFIG,
        list_png_frames=list_png_frames,
        musetalk_state_module=musetalk_state,
    )


def _normalize_musetalk_enabled_pack_emotions(value):
    return pack_runtime.normalize_enabled_pack_emotions(value)


def get_musetalk_enabled_pack_emotions(pack_id):
    return pack_runtime.enabled_pack_emotions(RUNTIME_CONFIG, pack_id)


def configure_runtime_symbols(
    *,
    runtime_config,
    invalidate_available_emotion_names_fn,
    musetalk_state_module,
    log_memory_checkpoint_fn,
    stop_flag_event,
    stop_playback_event,
    dry_run_module,
):
    """Install host-owned runtime hooks without making the addon import engine."""
    global RUNTIME_CONFIG
    global invalidate_available_emotion_names
    global log_musetalk_memory_checkpoint
    global stop_flag
    global stop_playback
    global dry_run
    global _RUNTIME_SYMBOLS_READY

    RUNTIME_CONFIG = runtime_config
    invalidate_available_emotion_names = invalidate_available_emotion_names_fn
    log_musetalk_memory_checkpoint = log_memory_checkpoint_fn
    stop_flag = stop_flag_event
    stop_playback = stop_playback_event
    dry_run = dry_run_module
    _RUNTIME_SYMBOLS_READY = True


def _hydrate_engine_symbols():
    # Modern hosts pass runtime hooks through AvatarRuntimeContext. Older hosts
    # fall back to addon-local no-op hooks instead of importing engine.
    if _RUNTIME_SYMBOLS_READY:
        return


class MuseTalkAdapter(avatar_runtime.AvatarAdapter):
    avatar_provider_id = "musetalk"

    def __init__(
        self,
        root_dir="./MuseTalk",
        *,
        runtime_config=None,
        invalidate_available_emotion_names_fn=None,
        musetalk_state_module=None,
        log_memory_checkpoint_fn=None,
        stop_flag_event=None,
        stop_playback_event=None,
        dry_run_module=None,
    ):
        if runtime_config is not None:
            configure_runtime_symbols(
                runtime_config=runtime_config,
                invalidate_available_emotion_names_fn=invalidate_available_emotion_names_fn,
                musetalk_state_module=musetalk_state_module,
                log_memory_checkpoint_fn=log_memory_checkpoint_fn,
                stop_flag_event=stop_flag_event,
                stop_playback_event=stop_playback_event,
                dry_run_module=dry_run_module,
            )
        else:
            _hydrate_engine_symbols()
        self.root_dir = root_dir
        self.vram_mode = normalize_vram_mode(RUNTIME_CONFIG.get("musetalk_vram_mode", "quality"))
        self.bridge = MuseTalkBridge(root_dir=self.root_dir, worker_options={"vram_mode": self.vram_mode})
        self.current_emotion = "neutral"
        self.is_speaking = False
        self.avatar_pack_id = str(RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or "").strip()
        self.avatar_pack = None
        self.available_avatar_packs = {}
        self.avatar_path_overrides = {}
        self.default_avatar_id = RUNTIME_CONFIG.get("musetalk_avatar_id", "default_avatar")
        self.video_path = RUNTIME_CONFIG.get("musetalk_video_path", os.path.join("data", "video", "ani.mp4"))
        self.fps = int(RUNTIME_CONFIG.get("musetalk_fps", 24) or 24)
        self.avatar_id = self.default_avatar_id
        self.avatar_path = None
        self.prepared_avatars = {}
        self.emotion_avatar_map = {}
        self.last_queued_avatar_id = self.default_avatar_id
        self.previous_audio_tail = None
        self.reply_chunk_index = 0
        self.reply_generation = 0
        self.first_chunk_ready_samples = []
        self.first_chunk_seconds_per_frame_samples = []
        self.render_slots = threading.BoundedSemaphore(MUSE_MAX_INFLIGHT_RENDERS)
        self.render_order_condition = threading.Condition()
        self.next_render_order = 0
        self.active_render_order = 0
        self._last_logged_emotion_registry_signature = None
        self._stop_requested = threading.Event()
        self._stop_lock = threading.Lock()
        self._stopped = True

    def _raise_if_start_cancelled(self):
        if self._stop_requested.is_set() or stop_flag.is_set():
            raise RuntimeError("MuseTalk startup cancelled.")

    def _shutdown_requested(self):
        return self._stop_requested.is_set() or stop_flag.is_set()

    def start(self):
        self._stop_requested.clear()
        self._stopped = False
        print(f"🎬 [MuseTalk] Starting worker ({self.vram_mode})...")
        self.bridge.start()
        self._raise_if_start_cancelled()
        self.previous_audio_tail = None
        self._reload_avatar_pose_connections()
        self._raise_if_start_cancelled()
        self.last_queued_avatar_id = self.default_avatar_id
        self._ensure_avatar_prepared(self.default_avatar_id, allow_missing=False)
        self._raise_if_start_cancelled()
        self.avatar_id = self.default_avatar_id
        self.avatar_path = self.prepared_avatars.get(self.default_avatar_id)
        for avatar_id in sorted(set(self.emotion_avatar_map.values())):
            self._raise_if_start_cancelled()
            self._ensure_avatar_prepared(avatar_id, allow_missing=True)
        self._raise_if_start_cancelled()
        print(f"✅ [MuseTalk] Avatar pack ready: {self.avatar_pack_id} -> {self.default_avatar_id}")

    def warm_up(self):
        warmup_dir = os.path.abspath(os.path.join(self.root_dir, "runtime", "warmup"))
        os.makedirs(warmup_dir, exist_ok=True)
        warmup_audio_path = os.path.join(warmup_dir, "musetalk_warmup.wav")
        warmup_chunk_id = f"warmup_{uuid.uuid4().hex[:8]}"
        warmup_frame_dir = os.path.join(warmup_dir, warmup_chunk_id)
        try:
            print("🔥 [MuseTalk] Running early warmup render before LLM reload...")
            AudioSegment.silent(duration=900).export(warmup_audio_path, format="wav")
            started_at = time.time()
            result = self.bridge.request(
                {
                    "action": "render_audio",
                    "avatar_id": self.default_avatar_id,
                    "avatar_path_override": self._avatar_path_override_for_id(self.default_avatar_id),
                    "audio_path": warmup_audio_path,
                    "chunk_id": warmup_chunk_id,
                    "fps": self.fps,
                    "output_root": os.path.join("runtime", "warmup"),
                    "reset_timeline": True,
                    "start_timeline_idx": 0,
                },
                timeout=180,
            )
            elapsed = time.time() - started_at
            print(
                f"✓ [MuseTalk] Early warmup complete: "
                f"{int(result.get('frame_count', 0) or 0)} frame(s) in {elapsed:.2f}s"
            )
            return True
        except Exception as e:
            print(f"⚠️ [MuseTalk] Early warmup failed: {e}")
            return False
        finally:
            safe_delete_with_retry(warmup_audio_path)
            shutil.rmtree(warmup_frame_dir, ignore_errors=True)

    def stop(self):
        with self._stop_lock:
            if self._stopped and self._stop_requested.is_set():
                return
            self._stop_requested.set()
            self._stopped = True
            self.reply_generation += 1
            with self.render_order_condition:
                self.active_render_order = self.next_render_order
                self.render_order_condition.notify_all()
            print("🛑 [MuseTalk] Stopping worker...")
            self.previous_audio_tail = None
            self.bridge.stop()
            print("🔌 [MuseTalk] Disconnected.")

    def set_emotion(self, emotion_name: str):
        self.current_emotion = emotion_name

    def _avatar_path_override_for_id(self, avatar_id):
        return str((self.avatar_path_overrides or {}).get(avatar_id) or "").strip()

    def _prepared_avatar_root(self, avatar_id):
        override = self._avatar_path_override_for_id(avatar_id)
        if override:
            return os.path.abspath(override)
        return os.path.abspath(os.path.join(self.root_dir, "results", "v15", "avatars", avatar_id))

    def _reload_avatar_pose_connections(self):
        requested_pack_id = str(RUNTIME_CONFIG.get("musetalk_avatar_pack_id", self.avatar_pack_id or "") or self.avatar_pack_id or "").strip()
        packs = discover_avatar_packs(
            default_avatar_id=str(RUNTIME_CONFIG.get("musetalk_avatar_id", "default_avatar") or "default_avatar"),
            legacy_map=MUSE_EMOTION_AVATAR_MAP,
            legacy_transitions=MUSE_AVATAR_TRANSITIONS,
            avatars_dir=Path(self.root_dir) / "results" / "v15" / "avatars",
            include_legacy=False,
            include_standalone=False,
        )
        self.available_avatar_packs = dict(packs)
        if not self.available_avatar_packs:
            raise LookupError("No MuseTalk avatar packs found under avatar_packs.")
        selected = packs.get(requested_pack_id)
        if selected is None:
            try:
                selected = get_avatar_pack(
                    default_avatar_id=str(RUNTIME_CONFIG.get("musetalk_avatar_id", "default_avatar") or "default_avatar"),
                    requested_pack_id=requested_pack_id,
                    legacy_map=MUSE_EMOTION_AVATAR_MAP,
                    legacy_transitions=MUSE_AVATAR_TRANSITIONS,
                    avatars_dir=Path(self.root_dir) / "results" / "v15" / "avatars",
                    include_legacy=False,
                    include_standalone=False,
                )
            except LookupError:
                selected = next(iter(self.available_avatar_packs.values()))
            self.available_avatar_packs[selected.pack_id] = selected
        self.avatar_pack = selected
        self.avatar_pack_id = selected.pack_id
        self.default_avatar_id = selected.default_avatar_id
        full_emotion_avatar_map = selected.emotion_avatar_map()
        enabled_tags = get_musetalk_enabled_pack_emotions(selected.pack_id)
        if enabled_tags is None:
            self.emotion_avatar_map = dict(full_emotion_avatar_map)
        else:
            locked_tags = {
                str(tag or "").strip().lower()
                for tag, avatar_id in full_emotion_avatar_map.items()
                if str(tag or "").strip()
                and str(avatar_id or "").strip() == str(selected.default_avatar_id or "").strip()
            }
            allowed_tags = enabled_tags | locked_tags
            self.emotion_avatar_map = {
                tag: avatar_id
                for tag, avatar_id in full_emotion_avatar_map.items()
                if str(tag or "").strip().lower() in allowed_tags
            }
        invalidate_available_emotion_names()
        registered_tags = sorted(
            {
                str(tag or '').strip().lower()
                for tag in (self.emotion_avatar_map or {}).keys()
                if str(tag or '').strip()
            }
        )
        registry_signature = (str(self.avatar_pack_id or ''), tuple(registered_tags))
        if registry_signature != self._last_logged_emotion_registry_signature:
            self._last_logged_emotion_registry_signature = registry_signature
            if registered_tags:
                print(f"🧩 [MuseTalk] Registered emotion tags for pack '{self.avatar_pack_id}': {', '.join(registered_tags)}")
            else:
                print(f"🧩 [MuseTalk] No emotion tags registered for pack '{self.avatar_pack_id}'.")
        self.avatar_path_overrides = {
            str(variant.avatar_id or '').strip(): str(getattr(variant, 'avatar_path', '') or '').strip()
            for variant in (selected.variants or {}).values()
            if str(getattr(variant, 'avatar_path', '') or '').strip()
        }
        return dict(self.emotion_avatar_map)

    def select_avatar_pack(self, pack_id, reset_avatar=True):
        requested_pack_id = str(pack_id or "").strip()
        pack_changed = requested_pack_id != str(self.avatar_pack_id or "").strip()
        self.avatar_pack_id = requested_pack_id
        if pack_changed:
            self.prepared_avatars = {}
            self.avatar_path = None
        self._reload_avatar_pose_connections()
        self._ensure_avatar_prepared(self.default_avatar_id, allow_missing=False)
        if reset_avatar:
            self.current_emotion = "neutral"
            self.avatar_id = self.default_avatar_id
            self.avatar_path = self.prepared_avatars.get(self.default_avatar_id, self.avatar_path)
            self.last_queued_avatar_id = self.default_avatar_id
        return self.avatar_pack

    def get_transition_rule(self, from_avatar_id, to_avatar_id):
        if getattr(self, "avatar_pack", None) is None:
            self._reload_avatar_pose_connections()
        if self.avatar_pack is None:
            return None
        return self.avatar_pack.transition_rule_for_avatar_ids(from_avatar_id, to_avatar_id)

    def _resolve_avatar_id_for_emotion(self, emotion_name):
        clean_emotion = str(emotion_name or "").strip().lower()
        if not getattr(self, "emotion_avatar_map", None):
            self._reload_avatar_pose_connections()
        if not clean_emotion or clean_emotion in {"neutral", "default", "idle", "base"}:
            return self.default_avatar_id
        if clean_emotion:
            exact_avatar_id = self.emotion_avatar_map.get(clean_emotion)
            if exact_avatar_id:
                return exact_avatar_id
        for emotion_key, avatar_id in self.emotion_avatar_map.items():
            if str(emotion_key or "").strip().lower() in clean_emotion:
                return avatar_id
        return None

    def _prepared_avatar_bbox_shift(self, avatar_id):
        avatar_root = self._prepared_avatar_root(avatar_id)
        info_path = os.path.join(avatar_root, "avator_info.json")
        try:
            if os.path.isfile(info_path):
                payload = json.loads(Path(info_path).read_text(encoding="utf-8"))
                return int(payload.get("bbox_shift", 0) or 0)
        except Exception:
            pass
        return 0

    def _ensure_avatar_prepared(self, avatar_id, allow_missing=False):
        if avatar_id in self.prepared_avatars:
            return avatar_id

        avatar_root = self._prepared_avatar_root(avatar_id)
        if allow_missing and not os.path.isdir(avatar_root):
            return None

        bbox_shift = self._prepared_avatar_bbox_shift(avatar_id)

        request_start = time.perf_counter()
        result = self.bridge.request(
            {
                "action": "prepare_avatar",
                "avatar_id": avatar_id,
                "avatar_path_override": self._avatar_path_override_for_id(avatar_id),
                "video_path": self.video_path,
                "bbox_shift": bbox_shift,
                "recreate": False,
                "create_frame_cache": bool(RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)),
            },
            timeout=600,
        )
        request_seconds = time.perf_counter() - request_start
        avatar_path = result.get("avatar_path")
        if avatar_path:
            self.prepared_avatars[avatar_id] = avatar_path
            self._reload_avatar_pose_connections()
            print(f"🎭 [MuseTalk] Prepared avatar variant: {avatar_id}")
            self._log_prepare_timing(avatar_id, result.get("prepare_timing"), request_seconds)
            return avatar_id
        return None

    def _log_prepare_timing(self, avatar_id, timing, request_seconds):
        if not isinstance(timing, dict) or not timing:
            print(f"⏱️ [MuseTalkPrep] {avatar_id}: request={request_seconds:.2f}s")
            return

        runtime = timing.get("runtime_load") if isinstance(timing.get("runtime_load"), dict) else {}
        cache_state = "unknown"
        if runtime:
            if runtime.get("frame_cache_hit"):
                cache_state = "hit/mmap" if runtime.get("frame_cache_mmap") else "hit"
            elif runtime.get("frame_cache_saved"):
                cache_state = "miss/saved"
            elif runtime.get("frame_cache_skipped"):
                cache_state = f"skipped/{runtime.get('frame_cache_skipped')}"
            else:
                cache_state = "miss"
        print(
            "⏱️ [MuseTalkPrep] "
            f"{avatar_id}: request={request_seconds:.2f}s, "
            f"worker_total={float(timing.get('total_seconds', 0.0) or 0.0):.2f}s, "
            f"runtime_load={float(timing.get('runtime_load_seconds', 0.0) or 0.0):.2f}s, "
            f"frames={float(runtime.get('frame_read_imgs_seconds', 0.0) or 0.0):.2f}s, "
            f"masks={float(runtime.get('mask_read_imgs_seconds', 0.0) or 0.0):.2f}s, "
            f"cache={cache_state}"
        )
        if runtime and bool(RUNTIME_CONFIG.get("musetalk_prepare_timing_verbose", False)):
            print(
                "   ↳ "
                f"latents={float(runtime.get('latents_torch_load_seconds', 0.0) or 0.0):.2f}s "
                f"({runtime.get('latent_count', '?')} tensors, {runtime.get('latents_mb', '?')} MiB), "
                f"frames={float(runtime.get('frame_read_imgs_seconds', 0.0) or 0.0):.2f}s "
                f"({runtime.get('frame_count', '?')} imgs, cache={'hit' if runtime.get('frame_cache_hit') else 'miss'}), "
                f"masks={float(runtime.get('mask_read_imgs_seconds', 0.0) or 0.0):.2f}s "
                f"({runtime.get('mask_count', '?')} imgs), "
                f"coords={float(runtime.get('coords_pickle_load_seconds', 0.0) or 0.0):.2f}s, "
                f"mask_coords={float(runtime.get('mask_coords_pickle_load_seconds', 0.0) or 0.0):.2f}s, "
                f"glob={float(runtime.get('frame_glob_sort_seconds', 0.0) or 0.0) + float(runtime.get('mask_glob_sort_seconds', 0.0) or 0.0):.2f}s"
            )
            if runtime.get("frame_cache_saved"):
                print(
                    "   ↳ "
                    f"frame cache saved in {float(runtime.get('frame_cache_save_seconds', 0.0) or 0.0):.2f}s "
                    f"shape={runtime.get('frame_cache_shape', '?')} "
                    f"size={runtime.get('frame_cache_mb', '?')} MiB"
                )
            elif runtime.get("frame_cache_load_seconds") is not None:
                print(
                    "   ↳ "
                    f"frame cache loaded in {float(runtime.get('frame_cache_load_seconds', 0.0) or 0.0):.2f}s "
                    f"shape={runtime.get('frame_cache_shape', '?')} "
                    f"size={runtime.get('frame_cache_mb', '?')} MiB "
                    f"mode={'mmap' if runtime.get('frame_cache_mmap') else 'ram'}"
                )

    def _set_active_avatar(self, avatar_id):
        self.avatar_id = avatar_id
        self.avatar_path = self.prepared_avatars.get(avatar_id, self.avatar_path)

    def set_speaking_state(self, is_speaking: bool):
        self.is_speaking = is_speaking

    def begin_reply(self):
        self.reply_generation += 1
        self.reply_chunk_index = 0
        self.previous_audio_tail = None
        self.last_queued_avatar_id = self.avatar_id or self.default_avatar_id
        with self.render_order_condition:
            self.next_render_order = 0
            self.active_render_order = 0
            self.render_order_condition.notify_all()

    def _estimate_first_chunk_delay(self):
        if bool(RUNTIME_CONFIG.get("stream_mode", False)):
            startup_buffer_frames = max(10, min(int(self.fps * 0.5), 16))
        else:
            startup_buffer_frames = max(24, min(int(self.fps * 2.5), 72))
        if self.first_chunk_seconds_per_frame_samples:
            avg_seconds_per_frame = (
                sum(self.first_chunk_seconds_per_frame_samples)
                / len(self.first_chunk_seconds_per_frame_samples)
            )
            estimated = avg_seconds_per_frame * startup_buffer_frames
            return max(0.25, estimated)
        if not self.first_chunk_ready_samples:
            return MUSE_FIRST_CHUNK_PREDICTED_DELAY_SECONDS
        return sum(self.first_chunk_ready_samples) / len(self.first_chunk_ready_samples)

    def _record_first_chunk_delay(self, delay_seconds):
        try:
            delay_seconds = float(delay_seconds)
        except Exception:
            return
        if delay_seconds <= 0:
            return
        self.first_chunk_ready_samples.append(delay_seconds)
        if len(self.first_chunk_ready_samples) > MUSE_FIRST_CHUNK_DELAY_SAMPLE_LIMIT:
            self.first_chunk_ready_samples = self.first_chunk_ready_samples[-MUSE_FIRST_CHUNK_DELAY_SAMPLE_LIMIT:]

    def _record_first_chunk_seconds_per_frame(self, delay_seconds, frame_count):
        try:
            delay_seconds = float(delay_seconds)
            frame_count = int(frame_count)
        except Exception:
            return
        if delay_seconds <= 0 or frame_count <= 0:
            return
        seconds_per_frame = delay_seconds / max(frame_count, 1)
        self.first_chunk_seconds_per_frame_samples.append(seconds_per_frame)
        if len(self.first_chunk_seconds_per_frame_samples) > MUSE_FIRST_CHUNK_DELAY_SAMPLE_LIMIT:
            self.first_chunk_seconds_per_frame_samples = self.first_chunk_seconds_per_frame_samples[-MUSE_FIRST_CHUNK_DELAY_SAMPLE_LIMIT:]

    def _build_loop_frame_paths(self, full_frame_paths, start_index, count):
        if not full_frame_paths:
            return []
        frame_total = len(full_frame_paths)
        start_index = int(start_index) % frame_total
        count = max(1, int(count))
        return [
            full_frame_paths[(start_index + offset) % frame_total]
            for offset in range(count)
        ]

    def _build_pingpong_frame_paths(self, full_frame_paths, start_index, count):
        forward_paths = self._build_loop_frame_paths(full_frame_paths, start_index, count)
        if len(forward_paths) <= 1:
            return forward_paths
        backward_paths = forward_paths[-2:0:-1]
        return forward_paths + backward_paths

    def _plan_first_chunk_idle_window(self, avatar_id):
        current_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
        if current_state.get("status") != "idle":
            return None
        if current_state.get("avatar_id") != avatar_id:
            return None

        avatar_path = self.prepared_avatars.get(avatar_id)
        if not avatar_path:
            return None

        full_frame_paths = list_png_frames(os.path.join(avatar_path, "full_imgs"))
        if not full_frame_paths:
            return None

        fps = int(current_state.get("fps", self.fps) or self.fps)
        preview_source_index = current_state.get("preview_source_index")
        preview_chunk_id = current_state.get("preview_chunk_id")
        current_chunk_id = current_state.get("chunk_id")
        if preview_chunk_id == current_chunk_id and preview_source_index is not None:
            try:
                current_visible_index = int(preview_source_index) % len(full_frame_paths)
            except Exception:
                current_visible_index = get_current_musetalk_source_index(current_state, advance_to_next_frame=False) % len(full_frame_paths)
        else:
            current_visible_index = get_current_musetalk_source_index(current_state, advance_to_next_frame=False) % len(full_frame_paths)
        predicted_delay = self._estimate_first_chunk_delay()
        predicted_offset_frames = max(1, int(round(predicted_delay * max(fps, 1))))
        predicted_entry_index = (current_visible_index + predicted_offset_frames) % len(full_frame_paths)
        # In normal mode we keep the longer anticipation runway. In stream mode
        # we shorten it so startup stays responsive.
        if bool(RUNTIME_CONFIG.get("stream_mode", False)):
            desired_pingpong_frames = max(18, int(round(fps * STREAM_FIRST_CHUNK_PLAN_SECONDS)))
        else:
            desired_pingpong_frames = max(24, int(round(fps * 3.0)))
        window_size = min(
            max(13, desired_pingpong_frames + 1),
            max(len(full_frame_paths) - 1, 13),
        )
        window_start = predicted_entry_index % len(full_frame_paths)
        plan_id = f"first_chunk_plan:{time.time()}:{uuid.uuid4().hex[:8]}"

        def _orbit_predicted_entry():
            wait_frames = max(predicted_offset_frames - 1, 0)
            if wait_frames > 0:
                time.sleep(wait_frames / max(fps, 1))
            current_source_index = predicted_entry_index
            while not stop_flag.is_set():
                current_plan_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
                if current_plan_state.get("status") != "idle" or current_plan_state.get("avatar_id") != avatar_id:
                    return
                active_chunk_id = current_plan_state.get("chunk_id")
                if active_chunk_id and str(active_chunk_id).startswith("first_chunk_plan:"):
                    return
                current_source_index = get_current_musetalk_source_index(
                    current_plan_state,
                    advance_to_next_frame=False,
                ) % len(full_frame_paths)
                passed_predicted_index = (current_source_index - predicted_entry_index) % len(full_frame_paths)
                if 0 < passed_predicted_index < (len(full_frame_paths) // 2):
                    break
                time.sleep(0.01)
            if stop_flag.is_set():
                return

            window_paths = self._build_pingpong_frame_paths(full_frame_paths, window_start, window_size)
            forward_indices = [
                (window_start + offset) % len(full_frame_paths)
                for offset in range(window_size)
            ]
            backward_indices = forward_indices[-2:0:-1] if len(forward_indices) > 1 else []
            window_source_indices = forward_indices + backward_indices
            musetalk_state.append_musetalk_preview_log(
                f"🕒 [MuseTalkStartup] First chunk plan armed {plan_id}: "
                f"predicted_entry={predicted_entry_index} current_source={current_source_index} "
                f"window_end={(predicted_entry_index + desired_pingpong_frames) % len(full_frame_paths)}"
            )
            log_musetalk_memory_checkpoint(
                "first_chunk_plan_armed",
                plan_id,
                {
                    "predicted_entry": predicted_entry_index,
                    "current_source": current_source_index,
                    "window_size": len(window_paths),
                },
            )
            expression_state.reset_current_expression_data()
            musetalk_state.set_current_musetalk_frame_data({
                "frame_paths": window_paths,
                "source_indices": window_source_indices,
                "frame_dir": "",
                "fps": fps,
                "sync_time": time.time(),
                "duration_seconds": 0.0,
                "trim_start_frames": 0,
                "chunk_id": plan_id,
                "text": "",
                "status": "idle",
                "loop": True,
                "start_index": window_start,
                "frame_count": len(window_paths),
                "avatar_id": avatar_id,
            })
            prime_musetalk_preview_frame(musetalk_state.current_musetalk_frame_data)

        threading.Thread(target=_orbit_predicted_entry, daemon=True).start()
        return predicted_entry_index

    def process_audio_chunk(self, audio_path: str, text: str, output_filename="chunk.json", dry_run_reply_id=None, cancel_check=None):
        def _cancel_requested():
            if self._shutdown_requested() or stop_playback.is_set():
                return True
            if callable(cancel_check):
                try:
                    return bool(cancel_check())
                except Exception:
                    return False
            return False

        if self._shutdown_requested():
            return {"ok": False, "kind": "musetalk", "cancelled": True}
        requested_avatar_id = self._resolve_avatar_id_for_emotion(self.current_emotion)
        if requested_avatar_id:
            active_avatar_id = self._ensure_avatar_prepared(requested_avatar_id, allow_missing=True) or self.default_avatar_id
        else:
            active_avatar_id = self.avatar_id or self.last_queued_avatar_id or self.default_avatar_id
        print(f"🎭 [MuseTalk] Emotion '{self.current_emotion}' -> requested avatar '{requested_avatar_id}' -> active avatar '{active_avatar_id}'")
        self._ensure_avatar_prepared(active_avatar_id, allow_missing=False)
        previous_avatar_id = self.last_queued_avatar_id
        is_first_reply_chunk = self.reply_chunk_index == 0
        sequence_index = self.reply_chunk_index
        self.reply_chunk_index += 1
        reset_timeline = active_avatar_id == "angry_avatar" and previous_avatar_id != active_avatar_id
        self.last_queued_avatar_id = active_avatar_id
        self._set_active_avatar(active_avatar_id)
        with self.render_order_condition:
            render_order = self.next_render_order
            self.next_render_order += 1

        chunk_id = os.path.splitext(os.path.basename(output_filename))[0]
        frame_dir = os.path.abspath(os.path.join(self.root_dir, "runtime", "rendered_chunks", chunk_id))
        os.makedirs(frame_dir, exist_ok=True)
        staged_audio_dir = os.path.abspath(os.path.join(self.root_dir, "runtime", "staged_audio"))
        os.makedirs(staged_audio_dir, exist_ok=True)
        render_audio_path = os.path.join(staged_audio_dir, f"{chunk_id}.wav")
        result_holder = {
            "frame_dir": frame_dir,
            "fps": self.fps,
            "start_index": 0,
            "trim_start_frames": 0,
            "avatar_id": active_avatar_id,
            "sequence_index": sequence_index,
            "generation": self.reply_generation,
            "cancelled": False,
            "dry_run_reply_id": dry_run_reply_id,
        }
        try:
            shutil.copy2(audio_path, render_audio_path)
        except Exception as e:
            print(f"⚠️ [MuseTalk] Audio staging failed: {e}")
            return {"ok": False, "kind": "musetalk"}
        ready_event = threading.Event()

        def render_job():
            temp_audio_paths = []
            trim_start_frames = 0
            job_generation = self.reply_generation
            has_render_turn = False
            acquired_render_slot = False

            def _request_render(
                avatar_id,
                request_chunk_id,
                request_audio_path,
                reset=False,
                timeline_indices=None,
                overlap_prefix_frames=0,
                start_timeline_idx=None,
            ):
                if self._shutdown_requested():
                    raise RuntimeError("MuseTalk render cancelled during shutdown.")
                return self.bridge.request(
                    {
                        "action": "render_audio",
                        "avatar_id": avatar_id,
                        "avatar_path_override": self._avatar_path_override_for_id(avatar_id),
                        "audio_path": request_audio_path,
                        "chunk_id": request_chunk_id,
                        "fps": self.fps,
                        "output_root": os.path.join("runtime", "rendered_chunks"),
                        "reset_timeline": reset,
                        "timeline_indices": timeline_indices,
                        "overlap_prefix_frames": overlap_prefix_frames,
                        "start_timeline_idx": start_timeline_idx,
                    },
                    timeout=180,
                )

            def _merge_frame_dirs(source_dirs, target_dir):
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir, ignore_errors=True)
                os.makedirs(target_dir, exist_ok=True)
                frame_index = 0
                for source_dir in source_dirs:
                    for source_path in list_png_frames(source_dir):
                        shutil.copy2(source_path, os.path.join(target_dir, f"{frame_index:08d}.png"))
                        frame_index += 1
                return frame_index

            try:
                if job_generation != self.reply_generation or _cancel_requested():
                    result_holder["cancelled"] = True
                    return
                self.render_slots.acquire()
                acquired_render_slot = True
                if job_generation != self.reply_generation or _cancel_requested():
                    result_holder["cancelled"] = True
                    return
                with self.render_order_condition:
                    while (
                        render_order != self.active_render_order
                        and job_generation == self.reply_generation
                        and not _cancel_requested()
                    ):
                        self.render_order_condition.wait(timeout=0.1)
                    if job_generation != self.reply_generation or _cancel_requested():
                        result_holder["cancelled"] = True
                        return
                    has_render_turn = True
                transition_rule = self.get_transition_rule(previous_avatar_id, active_avatar_id)
                use_transition_render = bool(
                    transition_rule
                    and previous_avatar_id != active_avatar_id
                )
                overlap_source = self.previous_audio_tail
                if use_transition_render:
                    overlap_source = None
                requested_start_timeline_idx = None
                render_started_at = time.time()
                if is_first_reply_chunk:
                    musetalk_state.append_musetalk_preview_log(
                        f"🕒 [MuseTalkStartup] First chunk render start {chunk_id}: "
                        f"avatar={active_avatar_id} emotion={self.current_emotion} "
                        f"audio_path={os.path.basename(render_audio_path)}"
                    )
                    log_musetalk_memory_checkpoint(
                        "first_chunk_render_start",
                        chunk_id,
                        {
                            "avatar": active_avatar_id,
                            "emotion": self.current_emotion,
                            "audio_path": os.path.basename(render_audio_path),
                        },
                    )
                if is_first_reply_chunk and not use_transition_render:
                    requested_start_timeline_idx = self._plan_first_chunk_idle_window(active_avatar_id)
                    if requested_start_timeline_idx is not None:
                        result_holder["start_index"] = int(requested_start_timeline_idx)

                if use_transition_render:
                    audio_segment = AudioSegment.from_wav(render_audio_path)
                    transition_indices_full = list(
                        range(
                            int(transition_rule["start_frame"]),
                            int(transition_rule["end_frame"]) - 1,
                            -1,
                        )
                    )
                    max_transition_frames = max(1, int((len(audio_segment) / 1000.0) * self.fps))
                    transition_indices = transition_indices_full[:max_transition_frames]
                    transition_ms = int(round((len(transition_indices) / max(self.fps, 1)) * 1000))

                    frame_dirs_to_merge = []
                    total_render_seconds = 0.0

                    if transition_indices:
                        transition_audio_path = os.path.join(staged_audio_dir, f"{chunk_id}_transition.wav")
                        temp_audio_paths.append(transition_audio_path)
                        audio_segment[:transition_ms].export(transition_audio_path, format="wav")
                        transition_chunk_id = f"{chunk_id}_transition"
                        transition_result = _request_render(
                            previous_avatar_id,
                            transition_chunk_id,
                            transition_audio_path,
                            reset=False,
                            timeline_indices=transition_indices,
                        )
                        frame_dirs_to_merge.append(transition_result.get("frame_dir"))
                        total_render_seconds += float(transition_result.get("render_seconds", 0.0) or 0.0)

                    remainder_audio = audio_segment[transition_ms:]
                    if len(remainder_audio) > 0:
                        default_audio_path = os.path.join(staged_audio_dir, f"{chunk_id}_default.wav")
                        temp_audio_paths.append(default_audio_path)
                        remainder_audio.export(default_audio_path, format="wav")
                        default_chunk_id = f"{chunk_id}_default"
                        default_result = _request_render(
                            active_avatar_id,
                            default_chunk_id,
                            default_audio_path,
                            reset=True,
                        )
                        frame_dirs_to_merge.append(default_result.get("frame_dir"))
                        total_render_seconds += float(default_result.get("render_seconds", 0.0) or 0.0)

                    merged_frame_count = _merge_frame_dirs(frame_dirs_to_merge, frame_dir)
                    result = {
                        "frame_dir": frame_dir,
                        "frame_count": merged_frame_count,
                        "fps": self.fps,
                        "render_seconds": total_render_seconds,
                        "start_index": 0,
                    }
                else:
                    request_audio_path = render_audio_path
                    if overlap_source is not None and len(overlap_source) > 0:
                        current_audio = AudioSegment.from_wav(render_audio_path)
                        combined_audio = overlap_source + current_audio
                        overlap_audio_path = os.path.join(staged_audio_dir, f"{chunk_id}_overlap.wav")
                        temp_audio_paths.append(overlap_audio_path)
                        combined_audio.export(overlap_audio_path, format="wav")
                        request_audio_path = overlap_audio_path
                        if _cancel_requested():
                            result_holder["cancelled"] = True
                            return
                        combined_count_result = self.bridge.request(
                            {
                                "action": "estimate_frame_count",
                                "avatar_id": active_avatar_id,
                                "avatar_path_override": self._avatar_path_override_for_id(active_avatar_id),
                                "audio_path": overlap_audio_path,
                                "fps": self.fps,
                            },
                            timeout=120,
                        )
                        if _cancel_requested():
                            result_holder["cancelled"] = True
                            return
                        current_count_result = self.bridge.request(
                            {
                                "action": "estimate_frame_count",
                                "avatar_id": active_avatar_id,
                                "avatar_path_override": self._avatar_path_override_for_id(active_avatar_id),
                                "audio_path": render_audio_path,
                                "fps": self.fps,
                            },
                            timeout=120,
                        )
                        if _cancel_requested():
                            result_holder["cancelled"] = True
                            return
                        trim_start_frames = max(
                            0,
                            int(combined_count_result.get("frame_count", 0) or 0)
                            - int(current_count_result.get("frame_count", 0) or 0),
                        )
                        print(
                            f"🪡 [MuseTalk] Applying {len(overlap_source)} ms overlap "
                            f"({trim_start_frames} frame(s)) to {chunk_id}"
                        )
                        result_holder["trim_start_frames"] = trim_start_frames
                    if _cancel_requested():
                        result_holder["cancelled"] = True
                        return
                    result = _request_render(
                        active_avatar_id,
                        chunk_id,
                        request_audio_path,
                        reset=reset_timeline,
                        overlap_prefix_frames=trim_start_frames,
                        start_timeline_idx=requested_start_timeline_idx,
                    )
                    if _cancel_requested():
                        result_holder["cancelled"] = True
                        return
                result_holder.update(result)
                result_holder["trim_start_frames"] = trim_start_frames
                result_holder["avatar_id"] = active_avatar_id
                result_holder["sequence_index"] = sequence_index
                result_holder["generation"] = job_generation
                musetalk_state.update_musetalk_pipeline_chunk(
                    sequence_index,
                    status="rendered",
                    expected_frame_count=int(result.get("frame_count", 0) or 0),
                    chunk_id=chunk_id,
                )
                if is_first_reply_chunk:
                    measured_ready_delay = time.time() - render_started_at
                    self._record_first_chunk_delay(measured_ready_delay)
                    self._record_first_chunk_seconds_per_frame(
                        measured_ready_delay,
                        int(result.get("frame_count", 0) or 0),
                    )
                    seconds_per_frame = 0.0
                    frame_count = int(result.get("frame_count", 0) or 0)
                    if frame_count > 0:
                        seconds_per_frame = measured_ready_delay / frame_count
                    musetalk_state.append_musetalk_preview_log(
                        f"🕒 [MuseTalkStartup] First chunk render ready {chunk_id}: "
                        f"ready_in={measured_ready_delay * 1000.0:.1f} ms "
                        f"frames={int(result.get('frame_count', 0) or 0)} "
                        f"spf_ms={seconds_per_frame * 1000.0:.2f} "
                        f"start_index={int(result.get('start_index', 0) or 0)} "
                        f"trim={trim_start_frames}"
                    )
                    log_musetalk_memory_checkpoint(
                        "first_chunk_render_ready",
                        chunk_id,
                        {
                            "ready_ms": round(measured_ready_delay * 1000.0, 1),
                            "frames": int(result.get("frame_count", 0) or 0),
                            "spf_ms": round(seconds_per_frame * 1000.0, 2),
                            "start_index": int(result.get("start_index", 0) or 0),
                            "trim": trim_start_frames,
                        },
                    )
                    dry_run.record_reply_metric(
                        dry_run_reply_id,
                        "first_chunk_render_ready_ms",
                        round(measured_ready_delay * 1000.0, 1),
                    )
                    dry_run.record_reply_metric(
                        dry_run_reply_id,
                        "first_chunk_spf_ms",
                        round(seconds_per_frame * 1000.0, 2),
                    )
                    dry_run.record_reply_metric(
                        dry_run_reply_id,
                        "first_chunk_frame_count",
                        int(result.get("frame_count", 0) or 0),
                    )
                current_audio = AudioSegment.from_wav(render_audio_path)
                self.previous_audio_tail = current_audio[-MUSE_RENDER_OVERLAP_MS:] if len(current_audio) > 0 else None
                print(
                    f"🎞️ [MuseTalk] Chunk {chunk_id}: "
                    f"{result.get('frame_count', 0)} frame(s) at {result.get('fps', self.fps)} fps "
                    f"in {result.get('render_seconds', 0):.2f}s "
                    f"[avatar={active_avatar_id}, emotion={self.current_emotion}]"
                )
            except Exception as e:
                print(f"⚠️ [MuseTalk] Render failed: {e}")
            finally:
                if has_render_turn:
                    with self.render_order_condition:
                        if job_generation == self.reply_generation and render_order == self.active_render_order:
                            self.active_render_order += 1
                        self.render_order_condition.notify_all()
                try:
                    if acquired_render_slot:
                        self.render_slots.release()
                except Exception:
                    pass
                safe_delete_with_retry(render_audio_path)
                for temp_audio_path in temp_audio_paths:
                    safe_delete_with_retry(temp_audio_path)
                ready_event.set()

        try:
            threading.Thread(target=render_job, daemon=True).start()
            return {
                "ok": True,
                "kind": "musetalk",
                "frame_paths": [],
                "frame_dir": frame_dir,
                "fps": self.fps,
                "chunk_id": chunk_id,
                "ready_event": ready_event,
                "result_holder": result_holder,
                "avatar_id": active_avatar_id,
                "sequence_index": sequence_index,
            }
        except Exception as e:
            print(f"⚠️ [MuseTalk] Render failed: {e}")
            return {"ok": False, "kind": "musetalk"}

    def get_idle_payload(self, avatar_id=None):
        if self._shutdown_requested():
            return None
        target_avatar_id = avatar_id or self.avatar_id or self.default_avatar_id
        self._ensure_avatar_prepared(target_avatar_id, allow_missing=False)
        avatar_path = self.prepared_avatars.get(target_avatar_id)
        if not avatar_path:
            return None

        try:
            result = self.bridge.request(
                {
                    "action": "get_idle_payload",
                    "avatar_id": target_avatar_id,
                    "avatar_path_override": self._avatar_path_override_for_id(target_avatar_id),
                    "fps": self.fps,
                },
                timeout=30,
            )
        except Exception as e:
            print(f"⚠️ [MuseTalk] Idle payload failed: {e}")
            return None

        self._set_active_avatar(target_avatar_id)
        return {
            "frame_paths": result.get("ordered_frame_paths", result.get("frame_paths", [])),
            "frame_dir": result.get("frame_dir", ""),
            "fps": result.get("fps", self.fps),
            "sync_time": time.time(),
            "chunk_id": "idle",
            "text": "",
            "status": "idle",
            "loop": True,
            "avatar_id": target_avatar_id,
            "start_index": int(result.get("start_index", 0) or 0),
            "frame_count": int(result.get("frame_count", 0) or len(result.get("ordered_frame_paths", result.get("frame_paths", [])))),
        }

    def build_idle_payload_from_state(self, current_state=None, advance_to_next_frame=True):
        """Build a local idle loop from the current displayed avatar frames."""
        if self._shutdown_requested() or not self.avatar_path:
            return None

        current_state = dict(current_state or {})
        full_imgs_dir = os.path.join(self.avatar_path, "full_imgs")
        full_frame_paths = list_png_frames(full_imgs_dir)
        if not full_frame_paths:
            return None

        fps = int(current_state.get("fps", RUNTIME_CONFIG.get("musetalk_fps", self.fps)) or self.fps)
        sync_time = float(current_state.get("sync_time", 0.0) or 0.0)
        start_index = int(current_state.get("start_index", 0) or 0)
        rendered_frame_count = int(current_state.get("frame_count", 0) or len(current_state.get("frame_paths", []) or []))
        if rendered_frame_count <= 0:
            rendered_frame_count = len(full_frame_paths)

        elapsed = max(0.0, time.time() - sync_time) if sync_time else 0.0
        displayed_frame_index = min(int(elapsed * max(fps, 1)), max(rendered_frame_count - 1, 0))
        next_index = start_index + displayed_frame_index + (1 if advance_to_next_frame else 0)

        ordered_frame_paths = [
            full_frame_paths[(next_index + index) % len(full_frame_paths)]
            for index in range(len(full_frame_paths))
        ]
        source_indices = [
            (next_index + index) % len(full_frame_paths)
            for index in range(len(full_frame_paths))
        ]

        return {
            "frame_paths": ordered_frame_paths,
            "source_indices": source_indices,
            "frame_dir": "",
            "fps": fps,
            "sync_time": time.time(),
            "duration_seconds": 0.0,
            "chunk_id": "idle",
            "text": "",
            "status": "idle",
            "loop": True,
            "start_index": next_index % len(full_frame_paths),
            "frame_count": len(ordered_frame_paths),
            "avatar_id": current_state.get("avatar_id"),
        }

    def build_transition_payload(self, from_avatar_id, to_avatar_id):
        """Build a local avatar transition frame payload without invoking the worker."""
        if self._shutdown_requested():
            return None

        rule = self.get_transition_rule(from_avatar_id, to_avatar_id)
        if not rule:
            return None

        from_avatar_path = self.prepared_avatars.get(from_avatar_id)
        if not from_avatar_path:
            return None

        full_imgs_dir = os.path.join(from_avatar_path, "full_imgs")
        full_frame_paths = list_png_frames(full_imgs_dir)
        if not full_frame_paths:
            return None

        start_frame = max(0, min(int(rule.get("start_frame", len(full_frame_paths) - 1)), len(full_frame_paths) - 1))
        end_frame = max(0, min(int(rule.get("end_frame", 0)), len(full_frame_paths) - 1))
        if start_frame >= end_frame:
            indices = range(start_frame, end_frame - 1, -1)
        else:
            indices = range(start_frame, end_frame + 1)
        transition_frames = [full_frame_paths[index] for index in indices]
        source_indices = [int(index) for index in indices]
        if not transition_frames:
            return None

        fps = int(RUNTIME_CONFIG.get("musetalk_fps", self.fps) or self.fps)
        duration_seconds = len(transition_frames) / max(fps, 1)
        transition_id = f"transition:{from_avatar_id}->{to_avatar_id}:{time.time()}"
        return {
            "duration_seconds": duration_seconds,
            "payload": {
                "frame_paths": transition_frames,
                "source_indices": source_indices,
                "frame_dir": "",
                "fps": fps,
                "sync_time": time.time(),
                "duration_seconds": duration_seconds,
                "chunk_id": transition_id,
                "text": "",
                "status": "transition",
                "loop": False,
                "start_index": start_frame,
                "frame_count": len(transition_frames),
                "avatar_id": from_avatar_id,
            },
        }
