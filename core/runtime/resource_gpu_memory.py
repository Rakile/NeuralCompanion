"""Read-only per-process GPU memory probing for the Resources extension.

The probe is intentionally observational: it does not import torch, create a GPU
context, write settings, or install dependencies.  Windows prefers the PDH
``GPU Process Memory`` counters and falls back to a bounded, hidden
``nvidia-smi`` query.  Both sources report process/driver accounting rather than
the exact bytes owned by one model.
"""
from __future__ import annotations

import csv
import ctypes
import math
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping

__all__ = [
    "SOURCE_NVIDIA_SMI",
    "SOURCE_WINDOWS_PDH",
    "parse_nvidia_smi_compute_apps",
    "parse_pdh_instance_name",
    "parse_pdh_process_memory",
    "read_process_gpu_memory",
]

SOURCE_WINDOWS_PDH = (
    "Windows process GPU counters (OS-reported, not exact per-model bytes)"
)
SOURCE_NVIDIA_SMI = (
    "nvidia-smi compute-apps (driver-reported, not exact per-model bytes)"
)

_PDH_COUNTER_PATH = r"\GPU Process Memory(*)\Dedicated Usage"
_PDH_FMT_LARGE = 0x00000400
_PDH_MORE_DATA = 0x800007D2
_PDH_INVALID_ARGUMENT = 0xC0000BBD
_PDH_INSUFFICIENT_BUFFER = 0xC0000BC2
_PDH_CSTATUS_VALID_DATA = 0x00000000
_PDH_CSTATUS_NEW_DATA = 0x00000001
_PDH_MAX_BUFFER_BYTES = 4 * 1024 * 1024
_PDH_BUFFER_ATTEMPTS = 3
_PDH_SAMPLE_ATTEMPTS = 2

_NVIDIA_TIMEOUT_SECONDS = 3
_MIB = 1024 * 1024
_NVIDIA_NA_VALUES = {"", "n/a", "na", "none", "not available"}

_PDH_PID_PATTERN = re.compile(r"(?:^|_)pid_(\d+)(?=_|$)", re.IGNORECASE)
_PDH_ADAPTER_PATTERN = re.compile(
    r"(?:^|_)luid_(0x[0-9a-f]+_0x[0-9a-f]+)_phys_(\d+)", re.IGNORECASE
)
_PDH_LUID_PATTERN = re.compile(
    r"(?:^|_)luid_(0x[0-9a-f]+_0x[0-9a-f]+)", re.IGNORECASE
)


class _PdhFmtCounterValueUnion(ctypes.Union):
    _fields_ = [
        ("longValue", ctypes.c_long),
        ("doubleValue", ctypes.c_double),
        ("largeValue", ctypes.c_longlong),
        ("wideStringValue", ctypes.c_wchar_p),
    ]


class _PdhFmtCounterValue(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("CStatus", ctypes.c_ulong),
        ("value", _PdhFmtCounterValueUnion),
    ]


class _PdhFmtCounterValueItemW(ctypes.Structure):
    _fields_ = [
        ("szName", ctypes.c_wchar_p),
        ("FmtValue", _PdhFmtCounterValue),
    ]


