"""Runtime shutdown helpers for avatar, TTS, STT, and CUDA cleanup."""

from __future__ import annotations

import threading
import time


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


def shutdown_runtime_components(
    *,
    avatar_gui,
    tts_model,
    whisper_model,
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
        try:
            if hasattr(model, "close"):
                model.close()
        except Exception as exc:
            logger(f"⚠️ [TTS] Shutdown error: {exc}")
        finally:
            del model

    if unload_stt and whisper_model is not None:
        model = whisper_model
        whisper_model = None
        try:
            closer = getattr(model, "close", None)
            if callable(closer):
                closer()
        except Exception as exc:
            logger(f"⚠️ [STT] Shutdown error: {exc}")
        finally:
            del model

    _join_runtime_threads(
        name_prefixes=("nc-tts-",),
        name_contains=("stream_delegated_audio_progress",),
        timeout_seconds=4.0,
        logger=logger,
    )

    gc_module.collect()
    if torch_module.cuda.is_available():
        try:
            torch_module.cuda.empty_cache()
            if hasattr(torch_module.cuda, "ipc_collect"):
                torch_module.cuda.ipc_collect()
        except Exception:
            pass
    gc_module.collect()
    if torch_module.cuda.is_available():
        try:
            torch_module.cuda.empty_cache()
        except Exception:
            pass
    schedule_musetalk_runtime_cleanup(max_keep=0, force=True)
    return avatar_gui, tts_model, whisper_model
