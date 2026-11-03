"""Read-only Windows process identity checks; no optional Python dependency."""
import ctypes
from ctypes import wintypes
import os


def vseeface_processes() -> list[dict]:
    if os.name != 'nt':
        raise ValueError('The VSeeFace bridge installer currently supports Windows x64.')

    class Entry(ctypes.Structure):
        _fields_ = [('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),
                    ('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),
                    ('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
                    ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),
                    ('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
    k = ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    for name in ('Process32FirstW','Process32NextW'):
        getattr(k,name).argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
        getattr(k,name).restype=wintypes.BOOL
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    k.QueryFullProcessImageNameW.restype=wintypes.BOOL
    k.CloseHandle.argtypes=[wintypes.HANDLE];k.CloseHandle.restype=wintypes.BOOL
    snapshot=k.CreateToolhelp32Snapshot(2,0)
    if snapshot == ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    found=[]
    try:
        entry=Entry();entry.dwSize=ctypes.sizeof(entry)
        more=k.Process32FirstW(snapshot,ctypes.byref(entry))
        while more:
            if entry.szExeFile.casefold()=='vseeface.exe':
                handle=k.OpenProcess(0x1000,False,entry.th32ProcessID)
                if not handle:raise OSError('Cannot verify a running VSeeFace process; close it before setup.')
                try:
                    size=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
                    if not k.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    found.append({'pid':int(entry.th32ProcessID),'path':buffer.value})
                finally:k.CloseHandle(handle)
            more=k.Process32NextW(snapshot,ctypes.byref(entry))
        return found
    finally:k.CloseHandle(snapshot)
