"""Choose independent STUN discovery and an aiortc-compatible TURN transport."""

from __future__ import annotations


def desktop_ice_servers(entries: list[dict], *, prefer_tcp: bool = False) -> list[dict]:
    expanded = [{**entry, "urls": [url]} for entry in entries for url in entry["urls"]]
    first_stun = next((entry["urls"][0] for entry in expanded
                       if entry["urls"][0].startswith("stun:")), None)
    if first_stun in {
        "stun:turn.nc-relay.online:3478", "stun:nc-relay.online:3478",
    }:
        # aiortc uses the first STUN URL. A relay behind this desktop's NAT
        # can report the router's private hairpin address instead of its WAN IP.
        # Keep the supplied TURN endpoints/credentials and custom ICE configs.
        expanded.insert(0, {"urls": ["stun:stun.l.google.com:19302"]})
    if prefer_tcp:
        expanded.sort(
            key=lambda entry: (
                0
                if (
                    "transport=tcp" in entry["urls"][0]
                    or entry["urls"][0].startswith("turns:")
                )
                else 1
            )
        )
    return expanded
