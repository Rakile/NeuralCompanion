"""Bounded, owner-scoped subprocess execution for addon installers."""

from __future__ import annotations

import os
import select
import subprocess
import time
from dataclasses import dataclass
from typing import Sequence


_DRAIN_CHUNK_BYTES = 64 * 1024
_DRAIN_CHUNKS_PER_PASS = 16
_FINAL_DRAIN_MAX_PASSES = 8
_FINAL_DRAIN_MAX_BYTES = 256 * 1024
_FINAL_DRAIN_MAX_SECONDS = 0.1


@dataclass(frozen=True)
class InstallerResult:
    returncode: int | None
    output_tail: str
    cancelled: bool = False
    timed_out: bool = False


class _BoundedByteTail:
    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max(1, int(max_bytes))
        self._data = bytearray()

    def append(self, chunk: bytes) -> None:
        value = bytes(chunk or b"")
        if not value:
            return
        if len(value) >= self._max_bytes:
            self._data[:] = value[-self._max_bytes :]
            return
        self._data.extend(value)
        overflow = len(self._data) - self._max_bytes
        if overflow > 0:
            del self._data[:overflow]

    def text(self) -> str:
        return bytes(self._data).decode("utf-8", errors="replace").strip()


def _safe_poll(process):
    try:
        return process.poll()
    except Exception:
        return None


def _stop_exact_process(process, *, wait_seconds: float) -> bool:
    if _safe_poll(process) is not None:
        return True
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=wait_seconds)
        return True
    except Exception:
        pass
    if _safe_poll(process) is not None:
        return True
    try:
        process.kill()
    except Exception:
        pass
    try:
        process.wait(timeout=wait_seconds)
        return True
    except Exception:
        pass
    return _safe_poll(process) is not None


def _windows_available(fd: int) -> int | None:
    import ctypes
    import msvcrt

    available = ctypes.c_ulong(0)
    handle = msvcrt.get_osfhandle(fd)
    ok = ctypes.windll.kernel32.PeekNamedPipe(
        ctypes.c_void_p(handle),
        None,
        0,
        None,
        ctypes.byref(available),
        None,
    )
    if ok:
        return int(available.value)
    error = int(ctypes.windll.kernel32.GetLastError())
    if error in {6, 109, 232}:
        return None
    raise OSError(error, "PeekNamedPipe failed")


def _read_available(stream, max_bytes: int) -> bytes | None:
    if stream is None or getattr(stream, "closed", False):
        return None
    fd = stream.fileno()
    if os.name == "nt":
        available = _windows_available(fd)
        if available is None:
            return None
        if available <= 0:
            return b""
        return os.read(fd, min(int(max_bytes), available))
    readable, _, _ = select.select([fd], [], [], 0.0)
    if not readable:
        return b""
    chunk = os.read(fd, int(max_bytes))
    return chunk if chunk else None


def _drain_available(
    stream,
    tail: _BoundedByteTail,
    *,
    max_bytes: int | None = None,
) -> int:
    drained = 0
    for _ in range(_DRAIN_CHUNKS_PER_PASS):
        if max_bytes is not None and drained >= max(0, int(max_bytes)):
            return drained
        read_size = _DRAIN_CHUNK_BYTES
        if max_bytes is not None:
            read_size = min(read_size, max(0, int(max_bytes) - drained))
        if read_size <= 0:
            return drained
        try:
            chunk = _read_available(stream, read_size)
        except (OSError, ValueError):
            return drained
        if chunk is None or not chunk:
            return drained
        tail.append(chunk)
        drained += len(chunk)
    return drained


def _close_streams(process) -> None:
    for stream in (getattr(process, "stdout", None), getattr(process, "stderr", None)):
        if stream is None:
            continue
        try:
            stream.close()
        except Exception:
            pass


def run_owned_installer(
    command: Sequence[str],
    *,
    tasks,
    cancel,
    timeout_seconds: float = 900.0,
    stop_wait_seconds: float = 2.0,
    max_output_bytes: int = 64 * 1024,
    process_factory=subprocess.Popen,
) -> InstallerResult:
    """Run an installer with synchronous nonblocking pipe draining."""

    process = process_factory(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
    )
    try:
        tasks.register_process(
            "install-runtime",
            process,
            graceful_stop=lambda: _stop_exact_process(
                process,
                wait_seconds=stop_wait_seconds,
            ),
        )
    except BaseException:
        try:
            _stop_exact_process(process, wait_seconds=stop_wait_seconds)
        finally:
            _close_streams(process)
        raise

    tail = _BoundedByteTail(max_output_bytes)
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    cancelled = False
    timed_out = False
    try:
        while True:
            _drain_available(process.stdout, tail)
            _drain_available(process.stderr, tail)
            if _safe_poll(process) is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                timed_out = True
                break
            if cancel.wait(min(0.02, remaining)):
                cancelled = True
                break

        if cancelled or timed_out:
            _stop_exact_process(process, wait_seconds=stop_wait_seconds)

        # A descendant may inherit the pipe after the registered parent exits.
        # Bound retirement independently of descendant lifetime and output rate.
        final_deadline = time.monotonic() + _FINAL_DRAIN_MAX_SECONDS
        final_bytes = 0
        for _ in range(_FINAL_DRAIN_MAX_PASSES):
            if time.monotonic() >= final_deadline or final_bytes >= _FINAL_DRAIN_MAX_BYTES:
                break
            remaining = _FINAL_DRAIN_MAX_BYTES - final_bytes
            stdout_bytes = _drain_available(
                process.stdout,
                tail,
                max_bytes=remaining,
            )
            final_bytes += stdout_bytes
            remaining = _FINAL_DRAIN_MAX_BYTES - final_bytes
            stderr_bytes = _drain_available(
                process.stderr,
                tail,
                max_bytes=remaining,
            )
            final_bytes += stderr_bytes
            if stdout_bytes == 0 and stderr_bytes == 0:
                break
    finally:
        _close_streams(process)

    return InstallerResult(
        returncode=_safe_poll(process),
        output_tail=tail.text(),
        cancelled=cancelled,
        timed_out=timed_out,
    )
