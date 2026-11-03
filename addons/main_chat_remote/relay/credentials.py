"""Windows Credential Manager storage. Never falls back to plaintext."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class CredentialStore:
    def __init__(self, target: str):
        self.target = target

    @staticmethod
    def _api():
        if sys.platform != "win32":
            raise RuntimeError(
                "NC Relay secure storage currently requires Windows Credential Manager."
            )
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        return api

    def get(self) -> str | None:
        api = self._api()
        pointer = ctypes.POINTER(_Credential)()
        if not api.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise RuntimeError("Could not read NC Relay secure credentials.")
        try:
            return ctypes.string_at(
                pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize
            ).decode("utf-16-le")
        finally:
            api.CredFree(pointer)

    def set(self, value: str) -> None:
        encoded = value.encode("utf-16-le")
        if len(encoded) > 2500:
            raise ValueError("Credential exceeds secure storage limit.")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = _Credential(
            Type=1,
            TargetName=self.target,
            Comment="NC Relay rotating session",
            CredentialBlobSize=len(encoded),
            CredentialBlob=blob,
            Persist=2,
            UserName="NC Relay",
        )
        if not self._api().CredWriteW(ctypes.byref(credential), 0):
            raise RuntimeError("Could not save NC Relay secure credentials.")

    def delete(self) -> None:
        if (
            not self._api().CredDeleteW(self.target, 1, 0)
            and ctypes.get_last_error() != 1168
        ):
            raise RuntimeError("Could not clear NC Relay secure credentials.")
