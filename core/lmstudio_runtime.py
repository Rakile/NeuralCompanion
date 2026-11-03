"""LM Studio model lifecycle helpers.

Provider-specific model load/unload behavior lives here so the engine can stay
focused on orchestration instead of embedding LM Studio mechanics directly.
"""

from __future__ import annotations

import importlib
import contextlib
import csv
import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_DEFAULT_TTL = object()
_LAST_PRIORITY_LOG_AT = 0.0
_PRIORITY_LOG_INTERVAL_SECONDS = 30.0

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_SET_INFORMATION = 0x0200
_NORMAL_PRIORITY_CLASS = 0x00000020
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
_ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
_LMSTUDIO_PROCESS_MARKERS = (
    "lm studio",
    "lmstudio",
    "lm-studio",
    "lms.exe",
    "llama-server",
)


def _hidden_subprocess_options() -> dict[str, object]:
    """Keep helper commands owned by the GUI from flashing console windows."""

    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }

MAIN_CHAT_LOAD_CONFIG: Mapping[str, object] = {
    "gpu": {"ratio": 1.0},
    "offloadKVCacheToGpu": True,
    "contextLength": 8192,
    "evalBatchSize": 512,
    "flashAttention": True,
    "keepModelInMemory": True,
    "tryMmap": True,
}
VISION_LOAD_CONFIG: Mapping[str, object] = {
    "gpu": {"ratio": 1.0},
    "offloadKVCacheToGpu": True,
    "contextLength": 6400,
    "evalBatchSize": 256,
    "flashAttention": True,
    "keepModelInMemory": True,
    "tryMmap": True,
}
DEFAULT_PARALLEL_PREDICTIONS = 1
MAIN_CHAT_CONTEXT_RANGE = (8192, 12288)
VISION_CONTEXT_RANGE = (4096, 8192)
MAIN_CHAT_CONTEXT_LIMITS = (512, 1048576)


def configured_chat_context_length(value: object) -> int | None:
    """Resolve a saved model-load setting; older sessions retain the default."""
    if isinstance(value, bool):
        return None
    try:
        length = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    minimum, maximum = MAIN_CHAT_CONTEXT_LIMITS
    return length if minimum <= length <= maximum else None


def model_key_matches(requested_model: object, loaded_key: object) -> bool:
    requested = str(requested_model or '').strip().casefold()
    loaded = str(loaded_key or '').strip().casefold()
    return bool(requested and loaded and (loaded == requested or loaded.startswith(requested + '@')))


def main_chat_load_config(context_length: int | None = None) -> dict[str, object]:
    config = dict(MAIN_CHAT_LOAD_CONFIG)
    length = configured_chat_context_length(context_length)
    if length is not None:
        config["contextLength"] = length
    return config


@dataclass(frozen=True, slots=True)
class LoadedModelInstance:
    identifier: str
    model_key: str
    context_length: int | None = None
    eval_batch_size: int | None = None
    parallel: int | None = None
    flash_attention: bool | None = None
    offload_kv_cache_to_gpu: bool | None = None


@dataclass(slots=True)
class _ModelLoadFlight:
    key: tuple[str, str]
    done: threading.Event = field(default_factory=threading.Event)
    result: bool = False


_MODEL_LOAD_CONDITION = threading.Condition()
_MODEL_LOAD_ACTIVE: _ModelLoadFlight | None = None


def _loaded_model_instances_from_payload(
    payload: object,
) -> tuple[LoadedModelInstance, ...]:
    if not isinstance(payload, list):
        return ()
    instances = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        identifier = str(item.get("identifier") or "").strip()
        model_key = str(
            item.get("modelKey")
            or item.get("model_key")
            or item.get("path")
            or item.get("model")
            or item.get("loadedModelKey")
            or ""
        ).strip()
        if identifier and model_key:
            instances.append(
                LoadedModelInstance(
                    identifier,
                    model_key,
                    context_length=_optional_positive_int(
                        item.get("contextLength") or item.get("context_length")
                    ),
                    eval_batch_size=_optional_positive_int(
                        item.get("evalBatchSize") or item.get("eval_batch_size")
                    ),
                    parallel=_optional_positive_int(item.get("parallel")),
                    flash_attention=_optional_bool(
                        item.get("flashAttention")
                        if "flashAttention" in item
                        else item.get("flash_attention")
                    ),
                    offload_kv_cache_to_gpu=_optional_bool(
                        item.get("offloadKVCacheToGpu")
                        if "offloadKVCacheToGpu" in item
                        else item.get("offload_kv_cache_to_gpu")
                    ),
                )
            )
    return tuple(instances)


