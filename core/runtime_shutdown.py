"""Runtime shutdown helpers for avatar, TTS, STT, and CUDA cleanup."""

from __future__ import annotations

import threading
import time
import os

_DEFERRED_NATIVE_REFS = []


def _join_runtime_threads(*, name_prefixes=(), name_contains=(), timeout_seconds=4.0, logger=print):
    """Give real-time workers a brief chance to drop model references."""
    deadline = time.time() + max(0.0, float(timeout_seconds or 0.0))
    current = threading.current_thread()
    watched = []
    for thread in threading.enumerate():
        if thread is current or not thread.is_alive():
            continue
        name = str(getattr(thread, "name", "") or "")
        if any(name.startswith(prefix) for prefix in name_prefixes) or any(part in name for part in name_contains):
            watched.append(thread)

    for thread in watched:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            thread.join(timeout=remaining)
        except RuntimeError:
            pass

    still_alive = [
        str(getattr(thread, "name", "") or "")
        for thread in watched
        if thread.is_alive()
    ]
    if still_alive:
        logger(f"⚠️ [Shutdown] Runtime worker(s) still active after cleanup wait: {', '.join(still_alive)}")


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _defer_native_ref(label, model, *, logger=print):
    if model is None:
        return
    _DEFERRED_NATIVE_REFS.append(model)
    logger(f"ℹ️ [{label}] Native model cleanup deferred for stable stop.")


def shutdown_runtime_components(
    *,
    avatar_gui,
    tts_model,
    stt_model,
    unload_tts=True,
    unload_stt=True,
    stop_playback,
    pause_after_chunk,
    playback_paused,
    clear_avatar_stream_state,
    schedule_musetalk_runtime_cleanup,
    gc_module,
    torch_module,
    logger=print,
):
    """Run the existing shutdown sequence and return cleared component refs."""
    aggressive_native_unload = _env_flag("NC_AGGRESSIVE_NATIVE_UNLOAD")
    stop_playback.set()
    pause_after_chunk.clear()
    playback_paused.clear()
    clear_avatar_stream_state()

    if avatar_gui:
        try:
            avatar_gui.stop()
        except Exception as exc:
            logger(f"⚠️ [Avatar] Shutdown error: {exc}")
        finally:
            avatar_gui = None

    if unload_tts and tts_model is not None:
        model = tts_model
        tts_model = None
        if aggressive_native_unload:
            try:
                if hasattr(model, "close"):
                    model.close()
            except Exception as exc:
                logger(f"⚠️ [TTS] Shutdown error: {exc}")
            finally:
                del model
        else:
            _defer_native_ref("TTS", model, logger=logger)

    if unload_stt and stt_model is not None:
        model = stt_model
        stt_model = None
        if aggressive_native_unload:
            try:
                closer = getattr(model, "close", None)
                if callable(closer):
                    closer()
            except Exception as exc:
                logger(f"⚠️ [STT] Shutdown error: {exc}")
            finally:
                del model
        else:
            _defer_native_ref("STT", model, logger=logger)

    _join_runtime_threads(
        name_prefixes=("nc-tts-", "nc-llm-stream"),
        name_contains=("stream_delegated_audio_progress",),
        timeout_seconds=4.0,
        logger=logger,
    )

    aggressive_gc_shutdown = _env_flag("NC_AGGRESSIVE_GC_SHUTDOWN")
    if aggressive_gc_shutdown:
        gc_module.collect()
    aggressive_cuda_shutdown = _env_flag("NC_AGGRESSIVE_CUDA_SHUTDOWN")
    if aggressive_cuda_shutdown and torch_module.cuda.is_available():
        try:
            torch_module.cuda.empty_cache()
            if hasattr(torch_module.cuda, "ipc_collect"):
                torch_module.cuda.ipc_collect()
        except Exception:
            pass
    if aggressive_gc_shutdown:
        gc_module.collect()
    if aggressive_cuda_shutdown and torch_module.cuda.is_available():
        try:
            torch_module.cuda.empty_cache()
        except Exception:
            pass
    schedule_musetalk_runtime_cleanup(max_keep=0, force=True)
    return avatar_gui, tts_model, stt_model
