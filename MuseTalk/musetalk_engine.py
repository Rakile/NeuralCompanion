import copy
import glob
import json
import os
import pickle
import queue
import gc
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np
import torch
from tqdm import tqdm
from transformers import WhisperModel

from musetalk.utils.audio_processor import AudioProcessor
from musetalk.utils.blending import get_crop_box, get_image_blending, get_image_prepare_material
from musetalk.utils.face_parsing import FaceParsing
from musetalk.utils.preprocessing import coord_placeholder, get_landmark_and_bbox, read_imgs
from musetalk.utils.utils import datagen, load_all_model


def _env_flag(name):
    return str(os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


RENDER_STAGE_DIAGNOSTIC_LOGGING = _env_flag("NC_MUSETALK_RENDER_DIAGNOSTICS")


def fast_check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def video2imgs(vid_path, save_path, ext=".png", cut_frame=10000000):
    cap = cv2.VideoCapture(vid_path)
    count = 0
    while True:
        if count > cut_frame:
            break
        ret, frame = cap.read()
        if ret:
            cv2.imwrite(f"{save_path}/{count:08d}{ext}", frame)
            count += 1
        else:
            break


def osmakedirs(path_list):
    for path in path_list:
        os.makedirs(path, exist_ok=True)


def gpu_vram_snapshot():
    try:
        if torch.cuda.is_available():
            free_bytes, total_bytes = torch.cuda.mem_get_info()
            return {
                "used_gib": round(float(total_bytes - free_bytes) / (1024 ** 3), 3),
                "free_gib": round(float(free_bytes) / (1024 ** 3), 3),
                "total_gib": round(float(total_bytes) / (1024 ** 3), 3),
                "allocated_gib": round(float(torch.cuda.memory_allocated()) / (1024 ** 3), 3),
                "reserved_gib": round(float(torch.cuda.memory_reserved()) / (1024 ** 3), 3),
            }
    except Exception:
        pass
    return None


def emit_render_stage(label, extra=None):
    if not RENDER_STAGE_DIAGNOSTIC_LOGGING:
        return
    payload = {
        "worker_info": "render_stage",
        "label": label,
        "pid": os.getpid(),
        "time": round(time.time(), 3),
        "gpu": gpu_vram_snapshot(),
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload), flush=True)


@dataclass
class PreparedAvatar:
    avatar_id: str
    avatar_path: str
    full_imgs_path: str
    coords_path: str
    latents_out_path: str
    mask_out_path: str
    mask_coords_path: str
    avatar_info_path: str
    video_out_path: str
    bbox_shift: int
    version: str


