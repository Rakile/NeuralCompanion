import json
import os
import sys
import traceback
import argparse
import time
from pathlib import Path

from musetalk_engine import MuseTalkEngine


def _env_flag(name):
    return str(os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


WORKER_DIAGNOSTIC_LOGGING = _env_flag("NC_MUSETALK_WORKER_DIAGNOSTICS")


def _configure_stdio_encoding():
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_configure_stdio_encoding()


def to_abs(path):
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.abspath(path)


def normalize_mask_overrides(mask_overrides):
    normalized = []
    worker_cwd = Path.cwd()
    project_root = worker_cwd.parent
    for entry in list(mask_overrides or []):
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        override_mask_path = str(item.get("override_mask_path", "") or "").strip()
        if override_mask_path:
            candidate = Path(override_mask_path)
            if not candidate.is_absolute():
                abs_from_worker = (worker_cwd / candidate).resolve()
                abs_from_project = (project_root / candidate).resolve()
                if abs_from_worker.exists():
                    candidate = abs_from_worker
                elif abs_from_project.exists():
                    candidate = abs_from_project
                else:
                    candidate = abs_from_project
            item["override_mask_path"] = str(candidate)
        normalized.append(item)
    return normalized


def resolve_vram_profile(mode):
    aliases = {
        "quality": "quality",
        "balanced": "balanced",
        "low": "low",
        "low_vram": "low",
        "very_low": "very_low",
        "very_low_vram": "very_low",
    }
    mode = aliases.get(str(mode or "quality").strip().lower(), "quality")
    profiles = {
        "quality": {
            "batch_size": 20,
            "whisper_device": "cuda",
            "enable_vae_slicing": False,
            "preload_face_parsing": True,
        },
        "balanced": {
            "batch_size": 10,
            "whisper_device": "cuda",
            "enable_vae_slicing": True,
            "preload_face_parsing": False,
        },
        "low": {
            "batch_size": 6,
            "whisper_device": "cpu",
            "enable_vae_slicing": True,
            "preload_face_parsing": False,
        },
        "very_low": {
            "batch_size": 3,
            "whisper_device": "cpu",
            "enable_vae_slicing": True,
            "preload_face_parsing": False,
        },
    }
    return mode if mode in profiles else "quality", profiles.get(mode, profiles["quality"])


def gpu_vram_snapshot():
    try:
        import torch
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


def torch_runtime_snapshot():
    try:
        import torch
        payload = {
            "torch": str(getattr(torch, "__version__", "") or ""),
            "torch_cuda": str(getattr(torch.version, "cuda", "") or ""),
            "cuda_available": bool(torch.cuda.is_available()),
        }
        if payload["cuda_available"]:
            capability = torch.cuda.get_device_capability(0)
            payload.update(
                {
                    "device_name": str(torch.cuda.get_device_name(0)),
                    "capability": [int(capability[0]), int(capability[1])],
                    "arch_list": list(torch.cuda.get_arch_list()),
                }
            )
        return payload
    except Exception as exc:
        return {"error": str(exc)}


def emit_worker_checkpoint(label, extra=None):
    if not WORKER_DIAGNOSTIC_LOGGING:
        return
    payload = {
        "worker_info": "checkpoint",
        "label": label,
        "pid": os.getpid(),
        "time": round(time.time(), 3),
        "gpu": gpu_vram_snapshot(),
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload), flush=True)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--vram-mode", default="quality")
    args, _ = parser.parse_known_args()
    resolved_mode, profile = resolve_vram_profile(args.vram_mode)

    engine = MuseTalkEngine(
        version="v15",
        ffmpeg_path=to_abs("./ffmpeg-master-latest-win64-gpl-shared/bin"),
        unet_config=to_abs("./models/musetalkV15/musetalk.json"),
        unet_model_path=to_abs("./models/musetalkV15/unet.pth"),
        whisper_dir=to_abs("./models/whisper"),
        result_dir=to_abs("./results"),
        batch_size=profile["batch_size"],
        whisper_device=profile["whisper_device"],
        enable_vae_slicing=profile["enable_vae_slicing"],
        preload_face_parsing=profile["preload_face_parsing"],
    )
    if WORKER_DIAGNOSTIC_LOGGING:
        print(
            json.dumps(
                {
                    "worker_info": "musetalk_vram_profile",
                    "pid": os.getpid(),
                    "mode": resolved_mode,
                    "batch_size": profile["batch_size"],
                    "whisper_device": profile["whisper_device"],
                    "vae_slicing": bool(profile["enable_vae_slicing"]),
                    "preload_face_parsing": bool(profile["preload_face_parsing"]),
                    "gpu": gpu_vram_snapshot(),
                    "torch_runtime": torch_runtime_snapshot(),
                }
            ),
            flush=True,
        )
    emit_worker_checkpoint("engine_initialized", {"mode": resolved_mode})

    while True:
        line = sys.stdin.readline()
        if not line:
            break

        try:
            payload = json.loads(line.strip())
            action = payload.get("action")
            request_id = payload.get("request_id")

            if action == "shutdown":
                print(json.dumps({"ok": True, "request_id": request_id}))
                sys.stdout.flush()
                break

            if action == "prepare_avatar":
                emit_worker_checkpoint("prepare_avatar_start", {"avatar_id": payload["avatar_id"]})
                prepared = engine.prepare_avatar(
                    avatar_id=payload["avatar_id"],
                    video_path=to_abs(payload["video_path"]),
                    bbox_shift=int(payload.get("bbox_shift", 0)),
                    recreate=bool(payload.get("recreate", False)),
                    extra_margin=payload.get("extra_margin"),
                    parsing_mode=payload.get("parsing_mode"),
                    left_cheek_width=payload.get("left_cheek_width"),
                    right_cheek_width=payload.get("right_cheek_width"),
                    mask_ranges=payload.get("mask_ranges"),
                    mask_overrides=normalize_mask_overrides(payload.get("mask_overrides")),
                    avatar_path_override=to_abs(payload.get("avatar_path_override", "")) if payload.get("avatar_path_override") else None,
                    create_frame_cache=bool(payload.get("create_frame_cache", True)),
                )
                result = {
                    "ok": True,
                    "request_id": request_id,
                    "avatar_id": prepared.avatar_id,
                    "avatar_path": prepared.avatar_path,
                    "prepare_timing": dict(getattr(engine, "last_prepare_timing", {}) or {}),
                }
                emit_worker_checkpoint("prepare_avatar_done", {"avatar_id": payload["avatar_id"]})
            elif action == "render_audio":
                emit_worker_checkpoint("render_audio_start", {"chunk_id": payload["chunk_id"], "avatar_id": payload["avatar_id"]})
                result_payload = engine.render_audio(
                    avatar_id=payload["avatar_id"],
                    audio_path=to_abs(payload["audio_path"]),
                    chunk_id=payload["chunk_id"],
                    fps=int(payload.get("fps", 24)),
                    output_root=to_abs(payload.get("output_root", "./runtime/rendered_chunks")),
                    reset_timeline=bool(payload.get("reset_timeline", False)),
                    timeline_indices=payload.get("timeline_indices"),
                    overlap_prefix_frames=int(payload.get("overlap_prefix_frames", 0) or 0),
                    start_timeline_idx=payload.get("start_timeline_idx"),
                    max_frames=payload.get("max_frames"),
                    avatar_path_override=to_abs(payload.get("avatar_path_override", "")) if payload.get("avatar_path_override") else None,
                )
                result = {
                    "ok": True,
                    "request_id": request_id,
                    **result_payload,
                }
                emit_worker_checkpoint(
                    "render_audio_done",
                    {
                        "chunk_id": payload["chunk_id"],
                        "frame_count": int(result_payload.get("frame_count", 0) or 0),
                    },
                )
            elif action == "debug_first_frame":
                emit_worker_checkpoint("debug_first_frame_start", {"source_path": payload.get("source_path", "")})
                result_payload = engine.debug_first_frame(
                    source_path=to_abs(payload["source_path"]),
                    bbox_shift=int(payload.get("bbox_shift", 0) or 0),
                    output_root=to_abs(payload.get("output_root", "./runtime/first_frame_debug")),
                    frame_index=int(payload.get("frame_index", 0) or 0),
                    extra_margin=payload.get("extra_margin"),
                    parsing_mode=payload.get("parsing_mode"),
                    left_cheek_width=payload.get("left_cheek_width"),
                    right_cheek_width=payload.get("right_cheek_width"),
                    modified_mask_path=to_abs(payload.get("modified_mask_path", "")) if payload.get("modified_mask_path") else None,
                )
                result = {
                    "ok": True,
                    "request_id": request_id,
                    **result_payload,
                }
                emit_worker_checkpoint("debug_first_frame_done", {"frame_path": result_payload.get("frame_path", "")})
            elif action == "get_idle_payload":
                result_payload = engine.get_idle_payload(
                    avatar_id=payload["avatar_id"],
                    fps=int(payload.get("fps", 24)),
                    avatar_path_override=to_abs(payload.get("avatar_path_override", "")) if payload.get("avatar_path_override") else None,
                )
                result = {
                    "ok": bool(result_payload),
                    "request_id": request_id,
                    **(result_payload or {}),
                    **({} if result_payload else {"error": "Idle payload unavailable"}),
                }
            elif action == "estimate_frame_count":
                frame_count = engine.estimate_frame_count(
                    avatar_id=payload["avatar_id"],
                    audio_path=to_abs(payload["audio_path"]),
                    fps=int(payload.get("fps", 24)),
                    avatar_path_override=to_abs(payload.get("avatar_path_override", "")) if payload.get("avatar_path_override") else None,
                )
                result = {
                    "ok": True,
                    "request_id": request_id,
                    "frame_count": int(frame_count),
                }
            else:
                result = {
                    "ok": False,
                    "request_id": request_id,
                    "error": f"Unsupported action: {action}",
                }
        except Exception as exc:
            result = {
                "ok": False,
                "request_id": payload.get("request_id") if "payload" in locals() else None,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }

        print(json.dumps(result))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
