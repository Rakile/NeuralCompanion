"""Audited per-connection ICE hook. No global monkeypatch or dependency edits."""
from __future__ import annotations

import asyncio
import inspect
import ipaddress
import time
from typing import Any, Callable

from .router_mapping import RouterMapper, default_gateway


async def _mapper():
    return RouterMapper(await default_gateway())


class _MappedTransport:
    def __init__(self, connection, factory, event):
        self.connection, self.factory, self.event = connection, factory, event
        self.original_gather = connection.get_component_candidates
        self.original_close = connection.close
        self.mapper = None
        self.closed = False
        self.pending: set[asyncio.Task] = set()
        self.close_task = None

    async def gather(self, component: int, addresses: list[str], timeout: int = 5):
        task = asyncio.current_task()
        if self.closed:
            return []
        self.pending.add(task)
        try:
            base = await self.original_gather(component, addresses, timeout)
            extra = []
            try:
                async with asyncio.timeout(6):
                    if self.mapper is None:
                        value = self.factory()
                        self.mapper = await value if inspect.isawaitable(value) else value
                    for candidate in base:
                        if candidate.type != "host" or ipaddress.ip_address(candidate.host).version != 4:
                            continue
                        if hasattr(self.mapper, "accepts_host") and not self.mapper.accepts_host(candidate.host):
                            continue
                        lease = await self.mapper.map_udp(candidate.host, candidate.port, 120)
                        if (not ipaddress.IPv4Address(lease.external_host).is_global
                                or not 1 <= lease.external_port <= 65535
                                or not 0 < lease.expires_at - time.monotonic() <= 121):
                            raise ValueError("Invalid public mapping lease")
                        from aioice.candidate import Candidate, candidate_foundation, candidate_priority
                        if not any(c.host == lease.external_host and c.port == lease.external_port
                                   and c.component == component for c in base + extra):
                            extra.append(Candidate(
                                foundation=candidate_foundation("srflx", "udp", candidate.host),
                                component=component, transport="udp",
                                priority=candidate_priority(component, "srflx"),
                                host=lease.external_host, port=lease.external_port, type="srflx",
                                related_address=candidate.host, related_port=candidate.port))
                self.event("candidate_added" if extra else "no_extra_candidate")
                return base + extra
            except asyncio.CancelledError:
                await self.cleanup()
                raise
            except Exception:
                self.event("fallback")
                await self.cleanup()
                return base
        finally:
            self.pending.discard(task)

    async def cleanup(self):
        if self.mapper is not None:
            try:
                async with asyncio.timeout(3):
                    await self.mapper.close()
            except Exception:
                self.event("cleanup_unconfirmed")

    async def close(self):
        if self.close_task is None:
            self.closed = True
            self.close_task = asyncio.create_task(self._close())
        await asyncio.shield(self.close_task)

    async def _close(self):
        pending = list(self.pending)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            await self.cleanup()
        finally:
            await self.original_close()


def install_mapping(peer: Any, *, enabled: bool = False,
                    mapper_factory: Callable = _mapper,
                    event: Callable[[str], None] = lambda status: None) -> int:
    """Install after remote SDP creates transports, before local ICE gathering.

    Disabled/unsupported paths leave all methods and original candidates alone.
    Hooks are private to these connections, including cleanup via peer.close().
    """
    if not enabled:
        return 0
    import aiortc
    import aioice
    if (aiortc.__version__, aioice.__version__) != ("1.15.0", "0.10.2"):
        event("unsupported_version")
        return 0
    transports = {t.receiver.transport for t in peer.getTransceivers()}
    if peer.sctp is not None:
        transports.add(peer.sctp.transport)
    installed = 0
    for transport in transports:
        connection = transport.transport.iceGatherer._connection
        if (getattr(connection, "_nc_mapping", None) is not None
                or connection._local_candidates_start or connection._closed
                or len(connection._components) != 1):
            continue
        hook = _MappedTransport(connection, mapper_factory, event)
        connection._nc_mapping = hook
        connection.get_component_candidates = hook.gather
        connection.close = hook.close
        installed += 1
    return installed


def selected_route(peer: Any) -> str:
    """Inspect nominated pairs only; no addresses, SDP or payloads in logs."""
    transports = {t.receiver.transport for t in peer.getTransceivers()}
    if peer.sctp is not None:
        transports.add(peer.sctp.transport)
    pairs = [pair for transport in transports
             for pair in transport.transport.iceGatherer._connection._nominated.values()]
    if not pairs:
        return "unknown"
    relay = [p.local_candidate.type == "relay" or p.remote_candidate.type == "relay" for p in pairs]
    return "relay" if all(relay) else "mixed" if any(relay) else "direct"
