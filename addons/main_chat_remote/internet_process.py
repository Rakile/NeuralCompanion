from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from addons.main_chat_remote.internet_settings import InternetRemoteSettings


class InternetGatewaySupervisor:
    def __init__(self, *, app_root: str | Path, runtime_dir: str | Path, logger=None):
        self.app_root = Path(app_root)
        self.runtime_dir = Path(runtime_dir)
        self.logger = logger
        self.gateway_script = self.app_root / "addons" / "main_chat_remote" / "internet_gateway.py"
        self.registry_file = self.runtime_dir / "credentials.json"
        self.signing_key_file = self.runtime_dir / "signing.key"
        self.certificate_file = self.runtime_dir / "active" / "fullchain.pem"
        self.private_key_file = self.runtime_dir / "active" / "private-key.pem"
        self.log_file = self.runtime_dir / "internet_gateway.log"
        self._lock = threading.RLock()
        self._process: subprocess.Popen[Any] | None = None
        self._settings = InternetRemoteSettings()
        self._started_at = 0.0
        self._last_message = ""

    def build_launch(
        self,
        settings: InternetRemoteSettings,
        *,
        upstream_code: str,
    ) -> tuple[list[str], dict[str, str]]:
        normalized = settings.normalized()
        command = [
            sys.executable,
            str(self.gateway_script),
            "--host",
            normalized.gateway_host,
            "--port",
            str(normalized.gateway_port),
            "--cert-file",
            str(self.certificate_file),
            "--key-file",
            str(self.private_key_file),
        ]
        for host in (normalized.ddns_hostname, normalized.public_ip):
            if host:
                command.extend(("--allowed-host", host))
        environment = dict(os.environ)
        environment.update(
            {
                "NC_MAIN_CHAT_INTERNET_UPSTREAM_CODE": str(upstream_code or "").strip(),
                "NC_MAIN_CHAT_INTERNET_REGISTRY_FILE": str(self.registry_file),
                "NC_MAIN_CHAT_INTERNET_SIGNING_KEY_FILE": str(self.signing_key_file),
            }
        )
        return command, environment

    @staticmethod
    def public_launch_snapshot(command: list[str], environment: dict[str, str]) -> dict[str, Any]:
        del environment
        return {"command": list(command), "secrets": "passed through a private process environment"}

    def start(self, settings: InternetRemoteSettings, *, upstream_code: str) -> dict[str, Any]:
        normalized = settings.normalized()
        with self._lock:
            process = self._live_process_unlocked()
            if process is not None:
                return {"accepted": True, "running": True, "message": "Internet gateway is already running."}
            validation = self._launch_error(normalized, upstream_code)
            if validation:
                self._last_message = validation
                return {"accepted": False, "running": False, "message": validation}
            conflict = self._port_conflict(normalized.gateway_host, normalized.gateway_port)
            if conflict:
                self._last_message = conflict
                return {"accepted": False, "running": False, "message": conflict}
            command, environment = self.build_launch(normalized, upstream_code=upstream_code)
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            try:
                log_handle = self.log_file.open("a", encoding="utf-8", buffering=1)
                process = subprocess.Popen(
                    command,
                    cwd=str(self.app_root),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    close_fds=True,
                )
                log_handle.close()
            except (OSError, ValueError) as exc:
                self._last_message = f"Could not start Internet gateway: {exc}"
                return {"accepted": False, "running": False, "message": self._last_message}
            self._process = process
            self._settings = normalized
            self._started_at = time.time()
        if not self._wait_for_start(process, normalized.gateway_host, normalized.gateway_port):
            returncode = process.poll()
            self.stop()
            message = (
                f"Internet gateway exited during startup ({returncode})."
                if returncode is not None
                else "Internet gateway did not open its listening port in time."
            )
            with self._lock:
                self._last_message = message
            return {"accepted": False, "running": False, "message": message}
        with self._lock:
            self._last_message = "Internet gateway is running."
        return {"accepted": True, "running": True, "message": self._last_message, "pid": process.pid}

    def reload(self, settings: InternetRemoteSettings, *, upstream_code: str) -> dict[str, Any]:
        self.stop()
        return self.start(settings, upstream_code=upstream_code)

    def stop(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            self._process = None
        if process is None or process.poll() is not None:
            with self._lock:
                self._last_message = "Internet gateway is stopped."
            return {"accepted": True, "running": False, "message": self._last_message}
        try:
            process.terminate()
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass
        with self._lock:
            self._last_message = "Internet gateway stopped."
        return {"accepted": True, "running": False, "message": self._last_message}

    def status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            process = self._live_process_unlocked()
            return {
                "running": process is not None,
                "pid": int(process.pid) if process is not None else 0,
                "started_at": self._started_at if process is not None else 0.0,
                "host": self._settings.gateway_host,
                "port": self._settings.gateway_port,
                "log_file": str(self.log_file),
                "last_message": self._last_message,
            }

    def _live_process_unlocked(self) -> subprocess.Popen[Any] | None:
        process = self._process
        if process is not None and process.poll() is not None:
            self._process = None
            process = None
        return process

    def _launch_error(self, settings: InternetRemoteSettings, upstream_code: str) -> str:
        if not settings.enabled:
            return "Internet Remote is disabled."
        if not self.gateway_script.is_file():
            return f"Internet gateway script is missing: {self.gateway_script}"
        for label, path in (
            ("certificate", self.certificate_file),
            ("private key", self.private_key_file),
            ("credential registry", self.registry_file),
            ("signing key", self.signing_key_file),
        ):
            if not path.is_file() or path.stat().st_size <= 0:
                return f"Internet gateway {label} is missing."
        code = str(upstream_code or "").strip()
        if not (4 <= len(code) <= 9 and code.isdigit()):
            return "A running LAN backend pairing code is required."
        return ""

    @staticmethod
    def _port_conflict(host: str, port: int) -> str:
        probe_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
        try:
            with socket.create_connection((probe_host, int(port)), timeout=0.25):
                return f"Another process is already using Internet gateway port {int(port)}."
        except OSError:
            return ""

    @staticmethod
    def _wait_for_start(process: subprocess.Popen[Any], host: str, port: int) -> bool:
        probe_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
        deadline = time.time() + 4.0
        while time.time() < deadline:
            if process.poll() is not None:
                return False
            try:
                with socket.create_connection((probe_host, int(port)), timeout=0.25):
                    return True
            except OSError:
                time.sleep(0.1)
        return False
