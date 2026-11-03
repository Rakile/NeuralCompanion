"""Read-only shared process telemetry, independent of model loading or cleanup.

RSS/working sets include runtime overhead and may contain shared pages. GPU
figures are OS/driver accounting. Neither is an exact allocation for a model.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from .resources import _bytes


_BACKENDS = {
    'lmstudio': {'lm studio.exe', 'lm studio', 'llmster.exe', 'llmster'},
    'ollama': {'ollama.exe', 'ollama', 'ollama app.exe', 'ollama app'},
}


def _local_port(endpoint):
    try:
        url = urlsplit(str(endpoint))
        host = (url.hostname or '').casefold()
        local = host == 'localhost'
        if not local:
            local = ipaddress.ip_address(host).is_loopback
        if local and url.scheme in ('http', 'https'):
            return url.port or (443 if url.scheme == 'https' else 80)
    except (ValueError, TypeError):
        pass
    return None


def _pid(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _server_group(row, connections, process_factory):
    port = _local_port(row.get('processEndpoint'))
    names = _BACKENDS.get(row.get('processBackend'), ())
    if port is None or not names:
        return None
    candidates = {c.pid for c in connections
                  if c.status == 'LISTEN' and c.laddr.port == port and _pid(c.pid)}
    # An ambiguous listener cannot establish model/process ownership.
    if len(candidates) != 1:
        return None
    root = process_factory(candidates.pop())
    if root.name().casefold() not in names:
        return None
    for _ in range(6):
        parent = root.parent()
        if parent is None or parent.name().casefold() not in names:
            break
        root = parent
    members = {p.pid: p for p in [root, *root.children(recursive=True)]}
    return root.pid, members


def read_resource_process_memory(rows, *, process_factory=None, connection_reader=None,
                                 gpu_reader=None):
    """Return resource-id -> explicitly shared process measurements.

    Explicit worker PIDs are measured individually unless the source opts in
    to including child processes. Local LM Studio/Ollama
    endpoints are tied to their listening process and its backend process tree;
    remote endpoints are never attributed to this computer. Unique groups are
    sampled once, then referenced by all their resident resources.
    """
    rows = tuple(rows)
    candidates = [r for r in rows if _pid(r.get('processId')) or _local_port(r.get('processEndpoint'))]
    if not candidates:
        return {}
    if process_factory is None or connection_reader is None:
        try:
            import psutil
        except ImportError:
            return {}
        process_factory = process_factory or psutil.Process
        connection_reader = connection_reader or (lambda: psutil.net_connections(kind='tcp'))
    if gpu_reader is None:
        from .resource_gpu_memory import read_process_gpu_memory
        gpu_reader = read_process_gpu_memory
    try:
        gpu = gpu_reader()
    except Exception:
        gpu = {}
    connections = ()
    if any(not _pid(r.get('processId')) for r in candidates):
        try:
            connections = tuple(connection_reader())
        except Exception:
            pass
    groups, endpoints, result = {}, {}, {}
    for row in candidates:
        try:
            pid = _pid(row.get('processId'))
            if pid:
                include_children = row.get('processIncludeChildren') is True
                key = ('pid-tree:' if include_children else 'pid:') + str(pid)
                members = None
                if key not in groups:
                    process = process_factory(pid)
                    # A Windows venv launcher can own the worker handle while
                    # its interpreter child owns all CUDA allocations.
                    children = process.children(recursive=True) if include_children else []
                    members = {p.pid: p for p in [process, *children]}
            else:
                endpoint = (row.get('processBackend'), row.get('processEndpoint'))
                if endpoint not in endpoints:
                    endpoints[endpoint] = _server_group(row, connections, process_factory)
                group = endpoints[endpoint]
                if group is None:
                    continue
                root_pid, members = group
                key = str(row.get('processBackend')) + ':' + str(root_pid)
            if key not in groups:
                ram, ram_complete = 0, True
                for process in members.values():
                    try:
                        amount = _bytes(process.memory_info().rss)
                        if amount is None:
                            ram_complete = False
                        else:
                            ram += amount
                    except Exception:
                        ram_complete = False
                readings = [gpu.get(p, {}) for p in members]
                vram = [_bytes(g.get('vramBytes')) for g in readings]
                known_vram = [v for v in vram if v is not None]
                sources = list(dict.fromkeys(str(g.get('source')) for g in readings
                                            if g.get('source') and _bytes(g.get('vramBytes')) is not None))
                groups[key] = {
                    'sharedRamBytes': ram if ram_complete else None,
                    'sharedVramBytes': sum(known_vram) if known_vram else None,
                    'memoryGroupId': key, 'memoryProcessIds': sorted(members),
                    'memoryProcessLabel': str(row.get('processLabel') or 'Worker process'),
                    'processMemorySource': '; '.join(['Process RAM working set (RSS)', *sources]),
                    'sharedMemoryNote': 'Shared process usage includes runtime overhead and other resources. '
                                        'Rows with the same process group repeat the same total; do not add them together. '
                                        'GPU usage includes only processes with available OS/driver readings.',
                }
            result[row['id']] = dict(groups[key])
        except Exception:
            # Process exit/access denial cannot change residency or cleanup safety.
            continue
    return result
