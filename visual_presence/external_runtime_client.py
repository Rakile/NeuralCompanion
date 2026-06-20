from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable


LOG_RELATIVE_PATH = "runtime/ai_presence/external_runtime.log"


class ExternalAIPresenceRuntimeClient:
    """JSON-lines IPC client for the out-of-process AI Presence renderer."""

    def __init__(self, app_root: Path, logger: Callable[[str], None] | None = None):
        self.app_root = Path(app_root)
        self._logger = logger or (lambda _message: None)
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._log_handle = None

    def is_running(self) -> bool:
        process = self._process
        return bool(process is not None and process.poll() is None)

    def start(self) -> bool:
        with self._lock:
            if self.is_running():
                return True
            self.stop()
            script = Path(__file__).with_name("external_ai_presence_runtime.py")
            if not script.exists():
                self._logger(f"AI Presence external runtime script missing: {script}")
                return False
            python = self._python_executable()
            log_path = self.app_root / LOG_RELATIVE_PATH
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                self._log_handle = log_path.open("a", encoding="utf-8", buffering=1)
                self._log_handle.write(f"\n--- AI Presence external runtime start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                env = os.environ.copy()
                env["PYTHONPATH"] = str(self.app_root) + os.pathsep + str(env.get("PYTHONPATH", ""))
                self._process = subprocess.Popen(
                    [str(python), "-u", str(script), "--app-root", str(self.app_root)],
                    cwd=str(self.app_root),
                    stdin=subprocess.PIPE,
                    stdout=self._log_handle,
                    stderr=self._log_handle,
                    text=True,
                    encoding="utf-8",
                    env=env,
                    creationflags=self._creation_flags(),
                )
                return self.is_running()
            except Exception as exc:
                self._logger(f"Could not start AI Presence external runtime: {exc}")
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
            self._logger(f"AI Presence external runtime IPC failed: {exc}")
            return False

    def _python_executable(self) -> Path:
        override = os.environ.get("NC_AI_PRESENCE_PYTHON", "").strip()
        if override:
            path = Path(override)
            if path.exists():
                return path
        for candidate in (
            self.app_root / "addons" / "ai_presence_mode" / ".ai_presence_venv" / "Scripts" / "python.exe",
            self.app_root / "runtime" / "ai_presence" / "external_venv" / "Scripts" / "python.exe",
            self.app_root / ".venvs" / "ai_presence_runtime" / "Scripts" / "python.exe",
            self.app_root / ".venvs" / "nc_ai_presence" / "Scripts" / "python.exe",
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