class PreparedAvatarRuntime:
    def __init__(self, engine, prepared_avatar, batch_size, create_frame_cache=True):
        self.engine = engine
        self.prepared = prepared_avatar
        self.batch_size = batch_size
        self.create_frame_cache = bool(create_frame_cache)
        self.timeline_idx = 0
        self.frame_list_cycle = []
        self.coord_list_cycle = []
        self.input_latent_list_cycle = []
        self.mask_coords_list_cycle = []
        self.mask_list_cycle = []
        self.load_timing = {}
        self._timeline_lock = threading.Lock()
        self._load_or_prepare()

    def _load_or_prepare(self):
        total_start = time.perf_counter()
        timing = {
            "avatar_id": self.prepared.avatar_id,
            "avatar_path": self.prepared.avatar_path,
        }

        def mark(label, start):
            timing[f"{label}_seconds"] = round(time.perf_counter() - start, 3)

        if not os.path.exists(self.prepared.avatar_path):
            raise FileNotFoundError(
                f"Prepared avatar not found at {self.prepared.avatar_path}. Run preparation first."
            )

        step_start = time.perf_counter()
        with open(self.prepared.avatar_info_path, "r", encoding="utf-8") as f:
            avatar_info = json.load(f)
        mark("avatar_info", step_start)

        if int(avatar_info.get("bbox_shift", 0)) != int(self.prepared.bbox_shift):
            raise RuntimeError("Prepared avatar bbox_shift does not match the requested configuration.")

        step_start = time.perf_counter()
        self.input_latent_list_cycle = torch.load(self.prepared.latents_out_path)
        mark("latents_torch_load", step_start)
        try:
            timing["latents_mb"] = round(float(os.path.getsize(self.prepared.latents_out_path)) / (1024 ** 2), 1)
        except Exception:
            timing["latents_mb"] = None
        try:
            timing["latent_count"] = int(len(self.input_latent_list_cycle))
        except Exception:
            timing["latent_count"] = None

        step_start = time.perf_counter()
        with open(self.prepared.coords_path, "rb") as f:
            self.coord_list_cycle = pickle.load(f)
        mark("coords_pickle_load", step_start)

        step_start = time.perf_counter()
        input_img_list = glob.glob(os.path.join(self.prepared.full_imgs_path, "*.[jpJP][pnPN]*[gG]"))
        input_img_list = sorted(
            input_img_list,
            key=lambda x: int(os.path.splitext(os.path.basename(x))[0]),
        )
        timing["frame_count"] = int(len(input_img_list))
        mark("frame_glob_sort", step_start)

        self.frame_list_cycle = self._load_cached_frame_list(input_img_list, timing)

        step_start = time.perf_counter()
        with open(self.prepared.mask_coords_path, "rb") as f:
            self.mask_coords_list_cycle = pickle.load(f)
        mark("mask_coords_pickle_load", step_start)

        step_start = time.perf_counter()
        input_mask_list = glob.glob(os.path.join(self.prepared.mask_out_path, "*.[jpJP][pnPN]*[Gg]"))
        input_mask_list = sorted(
            input_mask_list,
            key=lambda x: int(os.path.splitext(os.path.basename(x))[0]),
        )
        timing["mask_count"] = int(len(input_mask_list))
        mark("mask_glob_sort", step_start)

        step_start = time.perf_counter()
        self.mask_list_cycle = read_imgs(input_mask_list)
        mark("mask_read_imgs", step_start)
        timing["total_seconds"] = round(time.perf_counter() - total_start, 3)
        self.load_timing = timing

    def _frame_cache_paths(self):
        return (
            os.path.join(self.prepared.avatar_path, "full_imgs_cache.npy"),
            os.path.join(self.prepared.avatar_path, "full_imgs_cache.json"),
        )

    def _frame_source_signature(self, input_img_list):
        max_mtime_ns = 0
        total_bytes = 0
        for path in input_img_list:
            try:
                stat = os.stat(path)
                max_mtime_ns = max(max_mtime_ns, int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))))
                total_bytes += int(stat.st_size)
            except OSError:
                return None
        return {
            "version": 1,
            "frame_count": int(len(input_img_list)),
            "max_mtime_ns": int(max_mtime_ns),
            "total_bytes": int(total_bytes),
        }

    def _load_cached_frame_list(self, input_img_list, timing):
        cache_path, manifest_path = self._frame_cache_paths()
        signature = self._frame_source_signature(input_img_list)
        timing["frame_cache_hit"] = False
        timing["frame_cache_path"] = cache_path

        if not self.create_frame_cache:
            read_start = time.perf_counter()
            frames = read_imgs(input_img_list)
            timing["frame_read_imgs_seconds"] = round(time.perf_counter() - read_start, 3)
            timing["frame_cache_skipped"] = "disabled"
            return frames

        if signature and os.path.isfile(cache_path) and os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                if manifest == signature:
                    cache_start = time.perf_counter()
                    cached = np.load(cache_path, mmap_mode="r", allow_pickle=False)
                    if cached.ndim == 4 and int(cached.shape[0]) == int(len(input_img_list)):
                        self._frame_cache_array = cached
                        timing["frame_cache_hit"] = True
                        timing["frame_cache_load_seconds"] = round(time.perf_counter() - cache_start, 3)
                        timing["frame_read_imgs_seconds"] = timing["frame_cache_load_seconds"]
                        timing["frame_cache_shape"] = [int(v) for v in cached.shape]
                        timing["frame_cache_mmap"] = True
                        try:
                            timing["frame_cache_mb"] = round(float(os.path.getsize(cache_path)) / (1024 ** 2), 1)
                        except Exception:
                            timing["frame_cache_mb"] = None
                        return [cached[i] for i in range(cached.shape[0])]
            except Exception as exc:
                timing["frame_cache_error"] = str(exc)

        read_start = time.perf_counter()
        frames = read_imgs(input_img_list)
        timing["frame_read_imgs_seconds"] = round(time.perf_counter() - read_start, 3)
        self._write_frame_cache(cache_path, manifest_path, signature, frames, timing)
        return frames

    def _write_frame_cache(self, cache_path, manifest_path, signature, frames, timing):
        if not signature or not frames:
            return
        try:
            first_shape = tuple(getattr(frames[0], "shape", ()) or ())
            if not first_shape or any(tuple(getattr(frame, "shape", ()) or ()) != first_shape for frame in frames):
                timing["frame_cache_skipped"] = "frame_shapes_differ"
                return

            save_start = time.perf_counter()
            stacked = np.stack(frames, axis=0)
            tmp_cache_path = f"{cache_path}.tmp"
            tmp_manifest_path = f"{manifest_path}.tmp"
            with open(tmp_cache_path, "wb") as f:
                np.save(f, stacked, allow_pickle=False)
            with open(tmp_manifest_path, "w", encoding="utf-8") as f:
                json.dump(signature, f)
            os.replace(tmp_cache_path, cache_path)
            os.replace(tmp_manifest_path, manifest_path)
            timing["frame_cache_saved"] = True
            timing["frame_cache_save_seconds"] = round(time.perf_counter() - save_start, 3)
            timing["frame_cache_shape"] = [int(v) for v in stacked.shape]
            try:
                timing["frame_cache_mb"] = round(float(os.path.getsize(cache_path)) / (1024 ** 2), 1)
            except Exception:
                timing["frame_cache_mb"] = None
        except Exception as exc:
            timing["frame_cache_save_error"] = str(exc)

    def process_frames(
        self,
        res_frame_queue,
        frame_dir,
        start_timeline_idx=None,
        timeline_indices=None,
        chunk_id=None,
    ):
        local_idx = 0
        first_frame_logged = False
        while True:
            try:
                res_frame = res_frame_queue.get(block=True, timeout=1)
            except queue.Empty:
                continue

            if res_frame is None:
                break

            if timeline_indices is not None:
                timeline_idx = timeline_indices[min(local_idx, len(timeline_indices) - 1)]
            else:
                timeline_idx = start_timeline_idx + local_idx

            bbox = self.coord_list_cycle[timeline_idx % len(self.coord_list_cycle)]
            ori_frame = copy.deepcopy(self.frame_list_cycle[timeline_idx % len(self.frame_list_cycle)])
            x1, y1, x2, y2 = bbox

            try:
                res_frame = cv2.resize(res_frame.astype(np.uint8), (x2 - x1, y2 - y1))
            except Exception:
                local_idx += 1
                continue

            mask = self.mask_list_cycle[timeline_idx % len(self.mask_list_cycle)]
            mask_crop_box = self.mask_coords_list_cycle[timeline_idx % len(self.mask_coords_list_cycle)]
            combine_frame = get_image_blending(ori_frame, res_frame, bbox, mask, mask_crop_box)
            cv2.imwrite(os.path.join(frame_dir, f"{local_idx:08d}.png"), combine_frame)
            if not first_frame_logged:
                emit_render_stage(
                    "first_frame_written",
                    {
                        "chunk_id": chunk_id,
                        "frame_dir": frame_dir,
                        "frame_index": int(local_idx),
                        "timeline_idx": int(timeline_idx),
                    },
                )
                first_frame_logged = True
            local_idx += 1

    @torch.no_grad()
    def estimate_frame_count(self, audio_path, fps):
        whisper_input_features, librosa_length = self.engine.audio_processor.get_audio_feature(
            audio_path,
            weight_dtype=self.engine.whisper_dtype,
        )
        whisper_chunks = self.engine.audio_processor.get_whisper_chunk(
            whisper_input_features,
            self.engine.whisper_device,
            self.engine.whisper_dtype,
            self.engine.whisper,
            librosa_length,
            fps=fps,
            audio_padding_length_left=self.engine.audio_padding_length_left,
            audio_padding_length_right=self.engine.audio_padding_length_right,
        )
        return len(whisper_chunks)

    @torch.no_grad()
    def render_audio(
        self,
        audio_path,
        chunk_id,
        fps,
        output_root,
        reset_timeline=False,
        timeline_indices=None,
        overlap_prefix_frames=0,
        start_timeline_idx=None,
        max_frames=None,
    ):
        frame_dir = os.path.join(output_root, chunk_id)
        if os.path.exists(frame_dir):
            shutil.rmtree(frame_dir)
        os.makedirs(frame_dir, exist_ok=True)

        start_time = time.time()
        emit_render_stage("render_audio_enter", {"chunk_id": chunk_id, "audio_path": audio_path})
        whisper_input_features, librosa_length = self.engine.audio_processor.get_audio_feature(
            audio_path,
            weight_dtype=self.engine.whisper_dtype,
        )
        emit_render_stage(
            "audio_feature_ready",
            {
                "chunk_id": chunk_id,
                "librosa_length": int(librosa_length),
                "feature_shape": list(getattr(whisper_input_features, "shape", [])),
            },
        )
        whisper_chunks = self.engine.audio_processor.get_whisper_chunk(
            whisper_input_features,
            self.engine.whisper_device,
            self.engine.whisper_dtype,
            self.engine.whisper,
            librosa_length,
            fps=fps,
            audio_padding_length_left=self.engine.audio_padding_length_left,
            audio_padding_length_right=self.engine.audio_padding_length_right,
        )
        emit_render_stage(
            "whisper_chunks_ready",
            {
                "chunk_id": chunk_id,
                "whisper_chunk_count": int(len(whisper_chunks)),
            },
        )
        if max_frames is not None:
            max_frames = max(1, int(max_frames))
            whisper_chunks = whisper_chunks[:max_frames]

        video_num = len(whisper_chunks)
        explicit_timeline = [int(idx) for idx in (timeline_indices or [])]
        if explicit_timeline:
            if len(explicit_timeline) < video_num:
                explicit_timeline.extend([explicit_timeline[-1]] * (video_num - len(explicit_timeline)))
            elif len(explicit_timeline) > video_num:
                explicit_timeline = explicit_timeline[:video_num]
            start_timeline_idx = explicit_timeline[0]
        else:
            with self._timeline_lock:
                if reset_timeline:
                    self.timeline_idx = 0
                visible_start_idx = self.timeline_idx if start_timeline_idx is None else int(start_timeline_idx)
                prefix_frames = max(0, min(int(overlap_prefix_frames or 0), max(video_num - 1, 0)))
                start_timeline_idx = visible_start_idx - prefix_frames
                self.timeline_idx = visible_start_idx + max(video_num - prefix_frames, 0)

        res_frame_queue = queue.Queue()
        process_thread = threading.Thread(
            target=self.process_frames,
            args=(
                res_frame_queue,
                frame_dir,
                start_timeline_idx,
                explicit_timeline or None,
                chunk_id,
            ),
            daemon=True,
        )
        process_thread.start()
        emit_render_stage(
            "process_thread_started",
            {
                "chunk_id": chunk_id,
                "video_num": int(video_num),
                "start_timeline_idx": int(start_timeline_idx),
                "explicit_timeline": bool(explicit_timeline),
            },
        )

        if explicit_timeline:
            latent_sequence = [
                self.input_latent_list_cycle[idx % len(self.input_latent_list_cycle)]
                for idx in explicit_timeline
            ]
        else:
            latent_sequence = [
                self.input_latent_list_cycle[(start_timeline_idx + i) % len(self.input_latent_list_cycle)]
                for i in range(video_num)
            ]
        emit_render_stage(
            "latent_sequence_ready",
            {
                "chunk_id": chunk_id,
                "latent_count": int(len(latent_sequence)),
                "batch_size": int(self.batch_size),
            },
        )
        gen = datagen(whisper_chunks, latent_sequence, self.batch_size)
        first_batch_logged = False
        for whisper_batch, latent_batch in tqdm(
            gen,
            total=int(np.ceil(float(video_num) / self.batch_size)),
            disable=True,
        ):
            if not first_batch_logged:
                emit_render_stage(
                    "first_batch_received",
                    {
                        "chunk_id": chunk_id,
                        "whisper_batch_shape": list(getattr(whisper_batch, "shape", [])),
                        "latent_batch_shape": list(getattr(latent_batch, "shape", [])),
                    },
                )
            audio_feature_batch = self.engine.pe(
                whisper_batch.to(device=self.engine.device, dtype=self.engine.weight_dtype)
            )
            if not first_batch_logged:
                emit_render_stage(
                    "first_batch_pe_done",
                    {
                        "chunk_id": chunk_id,
                        "audio_feature_shape": list(getattr(audio_feature_batch, "shape", [])),
                    },
                )
            latent_batch = latent_batch.to(device=self.engine.device, dtype=self.engine.unet.model.dtype)

            pred_latents = self.engine.unet.model(
                latent_batch,
                self.engine.timesteps,
                encoder_hidden_states=audio_feature_batch,
            ).sample
            if not first_batch_logged:
                emit_render_stage(
                    "first_batch_unet_done",
                    {
                        "chunk_id": chunk_id,
                        "pred_latents_shape": list(getattr(pred_latents, "shape", [])),
                    },
                )
            pred_latents = pred_latents.to(device=self.engine.device, dtype=self.engine.vae.vae.dtype)
            recon = self.engine.vae.decode_latents(pred_latents)
            if not first_batch_logged:
                emit_render_stage(
                    "first_batch_vae_done",
                    {
                        "chunk_id": chunk_id,
                        "recon_shape": list(getattr(recon, "shape", [])),
                    },
                )
                first_batch_logged = True
            for res_frame in recon:
                res_frame_queue.put(res_frame)

        emit_render_stage("batch_loop_done", {"chunk_id": chunk_id})
        res_frame_queue.put(None)
        process_thread.join()
        emit_render_stage("process_thread_joined", {"chunk_id": chunk_id})

        frame_paths = sorted(glob.glob(os.path.join(frame_dir, "*.png")))
        emit_render_stage(
            "render_audio_return",
            {
                "chunk_id": chunk_id,
                "frame_count": int(len(frame_paths)),
                "render_seconds": round(time.time() - start_time, 3),
            },
        )
        return {
            "frame_dir": frame_dir,
            "frame_count": len(frame_paths),
            "fps": fps,
            "render_seconds": time.time() - start_time,
            "start_index": start_timeline_idx + (max(0, min(int(overlap_prefix_frames or 0), max(video_num - 1, 0))) if not explicit_timeline else 0),
        }

    def get_idle_payload(self, fps):
        frame_count = len(self.frame_list_cycle)
        if frame_count == 0:
            return None

        with self._timeline_lock:
            start_idx = self.timeline_idx % frame_count

        ordered_frame_paths = [
            os.path.join(self.prepared.full_imgs_path, f"{((start_idx + i) % frame_count):08d}.png")
            for i in range(frame_count)
        ]
        ordered_frame_paths = [path for path in ordered_frame_paths if os.path.exists(path)]
        if not ordered_frame_paths:
            return None

        return {
            "frame_paths": [],
            "frame_dir": "",
            "ordered_frame_paths": ordered_frame_paths,
            "frame_count": len(ordered_frame_paths),
            "fps": fps,
            "loop": True,
            "start_index": start_idx,
        }


