"""Bounded memory probes. Never import torch or initialize a GPU context."""
from __future__ import annotations

import csv
import ctypes
import os
import shutil
import subprocess
import sys
import gc


def parse_gpu_memory(output):
    gpus = []
    for row in csv.reader(str(output).splitlines()):
        try:
            index, name, total, used = [v.strip() for v in row]
            total, used = int(float(total) * 1024**2), int(float(used) * 1024**2)
            if total <= 0 or not 0 <= used <= total:
                continue
            gpus.append({'index': int(index), 'name': name, 'totalBytes': total, 'usedBytes': used})
        except (ValueError, TypeError):
            continue
    return gpus


def _windows_ram():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in ('total', 'available', 'totalPage', 'availablePage',
                                                   'totalVirtual', 'availableVirtual', 'extended')]
    status = MemoryStatus(); status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {}
    return {'totalBytes': status.total, 'usedBytes': status.total-status.available, 'ncBytes': None}


def read_memory():
    ram, gpus, notes = {}, [], []
    try:
        import psutil
        memory = psutil.virtual_memory()
        process = psutil.Process()
        resident = process.memory_info().rss
        for child in process.children(recursive=True):
            try:
                resident += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        ram = {'totalBytes': int(memory.total), 'usedBytes': int(memory.total-memory.available),
               'ncBytes': int(resident)}
    except ImportError:
        if os.name == 'nt':
            ram = _windows_ram()
    except Exception as exc:
        notes.append('System RAM: ' + str(exc))
    executable = shutil.which('nvidia-smi')
    if executable:
        try:
            result = subprocess.run([executable, '--query-gpu=index,name,memory.total,memory.used',
                                     '--format=csv,noheader,nounits'], capture_output=True, text=True,
                                    timeout=3, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode == 0:
                gpus = parse_gpu_memory(result.stdout)
            else:
                notes.append('GPU memory inspection unavailable.')
        except (OSError, subprocess.TimeoutExpired):
            notes.append('GPU memory inspection unavailable.')
    if not gpus:
        notes.append('GPU memory readings require an available NVIDIA driver probe.')
    return {'ram': ram, 'gpus': gpus, 'notes': notes}


def release_unused_memory():
    """Collect released model cycles without creating a CUDA context."""
    gc.collect()
    torch = sys.modules.get('torch')
    cuda = getattr(torch, 'cuda', None)
    if cuda is not None and cuda.is_initialized():
        cuda.empty_cache()