def _loaded_model_instances_from_native_payload(
    payload: object,
) -> tuple[LoadedModelInstance, ...]:
    if not isinstance(payload, Mapping):
        return ()
    models = payload.get("models")
    if not isinstance(models, list):
        return ()
    instances: list[LoadedModelInstance] = []
    for model in models:
        if not isinstance(model, Mapping):
            continue
        model_key = str(model.get("key") or "").strip()
        loaded = model.get("loaded_instances")
        if not model_key or not isinstance(loaded, list):
            continue
        for item in loaded:
            if not isinstance(item, Mapping):
                continue
            identifier = str(item.get("id") or "").strip()
            config = item.get("config")
            config = config if isinstance(config, Mapping) else {}
            if not identifier:
                continue
            instances.append(
                LoadedModelInstance(
                    identifier,
                    model_key,
                    context_length=_optional_positive_int(
                        config.get("context_length")
                    ),
                    eval_batch_size=_optional_positive_int(
                        config.get("eval_batch_size")
                    ),
                    parallel=_optional_positive_int(config.get("parallel")),
                    flash_attention=_optional_bool(
                        config.get("flash_attention")
                    ),
                    offload_kv_cache_to_gpu=_optional_bool(
                        config.get("offload_kv_cache_to_gpu")
                    ),
                )
            )
    return tuple(instances)


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def loaded_model_matches_profile(
    instance: LoadedModelInstance,
    *,
    load_config: Mapping[str, object],
    context_range: tuple[int, int],
    parallel_predictions: int,
) -> bool:
    """Reject load settings NC can safely correct without a reload loop."""

    minimum_context, maximum_context = context_range
    if (
        instance.context_length is not None
        and not minimum_context <= instance.context_length <= maximum_context
    ):
        return False
    if (
        instance.parallel is not None
        and instance.parallel != int(parallel_predictions)
    ):
        return False
    configured_batch = load_config.get("evalBatchSize")
    if (
        isinstance(configured_batch, int)
        and configured_batch > 0
        and instance.eval_batch_size is not None
        and instance.eval_batch_size != configured_batch
    ):
        return False
    configured_flash = load_config.get("flashAttention")
    if (
        isinstance(configured_flash, bool)
        and instance.flash_attention is not None
        and instance.flash_attention is not configured_flash
    ):
        return False
    configured_kv_offload = load_config.get("offloadKVCacheToGpu")
    if (
        isinstance(configured_kv_offload, bool)
        and instance.offload_kv_cache_to_gpu is not None
        and instance.offload_kv_cache_to_gpu is not configured_kv_offload
    ):
        return False
    return True


