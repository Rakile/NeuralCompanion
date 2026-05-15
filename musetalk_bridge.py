import json
import os
import queue
import re
import subprocess
import threading
import uuid
from collections import deque

MUSE_BRIDGE_DIAGNOSTIC_ECHO = False
MUSE_BRIDGE_WORKER_LOG = str(os.environ.get("NC_MUSETALK_WORKER_LOG", "") or "").strip().lower() in {"1", "true", "yes", "on"}
MUSE_BRIDGE_ALLOW_UNSUPPORTED_CUDA = str(os.environ.get("NC_MUSETALK_ALLOW_UNSUPPORTED_CUDA", "") or "").strip().lower() in {"1", "true", "yes", "on"}
_PROGRESS_LINE_RE = re.compile(r"^\s*\d+%\|.*\|\s*\d+/\d+\s*\[")


def _is_progress_noise_line(line):
    text = str(line or "").strip()
    if not text:
        return False
    if _PROGRESS_LINE_RE.match(text) and "it/s" in text:
        return True
    return False


class MuseTalkBridge:
    def __init__(self, root_dir="MuseTalk", worker_options=None):
        self.root_dir = os.path.abspath(root_dir)
        self.python_exe = os.path.join(self.root_dir, ".venv", "Scripts", "python.exe")
        self.worker_script = os.path.join(self.root_dir, "musetalk_worker.py")
        self.runtime_dir = os.path.join(self.root_dir, "runtime")
        self.log_path = os.path.join(self.runtime_dir, "musetalk_worker.log")
        self.worker_options = dict(worker_options or {})
        self.log_worker_output = bool(self.worker_options.get("log_worker_output", MUSE_BRIDGE_WORKER_LOG))
        self.process = None
        self.pending = {}
        self._reader_thread = None
        self._lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._stopping = False
        self._recent_output = deque(maxlen=12)
        self._torch_compat_checked = False

    def _validate_torch_cuda_compatibility(self):
        if self._torch_compat_checked or MUSE_BRIDGE_ALLOW_UNSUPPORTED_CUDA:
            self._torch_compat_checked = True
            return
        script = r"""
import json
payload = {"ok": True, "cuda_available": False}
try:
    import torch
    payload["torch"] = str(getattr(torch, "__version__", "") or "")
    payload["torch_cuda"] = str(getattr(torch.version, "cuda", "") or "")
    payload["cuda_available"] = bool(torch.cuda.is_available())
    payload["arch_list"] = list(torch.cuda.get_arch_list()) if payload["cuda_available"] else []
    if payload["cuda_available"]:
        name = torch.cuda.get_device_name(0)
        capability = torch.cuda.get_device_capability(0)
        sm = f"sm_{int(capability[0])}{int(capability[1])}"
        payload["device_name"] = str(name)
        payload["capability"] = [int(capability[0]), int(capability[1])]
        payload["sm"] = sm
        if int(capability[0]) >= 12 and sm not in payload["arch_list"]:
            payload["ok"] = False
            payload["error"] = (
                f"MuseTalk isolated runtime uses torch {payload['torch']} / CUDA {payload['torch_cuda']}, "
                f"which does not include {sm} support for {name}. "
                "RTX 50 / Blackwell cards need the MuseTalk CUDA 12.8 runtime path "
                "(for example torch==2.10.0 from the cu128 PyTorch index)."
            )
except Exception as exc:
    payload["ok"] = False
    payload["error"] = str(exc)
print(json.dumps(payload))
"""
        try:
            result = subprocess.run(
                [self.python_exe, "-c", script],
                cwd=self.root_dir,
                text=True,
                capture_output=True,
                timeout=30,
            )
        except Exception as exc:
            raise RuntimeError(f"Could not validate MuseTalk torch CUDA compatibility: {exc}") from exc
        raw = (result.stdout or "").strip().splitlines()
        detail = raw[-1] if raw else ""
        try:
            payload = json.loads(detail)
        except Exception as exc:
            combined = " ".join(part.strip() for part in [result.stdout, result.stderr] if part)
            raise RuntimeError(f"Could not parse MuseTalk torch CUDA compatibility check: {combined}") from exc
        if result.returncode != 0:
            combined = " ".join(part.strip() for part in [result.stdout, result.stderr] if part)
            raise RuntimeError(f"MuseTalk torch CUDA compatibility check failed: {combined}")
        if not payload.get("ok", False):
            raise RuntimeError(str(payload.get("error") or "MuseTalk torch CUDA compatibility check failed."))
        self._torch_compat_checked = True

    def _fail_pending_requests(self, error):
        payload = {"ok": False, "error": str(error or "MuseTalk worker stopped.")}
        with self._pending_lock:
            queues = list(self.pending.values())
        for response_queue in queues:
            try:
                response_queue.put_nowait(dict(payload))
            except Exception:
                pass

    def start(self):
        with self._lock:
            if self._stopping:
                raise RuntimeError("MuseTalk worker is stopping.")
            if self.process and self.process.poll() is None:
                return

            if not os.path.exists(self.python_exe):
                raise FileNotFoundError(f"MuseTalk Python not found: {self.python_exe}")
            if not os.path.exists(self.worker_script):
                raise FileNotFoundError(f"MuseTalk worker not found: {self.worker_script}")
            os.makedirs(self.runtime_dir, exist_ok=True)
            self._validate_torch_cuda_compatibility()

            command = [self.python_exe, self.worker_script]
            vram_mode = str(self.worker_options.get("vram_mode", "") or "").strip()
            if vram_mode:
                command.extend(["--vram-mode", vram_mode])

            worker_env = dict(os.environ)
            worker_env.setdefault("PYTHONUTF8", "1")
            worker_env.setdefault("PYTHONIOENCODING", "utf-8")

            self.process = subprocess.Popen(
                command,
                cwd=self.root_dir,
                env=worker_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self._recent_output.clear()
            print(f"[MuseTalkBridge] Worker process started: pid={self.process.pid}, command={os.path.basename(self.python_exe)} {os.path.basename(self.worker_script)}")
            self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
            self._reader_thread.start()

    def stop(self):
        with self._lock:
            process = self.process
            if not process:
                self._stopping = False
                return
            if self._stopping:
                return
            self._stopping = True
        if not process:
            return
        self._fail_pending_requests("MuseTalk worker stopping.")
        try:
            if process.poll() is None and process.stdin:
                process.stdin.write(json.dumps({"action": "shutdown", "request_id": str(uuid.uuid4())}) + "\n")
                process.stdin.flush()
        except Exception:
            pass
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        except Exception:
            pass
        try:
            if process.poll() is None and os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
        except Exception:
            pass
        reader = self._reader_thread
        if reader and reader.is_alive():
            try:
                reader.join(timeout=1.0)
            except RuntimeError:
                pass
        try:
            if process.stdin:
                process.stdin.close()
        except Exception:
            pass
        try:
            if process.stdout:
                process.stdout.close()
        except Exception:
            pass
        self._fail_pending_requests("MuseTalk worker stopped.")
        with self._lock:
            self.process = None
            self._reader_thread = None
            self._stopping = False

    def request(self, payload, timeout=120):
        self.start()
        request_id = str(uuid.uuid4())
        response_queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self.pending[request_id] = response_queue
        message = dict(payload)
        message["request_id"] = request_id

        with self._lock:
            if self._stopping:
                raise RuntimeError("MuseTalk worker is stopping.")
            if not self.process or self.process.poll() is not None:
                raise RuntimeError("MuseTalk worker is not running.")
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()

        try:
            if timeout is None:
                response = response_queue.get()
            else:
                timeout = max(0.0, float(timeout))
                import time

                end_at = time.time() + timeout
                while True:
                    remaining = end_at - time.time()
                    if remaining <= 0:
                        raise queue.Empty()
                    try:
                        response = response_queue.get(timeout=min(0.1, remaining))
                        break
                    except queue.Empty:
                        if not self.process or self.process.poll() is not None:
                            raise RuntimeError(self._worker_stopped_message("MuseTalk worker stopped before responding."))
        except queue.Empty:
            raise TimeoutError(f"MuseTalk worker request timed out after {timeout:.1f}s: {payload.get('action')}")
        finally:
            with self._pending_lock:
                self.pending.pop(request_id, None)
        if not response.get("ok", False):
            raise RuntimeError(response.get("error", "Unknown MuseTalk worker error"))
        return response

    def _worker_stopped_message(self, prefix):
        process = self.process
        code = None
        try:
            code = process.poll() if process is not None else None
        except Exception:
            code = None
        details = [str(prefix or "MuseTalk worker stopped.")]
        if code is not None:
            details.append(f"exit_code={code}")
        recent = [str(line or "").strip() for line in list(self._recent_output) if str(line or "").strip()]
        if recent:
            details.append("recent_output=" + " | ".join(recent[-5:]))
            recent_text = "\n".join(recent).lower()
            if "defaultcpuallocator" in recent_text or "not enough memory" in recent_text:
                details.append(
                    "hint=PyTorch could not allocate system RAM. On Windows this is often caused by "
                    "low/fragmented RAM or a full system drive/pagefile; close memory-heavy apps, free "
                    "space on C:, or reboot before starting MuseTalk again."
                )
        return " ".join(details)

    def _read_stdout(self):
        process = self.process
        stdout = process.stdout if process is not None else None
        while process and process.poll() is None and stdout:
            line = stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            if _is_progress_noise_line(line):
                continue
            self._recent_output.append(line)
            if self.log_worker_output:
                try:
                    with open(self.log_path, "a", encoding="utf-8") as log_file:
                        log_file.write(line + "\n")
                except Exception:
                    pass
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("worker_info") == "musetalk_vram_profile" and MUSE_BRIDGE_DIAGNOSTIC_ECHO:
                print(
                    "[MuseTalkBridge] Worker profile: "
                    f"pid={payload.get('pid')} mode={payload.get('mode')} "
                    f"batch_size={payload.get('batch_size')} whisper_device={payload.get('whisper_device')} "
                    f"vae_slicing={payload.get('vae_slicing')} preload_face_parsing={payload.get('preload_face_parsing')} "
                    f"gpu={payload.get('gpu')}"
                )
            elif payload.get("worker_info") == "checkpoint" and MUSE_BRIDGE_DIAGNOSTIC_ECHO:
                print(
                    "[MuseTalkBridge] Worker checkpoint: "
                    f"pid={payload.get('pid')} label={payload.get('label')} "
                    f"gpu={payload.get('gpu')}"
                )
            request_id = payload.get("request_id")
            with self._pending_lock:
                response_queue = self.pending.get(request_id)
            if response_queue is not None:
                try:
                    response_queue.put_nowait(payload)
                except Exception:
                    pass
