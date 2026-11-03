# Optional mapped ICE: isolated laboratory prototype

This directory is not imported by the NC relay worker. Nothing here is enabled
by NC startup, and no phone APK change is required. Deleting this directory
reverts the entire experiment. No installed dependency or existing worker code
has been modified.

## Run

From the repository root in PowerShell:

```powershell
rtk .\.venvs\nc_relay\Scripts\python.exe -B -m unittest addons.main_chat_remote.prototypes.test_mapped_ice -v
```

The tests use only loopback UDP sockets and synthetic payloads. They do not
contact your router, public relay, phone, or running NC session.

## What this proves

- Mapping is disabled unless `enabled=True` is explicitly supplied.
- A fake gateway can expose a different external port which forwards packets
  into the original aioice host socket; that socket's base candidate is retained.
- A normal server-reflexive (`srflx`) candidate can describe that mapping.
- Version mismatch and unsupported multi-component ICE skip the experiment.
- A test-only local TURN server handles actual aioice allocation, channel binding,
  bidirectional ChannelData, and allocation deletion. Forced TURN still carries
  payloads when mapping is disabled, successful, blackholed, rejected, timed out,
  or invalid. Host protocols are excluded from pairing ONLY by the test harness
  to force this route; production TURN policy has not changed.
- Mapping failures release partial fake allocations. Cancellation, peer closure,
  independent peers, and observable cleanup errors are covered.

DeepSeek supplied the initial proposal and a review. The applied prototype fixes
the proposal's fatal-version-check and skipped-cleanup defects. Review findings
were evaluated against actual asyncio behavior: no scheduling can occur between
the closing check and task registration (there is no await there). Mapping
reachability remains ICE's job; a local hairpin probe would not prove internet
reachability and could reject a usable mapping on a router without hairpin NAT.

## Strict limits

This is not an UPnP/NAT-PMP implementation or a usable NC setting. There is no
real gateway discovery, mapping library, aiortc gatherer integration, persistent
toggle, mapping renewal, live Pixel test, or direct-path recovery implementation.
It does not prove full ICE nomination through a real bidirectional NAT, only
mapped socket reachability and independent TURN transport viability.

The subclass audits aioice 0.10.2 and uses private lifecycle fields for a bounded
experiment. Tests deliberately use loopback addresses. A production adapter
must validate gateway/interface/public addresses and must not reuse this lab
address policy. Normal local candidates are untouched when the experiment skips.

The mapper contract requires one mapper per connection, finite leases, and
ownership of partially created mappings even if map_udp is cancelled. close()
must be idempotent and release all owned mappings. Mapping and cleanup timeouts
assume cancellation-cooperative async providers; a blocking or cancellation-
suppressing provider must be isolated separately. `mapping_cleanup_failed`
records unsuccessful cleanup, whose success cannot be guaranteed if a real
router is unavailable. Finite leases are the crash/failure backstop.

There is deliberately no renewal: mapped-path lab sessions must finish before
their lease expires (60 seconds by default, at most 120). Do not attach this
prototype to production calls. Mid-call expiry does not promise seamless TURN
switching. That requires separate recovery tests and production integration.

The local TURN fixture is an unauthenticated loopback-only subset, not coturn.
It omits credential challenges, Data indications before channel binding,
TCP/TLS, quotas, server-driven expiry, real NAT, and firewall behavior. Thus it
does not prove public relay authentication or network connectivity.

## Next decision

Before a real-router experiment: select an audited mapping provider, add renewal
and network-change handling, implement explicit per-peer aiortc hooks without
global monkeypatching, add the off-by-default persisted setting and local path
diagnostics, then exercise direct failure/reconnection with TURN credentials.
Retain normal `/v1/ice-servers` gathering throughout. Direct selection may still
leave TURN allocations alive; evaluate selected pairs and sustained media bytes,
not a requirement for zero allocations.
