"""Windows process handles for the exact worker and its launcher descendants."""
from __future__ import annotations
import ctypes
from ctypes import wintypes


class WindowsWorkerTree:
    def __init__(self, root_pid):
        self.root_pid = int(root_pid)
        self.handles = {}
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self.kernel
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.track(root_pid)

    def track(self, pid):
        pid = int(pid)
        if pid in self.handles:
            return
        handle = self.kernel.OpenProcess(0x100001, False, pid)  # synchronize + terminate
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # Already exited; no PID allocation to retain.
                return
            raise ctypes.WinError(error)
        self.handles[pid] = handle

    def capture(self):
        class Entry(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                ('pid', wintypes.DWORD), ('heap', ctypes.c_size_t),
                ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                ('parent', wintypes.DWORD), ('priority', wintypes.LONG),
                ('flags', wintypes.DWORD), ('exe', wintypes.WCHAR * 260)]
        k = self.kernel
        k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        snapshot = k.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        parents = {}
        try:
            entry = Entry(); entry.size = ctypes.sizeof(entry)
            more = k.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                parents[entry.pid] = entry.parent
                more = k.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            k.CloseHandle(snapshot)
        # Held process handles protect tracked PIDs from reuse. Discover only
        # descendants of those owned processes, including a launcher-exit race.
        owned = set(self.handles) | {self.root_pid}
        pending = True
        while pending:
            children = {pid for pid, parent in parents.items() if parent in owned and pid not in owned}
            pending = bool(children)
            for pid in children:
                self.track(pid)
            owned.update(children)

    def exited(self):
        for handle in self.handles.values():
            result = self.kernel.WaitForSingleObject(handle, 0)
            if result == 258:
                return False
            if result != 0:
                raise ctypes.WinError(ctypes.get_last_error())
        return True

    def terminate(self):
        self.capture()
        for pid, handle in reversed(tuple(self.handles.items())):
            if self.kernel.WaitForSingleObject(handle, 0) == 258:
                if not self.kernel.TerminateProcess(handle, 1):
                    error = ctypes.get_last_error()
                    if self.kernel.WaitForSingleObject(handle, 2000) != 0:
                        raise ctypes.WinError(error)
        self.capture()
        # Capture again after killing the launcher, covering a child created
        # between the first snapshot and launcher termination.
        for handle in self.handles.values():
            if self.kernel.WaitForSingleObject(handle, 0) == 258:
                if not self.kernel.TerminateProcess(handle, 1):
                    error = ctypes.get_last_error()
                    if self.kernel.WaitForSingleObject(handle, 2000) != 0:
                        raise ctypes.WinError(error)
        for handle in self.handles.values():
            if self.kernel.WaitForSingleObject(handle, 2000) != 0:
                raise OSError('An owned Chatterbox worker process has not exited.')

    def close(self):
        for handle in self.handles.values():
            self.kernel.CloseHandle(handle)
        self.handles.clear()