def _loaded_model_instances_from_handles(
    handles: object,
) -> tuple[LoadedModelInstance, ...]:
    instances = []
    for handle in handles if isinstance(handles, (list, tuple)) else ():
        identifier = str(getattr(handle, "identifier", "") or "").strip()
        model_key = str(
            getattr(handle, "model_key", "")
            or getattr(handle, "modelKey", "")
            or getattr(handle, "path", "")
            or getattr(handle, "loaded_model_key", "")
            or ""
        ).strip()
        if not model_key:
            get_info = getattr(handle, "get_info", None)
            if callable(get_info):
                try:
                    info = get_info()
                except Exception:
                    info = None
                if isinstance(info, Mapping):
                    model_key = str(
                        info.get("modelKey")
                        or info.get("model_key")
                        or info.get("path")
                        or ""
                    ).strip()
                elif info is not None:
                    model_key = str(
                        getattr(info, "model_key", "")
                        or getattr(info, "modelKey", "")
                        or getattr(info, "path", "")
                        or ""
                    ).strip()
        context_length = None
        get_context_length = getattr(handle, "get_context_length", None)
        if callable(get_context_length):
            try:
                context_length = _optional_positive_int(get_context_length())
            except Exception:
                context_length = None
        load_config: object = None
        get_load_config = getattr(handle, "get_load_config", None)
        if callable(get_load_config):
            try:
                load_config = get_load_config()
            except Exception:
                load_config = None
        to_dict = getattr(load_config, "to_dict", None)
        if callable(to_dict):
            try:
                load_config = to_dict()
            except Exception:
                load_config = None
        load_config = load_config if isinstance(load_config, Mapping) else {}
        if identifier and model_key:
            instances.append(
                LoadedModelInstance(
                    identifier,
                    model_key,
                    context_length=context_length
                    or _optional_positive_int(load_config.get("contextLength")),
                    eval_batch_size=_optional_positive_int(
                        load_config.get("evalBatchSize")
                    ),
                    flash_attention=_optional_bool(
                        load_config.get("flashAttention")
                    ),
                    offload_kv_cache_to_gpu=_optional_bool(
                        load_config.get("offloadKVCacheToGpu")
                    ),
                )
            )
    return tuple(instances)


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


def _native_models_url(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    if not value:
        value = "http://127.0.0.1:1234"
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        value = f"http://{value}"
    if value.lower().endswith("/v1"):
        value = value[:-3]
    return f"{value.rstrip('/')}/api/v1/models"


def _native_load_model(
    model_name: str,
    base_url: str,
    *,
    load_config: Mapping[str, object],
    parallel_predictions: int,
    timeout: float = 600.0,
) -> None:
    """Load a local model with every NC-owned performance setting explicit."""

    body: dict[str, object] = {
        "model": str(model_name or "").strip(),
        "parallel": int(parallel_predictions),
        "echo_load_config": True,
    }
    field_map = {
        "contextLength": "context_length",
        "evalBatchSize": "eval_batch_size",
        "flashAttention": "flash_attention",
        "offloadKVCacheToGpu": "offload_kv_cache_to_gpu",
    }
    for source, target in field_map.items():
        value = load_config.get(source)
        if value is not None:
            body[target] = value
    request = Request(
        f"{_native_models_url(base_url)}/load",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer lm-studio",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    opener = build_opener(ProxyHandler({}))
    with opener.open(request, timeout=max(1.0, float(timeout))) as response:
        response.read()


def _native_loaded_model_instances(
    base_url: str,
    *,
    timeout: float = 3.0,
    strict: bool = False,
) -> tuple[LoadedModelInstance, ...]:
    request = Request(
        _native_models_url(base_url),
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer lm-studio",
        },
        method="GET",
    )
    # Model endpoints are explicitly configured by the user. Bypass ambient
    # HTTP proxies so loopback and LAN LM Studio targets stay local.
    opener = build_opener(ProxyHandler({}))
    with opener.open(request, timeout=max(0.25, float(timeout))) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    if strict and (not isinstance(payload, Mapping) or not isinstance(payload.get('models'), list)):
        raise RuntimeError('LM Studio returned an invalid resident-model inventory.')
    return _loaded_model_instances_from_native_payload(payload)


def inspect_loaded_model_instances(*, base_url: str, timeout: float = 3.0):
    """Strict, bounded, read-only resource probe; unavailable is never empty."""
    return _native_loaded_model_instances(base_url, timeout=timeout, strict=True)


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
            **_hidden_subprocess_options(),
        )
        output = "\n".join(
            part.strip() for part in [completed.stdout or "", completed.stderr or ""] if part and part.strip()
        ).strip()
        output = _clean_cli_output(output)
        return completed.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def list_loaded_model_instances(
    *,
    base_url: str,
    logger=print,
    allow_cli_fallback: bool | None = None,
    prefer_native_api: bool = False,
) -> tuple[LoadedModelInstance, ...]:
    """Return exact loaded identifiers without parsing human-readable CLI output."""
    target = sdk_host(base_url)
    allow_local_cli_fallback = (
        is_local_base_url(base_url)
        if allow_cli_fallback is None
        else bool(allow_cli_fallback)
    )
    if prefer_native_api:
        try:
            return _native_loaded_model_instances(base_url)
        except Exception as exc:
            logger(
                f"[LM Studio] Native loaded-model inspection failed for "
                f"{target}; using SDK fallback: {exc}"
            )
    sdk = get_sdk()
    if sdk is not None:
        try:
            client = sdk_client(sdk, base_url)
            if client is None:
                raise RuntimeError("Could not create LM Studio SDK client")
            handles = list(client.list_loaded_models())
            return _loaded_model_instances_from_handles(handles)
        except Exception as exc:
            if not allow_local_cli_fallback:
                logger(
                    f"[LM Studio] Loaded-model inspection failed for remote target "
                    f"{target}: {exc}. local lms CLI fallback disabled."
                )
                return ()
            logger(
                f"[LM Studio] SDK loaded-model inspection failed, falling back "
                f"to CLI: {exc}"
            )
    if not allow_local_cli_fallback:
        logger(
            f"[LM Studio] Remote target {target}; SDK unavailable or failed; "
            "local lms CLI fallback disabled."
        )
        return ()
    ok, output = run_lms_cli(["ps", "--json"], timeout=30)
    if not ok:
        logger(f"[LM Studio] Loaded-model inspection failed: {output}")
        return ()
    try:
        payload = json.loads(output)
    except (TypeError, ValueError) as exc:
        logger(f"[LM Studio] Loaded-model inspection returned invalid JSON: {exc}")
        return ()
    return _loaded_model_instances_from_payload(payload)


