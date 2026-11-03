"""Observe counters only. No payload capture, peer mutation or relay uploads."""
import asyncio


class PeerTraffic:
    def __init__(self, peer, totals, *, start=True):
        self.peer, self.totals = peer, totals
        self.previous = {}
        self.data = {'sent': 0, 'received': 0}
        self.extra = {'sent': 0, 'received': 0}
        self.task = asyncio.create_task(self._run()) if start else None

    def sent(self, kind, count):
        self.data['sent'] += count
        self.totals.add(kind, 'sent', count)

    def received(self, kind, count, *, observed=False):
        if not observed:
            self.data['received'] += count
        self.totals.add(kind, 'received', count)

    def sample(self, report):
        media = {'sent': 0, 'received': 0}
        transport = {'sent': 0, 'received': 0}
        for key, row in report.items():
            if row.type == 'transport':
                for direction, field in (('sent', 'bytesSent'), ('received', 'bytesReceived')):
                    transport[direction] += getattr(row, field, 0)
            elif row.type in ('outbound-rtp', 'inbound-rtp') and row.kind in ('audio', 'video'):
                direction, field = ('sent', 'bytesSent') if row.type == 'outbound-rtp' else ('received', 'bytesReceived')
                count = getattr(row, field, 0)
                identity = key, direction
                self.totals.add(row.kind, direction, max(0, count-self.previous.get(identity, 0)))
                self.previous[identity] = count
                media[direction] += count
        for direction in transport:
            # The remainder includes observed DTLS/SRTP/SCTP/RTCP and retries,
            # not IP headers or TURN allocation/channel framing outside DTLS.
            extra = max(0, transport[direction]-media[direction]-self.data[direction])
            self.totals.add('transport_extra', direction, max(0, extra-self.extra[direction]))
            self.extra[direction] = max(self.extra[direction], extra)

    async def _run(self):
        try:
            while True:
                self.sample(await self.peer.getStats())
                if self.peer.connectionState == 'closed':
                    break
                await asyncio.sleep(2)
        except (Exception, asyncio.CancelledError):
            pass  # Statistics never change a connection's outcome.
