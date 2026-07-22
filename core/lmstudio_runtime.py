"""LM Studio model lifecycle helpers.

Provider-specific model load/unload behavior lives here so the engine can stay
focused on orchestration instead of embedding LM Studio mechanics directly.
"""

from __future__ import annotations

import importlib
import contextlib
import csv
import os
import re
import subprocess
import time
from urllib.parse import urlparse


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_LAST_PRIORITY_LOG_AT = 0.0
_PRIORITY_LOG_INTERVAL_SECONDS = 30.0

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_SET_INFORMATION = 0x0200
_NORMAL_PRIORITY_CLASS = 0x00000020
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
_ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
_LMSTUDIO_PROCESS_MARKERS = ("lm studio", "lmstudio", "lm-studio", "lms.exe")


def _clean_cli_output(text: str) -> str:
    cleaned = _ANSI_RE.sub("", str(text or ""))
    cleaned = cleaned.replace("\r", "\n")
    lines = []
    for line in cleaned.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("loading ") and "model loaded successfully" not in line.lower():
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def get_sdk():
    try:
        return importlib.import_module("lmstudio")
    except Exception:
        return None


def sdk_host(base_url: str) -> str:
    try:
        api_host = str(base_url or "").strip()
        api_host = re.sub(r"^https?://", "", api_host, flags=re.IGNORECASE)
        api_host = api_host.rstrip("/")
        if api_host.endswith("/v1"):
            api_host = api_host[:-3]
        return api_host.strip("/")
    except Exception:
        return "127.0.0.1:1234"


def _base_url_hostname(base_url: str) -> str:
    value = str(base_url or "").strip()
    if not value:
        return "127.0.0.1"
    parse_value = value if re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.IGNORECASE) else f"http://{value}"
    try:
        parsed = urlparse(parse_value)
        host = str(parsed.hostname or "").strip().lower()
    except Exception:
        host = ""
    if not host:
        host = sdk_host(value).split(":", 1)[0].strip("[]").lower()
    return host


def is_local_base_url(base_url: str) -> bool:
    host = _base_url_hostname(base_url)
    return host in {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}


def sdk_client(sdk, base_url: str):
    if sdk is None:
        return None
    try:
        return sdk.Client(api_host=sdk_host(base_url))
    except Exception:
        return None


def run_lms_cli(args, timeout=300):
    try:
        completed = subprocess.run(
            ["lms", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        output = "\n".join(
            part.strip() for part in [completed.stdout or "", completed.stderr or ""] if part and part.strip()
        ).strip()
        output = _clean_cli_output(output)
        return completed.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def _kernel32():
    if os.name != "nt":
        return None
    try:
        import ctypes

        return ctypes.windll.kernel32
    except Exception:
        return None


def _open_process(pid: int):
    kernel32 = _kernel32()
    if kernel32 is None:
        return None
    try:
        return kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_SET_INFORMATION,
            False,
            int(pid),
        )
    except Exception:
        return None


def _get_priority_class(pid: int) -> int:
    kernel32 = _kernel32()
    if kernel32 is None:
        return 0
    handle = _open_process(pid)
    if not handle:
        return 0
    try:
        return int(kernel32.GetPriorityClass(handle) or 0)
    finally:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass


def _set_priority_class(pid: int, priority_class: int) -> bool:
    kernel32 = _kernel32()
    if kernel32 is None:
        return False
    handle = _open_process(pid)
    if not handle:
        return False
    try:
        return bool(kernel32.SetPriorityClass(handle, int(priority_class)))
    finally:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass


def _tasklist_processes() -> list[tuple[int, str]]:
    if os.name != "nt":
        return []
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
    except Exception:
        return []
    if completed.returncode != 0 or not completed.stdout:
        return []
    rows = []
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row) < 2:
            continue
        name = str(row[0] or "").strip()
        try:
            pid = int(str(row[1] or "").strip())
        except Exception:
            continue
        if pid > 0 and name:
            rows.append((pid, name))
    return rows


def _lmstudio_processes() -> list[tuple[int, str]]:
    current_pid = os.getpid()
    matches = []
    for pid, name in _tasklist_processes():
        if pid == current_pid:
            continue
        lowered = name.lower()
        if any(marker in lowered for marker in _LMSTUDIO_PROCESS_MARKERS):
            matches.append((pid, name))
    return matches


@contextlib.contextmanager
def local_inference_responsiveness_guard(logger=print):
    """Give NC's Qt overlay scheduling room while LM Studio is generating locally."""
    if os.name != "nt":
        yield
        return
    originals: dict[int, int] = {}
    changed_names: list[str] = []
    current_pid = os.getpid()
    current_priority = _get_priority_class(current_pid)
    if current_priority in {_NORMAL_PRIORITY_CLASS, _BELOW_NORMAL_PRIORITY_CLASS}:
        if _set_priority_class(current_pid, _ABOVE_NORMAL_PRIORITY_CLASS):
            originals[current_pid] = current_priority
    for pid, name in _lmstudio_processes():
        priority = _get_priority_class(pid)
        if not priority or priority == _BELOW_NORMAL_PRIORITY_CLASS:
            continue
        if _set_priority_class(pid, _BELOW_NORMAL_PRIORITY_CLASS):
            originals[pid] = priority
            changed_names.append(name)
    global _LAST_PRIORITY_LOG_AT
    if changed_names:
        now = time.monotonic()
        if now - _LAST_PRIORITY_LOG_AT >= _PRIORITY_LOG_INTERVAL_SECONDS:
            _LAST_PRIORITY_LOG_AT = now
            try:
                logger(f"🫧 [LM Studio] Lowered local inference priority for UI responsiveness: {', '.join(sorted(set(changed_names)))}")
            except Exception:
                pass
    try:
        yield
    finally:
        for pid, priority in list(originals.items()):
            _set_priority_class(pid, priority)


