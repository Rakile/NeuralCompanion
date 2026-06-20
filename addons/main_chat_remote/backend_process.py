from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import threading
import secrets
import json
import urllib.error
import urllib.request


DEFAULT_BACKEND_HOST = "0.0.0.0"
DEFAULT_BACKEND_PORT = 8777
PAIRING_CODE_DIGITS = 6
PAIRING_CODE_MIN_DIGITS = 4
PAIRING_CODE_MAX_DIGITS = 9
HEALTH_REFRESH_INTERVAL_SECONDS = 2.0


def generate_pairing_code(digits: int = PAIRING_CODE_DIGITS) -> str:
    digits = max(PAIRING_CODE_MIN_DIGITS, min(PAIRING_CODE_MAX_DIGITS, int(digits or PAIRING_CODE_DIGITS)))
    floor = 10 ** (digits - 1)
    return str(floor + secrets.randbelow(9 * floor))


def normalize_pairing_code(value: str, *, max_digits: int = PAIRING_CODE_MAX_DIGITS) -> str:
    digits = "".join(ch for ch in str(value or "") if "0" <= ch <= "9")[: max(1, int(max_digits or PAIRING_CODE_MAX_DIGITS))]
    if len(digits) < PAIRING_CODE_MIN_DIGITS:
        return ""
    return digits


