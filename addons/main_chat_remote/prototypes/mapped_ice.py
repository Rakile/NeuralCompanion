"""Short-lived transport experiment. No real router client or worker integration.

Only aioice 0.10.2 is audited here. This adds an advertised address for an
existing host socket, leaving its protocol and all STUN/TURN candidates intact.
The injected mapper must be private to this connection and own partial mappings
even when map_udp is cancelled. close() must be idempotent and release them all.
No lease renewal is implemented: this is for bounded laboratory tests only.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import math
import time
from typing import Any, Protocol

import aioice
from aioice.candidate import Candidate, candidate_foundation, candidate_priority


@dataclass(frozen=True, slots=True)
class MappingLease:
    external_host: str
    external_port: int
    expires_at: float  # monotonic; a finite lease, never a permanent mapping


class EndpointMapper(Protocol):
    async def map_udp(self, host: str, port: int, lifetime: int) -> MappingLease: ...

    async def close(self) -> None:
        """Release ALL owned mappings, including partially completed requests."""
        ...


class MappedConnection(aioice.Connection):
    """Opt-in aioice experiment, unreferenced by normal NC startup."""

    def __init__(self, *args: Any, mapper: EndpointMapper | None = None,
                 enabled: bool = False, mapping_timeout: float = 0.25,
                 cleanup_timeout: float = 0.25, lifetime: int = 60,
                 **kwargs: Any) -> None:
        if not all(math.isfinite(value) and 0 < value <= 5
                   for value in (mapping_timeout, cleanup_timeout)):
            raise ValueError("Prototype timeouts must be finite and at most 5 seconds")
        if not 1 <= lifetime <= 120:
            raise ValueError("Prototype leases must be 1-120 seconds")
        super().__init__(*args, **kwargs)
        self._mapper = mapper if enabled else None
        self._mapping_timeout = mapping_timeout
        self._cleanup_timeout = cleanup_timeout
        self._lifetime = lifetime
        self._gathers: set[asyncio.Task[Any]] = set()
        self._closing_mapping = False
        self._shutdown_task: asyncio.Task[None] | None = None
        self.mapping_status = "disabled" if not enabled else "pending"
        self.mapping_cleanup_failed = False

    async def get_component_candidates(self, component: int, addresses: list[str],
                                       timeout: int = 5) -> list[Candidate]:
        task = asyncio.current_task()
        if self._closing_mapping:
            return []
        if task is not None:
            self._gathers.add(task)
        try:
            base = await super().get_component_candidates(component, addresses, timeout)
            if self._mapper is None:
                return base
            if aioice.__version__ != "0.10.2":
                self.mapping_status = "unsupported_version"
                return base  # Fail closed for the experiment, NOT for ICE.
            if len(self._components) != 1:
                # Multi-component lease ownership is deliberately out of scope.
                self.mapping_status = "unsupported_topology"
                return base
            extra: list[Candidate] = []
            try:
                async with asyncio.timeout(self._mapping_timeout):
                    for host in base:
                        if host.type != "host" or ipaddress.ip_address(host.host).version != 4:
                            continue
                        lease = await self._mapper.map_udp(host.host, host.port, self._lifetime)
                        address = ipaddress.IPv4Address(lease.external_host)
                        remaining = lease.expires_at - time.monotonic()
                        # Loopback is permitted solely for the injected lab mapper.
                        if (address.is_unspecified or address.is_multicast
                                or not 1 <= lease.external_port <= 65535
                                or not math.isfinite(remaining)
                                or not 0 < remaining <= self._lifetime + 1):
                            raise ValueError("Invalid mapping lease")
                        candidate = Candidate(
                            foundation=candidate_foundation("srflx", "udp", host.host),
                            component=host.component, transport=host.transport,
                            priority=candidate_priority(host.component, "srflx"),
                            host=str(address), port=lease.external_port, type="srflx",
                            related_address=host.host, related_port=host.port)
                        if not any((c.host, c.port, c.component) ==
                                   (candidate.host, candidate.port, candidate.component)
                                   for c in base + extra):
                            extra.append(candidate)
            except asyncio.CancelledError:
                await self._cleanup_mappings()
                raise
            except Exception:
                # Optional mapping errors cannot abort normal ICE gathering.
                self.mapping_status = "fallback"
                await self._cleanup_mappings()
                return base
            self.mapping_status = "mapped" if extra else "no_extra_candidate"
            return base + extra
        finally:
            if task is not None:
                self._gathers.discard(task)

    async def _cleanup_mappings(self) -> None:
        if self._mapper is not None:
            try:
                async with asyncio.timeout(self._cleanup_timeout):
                    await self._mapper.close()
            except Exception:
                self.mapping_cleanup_failed = True

    async def close(self) -> None:
        if self._shutdown_task is None:
            self._closing_mapping = True
            self._shutdown_task = asyncio.create_task(self._shutdown())
        await asyncio.shield(self._shutdown_task)

    async def _shutdown(self) -> None:
        pending = list(self._gathers)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            await self._cleanup_mappings()
        finally:
            await super().close()