def unload_model(
    identifier: str,
    *,
    base_url: str,
    logger=print,
    allow_cli_fallback: bool | None = None,
) -> bool:
    """Unload one exact LM Studio instance; this function never unloads all."""
    clean_identifier = str(identifier or "").strip()
    if not clean_identifier:
        return False
    target = sdk_host(base_url)
    allow_local_cli_fallback = (
        is_local_base_url(base_url)
        if allow_cli_fallback is None
        else bool(allow_cli_fallback)
    )
    sdk = get_sdk()
    if sdk is not None:
        try:
            client = sdk_client(sdk, base_url)
            if client is None:
                raise RuntimeError("Could not create LM Studio SDK client")
            for handle in list(client.list_loaded_models()):
                loaded_identifier = str(
                    getattr(handle, "identifier", "") or ""
                ).strip()
                if loaded_identifier == clean_identifier:
                    handle.unload()
                    logger(
                        f"[LM Studio] Unloaded exact model instance via SDK: "
                        f"{clean_identifier}"
                    )
                    return True
            if not allow_local_cli_fallback:
                logger(
                    f"[LM Studio] Exact model instance not found on remote target "
                    f"{target}: {clean_identifier}"
                )
                return False
        except Exception as exc:
            if not allow_local_cli_fallback:
                logger(
                    f"[LM Studio] Exact unload failed for remote target {target}: "
                    f"{exc}. local lms CLI fallback disabled."
                )
                return False
            logger(f"[LM Studio] SDK exact unload failed, falling back to CLI: {exc}")
    if not allow_local_cli_fallback:
        logger(
            f"[LM Studio] Remote target {target}; SDK unavailable or failed; "
            "local lms CLI fallback disabled."
        )
        return False
    ok, output = run_lms_cli(["unload", clean_identifier], timeout=180)
    if ok:
        logger(f"[LM Studio] Unloaded exact model instance: {clean_identifier}")
        return True
    logger(
        f"[LM Studio] Could not unload exact model instance "
        f"'{clean_identifier}': {output}"
    )
    return False


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
            **_hidden_subprocess_options(),
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
def local_inference_responsiveness_guard(
    logger=print,
    *,
    watch_new_processes: bool = False,
):
    """Give NC's Qt overlay scheduling room during local LM Studio work."""
    if os.name != "nt":
        yield
        return
    originals: dict[int, int] = {}
    changed_names: list[str] = []
    changes_lock = threading.Lock()
    watcher_stop = threading.Event()
    current_pid = os.getpid()
    current_priority = _get_priority_class(current_pid)
    if current_priority in {_NORMAL_PRIORITY_CLASS, _BELOW_NORMAL_PRIORITY_CLASS}:
        if _set_priority_class(current_pid, _ABOVE_NORMAL_PRIORITY_CLASS):
            originals[current_pid] = current_priority

    def lower_matching_processes() -> None:
        newly_changed: list[str] = []
        with changes_lock:
            for pid, name in _lmstudio_processes():
                if pid in originals:
                    continue
                priority = _get_priority_class(pid)
                if not priority or priority == _BELOW_NORMAL_PRIORITY_CLASS:
                    continue
                if _set_priority_class(pid, _BELOW_NORMAL_PRIORITY_CLASS):
                    originals[pid] = priority
                    changed_names.append(name)
                    newly_changed.append(name)
        global _LAST_PRIORITY_LOG_AT
        if newly_changed:
            now = time.monotonic()
            if now - _LAST_PRIORITY_LOG_AT >= _PRIORITY_LOG_INTERVAL_SECONDS:
                _LAST_PRIORITY_LOG_AT = now
                try:
                    logger(
                        "🫧 [LM Studio] Lowered local inference priority for UI "
                        f"responsiveness: {', '.join(sorted(set(newly_changed)))}"
                    )
                except Exception:
                    pass

    lower_matching_processes()
    watcher: threading.Thread | None = None
    if watch_new_processes:
        def watch_processes() -> None:
            while not watcher_stop.wait(0.25):
                lower_matching_processes()

        watcher = threading.Thread(
            target=watch_processes,
            name="lmstudio-load-priority-guard",
            daemon=True,
        )
        watcher.start()
    try:
        yield
    finally:
        watcher_stop.set()
        if watcher is not None:
            watcher.join(timeout=1.0)
        with changes_lock:
            restore = list(originals.items())
        for pid, priority in restore:
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