class BackendProcessSupervisor:
    def __init__(self, *, app_root: Path, runtime_dir: Path, bridge_info_path: Path, logger=None):
        self.app_root = Path(app_root)
        self.runtime_dir = Path(runtime_dir)
        self.bridge_info_path = Path(bridge_info_path)
        self.logger = logger
        self.venv_dir = self.app_root / ".venvs" / "nc_phone_remote"
        self.backend_script = self.app_root / "addons" / "main_chat_remote" / "remote_backend.py"
        self.setup_script = self.app_root / "addons" / "main_chat_remote" / "scripts" / "backend_venv.py"
        self.log_path = self.runtime_dir / "remote_backend.log"
        self._process: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._started_at = 0.0
        self._last_message = ""
        self._last_result: dict[str, Any] = {}
        self._pairing_code = ""
        self._host = DEFAULT_BACKEND_HOST
        self._port = DEFAULT_BACKEND_PORT
        self._health: dict[str, Any] = {"ok": False, "status": "not_started"}
        self._health_probe_process: subprocess.Popen | None = None

    @property
    def python_exe(self) -> Path:
        if sys.platform.startswith("win"):
            return self.venv_dir / "Scripts" / "python.exe"
        return self.venv_dir / "bin" / "python"

    def create_venv_command(self) -> list[str]:
        return [
            sys.executable,
            str(self.setup_script),
            "--venv-dir",
            str(self.venv_dir),
            "--bridge-info",
            str(self.bridge_info_path),
            "--create",
        ]

    def start_helper_command(
        self,
        *,
        host: str = DEFAULT_BACKEND_HOST,
        port: int = DEFAULT_BACKEND_PORT,
    ) -> list[str]:
        return [
            sys.executable,
            str(self.setup_script),
            "--venv-dir",
            str(self.venv_dir),
            "--bridge-info",
            str(self.bridge_info_path),
            "--host",
            str(host or DEFAULT_BACKEND_HOST),
            "--port",
            str(int(port or DEFAULT_BACKEND_PORT)),
            "--start",
        ]

    def start_command(
        self,
        *,
        host: str = DEFAULT_BACKEND_HOST,
        port: int = DEFAULT_BACKEND_PORT,
    ) -> list[str]:
        return [
            str(self.python_exe),
            str(self.backend_script),
            "--bridge-info",
            str(self.bridge_info_path),
            "--host",
            str(host or DEFAULT_BACKEND_HOST),
            "--port",
            str(int(port or DEFAULT_BACKEND_PORT)),
        ]

    def local_url(self, *, host: str | None = None, port: int | None = None) -> str:
        host_value = str(host if host is not None else self._host or DEFAULT_BACKEND_HOST).strip()
        probe_host = "127.0.0.1" if host_value in {"", "0.0.0.0", "::"} else host_value
        return f"http://{probe_host}:{int(port if port is not None else self._port or DEFAULT_BACKEND_PORT)}"

    def display_url(self, *, host: str | None = None, port: int | None = None) -> str:
        host_value = str(host if host is not None else self._host or DEFAULT_BACKEND_HOST).strip()
        if host_value in {"", "0.0.0.0", "::"}:
            try:
                from addons.main_chat_remote.remote_backend import lan_ip_address

                host_value = lan_ip_address()
            except Exception:
                host_value = "127.0.0.1"
        return f"http://{host_value}:{int(port if port is not None else self._port or DEFAULT_BACKEND_PORT)}"

    def status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            process, running, returncode = self._process_state_locked()
            if running and process is not None:
                self._schedule_health_refresh_locked(process=process, host=self._host, port=self._port)
            return {
                "running": bool(running),
                "pid": int(process.pid) if process is not None and running else 0,
                "returncode": returncode,
                "pairing_code": self._pairing_code if running else "",
                "pairing_code_digits": len(self._pairing_code) if running else 0,
                "host": self._host,
                "port": self._port,
                "local_url": self.local_url(),
                "display_url": self.display_url(),
                "health": dict(self._health),
                "venv_dir": str(self.venv_dir),
                "venv_python": str(self.python_exe),
                "venv_python_exists": self.python_exe.exists(),
                "bridge_info_path": str(self.bridge_info_path),
                "bridge_info_exists": self.bridge_info_path.exists(),
                "backend_script": str(self.backend_script),
                "backend_script_exists": self.backend_script.exists(),
                "setup_script": str(self.setup_script),
                "setup_script_exists": self.setup_script.exists(),
                "log_path": str(self.log_path),
                "started_at": self._started_at,
                "last_message": self._last_message,
                "last_result": dict(self._last_result),
                "create_command": self.create_venv_command(),
                "start_command": self.start_command(),
            }

    def create_venv(self) -> dict[str, Any]:
        if self.python_exe.exists():
            result = {"accepted": True, "skipped": True, "message": "Backend venv already exists.", "python": str(self.python_exe)}
            self._remember(result)
            return result
        if not self.setup_script.exists():
            result = {"accepted": False, "message": f"Backend venv helper is missing: {self.setup_script}"}
            self._remember(result)
            return result
        command = self.create_venv_command()
        try:
            completed = subprocess.run(command, cwd=str(self.app_root), check=False)
        except Exception as exc:
            result = {"accepted": False, "message": str(exc) or "Could not create backend venv.", "command": command}
            self._remember(result)
            return result
        accepted = completed.returncode == 0 and self.python_exe.exists()
        result = {
            "accepted": accepted,
            "returncode": int(completed.returncode),
            "command": command,
            "message": "Backend venv created." if accepted else "Backend venv creation failed.",
            "python": str(self.python_exe),
        }
        self._remember(result)
        return result

    def start(
        self,
        *,
        host: str = DEFAULT_BACKEND_HOST,
        port: int = DEFAULT_BACKEND_PORT,
        pairing_code: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            self._process_state_locked()
            if self._process is not None and self._process.poll() is None:
                result = {
                    "accepted": True,
                    "running": True,
                    "message": "LAN backend is already running.",
                    "pid": self._process.pid,
                    "pairing_code": self._pairing_code,
                }
                self._remember(result)
                return result
            if not self.python_exe.exists():
                result = {"accepted": False, "message": f"Backend venv Python not found: {self.python_exe}"}
                self._remember(result)
                return result
            if not self.bridge_info_path.exists():
                result = {"accepted": False, "message": f"Bridge info not found. Start the local bridge first: {self.bridge_info_path}"}
                self._remember(result)
                return result
            try:
                from addons.main_chat_remote.remote_backend import load_bridge_info

                load_bridge_info(self.bridge_info_path)
            except Exception as exc:
                result = {"accepted": False, "message": f"Bridge info is not usable. Start the local bridge first: {exc}"}
                self._remember(result)
                return result
            if not self.backend_script.exists():
                result = {"accepted": False, "message": f"Remote backend script not found: {self.backend_script}"}
                self._remember(result)
                return result
            code = normalize_pairing_code(pairing_code) or generate_pairing_code()
            port_value = int(port or DEFAULT_BACKEND_PORT)
            host_value = str(host or DEFAULT_BACKEND_HOST)
            command = self.start_command(host=host_value, port=port_value)
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                child_env = os.environ.copy()
                child_env["NC_MAIN_CHAT_REMOTE_CODE"] = code
                child_env["NC_MAIN_CHAT_REMOTE_HIDE_CODE_OUTPUT"] = "1"
                with self.log_path.open("a", encoding="utf-8") as log_file:
                    log_file.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting: {' '.join(command)}\n")
                    log_file.flush()
                    process = subprocess.Popen(
                        command,
                        cwd=str(self.app_root),
                        env=child_env,
                        stdin=subprocess.DEVNULL,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        creationflags=creationflags,
                    )
            except Exception as exc:
                result = {"accepted": False, "message": str(exc) or "Could not start LAN backend.", "command": command}
                self._remember(result)
                return result
            self._process = process
            self._pairing_code = code
            self._host = host_value
            self._port = port_value
            self._health = {"ok": False, "status": "starting", "url": self.local_url(host=host_value, port=port_value)}
            self._started_at = time.time()
            self._start_health_probe(host=host_value, port=port_value, process=process)
            result = {
                "accepted": True,
                "running": True,
                "message": "LAN backend started.",
                "pid": int(process.pid),
                "pairing_code": code,
                "url": self.display_url(host=host_value, port=port_value),
                "command": command,
            }
            self._remember(result)
            return result

    def stop(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
        if process is None:
            with self._lock:
                self._pairing_code = ""
                self._health = {"ok": False, "status": "stopped"}
            result = {"accepted": True, "running": False, "message": "LAN backend is not running."}
            self._remember(result)
            return result
        if process.poll() is not None:
            with self._lock:
                if self._process is process:
                    self._process = None
                self._pairing_code = ""
                self._health = {"ok": False, "status": "stopped", "returncode": process.returncode}
            result = {"accepted": True, "running": False, "message": "LAN backend is not running.", "returncode": process.returncode}
            self._remember(result)
            return result
        try:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        except Exception as exc:
            with self._lock:
                if process.poll() is not None and self._process is process:
                    self._process = None
            result = {"accepted": False, "message": str(exc) or "Could not stop LAN backend.", "pid": int(process.pid)}
            self._remember(result)
            return result
        with self._lock:
            if self._process is process:
                self._process = None
            self._pairing_code = ""
            self._health = {"ok": False, "status": "stopped"}
        result = {"accepted": True, "running": False, "message": "LAN backend stopped.", "returncode": process.returncode}
        self._remember(result)
        return result

    def probe_health(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        timeout_seconds: float = 1.0,
        process: subprocess.Popen | None = None,
    ) -> dict[str, Any]:
        url = f"{self.local_url(host=host, port=port)}/health"
        try:
            with urllib.request.urlopen(url, timeout=max(0.1, float(timeout_seconds or 1.0))) as response:
                payload = json.loads(response.read().decode("utf-8"))
            ok = bool(isinstance(payload, dict) and payload.get("ok") is True)
            result = {
                "ok": ok,
                "status": "ready" if ok else "unhealthy",
                "url": url,
                "payload": payload if isinstance(payload, dict) else {},
                "checked_at": time.time(),
            }
        except urllib.error.URLError as exc:
            result = {"ok": False, "status": "unreachable", "url": url, "error": str(exc), "checked_at": time.time()}
        except Exception as exc:
            result = {"ok": False, "status": "error", "url": url, "error": str(exc), "checked_at": time.time()}
        with self._lock:
            if process is None or self._process is process:
                self._health = dict(result)
        return result

    def _start_health_probe(self, *, host: str, port: int, process: subprocess.Popen) -> None:
        with self._lock:
            self._health_probe_process = process

        def worker() -> None:
            try:
                deadline = time.time() + 8.0
                while time.time() < deadline:
                    with self._lock:
                        current_process = self._process
                    if current_process is not process:
                        return
                    if process.poll() is not None:
                        with self._lock:
                            self._health = {
                                "ok": False,
                                "status": "exited",
                                "returncode": process.returncode,
                                "checked_at": time.time(),
                            }
                        return
                    result = self.probe_health(host=host, port=port, timeout_seconds=0.75, process=process)
                    if bool(result.get("ok", False)):
                        return
                    time.sleep(0.35)
            finally:
                with self._lock:
                    if self._health_probe_process is process:
                        self._health_probe_process = None

        threading.Thread(target=worker, name="nc-main-chat-remote-health", daemon=True).start()

    def _schedule_health_refresh_locked(self, *, process: subprocess.Popen, host: str, port: int) -> None:
        if self._health_probe_process is process:
            return
        now = time.time()
        checked_at = float(self._health.get("checked_at") or 0.0)
        if checked_at and now - checked_at < HEALTH_REFRESH_INTERVAL_SECONDS:
            return
        self._health_probe_process = process

        def worker() -> None:
            try:
                with self._lock:
                    current_process = self._process
                if current_process is not process:
                    return
                if process.poll() is not None:
                    with self._lock:
                        self._process_state_locked()
                    return
                self.probe_health(host=host, port=port, timeout_seconds=0.75, process=process)
            finally:
                with self._lock:
                    if self._health_probe_process is process:
                        self._health_probe_process = None

        threading.Thread(target=worker, name="nc-main-chat-remote-health-refresh", daemon=True).start()

    def _remember(self, result: dict[str, Any]) -> None:
        with self._lock:
            self._last_result = dict(result or {})
            self._last_message = str((result or {}).get("message") or "")
        log_fn = getattr(self.logger, "info", None)
        if callable(log_fn):
            try:
                log_fn("[MainChatRemote] %s", self._last_message)
            except Exception:
                pass

    def _process_state_locked(self) -> tuple[subprocess.Popen | None, bool, int | None]:
        process = self._process
        if process is None:
            return None, False, None
        returncode = process.poll()
        if returncode is None:
            return process, True, None
        self._process = None
        self._pairing_code = ""
        if self._health_probe_process is process:
            self._health_probe_process = None
        self._health = {
            "ok": False,
            "status": "exited",
            "returncode": int(returncode),
            "checked_at": time.time(),
        }
        return process, False, int(returncode)