def prepare_chat_model_lifecycle(
    provider_id: str,
    model_name: str,
    *,
    active_model_name: str = "",
    unload_func=None,
    load_func=None,
    is_placeholder=None,
    reason: str = "LM Studio chat model",
    force_unload: bool = False,
) -> tuple[bool, str]:
    """Unload stale LM Studio chat models before loading the requested model."""
    provider = str(provider_id or "").strip().lower()
    active_name = str(active_model_name or "").strip()
    clean_model_name = str(model_name or "").strip()
    if provider != "lmstudio":
        return True, active_name
    if not clean_model_name or (callable(is_placeholder) and is_placeholder(clean_model_name)):
        return True, active_name
    if not callable(unload_func) or not callable(load_func):
        return False, active_name

    should_unload = bool(force_unload) or (active_name and active_name != clean_model_name) or not active_name
    if not should_unload:
        return True, active_name
    if should_unload:
        try:
            unload_func(reason=reason)
        except TypeError:
            unload_func()
    ready = bool(load_func(clean_model_name))
    return ready, clean_model_name if ready else active_name


def unload_models(*, base_url: str, logger=print, reason: str = "MuseTalk warmup") -> bool:
    target = sdk_host(base_url)
    allow_local_cli_fallback = is_local_base_url(base_url)
    clean_reason = str(reason or "model load").strip()
    logger(f"🧠 [LM Studio] Unloading loaded models before {clean_reason}...")
    sdk = get_sdk()
    if sdk is not None:
        try:
            client = sdk_client(sdk, base_url)
            if client is None:
                raise RuntimeError("Could not create LM Studio SDK client")
            loaded_models = list(client.list_loaded_models())
            if not loaded_models:
                logger("✓ [LM Studio] No loaded models to unload.")
                return True
            unloaded = []
            for model in loaded_models:
                identifier = getattr(model, "identifier", None) or "<unknown>"
                model.unload()
                unloaded.append(str(identifier))
            logger(f"✓ [LM Studio] Unloaded via SDK: {', '.join(unloaded)}")
            return True
        except Exception as exc:
            if not allow_local_cli_fallback:
                logger(
                    f"[LM Studio] SDK unload failed for remote target {target}: {exc}. "
                    "local lms CLI fallback disabled."
                )
                return False
            logger(f"⚠️ [LM Studio] SDK unload failed, falling back to CLI: {exc}")
    if not allow_local_cli_fallback:
        logger(f"[LM Studio] Remote target {target}; SDK unavailable or failed; local lms CLI fallback disabled.")
        return False
    ok, output = run_lms_cli(["unload", "--all"], timeout=180)
    if ok:
        if output:
            logger(f"✓ [LM Studio] Unload complete: {output}")
        else:
            logger("✓ [LM Studio] Unload complete.")
        return True
    logger(f"⚠️ [LM Studio] Could not unload models: {output}")
    return False


def load_model(model_name: str, *, base_url: str, is_placeholder=None, logger=print) -> bool:
    clean_model_name = str(model_name or "").strip()
    if callable(is_placeholder) and is_placeholder(clean_model_name):
        return False
    target = sdk_host(base_url)
    allow_local_cli_fallback = is_local_base_url(base_url)
    logger(f"🧠 [LM Studio] Reloading selected model: {clean_model_name}")
    sdk = get_sdk()
    if sdk is not None:
        try:
            client = sdk_client(sdk, base_url)
            if client is None:
                raise RuntimeError("Could not create LM Studio SDK client")
            model = client.llm.model(clean_model_name)
            identifier = getattr(model, "identifier", None) or clean_model_name
            logger(f"✓ [LM Studio] Model ready via SDK: {identifier}")
            return True
        except Exception as exc:
            if not allow_local_cli_fallback:
                logger(
                    f"[LM Studio] SDK reload failed for remote target {target}: {exc}. "
                    "local lms CLI fallback disabled."
                )
                return False
            logger(f"⚠️ [LM Studio] SDK reload failed, falling back to CLI: {exc}")
    if not allow_local_cli_fallback:
        logger(f"[LM Studio] Remote target {target}; SDK unavailable or failed; local lms CLI fallback disabled.")
        return False
    ok, output = run_lms_cli(["load", clean_model_name, "--yes"], timeout=600)
    if ok:
        logger(f"✓ [LM Studio] Model ready: {clean_model_name}")
        return True
    logger(f"⚠️ [LM Studio] Could not reload '{clean_model_name}': {output}")
    return False
