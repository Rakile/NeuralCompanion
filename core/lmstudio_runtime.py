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


def unload_models(*, base_url: str, logger=print) -> bool:
    logger("🧠 [LM Studio] Unloading loaded models before MuseTalk warmup...")
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
            logger(f"⚠️ [LM Studio] SDK unload failed, falling back to CLI: {exc}")
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
            logger(f"⚠️ [LM Studio] SDK reload failed, falling back to CLI: {exc}")
    ok, output = run_lms_cli(["load", clean_model_name, "--yes"], timeout=600)
    if ok:
        logger(f"✓ [LM Studio] Model ready: {clean_model_name}")
        return True
    logger(f"⚠️ [LM Studio] Could not reload '{clean_model_name}': {output}")
    return False
