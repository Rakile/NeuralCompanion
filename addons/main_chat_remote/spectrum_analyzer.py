from __future__ import annotations

import base64
import json
import math
import os
import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


SPECTRUM_VERSION = 1
SPECTRUM_FPS = 24
SPECTRUM_BARS = 48
SPECTRUM_SAMPLE_RATE = 16000
MAX_SPECTRUM_SECONDS = 600
DEFAULT_MAX_PENDING = 8

SpectrumCallback = Callable[[str, dict[str, Any] | None, str], None]


@dataclass(frozen=True)
class AnalysisJob:
    audio_id: str
    audio_path: Path
    sidecar_path: Path
    callback: SpectrumCallback


class SpectrumAnalyzer:
    """Builds compact phone spectrum sidecars away from request and UI threads."""

    def __init__(
        self,
        logger=None,
        *,
        max_pending: int = DEFAULT_MAX_PENDING,
        ffmpeg_path: str | Path | None = None,
    ):
        self._logger = logger
        self._ffmpeg_path = self._resolve_ffmpeg(ffmpeg_path)
        self._queue: queue.Queue[AnalysisJob | None] = queue.Queue(
            maxsize=max(1, int(max_pending or DEFAULT_MAX_PENDING))
        )
        self._lock = threading.RLock()
        self._cancelled: set[str] = set()
        self._jobs: dict[str, AnalysisJob] = {}
        self._active_audio_id = ""
        self._active_process: subprocess.Popen[bytes] | None = None
        self._closed = False
        self._worker = threading.Thread(
            target=self._run,
            name="nc-phone-spectrum",
            daemon=True,
        )
        self._worker.start()

    def submit(
        self,
        audio_id: str,
        audio_path: Path,
        sidecar_path: Path,
        callback: SpectrumCallback,
    ) -> bool:
        wanted_id = str(audio_id or "").strip()
        if not wanted_id or not callable(callback):
            return False
        job = AnalysisJob(
            audio_id=wanted_id,
            audio_path=Path(audio_path),
            sidecar_path=Path(sidecar_path),
            callback=callback,
        )
        with self._lock:
            if self._closed:
                return False
            self._cancelled.discard(wanted_id)
            self._jobs[wanted_id] = job
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            with self._lock:
                if self._jobs.get(wanted_id) is job:
                    self._jobs.pop(wanted_id, None)
            return False

    def cancel(self, audio_id: str) -> None:
        wanted_id = str(audio_id or "").strip()
        if not wanted_id:
            return
        process = None
        sidecar_path = None
        with self._lock:
            self._cancelled.add(wanted_id)
            job = self._jobs.pop(wanted_id, None)
            sidecar_path = job.sidecar_path if job is not None else None
            if self._active_audio_id == wanted_id:
                process = self._active_process
        self._terminate_process(process)
        self._unlink(sidecar_path)
        if sidecar_path is not None:
            self._unlink(self._temporary_path(sidecar_path))

    def shutdown(self) -> None:
        process = None
        jobs: list[AnalysisJob] = []
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancelled.update(self._jobs)
            jobs = list(self._jobs.values())
            self._jobs.clear()
            process = self._active_process
        self._terminate_process(process)
        while True:
            try:
                queued = self._queue.get_nowait()
            except queue.Empty:
                break
            else:
                if queued is not None:
                    jobs.append(queued)
                self._queue.task_done()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._worker.join(timeout=3.0)
        for job in jobs:
            self._unlink(self._temporary_path(job.sidecar_path))

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                if self._cancelled_or_closed(job.audio_id):
                    continue
                self._process(job)
            finally:
                if job is not None:
                    with self._lock:
                        if self._jobs.get(job.audio_id) is job:
                            self._jobs.pop(job.audio_id, None)
                        self._cancelled.discard(job.audio_id)
                self._queue.task_done()

    def _process(self, job: AnalysisJob) -> None:
        payload = None
        error = ""
        try:
            payload = self._analyze(job)
            if self._cancelled_or_closed(job.audio_id):
                self._unlink(self._temporary_path(job.sidecar_path))
                return
            job.sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self._temporary_path(job.sidecar_path)
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary_path.replace(job.sidecar_path)
        except Exception as exc:
            error = str(exc or "Spectrum analysis failed").strip() or "Spectrum analysis failed"
            self._unlink(self._temporary_path(job.sidecar_path))
            self._log("debug", "Spectrum analysis unavailable for %s: %s", job.audio_id, error)
        if self._cancelled_or_closed(job.audio_id):
            return
        try:
            job.callback(job.audio_id, payload, error)
        except Exception as exc:
            self._log("debug", "Spectrum completion callback failed for %s: %s", job.audio_id, exc)

    def _analyze(self, job: AnalysisJob) -> dict[str, Any]:
        if self._ffmpeg_path is None:
            raise RuntimeError("FFmpeg is unavailable")
        try:
            import numpy as np
        except Exception as exc:
            raise RuntimeError("NumPy is unavailable") from exc
        if not job.audio_path.is_file():
            raise RuntimeError("Audio chunk is unavailable")

        command = [
            str(self._ffmpeg_path),
            "-v",
            "error",
            "-i",
            str(job.audio_path),
            "-t",
            str(MAX_SPECTRUM_SECONDS),
            "-ac",
            "1",
            "-ar",
            str(SPECTRUM_SAMPLE_RATE),
            "-f",
            "f32le",
            "pipe:1",
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with self._lock:
            if self._closed or job.audio_id in self._cancelled:
                self._terminate_process(process)
                raise RuntimeError("Spectrum analysis cancelled")
            self._active_audio_id = job.audio_id
            self._active_process = process
        try:
            stdout, stderr = process.communicate(timeout=120)
        except subprocess.TimeoutExpired as exc:
            self._terminate_process(process)
            raise RuntimeError("FFmpeg spectrum decode timed out") from exc
        finally:
            with self._lock:
                if self._active_process is process:
                    self._active_process = None
                    self._active_audio_id = ""
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail or "FFmpeg spectrum decode failed")

        samples = np.frombuffer(stdout, dtype="<f4")
        if samples.size <= 0:
            raise RuntimeError("Decoded audio was empty")
        frame_size = max(1, int(round(SPECTRUM_SAMPLE_RATE / SPECTRUM_FPS)))
        frame_count = min(
            SPECTRUM_FPS * MAX_SPECTRUM_SECONDS,
            max(1, int(math.ceil(samples.size / frame_size))),
        )
        wanted_samples = frame_count * frame_size
        if samples.size < wanted_samples:
            samples = np.pad(samples, (0, wanted_samples - samples.size))
        else:
            samples = samples[:wanted_samples]
        frames = samples.reshape(frame_count, frame_size)
        window = np.hanning(frame_size).astype(np.float32)
        magnitudes = np.abs(np.fft.rfft(frames * window, axis=1))
        frequencies = np.fft.rfftfreq(frame_size, 1.0 / SPECTRUM_SAMPLE_RATE)
        edges = np.geomspace(40.0, SPECTRUM_SAMPLE_RATE / 2.0, SPECTRUM_BARS + 1)
        energies = np.zeros((frame_count, SPECTRUM_BARS), dtype=np.float32)
        for band in range(SPECTRUM_BARS):
            indices = np.flatnonzero(
                (frequencies >= edges[band]) & (frequencies < edges[band + 1])
            )
            if indices.size:
                energies[:, band] = np.sqrt(
                    np.mean(np.square(magnitudes[:, indices]), axis=1)
                )
        compressed = np.log1p(energies)
        scale = float(np.percentile(compressed, 95.0))
        if scale > 0.0:
            compressed = np.clip(compressed / scale, 0.0, 1.0)
        else:
            compressed.fill(0.0)
        quantized = np.rint(compressed * 255.0).astype(np.uint8)
        return {
            "version": SPECTRUM_VERSION,
            "fps": SPECTRUM_FPS,
            "bars": SPECTRUM_BARS,
            "frame_count": frame_count,
            "encoding": "uint8-base64",
            "data": base64.b64encode(quantized.tobytes(order="C")).decode("ascii"),
        }

    def _cancelled_or_closed(self, audio_id: str) -> bool:
        with self._lock:
            return self._closed or str(audio_id or "") in self._cancelled

    @staticmethod
    def _temporary_path(sidecar_path: Path) -> Path:
        return sidecar_path.with_suffix(sidecar_path.suffix + ".tmp")

    @staticmethod
    def _unlink(path: Path | None) -> None:
        if path is None:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes] | None) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    @staticmethod
    def _resolve_ffmpeg(value: str | Path | None) -> Path | None:
        executable = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        candidates: list[Path] = []
        provided = str(value or "").strip()
        configured = str(os.environ.get("NC_FFMPEG_BIN", "") or "").strip()
        for raw in (provided, configured):
            if not raw:
                continue
            path = Path(raw)
            candidates.append(path / executable if path.is_dir() else path)
        candidates.append(Path(__file__).resolve().parents[2] / "tools" / "ffmpeg" / "bin" / executable)
        discovered = shutil.which("ffmpeg")
        if discovered:
            candidates.append(Path(discovered))
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    def _log(self, level: str, message: str, *args) -> None:
        logger = self._logger
        log_fn = getattr(logger, str(level or "debug"), None) if logger is not None else None
        if callable(log_fn):
            try:
                log_fn("[MainChatRemote] " + message, *args)
            except Exception:
                pass
