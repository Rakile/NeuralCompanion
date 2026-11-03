"""Optional finite UDP leases. No I/O occurs until explicitly enabled/called."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import time
from typing import Callable


@dataclass(frozen=True, slots=True)
class MappingSettings:
    enabled: bool = False

    @classmethod
    def load(cls, path: Path) -> MappingSettings:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return cls(value.get("enabled") is True)
        except (OSError, ValueError, AttributeError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps({"enabled": self.enabled}), encoding="utf-8")
        os.replace(temporary, path)


@dataclass(frozen=True, slots=True)
class MappingLease:
    external_host: str
    external_port: int
    expires_at: float


def pcp_request(host: str, port: int, lifetime: int, nonce: bytes,
                external_port: int = 0, external_host: str = "0.0.0.0") -> bytes:
    if len(nonce) != 12 or not 1 <= port <= 65535:
        raise ValueError("Invalid PCP mapping request")
    client = bytes(10) + b"\xff\xff" + ipaddress.IPv4Address(host).packed
    external = (bytes(16) if external_host == "0.0.0.0" else
                bytes(10) + b"\xff\xff" + ipaddress.IPv4Address(external_host).packed)
    return struct.pack("!BBHI16s12sB3xHH16s", 2, 1, 0, lifetime, client,
                       nonce, 17, port, external_port, external)


def parse_pcp(data: bytes, nonce: bytes, port: int) -> tuple[str, int, int, int]:
    if (len(data) < 60 or data[:2] != b"\x02\x81" or data[3] != 0
            or data[24:36] != nonce or data[36] != 17
            or struct.unpack_from("!H", data, 40)[0] != port):
        raise ValueError("PCP mapping response rejected")
    lifetime, epoch = struct.unpack_from("!II", data, 4)
    external = ipaddress.IPv6Address(data[44:60]).ipv4_mapped
    if external is None:
        raise ValueError("PCP did not return an IPv4 mapped address")
    return str(external), struct.unpack_from("!H", data, 42)[0], lifetime, epoch


def parse_pmp(data: bytes, port: int) -> tuple[int, int, int]:
    if len(data) != 16:
        raise ValueError("Invalid NAT-PMP mapping response")
    version, opcode, result, epoch, internal, external, lifetime = struct.unpack("!BBHIHHI", data)
    if (version, opcode, result, internal) != (0, 129, 0, port):
        raise ValueError("NAT-PMP mapping response rejected")
    return external, lifetime, epoch


async def default_gateway() -> str:
    """Resolve the IPv4 default route on the worker, never on the Qt thread."""
    if sys.platform == "win32":
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                   "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
                   "Sort-Object RouteMetric | Select-Object -First 1 -ExpandProperty NextHop"]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 3)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        address = output.decode().strip()
    else:
        # Route file access is tiny but kept off the worker event loop too.
        rows = await asyncio.to_thread(Path("/proc/net/route").read_text)
        address = next(socket.inet_ntoa(struct.pack("<I", int(row.split()[2], 16)))
                       for row in rows.splitlines()[1:] if row.split()[1] == "00000000")
    gateway = ipaddress.IPv4Address(address)
    if not gateway.is_private or gateway.is_loopback or gateway.is_unspecified:
        raise ValueError("No usable local IPv4 gateway")
    return str(gateway)


@dataclass
class _Record:
    protocol: str
    host: str
    port: int
    nonce: bytes
    external_host: str = "0.0.0.0"
    external_port: int = 0
    lifetime: int = 120
    requested_lifetime: int = 120
    epoch: int = 0
    task: asyncio.Task | None = None
    upnp: object | None = None
    deleted: bool = False


class RouterMapper:
    """One owner per ICE connection; no credentials or content in diagnostics.

    Provisional requests are retained before transmission so cancellation or a
    lost success response still gets a bounded deletion attempt at shutdown.
    """
    def __init__(self, gateway: str, *, timeout: float = 0.6, gateway_port: int = 5351,
                 protocols: tuple[str, ...] = ("pcp", "pmp", "upnp"),
                 event: Callable[[str], None] = lambda status: None,
                 on_failure: Callable[[], None] = lambda: None):
        self.gateway = str(ipaddress.IPv4Address(gateway))
        self.timeout, self.gateway_port, self.protocols = timeout, gateway_port, protocols
        self.event, self.on_failure = event, on_failure
        self.records: list[_Record] = []
        self.closed = False
        self.cleanup_failed = False
        self._close_lock = asyncio.Lock()

    async def _udp(self, data: bytes, host: str) -> bytes:
        loop = asyncio.get_running_loop()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            sock.bind((host, 0))
            sock.connect((self.gateway, self.gateway_port))
            async with asyncio.timeout(self.timeout):
                await loop.sock_sendall(sock, data)
                return await loop.sock_recv(sock, 2048)

    async def _exchange(self, record: _Record, lifetime: int) -> tuple[str, int, int, int]:
        if record.protocol == "pcp":
            data = await self._udp(pcp_request(record.host, record.port, lifetime, record.nonce,
                                              record.external_port, record.external_host), record.host)
            return parse_pcp(data, record.nonce, record.port)
        if record.protocol == "pmp":
            data = await self._udp(struct.pack("!BBHHHI", 0, 1, 0, record.port,
                                               record.external_port, lifetime), record.host)
            port, granted, epoch = parse_pmp(data, record.port)
            return record.external_host, port, granted, epoch
        lease = await record.upnp.update(lifetime)
        return lease[0], lease[1], lease[2], 0

    def accepts_host(self, host: str) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect((self.gateway, self.gateway_port))
            return route.getsockname()[0] == host

    async def map_udp(self, host: str, port: int, lifetime: int = 120) -> MappingLease:
        if self.closed or not 30 <= lifetime <= 120:
            raise ValueError("Mapping owner is closed or lease is out of range")
        if not self.accepts_host(host):
            raise OSError("Host socket does not use the selected gateway interface")
        for protocol in self.protocols:
            record = _Record(protocol, host, port, secrets.token_bytes(12),
                             lifetime=lifetime, requested_lifetime=lifetime)
            try:
                if protocol == "pmp":
                    public = await self._udp(b"\x00\x00", host)
                    if len(public) != 12 or public[:4] != b"\x00\x80\x00\x00":
                        raise ValueError("Invalid NAT-PMP public address response")
                    record.external_host = socket.inet_ntoa(public[8:12])
                elif protocol == "upnp":
                    from .upnp_mapping import UpnpMapping
                    record.upnp = await UpnpMapping.discover(self.gateway, host, port, self.timeout)
                self.records.append(record)
                address, external, granted, epoch = await self._exchange(record, lifetime)
                record.external_host, record.external_port = address, external
                if (not ipaddress.IPv4Address(address).is_global or not 1 <= external <= 65535
                        or not 30 <= granted <= lifetime):
                    raise ValueError("Router did not grant a finite public UDP mapping")
                record.lifetime, record.epoch = granted, epoch
                record.task = asyncio.create_task(self._renew(record))
                self.event("mapped_" + protocol)
                return MappingLease(address, external, time.monotonic() + granted)
            except asyncio.CancelledError:
                raise  # The owner calls close(), including provisional requests.
            except Exception:
                if record in self.records:
                    await self._delete(record)
        self.event("mapping_unavailable")
        raise OSError("Router mapping unavailable; normal ICE remains active")

    async def renew_once(self) -> None:
        for record in self.records:
            if record.deleted or record.task is None:
                continue
            await self._refresh(record)

    async def _refresh(self, record: _Record) -> None:
        if record.protocol == "pmp":
            public = await self._udp(b"\x00\x00", record.host)
            if (len(public) != 12 or public[:4] != b"\x00\x80\x00\x00"
                    or socket.inet_ntoa(public[8:12]) != record.external_host):
                raise OSError("Router public address changed")
        address, port, lifetime, epoch = await self._exchange(record, record.requested_lifetime)
        if ((address, port) != (record.external_host, record.external_port)
                or not 30 <= lifetime <= record.requested_lifetime or epoch < record.epoch):
            # The SDP alias cannot silently change during an established call.
            raise OSError("Mapping changed or router restarted")
        record.epoch, record.lifetime = epoch, lifetime

    async def _renew(self, record: _Record) -> None:
        try:
            while not self.closed:
                await asyncio.sleep(record.lifetime / 2)
                await self._refresh(record)
                self.event("mapping_renewed")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.event("mapping_renewal_failed")
            # Let the existing reconnect owner retry with mapping suppressed.
            self.on_failure()

    async def _delete(self, record: _Record) -> None:
        if record.deleted:
            return
        try:
            async with asyncio.timeout(max(1, self.timeout * 2)):
                result = await self._exchange(record, 0)
                if result[2] != 0:
                    raise OSError("Router did not acknowledge lease deletion")
            record.deleted = True
            self.event("mapping_removed")
        except Exception:
            self.cleanup_failed = True
            self.event("mapping_cleanup_unconfirmed")

    async def close(self) -> None:
        async with self._close_lock:
            self.closed = True
            tasks = [r.task for r in self.records if r.task is not None and r.task is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(*(self._delete(r) for r in self.records))
