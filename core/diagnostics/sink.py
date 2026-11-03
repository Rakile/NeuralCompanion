"""Strict adapter for the existing diagnostic_event log wrapper."""
import copy

from .contract import validate_event


def prepare_contract_record(details):
    event = details.get('contract') if type(details) is dict else None
    issues = validate_event(event)
    if issues:
        return 'diagnostics.validation_failed', {'site': 'diagnostic_sink', 'issues': issues}
    # Discard untrusted wrapper extras; identity lives inside the contract.
    return 'diagnostic_event', {'contract': copy.deepcopy(event)}
