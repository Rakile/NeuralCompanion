"""Allowlisted, nonblocking evidence for relay state transitions."""

from __future__ import annotations

import re
import sys
import uuid
from collections.abc import Mapping

from core.diagnostics.emitter import DiagnosticEmitter
from core.diagnostics.journal import enqueue_diagnostic


_ID = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
_TRIGGERS = frozenset((
    "socket_closed", "signaling_error", "peer_disconnected", "peer_failed",
    "data_channel_closed", "authorization_expired", "authorization_rejected",
    "explicit_cleanup", "reconnect_scheduled", "peer_recovered", "recovery_timeout",
    "desktop_changed", "peer_connecting", "peer_connected", "ice_state_changed",
    "candidate_selected",
))
_INITIATORS = frozenset(("signaling", "peer", "data_channel", "authorization", "application", "timer", "ice"))
_ROLES = frozenset(("initiating", "cleanup", "retry"))
_PEER = frozenset(("none", "new", "connecting", "connected", "disconnected", "failed", "closed", "unknown"))
_ICE = _PEER | {"checking", "completed"}
_CHANNEL = frozenset(("none", "connecting", "open", "closing", "closed", "unknown"))
_CANDIDATE = frozenset(("host", "srflx", "prflx", "relay", "unknown"))
_PROTOCOL = frozenset(("udp", "tcp", "unknown"))
_emitter: DiagnosticEmitter | None = None


def _label(value: object, allowed: frozenset[str] | set[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"


def build_relay_data(
    trigger: str, initiator: str, event_role: str, state: Mapping[str, object],
) -> dict[str, object]:
    remaining = state.get("authorization_remaining_ms")
    pending = state.get("pending_commands")
    data: dict[str, object] = {
        "site": "relay.transition",
        "trigger": trigger if trigger in _TRIGGERS else "signaling_error",
        "initiator": initiator if initiator in _INITIATORS else "application",
        "event_role": event_role if event_role in _ROLES else "initiating",
        "peer_state": _label(state.get("peer_state"), _PEER),
        "ice_state": _label(state.get("ice_state"), _ICE),
        "channel_state": _label(state.get("channel_state"), _CHANNEL),
        "signaling_state": _label(state.get("signaling_state"), _CHANNEL),
        "authorization_valid": state.get("authorization_valid") is True,
        "authorization_remaining_ms": min(int(remaining), 9007199254740991)
        if type(remaining) in (int, float) and 0 <= remaining < float("inf") else None,
        "pending_commands": min(pending, 10000) if type(pending) is int and pending >= 0 else 0,
        "selected_candidate_type": _label(state.get("selected_candidate_type"), _CANDIDATE),
        "candidate_protocol": _label(state.get("candidate_protocol"), _PROTOCOL),
    }
    cause = state.get("cause_event_id")
    if isinstance(cause, str) and _ID.fullmatch(cause):
        data["cause_event_id"] = cause
    return data


def emit_relay_transition(
    *, session_id: str, trigger: str, initiator: str, event_role: str,
    state: Mapping[str, object], failure: bool = False,
) -> None:
    """Observe the state before cleanup. Never influence relay control flow."""
    global _emitter
    if not isinstance(session_id, str) or not _ID.fullmatch(session_id):
        return
    try:
        if _emitter is None:
            _emitter = DiagnosticEmitter(
                component="backend", build_id=None, build_unavailable_reason="not_available",
                clock_id="backend-monotonic", enqueue=enqueue_diagnostic,
                emergency=lambda _: sys.stderr.write("[NC diagnostics] relay event unavailable\n"),
            )
        data = build_relay_data(trigger, initiator, event_role, state)
        cause = data.get("cause_event_id")
        _emitter.emit({
            "level": "warning" if failure else "info", "event_name": "relay.transition",
            "trace_id": session_id, "operation_id": uuid.uuid4().hex,
            "parent_operation_id": None, "phase": "snapshot", "outcome": "observed",
            "basis": "observed",
            "links": [{"relation": "cleanup_of", "event_id": cause, "operation_id": None}]
            if cause is not None and event_role == "cleanup" else [],
            "context": {"session_id": session_id}, "data": data,
        })
    except Exception:
        return
