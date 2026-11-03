"""Guarded desktop relaunch after normal Qt/runtime teardown and process exit."""
from __future__ import annotations

import argparse
from collections.abc import Callable
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

RESTART_EXIT_CODE = 73


class RestartRequest:
    """UI-thread state only; closing and cleanup remain owned by the desktop."""

    def __init__(self, *, close: Callable[[], bool], closing: Callable[[], bool],
                 complete: Callable[[], bool], report: Callable[[str], None]) -> None:
        self._close, self._closing, self._complete, self._report = close, closing, complete, report
        self._requested = False

    def confirm(self) -> None:
        if self._requested or self._closing():
            return
        self._requested = True
        try:
            accepted = self._close()
        except (RuntimeError, OSError, ValueError) as exc:
            self._requested = False
            self._report(f"Desktop restart could not begin: {exc}")
            return
        if not accepted and not self._closing():
            self._requested = False

    def shutdown_changed(self) -> None:
        if not self._closing():
            self._requested = False

    def exit_code(self, result: int) -> int:
        if result == RESTART_EXIT_CODE:
            # Reserve the launcher sentinel for this confirmed, completed path.
            return 1
        return RESTART_EXIT_CODE if result == 0 and self._requested and self._closing() and self._complete() else result


def _launch_options(directory: Path) -> dict:
    options: dict = dict(cwd=str(directory), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return options


def _report_failure(message: str) -> None:
    """The Qt desktop is gone at this point; retain and show actual failures."""
    try:
        log = Path(tempfile.gettempdir()) / f"NeuralCompanion-restart-{os.getpid()}.log"
        log.write_text(message, encoding="utf-8")
        message += f"\n\nDetails: {log}"
    except OSError:
        pass
    print(message, file=sys.stderr)
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        show = ctypes.WinDLL("user32").MessageBoxW
        show.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
        show.restype = ctypes.c_int
        show(None, message, "NeuralCompanion restart failed", 0x10)


def handle_desktop_exit(result: int, entrypoint: Path) -> int:
    if result != RESTART_EXIT_CODE:
        return result
    try:
        entry = entrypoint.resolve(strict=True)
        subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()),
                          "--wait-for-pid", str(os.getpid()), "--entry", str(entry)],
                         **_launch_options(entry.parent))
    except OSError as exc:
        _report_failure(f"NeuralCompanion could not restart. Please launch it again.\n{exc}")
        return 1
    return 0


def wait_for_process_exit(pid: int, *, timeout_seconds: float = 120.0) -> bool:
    """Blocking wait runs only in the detached helper, never the Qt UI thread."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return ctypes.get_last_error() == 87  # Process already exited.
        try:
            return kernel.WaitForSingleObject(handle, int(timeout_seconds * 1000)) == 0
        finally:
            kernel.CloseHandle(handle)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(.05)
    return False


def relaunch_when_exited(pid: int, entrypoint: Path, *, report: Callable[[str], None] | None = None) -> int:
    report = report or _report_failure
    try:
        entry = entrypoint.resolve(strict=True)
    except OSError as exc:
        report(f"NeuralCompanion's launcher is unavailable. Please launch it again.\n{exc}")
        return 1
    if not wait_for_process_exit(pid):
        report("NeuralCompanion did not finish closing. Restart was canceled. Wait for cleanup, then launch it again.")
        return 1
    try:
        subprocess.Popen([sys.executable, "-B", str(entry)], **_launch_options(entry.parent))
    except OSError as exc:
        report(f"NeuralCompanion could not restart. Please launch it again.\n{exc}")
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wait for NC shutdown before relaunching its desktop.")
    parser.add_argument("--wait-for-pid", type=int, required=True)
    parser.add_argument("--entry", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(relaunch_when_exited(args.wait_for_pid, args.entry))
