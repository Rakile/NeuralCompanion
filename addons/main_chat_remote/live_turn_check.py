"""Opt-in UDP/TCP TURN allocation and relay-to-relay data check; no NC content."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json

from aioice.stun import TransactionFailed
from aioice.turn import create_turn_endpoint
from aiortc.rtcicetransport import parse_stun_turn_uri

from .relay.auth import RelayAuth
from .relay.credentials import CredentialStore


class Receiver(asyncio.DatagramProtocol):
    def __init__(self):
        self.inbox = asyncio.Queue()
        self.closed = asyncio.Event()

    def datagram_received(self, data, address):
        self.inbox.put_nowait(data)

    def connection_lost(self, exc):
        self.closed.set()


async def main(target):
    credentials = json.loads(CredentialStore(target).get())
    auth = RelayAuth(
        CredentialStore("NeuralCompanion/NCRelay/LiveCheck/turn-probe"), role="mobile"
    )
    await auth.login(credentials["username"], credentials["password"], "NC TURN check")
    try:
        config = await auth.authorized("/v1/ice-servers")
        for entry in config["iceServers"]:
            for url in entry["urls"]:
                if not url.startswith("turn:"):
                    continue
                parsed = parse_stun_turn_uri(url)
                endpoints = []
                try:
                    for _ in range(2):
                        endpoints.append(
                            await asyncio.wait_for(
                                create_turn_endpoint(
                                    Receiver,
                                    (parsed["host"], parsed["port"]),
                                    entry["username"],
                                    entry["credential"],
                                    transport=parsed["transport"],
                                    lifetime=60,
                                ),
                                20,
                            )
                        )
                    global_address = ipaddress.ip_address(
                        endpoints[0][0].get_extra_info("sockname")[0]
                    ).is_global
                    print(
                        "PASS live TURN",
                        parsed["transport"],
                        "authenticated allocation; advertised address is",
                        "public" if global_address else "NON-PUBLIC",
                        flush=True,
                    )
                    left, right = endpoints[0][0], endpoints[1][0]
                    a = left._TurnTransport__inner_protocol
                    b = right._TurnTransport__inner_protocol
                    # Await channel binding directly so failures are observed,
                    # never emitted as unhandled tasks containing ICE addresses.
                    # send_data installs each endpoint's channel receive map;
                    # channel_bind alone only creates the server permission.
                    # Prime both directions, then repeat once both receive maps
                    # are installed so the first-packet race cannot lose proof.
                    payload = b"nc-turn-connectivity-check"
                    for _ in range(2):
                        await asyncio.gather(
                            a.send_data(payload, right.get_extra_info("sockname")),
                            b.send_data(payload, left.get_extra_info("sockname")),
                        )
                    for _, receiver in endpoints:
                        assert await asyncio.wait_for(receiver.inbox.get(), 10) == payload
                    print(
                        "PASS live TURN",
                        parsed["transport"],
                        "relay-to-relay data",
                        flush=True,
                    )
                except TransactionFailed as exc:
                    code, reason = exc.response.attributes.get(
                        "ERROR-CODE", (0, "Unknown")
                    )
                    print(
                        "BLOCKED live TURN",
                        parsed["transport"],
                        "peer binding:",
                        code,
                        reason,
                        flush=True,
                    )
                except Exception as exc:
                    print(
                        "FAIL live TURN",
                        parsed["transport"],
                        type(exc).__name__,
                        flush=True,
                    )
                finally:
                    for transport, receiver in endpoints:
                        transport.close()
                        try:
                            await asyncio.wait_for(receiver.closed.wait(), 5)
                        except TimeoutError:
                            pass
    finally:
        await auth.logout()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-target", required=True)
    asyncio.run(main(parser.parse_args().credential_target))
