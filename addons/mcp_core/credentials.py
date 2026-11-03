"""Addon-local Windows Credential Manager adapter; no plaintext fallback."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import sys


class _Credential(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
        ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME),
        ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
        ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR),
    ]


class WindowsVault:
    @staticmethod
    def _api():
        if sys.platform != 'win32':
            raise RuntimeError('Secure MCP credentials require Windows Credential Manager.')
        api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(_Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        return api

    def read(self, target):
        api = self._api()
        pointer = ctypes.POINTER(_Credential)()
        if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise RuntimeError('Could not read secure MCP credentials.')
        try:
            return ctypes.string_at(pointer.contents.CredentialBlob,
                                    pointer.contents.CredentialBlobSize).decode('utf-16-le')
        finally:
            api.CredFree(pointer)

    def write(self, target, secret):
        encoded = secret.encode('utf-16-le')
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = _Credential(Type=1, TargetName=target, Comment='NeuralCompanion MCP Core',
                                 CredentialBlobSize=len(encoded), CredentialBlob=blob,
                                 Persist=2, UserName='NeuralCompanion MCP Core')
        if not self._api().CredWriteW(ctypes.byref(credential), 0):
            raise RuntimeError('Could not save secure MCP credentials.')

    def delete(self, target):
        if not self._api().CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
            raise RuntimeError('Could not delete secure MCP credentials.')


class CredentialStore:
    def __init__(self, installation_id, server_id, *, vault=None):
        installation = hashlib.sha256(str(installation_id).encode()).hexdigest()[:32]
        server = hashlib.sha256(str(server_id).encode()).hexdigest()[:32]
        self.target = f'NeuralCompanion/MCP/{installation}/{server}'
        self._vault = vault if vault is not None else WindowsVault()

    def get(self):
        return self._vault.read(self.target)

    def set(self, secret):
        if (not isinstance(secret, str) or not secret or len(secret.encode('utf-16-le')) > 2500
                or any(ord(c) < 32 or ord(c) == 127 for c in secret)):
            raise ValueError('Invalid credential value or length.')
        self._vault.write(self.target, secret)

    def delete(self):
        self._vault.delete(self.target)