class MuseTalkEngine:
    def __init__(
        self,
        version="v15",
        ffmpeg_path="./ffmpeg-master-latest-win64-gpl-shared/bin",
        gpu_id=0,
        vae_type="sd-vae",
        unet_config="./models/musetalkV15/musetalk.json",
        unet_model_path="./models/musetalkV15/unet.pth",
        whisper_dir="./models/whisper",
        left_cheek_width=90,
        right_cheek_width=90,
        extra_margin=10,
        parsing_mode="jaw",
        batch_size=20,
        audio_padding_length_left=2,
        audio_padding_length_right=2,
        result_dir="./results",
        whisper_device="cuda",
        enable_vae_slicing=False,
        preload_face_parsing=True,
    ):
        self.version = version
        self.ffmpeg_path = ffmpeg_path
        self.gpu_id = gpu_id
        self.vae_type = vae_type
        self.unet_config = unet_config
        self.unet_model_path = unet_model_path
        self.whisper_dir = whisper_dir
        self.left_cheek_width = left_cheek_width
        self.right_cheek_width = right_cheek_width
        self.extra_margin = extra_margin
        self.parsing_mode = parsing_mode
        self.batch_size = batch_size
        self.audio_padding_length_left = audio_padding_length_left
        self.audio_padding_length_right = audio_padding_length_right
        self.result_dir = result_dir
        self.whisper_device_preference = whisper_device
        self.enable_vae_slicing = bool(enable_vae_slicing)
        self.preload_face_parsing = bool(preload_face_parsing)
        self.prepared_avatars = {}
        self.last_prepare_timing = {}

        if not fast_check_ffmpeg():
            path_separator = ";" if os.name == "nt" else ":"
            os.environ["PATH"] = f"{self.ffmpeg_path}{path_separator}{os.environ['PATH']}"

        self.device = torch.device(f"cuda:{self.gpu_id}" if torch.cuda.is_available() else "cpu")
        self.vae, self.unet, self.pe = load_all_model(
            unet_model_path=self.unet_model_path,
            vae_type=self.vae_type,
            unet_config=self.unet_config,
            device=self.device,
        )
        self.timesteps = torch.tensor([0], device=self.device)
        self.pe = self.pe.half().to(self.device)
        self.vae.vae = self.vae.vae.half().to(self.device)
        self.unet.model = self.unet.model.half().to(self.device)
        if self.enable_vae_slicing and hasattr(self.vae.vae, "enable_slicing"):
            self.vae.vae.enable_slicing()

        self.audio_processor = AudioProcessor(feature_extractor_path=self.whisper_dir)
        self.weight_dtype = self.unet.model.dtype
        preferred_whisper = str(self.whisper_device_preference or "cuda").lower()
        if preferred_whisper == "cuda" and torch.cuda.is_available():
            self.whisper_device = self.device
            self.whisper_dtype = self.weight_dtype
        else:
            self.whisper_device = torch.device("cpu")
            self.whisper_dtype = torch.float32
        self.whisper = WhisperModel.from_pretrained(self.whisper_dir)
        self.whisper = self.whisper.to(device=self.whisper_device, dtype=self.whisper_dtype).eval()
        self.whisper.requires_grad_(False)

        self.fp = None
        if self.preload_face_parsing:
            self.fp = self._build_face_parser()

    def _build_face_parser(self, left_cheek_width=None, right_cheek_width=None):
        cheek_left = self.left_cheek_width if left_cheek_width is None else int(left_cheek_width)
        cheek_right = self.right_cheek_width if right_cheek_width is None else int(right_cheek_width)
        if self.version == "v15":
            return FaceParsing(
                left_cheek_width=cheek_left,
                right_cheek_width=cheek_right,
            )
        return FaceParsing()

    def _get_face_parser(self):
        if self.fp is None:
            self.fp = self._build_face_parser()
        return self.fp

    def _resolve_mask_settings(
        self,
        extra_margin=None,
        parsing_mode=None,
        left_cheek_width=None,
        right_cheek_width=None,
        modified_mask_path=None,
    ):
        return {
            "extra_margin": int(self.extra_margin if extra_margin is None else extra_margin),
            "parsing_mode": str(self.parsing_mode if parsing_mode is None else parsing_mode or "jaw"),
            "left_cheek_width": int(self.left_cheek_width if left_cheek_width is None else left_cheek_width),
            "right_cheek_width": int(self.right_cheek_width if right_cheek_width is None else right_cheek_width),
        }

    def _normalize_mask_ranges(self, mask_ranges, default_bbox_shift=0):
        normalized = []
        for raw_entry in list(mask_ranges or []):
            if not isinstance(raw_entry, dict):
                continue
            start_frame = max(0, int(raw_entry.get("start_frame", 0) or 0))
            end_frame = max(start_frame, int(raw_entry.get("end_frame", start_frame) or start_frame))
            parsing_mode = str(raw_entry.get("parsing_mode", self.parsing_mode) or self.parsing_mode or "jaw").strip().lower() or "jaw"
            if parsing_mode not in {"jaw", "raw"}:
                parsing_mode = "jaw"
            normalized.append({
                "start_frame": start_frame,
                "end_frame": end_frame,
                "bbox_shift": int(raw_entry.get("bbox_shift", default_bbox_shift) or default_bbox_shift),
                "passthrough": bool(raw_entry.get("passthrough", False)),
                "extra_margin": int(raw_entry.get("extra_margin", self.extra_margin) or self.extra_margin),
                "parsing_mode": parsing_mode,
                "left_cheek_width": int(raw_entry.get("left_cheek_width", self.left_cheek_width) or self.left_cheek_width),
                "right_cheek_width": int(raw_entry.get("right_cheek_width", self.right_cheek_width) or self.right_cheek_width),
            })
        normalized.sort(key=lambda entry: (entry["start_frame"], entry["end_frame"]))
        return normalized

    def _resolve_mask_profile_for_frame(self, frame_index, default_bbox_shift, default_mask_settings, mask_ranges):
        profile = {
            "bbox_shift": int(default_bbox_shift),
            "passthrough": False,
            **dict(default_mask_settings or {}),
        }
        for entry in list(mask_ranges or []):
            if int(entry.get("start_frame", 0) or 0) <= int(frame_index) <= int(entry.get("end_frame", 0) or 0):
                profile.update({
                    "bbox_shift": int(entry.get("bbox_shift", profile["bbox_shift"]) or profile["bbox_shift"]),
                    "passthrough": bool(entry.get("passthrough", profile.get("passthrough", False))),
                    "extra_margin": int(entry.get("extra_margin", profile["extra_margin"]) or profile["extra_margin"]),
                    "parsing_mode": str(entry.get("parsing_mode", profile["parsing_mode"]) or profile["parsing_mode"]),
                    "left_cheek_width": int(entry.get("left_cheek_width", profile["left_cheek_width"]) or profile["left_cheek_width"]),
                    "right_cheek_width": int(entry.get("right_cheek_width", profile["right_cheek_width"]) or profile["right_cheek_width"]),
                })
        return profile

    def _normalize_mask_overrides(self, mask_overrides):
        normalized = []
        for raw_entry in list(mask_overrides or []):
            if not isinstance(raw_entry, dict):
                continue
            frame_index = max(0, int(raw_entry.get("frame_index", 0) or 0))
            override_mask_path = str(raw_entry.get("override_mask_path", "") or "").strip()
            if not override_mask_path:
                continue
            bbox = [int(v) for v in list(raw_entry.get("bbox", []) or [])[:4]]
            crop_box = [int(v) for v in list(raw_entry.get("crop_box", []) or [])[:4]]
            normalized.append({
                "frame_index": frame_index,
                "override_mask_path": override_mask_path,
                "range_label": str(raw_entry.get("range_label", "") or ""),
                "bbox_shift": int(raw_entry.get("bbox_shift", 0) or 0),
                "parsing_mode": str(raw_entry.get("parsing_mode", "jaw") or "jaw"),
                "extra_margin": int(raw_entry.get("extra_margin", 10) or 10),
                "left_cheek_width": int(raw_entry.get("left_cheek_width", 90) or 90),
                "right_cheek_width": int(raw_entry.get("right_cheek_width", 90) or 90),
                "bbox": bbox if len(bbox) == 4 else [],
                "crop_box": crop_box if len(crop_box) == 4 else [],
                "mask_width": int(raw_entry.get("mask_width", 0) or 0),
                "mask_height": int(raw_entry.get("mask_height", 0) or 0),
            })
        normalized.sort(key=lambda entry: entry["frame_index"])
        return normalized

    def _apply_mask_overrides(self, prepared, mask_overrides, frame_count, mask_coords_list_cycle):
        normalized = self._normalize_mask_overrides(mask_overrides)
        applied = []
        skipped = []
        if not normalized or frame_count <= 0:
            return {"applied": applied, "skipped": skipped, "normalized": normalized}
        cycle_len = frame_count * 2
        for entry in normalized:
            frame_index = int(entry["frame_index"])
            override_mask_path = str(entry["override_mask_path"] or "")
            if frame_index >= frame_count:
                skipped.append({**entry, "reason": "frame_out_of_range"})
                continue
            override_mask = cv2.imread(override_mask_path, cv2.IMREAD_GRAYSCALE) if override_mask_path and os.path.isfile(override_mask_path) else None
            if override_mask is None:
                skipped.append({**entry, "reason": "override_mask_missing"})
                continue
            target_indices = sorted({frame_index, max(0, cycle_len - 1 - frame_index)})
            target_mask_paths = []
            entry_applied = True
            for target_idx in target_indices:
                if target_idx >= len(mask_coords_list_cycle):
                    entry_applied = False
                    skipped.append({**entry, "reason": "target_index_missing", "target_index": target_idx})
                    continue
                expected_crop_box = [int(v) for v in list(entry.get("crop_box", []) or [])[:4]]
                current_crop_box = [int(v) for v in list(mask_coords_list_cycle[target_idx] or [])[:4]]
                if len(expected_crop_box) == 4 and current_crop_box != expected_crop_box:
                    entry_applied = False
                    skipped.append({**entry, "reason": "crop_box_mismatch", "target_index": target_idx, "current_crop_box": current_crop_box})
                    continue
                target_mask_path = os.path.join(prepared.mask_out_path, f"{target_idx:08d}.png")
                current_mask = cv2.imread(target_mask_path, cv2.IMREAD_GRAYSCALE) if os.path.isfile(target_mask_path) else None
                if current_mask is None:
                    entry_applied = False
                    skipped.append({**entry, "reason": "generated_mask_missing", "target_index": target_idx})
                    continue
                if override_mask.shape[:2] != current_mask.shape[:2]:
                    entry_applied = False
                    skipped.append({**entry, "reason": "mask_shape_mismatch", "target_index": target_idx, "current_shape": [int(current_mask.shape[1]), int(current_mask.shape[0])]})
                    continue
                cv2.imwrite(target_mask_path, override_mask)
                target_mask_paths.append(target_mask_path)
            if entry_applied and target_mask_paths:
                applied.append({**entry, "target_mask_paths": target_mask_paths})
        return {"applied": applied, "skipped": skipped, "normalized": normalized}

    def _avatar_base_path(self, avatar_id):
        if self.version == "v15":
            return os.path.join(self.result_dir, self.version, "avatars", avatar_id)
        return os.path.join(self.result_dir, "avatars", avatar_id)

    def _resolve_avatar_root(self, avatar_id, avatar_path_override=None):
        override = str(avatar_path_override or "").strip()
        if override:
            return os.path.abspath(override)
        return os.path.abspath(self._avatar_base_path(avatar_id))

    def _prepared_avatar_key(self, avatar_id, avatar_path_override=None):
        override = str(avatar_path_override or "").strip()
        if override:
            return f"path::{os.path.abspath(override)}"
        return f"id::{str(avatar_id or '').strip()}"

    def _build_prepared_avatar(self, avatar_id, avatar_path_override=None, bbox_shift=0):
        avatar_path = self._resolve_avatar_root(avatar_id, avatar_path_override=avatar_path_override)
        return PreparedAvatar(
            avatar_id=avatar_id,
            avatar_path=avatar_path,
            full_imgs_path=os.path.join(avatar_path, "full_imgs"),
            coords_path=os.path.join(avatar_path, "coords.pkl"),
            latents_out_path=os.path.join(avatar_path, "latents.pt"),
            mask_out_path=os.path.join(avatar_path, "mask"),
            mask_coords_path=os.path.join(avatar_path, "mask_coords.pkl"),
            avatar_info_path=os.path.join(avatar_path, "avator_info.json"),
            video_out_path=os.path.join(avatar_path, "vid_output"),
            bbox_shift=int(bbox_shift or 0),
            version=self.version,
        )

    def prepare_avatar(
        self,
        avatar_id,
        video_path,
        bbox_shift=0,
        recreate=False,
        extra_margin=None,
        parsing_mode=None,
        left_cheek_width=None,
        right_cheek_width=None,
        mask_ranges=None,
        mask_overrides=None,
        avatar_path_override=None,
        create_frame_cache=True,
    ):
        total_start = time.perf_counter()
        prepared = self._build_prepared_avatar(avatar_id, avatar_path_override=avatar_path_override, bbox_shift=bbox_shift)
        avatar_path = prepared.avatar_path
        cache_key = self._prepared_avatar_key(avatar_id, avatar_path_override=avatar_path_override)
        material_start_exists = os.path.exists(avatar_path)
        material_seconds = 0.0

        if recreate and os.path.exists(avatar_path):
            shutil.rmtree(avatar_path)
            material_start_exists = False

        if not os.path.exists(avatar_path):
            osmakedirs([avatar_path, prepared.full_imgs_path, prepared.video_out_path, prepared.mask_out_path])
            material_start = time.perf_counter()
            self._prepare_material(
                prepared,
                video_path,
                extra_margin=extra_margin,
                parsing_mode=parsing_mode,
                left_cheek_width=left_cheek_width,
                right_cheek_width=right_cheek_width,
                mask_ranges=mask_ranges,
                mask_overrides=mask_overrides,
            )
            material_seconds = time.perf_counter() - material_start

        runtime_start = time.perf_counter()
        runtime = PreparedAvatarRuntime(self, prepared, self.batch_size, create_frame_cache=create_frame_cache)
        runtime_seconds = time.perf_counter() - runtime_start
        self.prepared_avatars[cache_key] = runtime
        self.last_prepare_timing = {
            "avatar_id": avatar_id,
            "cache_key": cache_key,
            "prepared_folder_existed": bool(material_start_exists),
            "material_seconds": round(material_seconds, 3),
            "runtime_load_seconds": round(runtime_seconds, 3),
            "total_seconds": round(time.perf_counter() - total_start, 3),
            "runtime_load": dict(getattr(runtime, "load_timing", {}) or {}),
        }
        return prepared

    @torch.no_grad()
    def _prepare_material(
        self,
        prepared,
        video_path,
        extra_margin=None,
        parsing_mode=None,
        left_cheek_width=None,
        right_cheek_width=None,
        mask_ranges=None,
        mask_overrides=None,
    ):
        mask_settings = self._resolve_mask_settings(
            extra_margin=extra_margin,
            parsing_mode=parsing_mode,
            left_cheek_width=left_cheek_width,
            right_cheek_width=right_cheek_width,
        )
        normalized_mask_ranges = self._normalize_mask_ranges(mask_ranges, default_bbox_shift=prepared.bbox_shift)
        normalized_mask_overrides = self._normalize_mask_overrides(mask_overrides)
        avatar_info = {
            "avatar_id": prepared.avatar_id,
            "video_path": video_path,
            "bbox_shift": prepared.bbox_shift,
            "version": prepared.version,
            "extra_margin": mask_settings["extra_margin"],
            "parsing_mode": mask_settings["parsing_mode"],
            "left_cheek_width": mask_settings["left_cheek_width"],
            "right_cheek_width": mask_settings["right_cheek_width"],
            "mask_ranges": normalized_mask_ranges,
            "mask_overrides": normalized_mask_overrides,
        }
        with open(prepared.avatar_info_path, "w", encoding="utf-8") as f:
            json.dump(avatar_info, f)

        if os.path.isfile(video_path):
            video2imgs(video_path, prepared.full_imgs_path, ext=".png")
        else:
            files = [file for file in os.listdir(video_path) if file.lower().endswith(".png")]
            for filename in sorted(files):
                shutil.copyfile(
                    os.path.join(video_path, filename),
                    os.path.join(prepared.full_imgs_path, filename),
                )

        input_img_list = sorted(glob.glob(os.path.join(prepared.full_imgs_path, "*.[jpJP][pnPN]*[gG]")))
        bbox_shift_values = sorted({int(prepared.bbox_shift)} | {int(entry.get("bbox_shift", prepared.bbox_shift) or prepared.bbox_shift) for entry in normalized_mask_ranges})
        coords_by_shift = {}
        frame_list = None
        for shift_value in bbox_shift_values:
            coords_for_shift, frames_for_shift = get_landmark_and_bbox(input_img_list, shift_value)
            coords_by_shift[int(shift_value)] = coords_for_shift
            if frame_list is None:
                frame_list = frames_for_shift
        frame_list = frame_list or []
        coord_list = []
        profile_list = []
        parser_cache = {}

        input_latent_list = []
        coord_placeholder = (0.0, 0.0, 0.0, 0.0)
        for idx, frame in enumerate(frame_list):
            profile = self._resolve_mask_profile_for_frame(idx, prepared.bbox_shift, mask_settings, normalized_mask_ranges)
            bbox = coords_by_shift[int(profile["bbox_shift"])][idx]
            profile_list.append(dict(profile))
            coord_list.append(bbox)
            if bbox == coord_placeholder:
                continue

            x1, y1, x2, y2 = bbox
            if self.version == "v15":
                y2 = min(y2 + int(profile["extra_margin"]), frame.shape[0])
                coord_list[idx] = [x1, y1, x2, y2]
            crop_frame = frame[y1:y2, x1:x2]
            resized_crop_frame = cv2.resize(crop_frame, (256, 256), interpolation=cv2.INTER_LANCZOS4)
            latents = self.vae.get_latents_for_unet(resized_crop_frame)
            input_latent_list.append(latents)

        frame_list_cycle = frame_list + frame_list[::-1]
        coord_list_cycle = coord_list + coord_list[::-1]
        profile_list_cycle = profile_list + profile_list[::-1]
        input_latent_list_cycle = input_latent_list + input_latent_list[::-1]
        mask_coords_list_cycle = []

        for i, frame in enumerate(tqdm(frame_list_cycle, disable=True)):
            cv2.imwrite(os.path.join(prepared.full_imgs_path, f"{i:08d}.png"), frame)
            x1, y1, x2, y2 = coord_list_cycle[i]
            profile = profile_list_cycle[i]
            if bool(profile.get("passthrough", False)):
                crop_box, _ = get_crop_box([x1, y1, x2, y2], 1.5)
                crop_width = max(1, int(crop_box[2] - crop_box[0]))
                crop_height = max(1, int(crop_box[3] - crop_box[1]))
                mask = np.zeros((crop_height, crop_width), dtype=np.uint8)
            else:
                parser_key = (int(profile["left_cheek_width"]), int(profile["right_cheek_width"]))
                parser = parser_cache.get(parser_key)
                if parser is None:
                    parser = self._build_face_parser(
                        left_cheek_width=profile["left_cheek_width"],
                        right_cheek_width=profile["right_cheek_width"],
                    )
                    parser_cache[parser_key] = parser
                mode = str(profile["parsing_mode"] or "jaw") if self.version == "v15" else "raw"
                mask, crop_box = get_image_prepare_material(
                    frame,
                    [x1, y1, x2, y2],
                    fp=parser,
                    mode=mode,
                )
            cv2.imwrite(os.path.join(prepared.mask_out_path, f"{i:08d}.png"), mask)
            mask_coords_list_cycle.append(crop_box)

        override_result = self._apply_mask_overrides(
            prepared,
            normalized_mask_overrides,
            len(frame_list),
            mask_coords_list_cycle,
        )
        avatar_info["mask_override_apply_result"] = {
            "applied_count": len(override_result.get("applied", [])),
            "skipped_count": len(override_result.get("skipped", [])),
            "applied": override_result.get("applied", []),
            "skipped": override_result.get("skipped", []),
        }
        with open(prepared.avatar_info_path, "w", encoding="utf-8") as f:
            json.dump(avatar_info, f)
        with open(prepared.mask_coords_path, "wb") as f:
            pickle.dump(mask_coords_list_cycle, f)
        with open(prepared.coords_path, "wb") as f:
            pickle.dump(coord_list_cycle, f)
        torch.save(input_latent_list_cycle, prepared.latents_out_path)

        if not self.preload_face_parsing:
            self.fp = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def render_audio(
        self,
        avatar_id,
        audio_path,
        chunk_id,
        fps=24,
        output_root="./runtime/rendered_chunks",
        reset_timeline=False,
        timeline_indices=None,
        overlap_prefix_frames=0,
        start_timeline_idx=None,
        max_frames=None,
        avatar_path_override=None,
    ):
        cache_key = self._prepared_avatar_key(avatar_id, avatar_path_override=avatar_path_override)
        if cache_key not in self.prepared_avatars:
            prepared = self._build_prepared_avatar(avatar_id, avatar_path_override=avatar_path_override, bbox_shift=0)
            self.prepared_avatars[cache_key] = PreparedAvatarRuntime(self, prepared, self.batch_size)

        os.makedirs(output_root, exist_ok=True)
        return self.prepared_avatars[cache_key].render_audio(
            audio_path,
            chunk_id,
            fps,
            output_root,
            reset_timeline=reset_timeline,
            timeline_indices=timeline_indices,
            overlap_prefix_frames=overlap_prefix_frames,
            start_timeline_idx=start_timeline_idx,
            max_frames=max_frames,
        )

    def estimate_frame_count(self, avatar_id, audio_path, fps=24, avatar_path_override=None):
        cache_key = self._prepared_avatar_key(avatar_id, avatar_path_override=avatar_path_override)
        if cache_key not in self.prepared_avatars:
            prepared = self._build_prepared_avatar(avatar_id, avatar_path_override=avatar_path_override, bbox_shift=0)
            self.prepared_avatars[cache_key] = PreparedAvatarRuntime(self, prepared, self.batch_size)
        return self.prepared_avatars[cache_key].estimate_frame_count(audio_path, fps)

    def debug_first_frame(
        self,
        source_path,
        bbox_shift=0,
        output_root="./runtime/first_frame_debug",
        frame_index=0,
        extra_margin=None,
        parsing_mode=None,
        left_cheek_width=None,
        right_cheek_width=None,
        modified_mask_path=None,
    ):
        source_path = os.path.abspath(source_path)
        output_root = os.path.abspath(output_root)
        modified_mask = None
        modified_mask_path = os.path.abspath(modified_mask_path) if modified_mask_path else ""
        if modified_mask_path and os.path.isfile(modified_mask_path):
            modified_mask = cv2.imread(modified_mask_path, cv2.IMREAD_GRAYSCALE)
            if modified_mask is None:
                raise RuntimeError(f"Could not read modified debug mask: {modified_mask_path}")
        debug_dir = os.path.join(output_root, "latest")
        current_modified_mask_path = os.path.join(debug_dir, "debug_mask_modified.png")
        preserve_modified_mask = bool(modified_mask_path)
        preserved_modified_mask_bytes = None
        if preserve_modified_mask:
            try:
                modified_path_obj = Path(modified_mask_path)
                if modified_path_obj.is_file():
                    preserved_modified_mask_bytes = modified_path_obj.read_bytes()
            except Exception:
                preserved_modified_mask_bytes = None
        if preserve_modified_mask:
            os.makedirs(debug_dir, exist_ok=True)
            if preserved_modified_mask_bytes is not None:
                try:
                    Path(current_modified_mask_path).write_bytes(preserved_modified_mask_bytes)
                except Exception:
                    pass
        else:
            if os.path.isdir(debug_dir):
                shutil.rmtree(debug_dir, ignore_errors=True)
            os.makedirs(debug_dir, exist_ok=True)
        mask_settings = self._resolve_mask_settings(
            extra_margin=extra_margin,
            parsing_mode=parsing_mode,
            left_cheek_width=left_cheek_width,
            right_cheek_width=right_cheek_width,
        )

        input_frame_path = os.path.join(debug_dir, "debug_input.png")
        requested_frame_index = max(0, int(frame_index or 0))
        frame = None
        actual_frame_index = 0
        if os.path.isfile(source_path):
            ext = os.path.splitext(source_path)[1].lower()
            if ext in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
                frame = cv2.imread(source_path)
            else:
                cap = cv2.VideoCapture(source_path)
                if requested_frame_index > 0:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, requested_frame_index)
                ok, first_frame = cap.read()
                cap.release()
                if ok:
                    frame = first_frame
                    actual_frame_index = requested_frame_index
        elif os.path.isdir(source_path):
            candidates = sorted(
                [
                    os.path.join(source_path, name)
                    for name in os.listdir(source_path)
                    if os.path.isfile(os.path.join(source_path, name))
                    and os.path.splitext(name)[1].lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
                ]
            )
            if candidates:
                selected_index = min(requested_frame_index, len(candidates) - 1)
                frame = cv2.imread(candidates[selected_index])
                actual_frame_index = selected_index

        if frame is None:
            raise RuntimeError(f"Could not read a first frame from source: {source_path}")

        cv2.imwrite(input_frame_path, frame)
        coord_list, frame_list = get_landmark_and_bbox([input_frame_path], int(bbox_shift))
        if not coord_list or not frame_list:
            raise RuntimeError("No frame data was returned while preparing the debug frame.")

        bbox = coord_list[0]
        frame = frame_list[0]
        if bbox == coord_placeholder:
            raise RuntimeError("No face detected in the first frame. Adjust bbox_shift and try again.")

        x1, y1, x2, y2 = [int(value) for value in bbox]
        y2 = min(int(y2 + mask_settings["extra_margin"]), int(frame.shape[0]))
        if x2 <= x1 or y2 <= y1:
            raise RuntimeError("Detected face crop is invalid. Adjust bbox_shift and try again.")

        crop_frame = frame[y1:y2, x1:x2]
        if crop_frame.size == 0:
            raise RuntimeError("Detected face crop is empty. Adjust bbox_shift and try again.")

        crop_frame = cv2.resize(crop_frame, (256, 256), interpolation=cv2.INTER_LANCZOS4)
        random_audio = torch.randn(1, 50, 384, device=self.device, dtype=self.weight_dtype)
        audio_feature = self.pe(random_audio)
        latents = self.vae.get_latents_for_unet(crop_frame)
        latent_batch = latents.to(device=self.device, dtype=self.unet.model.dtype)
        pred_latents = self.unet.model(
            latent_batch,
            self.timesteps,
            encoder_hidden_states=audio_feature,
        ).sample
        pred_latents = pred_latents.to(device=self.device, dtype=self.vae.vae.dtype)
        recon = self.vae.decode_latents(pred_latents)
        res_frame = recon[0]
        res_frame = cv2.resize(
            res_frame.astype(np.uint8),
            (max(1, x2 - x1), max(1, y2 - y1)),
            interpolation=cv2.INTER_LANCZOS4,
        )

        mode = mask_settings["parsing_mode"] if self.version == "v15" else "raw"
        parser = self._build_face_parser(
            left_cheek_width=mask_settings["left_cheek_width"],
            right_cheek_width=mask_settings["right_cheek_width"],
        )
        mask, crop_box = get_image_prepare_material(
            frame,
            (x1, y1, x2, y2),
            fp=parser,
            mode=mode,
        )
        if modified_mask is not None:
            if tuple(modified_mask.shape[:2]) != tuple(mask.shape[:2]):
                modified_mask = cv2.resize(modified_mask, (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_NEAREST)
            mask = modified_mask.astype(np.uint8)
        combined_frame = get_image_blending(frame, res_frame, (x1, y1, x2, y2), mask, crop_box)

        mask_frame_path = os.path.join(debug_dir, "debug_mask.png")
        cv2.imwrite(mask_frame_path, mask)
        mask_overlay = frame.copy()
        full_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        x_s, y_s, x_e, y_e = [int(value) for value in crop_box]
        dest_x1 = max(0, x_s)
        dest_y1 = max(0, y_s)
        dest_x2 = min(frame.shape[1], x_e)
        dest_y2 = min(frame.shape[0], y_e)
        if dest_x2 > dest_x1 and dest_y2 > dest_y1:
            src_x1 = dest_x1 - x_s
            src_y1 = dest_y1 - y_s
            src_x2 = src_x1 + (dest_x2 - dest_x1)
            src_y2 = src_y1 + (dest_y2 - dest_y1)
            full_mask[dest_y1:dest_y2, dest_x1:dest_x2] = mask[src_y1:src_y2, src_x1:src_x2]
        alpha = (full_mask.astype(np.float32) / 255.0)[:, :, None] * 0.75
        overlay_color = np.zeros_like(mask_overlay)
        overlay_color[:, :, 2] = 255
        overlay_color[:, :, 1] = 40
        mask_overlay = (mask_overlay.astype(np.float32) * (1.0 - alpha) + overlay_color.astype(np.float32) * alpha).clip(0, 255).astype(np.uint8)
        cv2.rectangle(mask_overlay, (int(x1), int(y1)), (int(x2), int(y2)), (0, 220, 255), 3)
        cv2.putText(mask_overlay, "MASK OVERLAY", (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 255), 2, cv2.LINE_AA)

        result_frame_path = os.path.join(debug_dir, "debug_result.png")
        mask_overlay_path = os.path.join(debug_dir, "debug_mask_overlay.png")
        cv2.imwrite(result_frame_path, combined_frame)
        cv2.imwrite(mask_overlay_path, mask_overlay)
        info_path = os.path.join(debug_dir, "debug_info.json")
        info_payload = {
            "source_path": source_path,
            "requested_frame_index": requested_frame_index,
            "actual_frame_index": actual_frame_index,
            "bbox_shift": int(bbox_shift),
            "extra_margin": mask_settings["extra_margin"],
            "parsing_mode": mode,
            "left_cheek_width": mask_settings["left_cheek_width"],
            "right_cheek_width": mask_settings["right_cheek_width"],
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
            "crop_box": [int(v) for v in crop_box],
            "debug_dir": debug_dir,
            "result_frame_path": result_frame_path,
            "mask_frame_path": mask_frame_path,
            "mask_overlay_path": mask_overlay_path,
            "used_modified_mask": bool(modified_mask is not None),
            "modified_mask_path": current_modified_mask_path if modified_mask is not None else "",
        }
        with open(info_path, "w", encoding="utf-8") as handle:
            json.dump(info_payload, handle, indent=2)
        return {
            "debug_dir": debug_dir,
            "frame_path": result_frame_path,
            "mask_frame_path": mask_frame_path,
            "mask_overlay_path": mask_overlay_path,
            "input_frame_path": input_frame_path,
            "info_path": info_path,
            "requested_frame_index": requested_frame_index,
            "actual_frame_index": actual_frame_index,
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
            "crop_box": [int(v) for v in crop_box],
            "bbox_shift": int(bbox_shift),
            "extra_margin": mask_settings["extra_margin"],
            "parsing_mode": mode,
            "left_cheek_width": mask_settings["left_cheek_width"],
            "right_cheek_width": mask_settings["right_cheek_width"],
            "used_modified_mask": bool(modified_mask is not None),
            "modified_mask_path": current_modified_mask_path if modified_mask is not None else "",
        }

    def get_idle_payload(self, avatar_id, fps=24, avatar_path_override=None):
        cache_key = self._prepared_avatar_key(avatar_id, avatar_path_override=avatar_path_override)
        if cache_key not in self.prepared_avatars:
            prepared = self._build_prepared_avatar(avatar_id, avatar_path_override=avatar_path_override, bbox_shift=0)
            self.prepared_avatars[cache_key] = PreparedAvatarRuntime(self, prepared, self.batch_size)

        return self.prepared_avatars[cache_key].get_idle_payload(fps)
