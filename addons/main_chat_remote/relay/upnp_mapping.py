"""Bounded, gateway-only IGD client; finite leases and ownership-checked deletion."""
from __future__ import annotations

import asyncio
import ipaddress
import secrets
import socket
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

_LIMIT = 65536


class UpnpError(OSError):
    def __init__(self, code: str):
        super().__init__("UPnP action rejected")
        self.code = code


def _endpoint(url: str, gateway: str):
    if len(url) > 2048 or any(ord(char) < 32 for char in url):
        raise ValueError("Invalid UPnP URL")
    value = urlsplit(url)
    if (value.scheme != "http" or value.hostname != gateway or value.username
            or value.password or value.fragment):
        raise ValueError("UPnP control URL must stay on the selected gateway")
    return value


async def _http(url: str, gateway: str, timeout: float, body: bytes = b"",
                action: str = "") -> bytes:
    value = _endpoint(url, gateway)
    writer = None
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(gateway, value.port or 80, limit=_LIMIT)
            path = (value.path or "/") + ("?" + value.query if value.query else "")
            headers = [f"{'POST' if action else 'GET'} {path} HTTP/1.1",
                       f"Host: {value.netloc}", "Connection: close"]
            if action:
                headers.extend([f'SOAPAction: "{action}"', 'Content-Type: text/xml; charset="utf-8"',
                                f"Content-Length: {len(body)}"])
            writer.write(("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body)
            await writer.drain()
            raw_headers = await reader.readuntil(b"\r\n\r\n")
            lines = raw_headers.decode("iso-8859-1").split("\r\n")
            status = int(lines[0].split()[1])
            if status not in (200, 500):
                raise OSError("UPnP HTTP action failed")  # No redirects.
            fields = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
            fields = {k.lower(): v.strip().lower() for k, v in fields.items()}
            if fields.get("transfer-encoding") == "chunked":
                result = bytearray()
                while True:
                    size = int((await reader.readline()).split(b";", 1)[0].strip(), 16)
                    if size == 0:
                        break
                    if size < 0 or len(result) + size > _LIMIT:
                        raise ValueError("UPnP reply too large")
                    result.extend(await reader.readexactly(size))
                    if await reader.readexactly(2) != b"\r\n":
                        raise ValueError("Invalid UPnP HTTP chunk")
                return bytes(result)
            size = int(fields.get("content-length", _LIMIT + 1))
            if size > _LIMIT or size < 0:
                raise ValueError("UPnP reply must have bounded Content-Length")
            return await reader.readexactly(size)
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 0.2)
            except (OSError, asyncio.TimeoutError):
                pass


def _xml(data: bytes):
    if b"<!" in data:
        raise ValueError("UPnP XML declarations/entities are not accepted")
    return ET.fromstring(data)


class UpnpMapping:
    def __init__(self, gateway: str, host: str, port: int, url: str,
                 service: str, timeout: float):
        self.gateway, self.host, self.port = gateway, host, port
        self.url, self.service, self.timeout = url, service, timeout
        self.external_port = 49152 + secrets.randbelow(16384)
        self.owner = "NC-UDP-" + secrets.token_hex(8)

    @classmethod
    async def discover(cls, gateway: str, host: str, port: int, timeout: float):
        loop = asyncio.get_running_loop()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            sock.bind((host, 0))
            message = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
                       'MAN: "ssdp:discover"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n').encode()
            await loop.sock_sendto(sock, message, (gateway, 1900))
            await loop.sock_sendto(sock, message, ("239.255.255.250", 1900))
            async with asyncio.timeout(timeout):
                while True:
                    data, source = await loop.sock_recvfrom(sock, 8192)
                    if source[0] != gateway:
                        continue
                    locations = [s.split(":", 1)[1].strip() for s in data.decode("ascii", "ignore").splitlines()
                                 if s.lower().startswith("location:")]
                    if locations:
                        location = locations[0]
                        _endpoint(location, gateway)
                        break
        descriptor = _xml(await _http(location, gateway, timeout))
        for element in descriptor.iter():
            if element.tag.rsplit("}", 1)[-1] != "service":
                continue
            values = {child.tag.rsplit("}", 1)[-1]: child.text or "" for child in element}
            service = values.get("serviceType", "")
            if service in {"urn:schemas-upnp-org:service:WANIPConnection:1",
                           "urn:schemas-upnp-org:service:WANIPConnection:2",
                           "urn:schemas-upnp-org:service:WANPPPConnection:1"}:
                url = urljoin(location, values.get("controlURL", ""))
                _endpoint(url, gateway)
                return cls(gateway, host, port, url, service, timeout)
        raise OSError("No gateway IGD mapping service")

    async def _soap(self, action: str, values: dict[str, object]) -> dict[str, str]:
        args = "".join(f"<{key}>{escape(str(value))}</{key}>" for key, value in values.items())
        body = ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                f'<u:{action} xmlns:u="{self.service}">{args}</u:{action}></s:Body></s:Envelope>').encode()
        root = _xml(await _http(self.url, self.gateway, self.timeout, body, self.service + "#" + action))
        result = {node.tag.rsplit("}", 1)[-1]: node.text or "" for node in root.iter()}
        if "errorCode" in result:
            raise UpnpError(result["errorCode"])
        return result

    def _key(self) -> dict[str, object]:
        return dict(NewRemoteHost="", NewExternalPort=self.external_port, NewProtocol="UDP")

    async def _lookup(self) -> dict[str, str] | None:
        try:
            return await self._soap("GetSpecificPortMappingEntry", self._key())
        except UpnpError as error:
            if error.code == "714":
                return None
            raise

    def _owned(self, record: dict[str, str]) -> bool:
        return (record.get("NewPortMappingDescription") == self.owner
                and record.get("NewInternalClient") == self.host
                and record.get("NewInternalPort") == str(self.port))

    async def update(self, lifetime: int) -> tuple[str, int, int]:
        existing = await self._lookup()
        if existing and not self._owned(existing):
            raise OSError("Existing router mapping belongs to another owner")
        if lifetime == 0:
            if existing:
                await self._soap("DeletePortMapping", self._key())
            if await self._lookup() is not None:
                raise OSError("UPnP mapping deletion not confirmed")
            return "0.0.0.0", self.external_port, 0
        public = await self._soap("GetExternalIPAddress", {})
        external_host = str(ipaddress.IPv4Address(public.get("NewExternalIPAddress", "")))
        if not ipaddress.IPv4Address(external_host).is_global:
            raise OSError("Gateway has no public IPv4 address")
        # Never retry with lifetime=0 if a router accepts only permanent leases.
        await self._soap("AddPortMapping", {
            **self._key(), "NewInternalPort": self.port, "NewInternalClient": self.host,
            "NewEnabled": 1, "NewPortMappingDescription": self.owner,
            "NewLeaseDuration": lifetime})
        confirmed = await self._lookup()
        if not confirmed or not self._owned(confirmed):
            raise OSError("UPnP lease ownership not confirmed")
        granted = int(confirmed.get("NewLeaseDuration", "0"))
        if not 30 <= granted <= lifetime:
            raise OSError("Router did not confirm a finite lease")
        return external_host, self.external_port, granted