def unload_models(
    *,
    base_url: str,
    logger=print,
    reason: str = "MuseTalk warmup",
    allow_cli_fallback: bool | None = None,
) -> bool:
    target = sdk_host(base_url)
    allow_local_cli_fallback = (
        is_local_base_url(base_url)
        if allow_cli_fallback is None
        else bool(allow_cli_fallback)
    )
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


def load_model(
    model_name: str,
    *,
    base_url: str,
    is_placeholder=None,
    logger=print,
    allow_cli_fallback: bool | None = None,
    ttl_seconds: object = _DEFAULT_TTL,
    preserve_existing_models: bool = False,
    load_config: Mapping[str, object] | None = None,
    parallel_predictions: int | None = None,
) -> bool:
    """Load one LM Studio model while serializing and coalescing load requests."""

    clean_model_name = str(model_name or "").strip()
    if callable(is_placeholder) and is_placeholder(clean_model_name):
        return False
    if not clean_model_name:
        return False
    key = (sdk_host(base_url).casefold(), clean_model_name.casefold())
    global _MODEL_LOAD_ACTIVE
    with _MODEL_LOAD_CONDITION:
        while True:
            active = _MODEL_LOAD_ACTIVE
            if active is None:
                flight = _ModelLoadFlight(key)
                _MODEL_LOAD_ACTIVE = flight
                leader = True
                break
            if active.key == key:
                flight = active
                leader = False
                break
            _MODEL_LOAD_CONDITION.wait()
    if not leader:
        flight.done.wait()
        return bool(flight.result)

    result = False
    try:
        result = _load_model_once(
            clean_model_name,
            base_url=base_url,
            is_placeholder=is_placeholder,
            logger=logger,
            allow_cli_fallback=allow_cli_fallback,
            ttl_seconds=ttl_seconds,
            preserve_existing_models=preserve_existing_models,
            load_config=load_config,
            parallel_predictions=parallel_predictions,
        )
        return result
    finally:
        with _MODEL_LOAD_CONDITION:
            flight.result = bool(result)
            flight.done.set()
            if _MODEL_LOAD_ACTIVE is flight:
                _MODEL_LOAD_ACTIVE = None
            _MODEL_LOAD_CONDITION.notify_all()