def _nonnegative_int(value: object) -> int | None:
    """Return a nonnegative integer, rejecting booleans and non-finite floats."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if not math.isfinite(value) or value < 0:
            return None
        return int(value)
    return None


def parse_pdh_instance_name(instance_name: object) -> tuple[int, str] | None:
    """Return ``(pid, adapter_key)`` from a GPU-process counter instance name.

    PDH instance names look like
    ``pid_1234_luid_0x00000000_0x0000abcd_phys_0_eng_0_engtype_3D``.  The adapter
    key excludes the engine fields because one process commonly has several
    engine instances that repeat the same dedicated allocation.
    """

    if not isinstance(instance_name, str):
        return None
    pid_match = _PDH_PID_PATTERN.search(instance_name)
    if pid_match is None:
        return None
    try:
        pid = int(pid_match.group(1))
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    adapter_match = _PDH_ADAPTER_PATTERN.search(instance_name)
    if adapter_match is None:
        luid_match = _PDH_LUID_PATTERN.search(instance_name)
        if luid_match is None:
            return pid, ""
        return pid, luid_match.group(1).lower()
    return pid, adapter_match.group(1).lower() + "/" + adapter_match.group(2)


def parse_pdh_process_memory(
    entries: Iterable[tuple[str, object]],
) -> dict[int, int]:
    """Convert PDH ``(instance_name, dedicated_bytes)`` rows to per-PID bytes.

    Engine instances for the same process and adapter are deduplicated by keeping
    the largest reported value.  Distinct adapters for one PID are then summed.
    Invalid names and invalid values are ignored; a valid zero is retained.
    """

    per_process: dict[int, dict[str, int]] = {}
    for entry in entries:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            continue
        identity = parse_pdh_instance_name(entry[0])
        if identity is None:
            continue
        amount = _nonnegative_int(entry[1])
        if amount is None:
            continue
        pid, adapter = identity
        adapters = per_process.setdefault(pid, {})
        previous = adapters.get(adapter)
        if previous is None or amount > previous:
            adapters[adapter] = amount
    return {pid: sum(adapters.values()) for pid, adapters in per_process.items()}


def _nvidia_field(value: str) -> str:
    return value.strip().strip("[]").strip()


def parse_nvidia_smi_compute_apps(output: object) -> dict[int, int]:
    """Parse ``nvidia-smi --query-compute-apps`` CSV output into per-PID bytes.

    Rows are ``gpu_uuid, pid, used_gpu_memory`` in MiB (``nounits``).  N/A and
    malformed rows are ignored.  A repeated GPU UUID/PID pair is counted once,
    while distinct GPUs for the same PID are summed.  A reported zero is a real
    measurement and is preserved.
    """

    per_process: dict[int, dict[str, int]] = {}
    text = "" if output is None else str(output)
    for row in csv.reader(text.splitlines()):
        if len(row) != 3:
            continue
        gpu, pid_text, used_text = (_nvidia_field(cell) for cell in row)
        if (
            gpu.casefold() in _NVIDIA_NA_VALUES
            or pid_text.casefold() in _NVIDIA_NA_VALUES
            or used_text.casefold() in _NVIDIA_NA_VALUES
        ):
            continue
        try:
            pid = int(pid_text)
            used_mib = float(used_text)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or not math.isfinite(used_mib) or used_mib < 0:
            continue
        used_bytes = int(used_mib * _MIB)
        if used_bytes < 0:
            continue
        gpu_key = gpu.casefold()
        gpus = per_process.setdefault(pid, {})
        previous = gpus.get(gpu_key)
        if previous is None or used_bytes > previous:
            gpus[gpu_key] = used_bytes
    return {pid: sum(gpus.values()) for pid, gpus in per_process.items()}


def _load_pdh() -> object | None:
    """Load the PDH DLL lazily and declare 64-bit-safe native signatures."""

    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        return None
    try:
        pdh = win_dll("pdh")
        pdh.PdhOpenQueryW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        pdh.PdhOpenQueryW.restype = ctypes.c_ulong
        pdh.PdhAddEnglishCounterW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        pdh.PdhAddEnglishCounterW.restype = ctypes.c_ulong
        pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        pdh.PdhCollectQueryData.restype = ctypes.c_ulong
        pdh.PdhGetFormattedCounterArrayW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(_PdhFmtCounterValueItemW),
        ]
        pdh.PdhGetFormattedCounterArrayW.restype = ctypes.c_ulong
        pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        pdh.PdhCloseQuery.restype = ctypes.c_ulong
    except (AttributeError, OSError):
        return None
    return pdh


def _pdh_entries(
    items: ctypes.POINTER(_PdhFmtCounterValueItemW),
    item_count: int,
    buffer_size: int,
) -> list[tuple[str, int]]:
    """Copy valid formatted items out of a caller-owned PDH buffer."""

    if not items:
        return []
    capacity = max(0, int(buffer_size)) // ctypes.sizeof(_PdhFmtCounterValueItemW)
    entries: list[tuple[str, int]] = []
    for index in range(min(int(item_count), capacity)):
        item = items[index]
        if not item.szName:
            continue
        status = int(item.FmtValue.CStatus)
        if status not in (_PDH_CSTATUS_VALID_DATA, _PDH_CSTATUS_NEW_DATA):
            continue
        entries.append((item.szName, int(item.FmtValue.largeValue)))
    return entries


def _query_pdh_entries(pdh: object, counter: ctypes.c_void_p) -> list[tuple[str, int]] | None:
    """Read a wildcard counter array with a bounded, growing caller buffer."""

    size = ctypes.c_ulong(0)
    count = ctypes.c_ulong(0)
    items = ctypes.POINTER(_PdhFmtCounterValueItemW)()
    capacity = 0
    for _ in range(_PDH_BUFFER_ATTEMPTS):
        status = int(
            pdh.PdhGetFormattedCounterArrayW(
                counter,
                _PDH_FMT_LARGE,
                ctypes.byref(size),
                ctypes.byref(count),
                items,
            )
        )
        if status == 0:
            return _pdh_entries(items, count.value, capacity or int(size.value))
        if status not in (
            _PDH_MORE_DATA,
            _PDH_INVALID_ARGUMENT,
            _PDH_INSUFFICIENT_BUFFER,
        ):
            return None
        required = int(size.value)
        # PDH advises against trusting the returned size when a non-empty buffer
        # was too small, so grow that buffer geometrically as well.
        next_size = required if capacity == 0 else max(required, capacity * 2)
        if next_size <= capacity or next_size > _PDH_MAX_BUFFER_BYTES:
            return None
        buffer = ctypes.create_string_buffer(next_size)
        items = ctypes.cast(buffer, ctypes.POINTER(_PdhFmtCounterValueItemW))
        capacity = next_size
        size = ctypes.c_ulong(next_size)
    return None


def _read_windows_pdh_process_memory() -> dict[int, int] | None:
    """Read Windows process GPU counters, or ``None`` when PDH is unavailable."""

    pdh = _load_pdh()
    if pdh is None:
        return None
    query = ctypes.c_void_p()
    counter = ctypes.c_void_p()
    opened = False
    try:
        if int(pdh.PdhOpenQueryW(None, 0, ctypes.byref(query))) != 0:
            return None
        opened = True
        status = int(
            pdh.PdhAddEnglishCounterW(
                query, _PDH_COUNTER_PATH, 0, ctypes.byref(counter)
            )
        )
        if status != 0:
            return None
        entries: list[tuple[str, int]] | None = None
        # Collect immediately, with no sleep.  A second immediate sample covers
        # counters that need a second collection; Dedicated Usage is a raw count.
        for _ in range(_PDH_SAMPLE_ATTEMPTS):
            if int(pdh.PdhCollectQueryData(query)) != 0:
                return None
            entries = _query_pdh_entries(pdh, counter)
            if entries:
                break
        if entries is None:
            return None
        return parse_pdh_process_memory(entries)
    except Exception:
        # A broken or unsupported performance-counter stack must not break the
        # Resources snapshot; the caller can use the nvidia-smi fallback.
        return None
    finally:
        if opened:
            try:
                pdh.PdhCloseQuery(query)
            except Exception:
                pass


def _hidden_window_options() -> dict[str, object]:
    """Return subprocess options that keep a console tool hidden on Windows."""

    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _read_nvidia_smi_process_memory() -> dict[int, int] | None:
    """Run the bounded nvidia-smi compute-process query, or return ``None``."""

    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    options: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": _NVIDIA_TIMEOUT_SECONDS,
        "check": False,
    }
    options.update(_hidden_window_options())
    try:
        result = subprocess.run(
            [
                executable,
                "--query-compute-apps=gpu_uuid,pid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            **options,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_nvidia_smi_compute_apps(result.stdout)


def _safe_probe(
    reader: Callable[[], Mapping[int, int] | None],
) -> Mapping[int, int] | None:
    try:
        value = reader()
    except Exception:
        return None
    return value if isinstance(value, Mapping) else None


def _format_result(
    values: Mapping[object, object], source: str
) -> dict[int, dict[str, object]]:
    result: dict[int, dict[str, object]] = {}
    for pid, raw_bytes in values.items():
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            continue
        amount = _nonnegative_int(raw_bytes)
        if amount is None:
            continue
        result[pid] = {"vramBytes": amount, "source": source}
    return result


def read_process_gpu_memory(
    *,
    os_name: str | None = None,
    pdh_reader: Callable[[], Mapping[int, int] | None] | None = None,
    nvidia_reader: Callable[[], Mapping[int, int] | None] | None = None,
) -> dict[int, dict[str, object]]:
    """Return ``pid -> {'vramBytes': int, 'source': str}`` for GPU processes.

    PDH is preferred on Windows.  When it is unavailable or reports no instances,
    the bounded nvidia-smi query is used instead.  Readers are injectable so
    callers and tests can supply already-collected values without touching a
    live GPU; the zero-argument form uses the platform probes.
    """

    platform_name = os.name if os_name is None else os_name
    if platform_name == "nt":
        read_pdh = pdh_reader or _read_windows_pdh_process_memory
        pdh_values = _safe_probe(read_pdh)
        if pdh_values:
            return _format_result(pdh_values, SOURCE_WINDOWS_PDH)

    read_nvidia = nvidia_reader or _read_nvidia_smi_process_memory
    nvidia_values = _safe_probe(read_nvidia)
    if not nvidia_values:
        return {}
    return _format_result(nvidia_values, SOURCE_NVIDIA_SMI)
