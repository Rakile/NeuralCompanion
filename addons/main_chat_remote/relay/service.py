"""Qt-safe supervisor for the isolated Internet worker and dependency setup."""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


class RelayService:
    def __init__(
        self, *, runtime_dir: Path, app_root: Path, bridge_info_path: Path, logger=None
    ):
        self.runtime_dir = Path(runtime_dir) / "relay"
        self.app_root = Path(app_root)
        self.bridge_info = Path(bridge_info_path)
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._wake = threading.Event()
        self._queue = queue.Queue(maxsize=16)
        self._process = None
        self._thread = None
        self._stopped = False
        self._active_command = False
        self._action_started = False
        self._disconnect_requested = False
        self._closing = False
        self._exited_process = None
        self._local_settings_process = None
        self._account_cache = None
        self._pipe_lock = threading.Lock()
        self._chess_replies = {}
        self._snapshot = {
            "enabled": False,
            "busy": False,
            "status": "disconnected",
            "message": "Internet disconnected. Connect to go online.",
            "worker_running": False,
            "stopping": False,
            "error_code": "",
            "authenticated": False,
            "email_verified": False,
            "account": {},
            "registered": False,
            "online": False,
            "peer_count": 0,
            "dependencies_ready": False,
            "router_mapping_enabled": False,
            "router_mapping_status": "disabled",
            "mfa_pending": False,
            "mfa_status": "",
            "mfa_secret": "",
            "mfa_uri": "",
            "mfa_qr": "",
            "mfa_recovery_codes": [],
        }

        # Read the saved opt-in without starting the worker or touching the router.
        from .router_mapping import MappingSettings
        mapping_enabled = MappingSettings.load(self.runtime_dir / "router_mapping.json").enabled
        self._snapshot.update(router_mapping_enabled=mapping_enabled,
                              router_mapping_status="ready" if mapping_enabled else "disabled")

        # Display metadata is not authentication authority. Only the isolated
        # worker accesses/validates saved credentials in Credential Manager.
        try:
            path = self.runtime_dir / "account_status.json"
            if path.stat().st_size <= 65536:
                cached = self._account_fields(json.loads(path.read_text(encoding="utf-8")))
                self._snapshot.update(cached)
                self._account_cache = cached
        except (OSError, ValueError, TypeError):
            pass

    @staticmethod
    def _account_fields(value):
        value = value if isinstance(value, dict) else {}
        account = value.get("account")
        account = account if isinstance(account, dict) else {}
        return {"authenticated": value.get("authenticated") is True,
                "email_verified": value.get("email_verified") is True,
                "account": {key: account[key] for key in ("username", "email")
                            if isinstance(account.get(key), str) and len(account[key]) <= 320}}

    def _cache_account(self, state):
        cached = self._account_fields(state)
        if cached == self._account_cache:
            return
        temporary = None
        try:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.runtime_dir,
                                             prefix="account_status-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(cached, stream)
            os.replace(temporary, self.runtime_dir / "account_status.json")
            self._account_cache = cached
        except OSError:
            # Display caching must not affect connection or credential rotation.
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def snapshot(self):
        with self._lock:
            return {
                **self._snapshot,
                "account": dict(self._snapshot.get("account") or {}),
            }

    def _update(self, **values):
        with self._lock:
            self._snapshot.update(values)
            self._condition.notify_all()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stopped = False
            self._thread = threading.Thread(
                target=self._run, name="nc-relay-supervisor", daemon=True
            )
            self._thread.start()

    def stop(self):
        with self._lock:
            self._stopped = True
        self._wake.set()

    def disconnect(self):
        """Request cleanup without signing out, including during a pending action."""
        with self._lock:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._disconnect_requested = True
            if self._process is None and not self._active_command:
                self._disconnect_requested = False
                self._update(enabled=False, online=False, busy=False, peer_count=0, stopping=False,
                             status="disconnected", message="Internet disconnected.")
            else:
                self._update(online=False, busy=True, stopping=True)
        self._wake.set()

    def wait_for_offline(self, timeout=15.0):
        with self._condition:
            return self._condition.wait_for(lambda: self._process is None
                and not self._active_command and not self._disconnect_requested
                and not self._snapshot["busy"], timeout)

    def submit(self, action, payload=None):
        if action not in {
            "prepare", "register_account", "verify_email", "login", "logout",
            "connect", "disconnect", "replace_desktop", "resend_verification",
            "forgot_password", "reset_password", "set_router_mapping",
            "mfa_enroll", "mfa_confirm", "mfa_verify", "mfa_acknowledge", "mfa_cancel",
        }:
            return False
        with self._lock:
            if self._snapshot.get("busy") or self._stopped:
                return False
            if (self._snapshot.get("error_code") == "WORKER_STOP_FAILED"
                    and self._process is not None and action != "disconnect"):
                return False
            if action == "disconnect":
                self.disconnect()
                return True
            try:
                self._queue.put_nowait({"action": action, "payload": dict(payload or {})})
            except queue.Full:
                return False
            self._snapshot["busy"] = True
            self.start()
            self._wake.set()
        return True

    def _python(self):
        dedicated = (
            self.app_root
            / ".venvs/nc_relay"
            / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        )
        if dedicated.is_file():
            return str(dedicated)
        if importlib.util.find_spec("aiortc") and importlib.util.find_spec(
            "websockets"
        ):
            return sys.executable
        return None

    def _prepare(self):
        if not shutil.which("node"):
            raise RuntimeError("Install Node.js before preparing NC Relay.")
        target = self.app_root / ".venvs/nc_relay"
        if target.exists():
            raise RuntimeError(
                "Existing Internet environment needs manual repair; it was not modified."
            )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._update(message="Preparing isolated Internet runtime…", busy=True)
        subprocess.run(
            [sys.executable, "-m", "venv", str(target)],
            check=True,
            capture_output=True,
            creationflags=flags,
            timeout=120,
        )
        python = target / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "-r",
                str(self.app_root / "addons/main_chat_remote/requirements-relay.txt"),
            ],
            check=True,
            capture_output=True,
            creationflags=flags,
            timeout=600,
        )

    def _check_runtime(self):
        if (
            not shutil.which("node")
            or not (
                self.app_root / "packages/nc-relay-protocol/dist/validator.cjs"
            ).is_file()
        ):
            self._update(
                busy=False,
                status="setup_required",
                message="NC Relay needs Node.js and the built shared protocol package.",
                dependencies_ready=False,
            )
            return None
        python = self._python()
        if not python:
            self._update(
                busy=False,
                status="setup_required",
                message="Prepare Internet runtime to enable NC Relay.",
                dependencies_ready=False,
            )
            return None
        # An interrupted installation can leave python.exe present without
        # worker dependencies. Probe that exact interpreter off the Qt thread.
        try:
            checked = subprocess.run(
                [python, "-B", "-c",
                 "import aiortc; from websockets.asyncio.client import connect"],
                cwd=self.app_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=30,
                check=False,
            )
            dependencies_ready = checked.returncode == 0
        except (OSError, subprocess.SubprocessError):
            dependencies_ready = False
        if not dependencies_ready:
            self._update(
                busy=False,
                enabled=False,
                online=False,
                status="setup_required",
                message="Internet runtime is incomplete. Its dependencies need repair.",
                error_code="DEPENDENCIES_MISSING",
                dependencies_ready=False,
            )
            return None
        self._update(dependencies_ready=True)
        return True

    def _launch(self):
        if not self._check_runtime():
            return None
        python = self._python()
        proc = subprocess.Popen(
            [
                python,
                "-B",
                "-u",
                "-m",
                "addons.main_chat_remote.relay.worker",
                str(self.runtime_dir),
                str(self.bridge_info),
            ],
            cwd=self.app_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with self._lock:
            self._process = proc
            self._local_settings_process = None
            self._exited_process = None
            self._update(worker_running=True)

        def receive():
            try:
                for line in proc.stdout:
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict):
                            self._receive_state(proc, value)
                    except (ValueError, TypeError):
                        pass
            finally:
                with self._lock:
                    if self._process is proc:
                        self._exited_process = proc
                self._wake.set()

        threading.Thread(target=receive, name="nc-relay-status", daemon=True).start()
        return proc

    def chess_request(self, message):
        """Worker-thread-only RPC. Does not publish chess data into phone snapshots."""
        if threading.current_thread() is threading.main_thread():
            raise RuntimeError('Online chess requests must run outside the UI thread.')
        from .chess_rpc import validate_chess_rpc
        from uuid import uuid4
        validate_chess_rpc(message)
        rid=uuid4().hex
        with self._lock:
            proc=self._process
            if (proc is None or self._closing or self._stopped or self._disconnect_requested
                    or not self._snapshot.get('enabled') or not self._snapshot.get('authenticated')):
                return dict(error=dict(code='RELAY_CONNECTION_REQUIRED',
                    message='Connect NC Relay in Main Chat Remote → Internet, then press Refresh in chess.'))
            if len(self._chess_replies)>=4:
                return dict(error=dict(code='CHESS_BUSY',message='The chess connection is busy; try again shortly.'))
            self._chess_replies[rid]=None
        try:
            with self._pipe_lock:
                proc.stdin.write(json.dumps(dict(action='chess_mcp',request_id=rid,request=message))+'\n')
                proc.stdin.flush()
            with self._condition:
                self._condition.wait_for(lambda:self._chess_replies.get(rid) is not None
                    or self._process is not proc or self._closing or self._stopped,timeout=15)
                response=self._chess_replies.get(rid)
            if not response or response.get('error'):
                return dict(error=dict(code='CHESS_REQUEST_UNCONFIRMED',
                    message='Online chess request unconfirmed; synchronize before retrying.'))
            return response['result']
        except (OSError,ValueError):
            return dict(error=dict(code='CHESS_REQUEST_UNCONFIRMED',
                message='Online chess connection changed; synchronize before retrying.'))
        finally:
            with self._lock: self._chess_replies.pop(rid,None)

    def _receive_state(self, proc, value):
        # Receiver thread only. Optional OpenCV belongs to the desktop environment,
        # not the minimal network worker. Never persist the URI or rendered QR.
        if value.get("mfa_uri") and not value.get("mfa_qr"):
            from .mfa_display import enrollment_qr
            uri = str(value["mfa_uri"])
            with self._lock:
                previous_uri = self._snapshot.get("mfa_uri")
                previous_qr = self._snapshot.get("mfa_qr", "")
            value = {**value, "mfa_qr": previous_qr if uri == previous_uri else enrollment_qr(uri)}
        with self._lock:
            if self._process is not proc or self._closing:
                return
            if value.get('kind') == 'chess_response':
                rid=value.get('request_id')
                if rid in self._chess_replies:
                    self._chess_replies[rid]=value
                    self._condition.notify_all()
                return
            if self._active_command:
                if value.get("busy"):
                    self._action_started = True
                elif not self._action_started:
                    # Initial worker publication precedes the first command.
                    # It must not clear busy or trigger premature offline cleanup.
                    return
                else:
                    self._active_command = False
                    self._action_started = False
            allowed = set(self._snapshot) - {"worker_running", "stopping"}
            allowed.add("desktop_id")
            incoming = {key: item for key, item in value.items() if key in allowed}
            if self._local_settings_process is proc:
                # A fresh settings-only worker has not checked saved credentials.
                for key in ("authenticated", "email_verified", "account"):
                    incoming.pop(key, None)
            if "account" in incoming:
                incoming["account"] = self._account_fields(value)["account"]
            self._snapshot.update(incoming)
            if not value.get("busy"):
                self._cache_account(self._snapshot)
                if not self._snapshot.get("enabled") and not self._snapshot.get("mfa_pending"):
                    self._snapshot.update(busy=True, stopping=True)
            if self._disconnect_requested:
                self._snapshot.update(online=False, busy=True, stopping=True)
            self._condition.notify_all()
        self._wake.set()

    def _close_process(self, proc):
        with self._lock:
            self._closing = True
            self._update(online=False, busy=True, stopping=True)
        try:
            if proc.poll() is None:
                try:
                    with self._pipe_lock:
                        proc.stdin.write('{"action":"stop"}\n')
                        proc.stdin.flush()
                    proc.wait(timeout=6)
                except (OSError, ValueError, subprocess.SubprocessError):
                    if sys.platform == "win32":
                        # venv's Windows launcher can own a base-Python child.
                        # Kill only this owned worker tree if graceful stop fails.
                        try:
                            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=5)
                        except (OSError, subprocess.SubprocessError):
                            pass
                    if proc.poll() is None:
                        proc.kill()
            proc.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            with self._lock:
                self._closing = False
                self._update(busy=False, stopping=False, status="error",
                             error_code="WORKER_STOP_FAILED",
                             message="Internet worker did not exit. Disconnect to retry cleanup.")
            return False
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        with self._lock:
            if self._process is proc:
                self._process = None
                self._local_settings_process = None
            self._exited_process = None
            self._closing = False
            self._active_command = False
            self._action_started = False
            self._update(enabled=False, online=False, peer_count=0, busy=False,
                         worker_running=False, stopping=False, mfa_pending=False,
                         mfa_status="", mfa_secret="", mfa_uri="", mfa_qr="", mfa_recovery_codes=[])
        return True

    def _run(self):
        try:
            # One dependency probe, without starting WebRTC or restoring a login.
            self._check_runtime()
            while True:
                self._wake.wait()
                self._wake.clear()
                with self._lock:
                    if self._stopped:
                        break
                    proc = self._process
                    active = self._active_command
                    exited = proc is not None and self._exited_process is proc
                    disconnect = self._disconnect_requested
                    enabled = self._snapshot.get("enabled")
                    pending_mfa = self._snapshot.get("mfa_pending")
                if proc is None and disconnect and not active:
                    # Setup or a failed launch can finish without ever owning
                    # a child. Settle cancellation before accepting another action.
                    with self._lock:
                        self._disconnect_requested = False
                        self._update(enabled=False, online=False, busy=False, stopping=False,
                                     status="disconnected", message="Internet disconnected.")
                if proc is not None and (exited or (not active and (disconnect or (not enabled and not pending_mfa)))):
                    unexpected = exited and (enabled or active) and not disconnect
                    if not self._close_process(proc):
                        continue
                    with self._lock:
                        self._disconnect_requested = False
                    if unexpected:
                        self._update(status="error", error_code="WORKER_EXITED",
                                     message="Internet worker stopped. Connect to retry.")
                    elif disconnect:
                        self._update(status="disconnected", message="Internet disconnected.")
                with self._lock:
                    if self._active_command or self._disconnect_requested:
                        continue
                    try:
                        command = self._queue.get_nowait()
                    except queue.Empty:
                        continue
                    self._active_command = True
                    self._action_started = False
                    self._update(busy=True)
                try:
                    if command["action"] == "prepare":
                        if self._process is not None:
                            raise RuntimeError("Internet runtime is already running.")
                        self._prepare()
                        self._check_runtime()
                        with self._lock:
                            self._active_command = False
                            self._update(busy=self._disconnect_requested)
                        self._wake.set()
                        continue
                    local_settings_only = self._process is None and command["action"] == "set_router_mapping"
                    proc = self._process or self._launch()
                    if local_settings_only and proc is not None:
                        with self._lock:
                            self._local_settings_process = proc
                    if proc is None:
                        with self._lock:
                            self._active_command = False
                            self._update(busy=self._disconnect_requested)
                        self._wake.set()
                        continue
                    with self._lock:
                        cancelled = self._stopped or self._disconnect_requested
                        if cancelled:
                            self._active_command = False
                            self._action_started = False
                    if cancelled:
                        self._wake.set()
                        continue
                    with self._pipe_lock:
                        proc.stdin.write(json.dumps(command) + "\n")
                        proc.stdin.flush()
                except Exception:
                    with self._lock:
                        self._active_command = False
                        self._update(busy=False, enabled=False, online=False, status="error",
                            message="Internet setup or worker request failed. No credentials were logged.",
                            error_code="RUNTIME_ERROR")
                    self._wake.set()
        finally:
            proc = self._process
            if proc is not None:
                self._close_process(proc)
            with self._lock:
                self._active_command = False
                if self._process is None:
                    self._disconnect_requested = False
                self._update(online=False, busy=False, stopping=False)
