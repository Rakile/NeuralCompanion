from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable


def _parse_event_line(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(str(line or "").strip())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    event_type = str(payload.get("type") or "").strip()
    if not event_type:
        return None
    payload["type"] = event_type
    return payload


class ExternalOrbRuntimeClient:
    """Small JSON-lines IPC client for the out-of-process Companion Orb overlay."""

    def __init__(
        self,
        app_root: Path,
        logger: Callable[[str], None] | None = None,
        event_handler: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.app_root = Path(app_root)
        self._logger = logger or (lambda _message: None)
        self._event_handler = event_handler
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._log_handle = None
        self._event_thread: threading.Thread | None = None

    def is_running(self) -> bool:
        process = self._process
        return bool(process is not None and process.poll() is None)

    def start(self) -> bool:
        with self._lock:
            if self.is_running():
                return True
            self.stop()
            script = Path(__file__).with_name("external_orb_runtime.py")
            if not script.exists():
                self._logger(f"Companion Orb external runtime script missing: {script}")
                return False
            python = self._python_executable()
            log_path = self.app_root / "runtime" / "companion_orb" / "external_runtime.log"
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                self._log_handle = log_path.open("a", encoding="utf-8", buffering=1)
                self._log_handle.write(f"\n--- Companion Orb external runtime start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                env = os.environ.copy()
                env["PYTHONPATH"] = str(self.app_root) + os.pathsep + str(env.get("PYTHONPATH", ""))
                self._process = subprocess.Popen(
                    [str(python), "-u", str(script), "--app-root", str(self.app_root)],
                    cwd=str(self.app_root),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=self._log_handle,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    creationflags=self._creation_flags(),
                )
                self._start_event_reader(self._process)
                return self.is_running()
            except Exception as exc:
                self._logger(f"Could not start Companion Orb external runtime: {exc}")
                self._close_log_handle()
                self._process = None
                return False

    def send(self, message: dict[str, Any]) -> bool:
        payload = dict(message or {})
        with self._lock:
            if not self.start():
                return False
            if not self._write(payload):
                self.stop()
                if not self.start():
                    return False
                return self._write(payload)
            return True

    def _start_event_reader(self, process: subprocess.Popen) -> None:
        if process.stdout is None:
            return
        self._event_thread = threading.Thread(
            target=self._read_events_loop,
            args=(process,),
            daemon=True,
            name="companion-orb-external-events",
        )
        self._event_thread.start()

    def _read_events_loop(self, process: subprocess.Popen) -> None:
        stream = process.stdout
        if stream is None:
            return
        for line in stream:
            event = _parse_event_line(line)
            if event is None:
                text = str(line or "").strip()
                if text:
                    self._logger(f"Companion Orb external runtime: {text}")
                continue
            handler = self._event_handler
            if not callable(handler):
                continue
            try:
                handler(event)
            except Exception as exc:
                self._logger(f"Companion Orb external event handler failed: {exc}")

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None:
            try:
                if process.poll() is None and process.stdin is not None:
                    process.stdin.write(json.dumps({"type": "shutdown"}) + "\n")
                    process.stdin.flush()
            except Exception:
                pass
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except Exception:
                pass
            try:
                process.wait(timeout=1.5)
            except Exception:
                try:
                    process.terminate()
                    process.wait(timeout=1.0)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
        self._event_thread = None
        self._close_log_handle()

    def _write(self, payload: dict[str, Any]) -> bool:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
            process.stdin.flush()
            return True
        except Exception as exc:
            self._logger(f"Companion Orb external runtime IPC failed: {exc}")
            return False

    def _python_executable(self) -> Path:
        override = os.environ.get("NC_COMPANION_ORB_PYTHON", "").strip()
        if override:
            path = Path(override)
            if path.exists():
                return path
        for candidate in (
            self.app_root / "addons" / "companion_orb_overlay" / ".orb_runtime_venv" / "Scripts" / "python.exe",
            self.app_root / "runtime" / "companion_orb" / "external_venv" / "Scripts" / "python.exe",
        ):
            if candidate.exists():
                return candidate
        return Path(sys.executable)

    def _creation_flags(self) -> int:
        if os.name != "nt":
            return 0
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def _close_log_handle(self) -> None:
        handle = self._log_handle
        self._log_handle = None
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