def _load_model_once(
    model_name: str,
    *,
    base_url: str,
    is_placeholder=None,
    logger=print,
    allow_cli_fallback: bool | None = None,
    ttl_seconds: object = _DEFAULT_TTL,
    preserve_existing_models: bool = False,
    load_config: Mapping[str, object] | None = None,
    parallel_predictions: int | None = None,
) -> bool:
    clean_model_name = str(model_name or "").strip()
    if callable(is_placeholder) and is_placeholder(clean_model_name):
        return False
    target = sdk_host(base_url)
    allow_local_cli_fallback = (
        is_local_base_url(base_url)
        if allow_cli_fallback is None
        else bool(allow_cli_fallback)
    )
    logger(f"🧠 [LM Studio] Reloading selected model: {clean_model_name}")
    # LM Studio's native local endpoint accepts the complete per-instance load
    # profile. Prefer it to the CLI, whose flags cannot express evaluation
    # batch, Flash Attention, or GPU KV-cache ownership.
    prefer_local_cli = bool(
        allow_local_cli_fallback
        and isinstance(parallel_predictions, int)
        and parallel_predictions > 0
    )
    if prefer_local_cli and load_config:
        try:
            with local_inference_responsiveness_guard(
                logger,
                watch_new_processes=True,
            ):
                _native_load_model(
                    clean_model_name,
                    base_url,
                    load_config=load_config,
                    parallel_predictions=parallel_predictions,
                )
            logger(
                f"✓ [LM Studio] Model ready with explicit NC profile: "
                f"{clean_model_name}"
            )
            return True
        except Exception as exc:
            logger(
                f"⚠️ [LM Studio] Native profiled load failed, falling back "
                f"to CLI: {exc}"
            )
    sdk = get_sdk()
    if sdk is not None and not prefer_local_cli:
        try:
            client = sdk_client(sdk, base_url)
            if client is None:
                raise RuntimeError("Could not create LM Studio SDK client")
            load_kwargs = (
                {}
                if ttl_seconds is _DEFAULT_TTL
                else {"ttl": ttl_seconds}
            )
            if load_config:
                load_kwargs["config"] = dict(load_config)
            load_guard = (
                local_inference_responsiveness_guard(
                    logger,
                    watch_new_processes=True,
                )
                if allow_local_cli_fallback
                else contextlib.nullcontext()
            )
            if preserve_existing_models:
                load_new_instance = getattr(client.llm, "load_new_instance", None)
                if not callable(load_new_instance):
                    raise RuntimeError(
                        "The LM Studio SDK does not support parallel model instances."
                    )
                with load_guard:
                    model = load_new_instance(clean_model_name, **load_kwargs)
            else:
                with load_guard:
                    model = client.llm.model(clean_model_name, **load_kwargs)
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
    cli_args = ["load", clean_model_name, "--yes"]
    configured_context = (
        load_config.get("contextLength")
        if isinstance(load_config, Mapping)
        else None
    )
    if isinstance(configured_context, int) and configured_context > 0:
        cli_args.extend(["--context-length", str(configured_context)])
    if isinstance(parallel_predictions, int) and parallel_predictions > 0:
        cli_args.extend(["--parallel", str(parallel_predictions)])
    configured_gpu = (
        load_config.get("gpu")
        if isinstance(load_config, Mapping)
        else None
    )
    if (
        isinstance(configured_gpu, Mapping)
        and configured_gpu.get("ratio") == 1.0
    ):
        cli_args.extend(["--gpu", "max"])
    with local_inference_responsiveness_guard(
        logger,
        watch_new_processes=True,
    ):
        ok, output = run_lms_cli(cli_args, timeout=600)
    if ok:
        logger(f"✓ [LM Studio] Model ready: {clean_model_name}")
        return True
    logger(f"⚠️ [LM Studio] Could not reload '{clean_model_name}': {output}")
    return False
