"""Fixed diagnostic vocabulary only; never export exception messages."""
from core.diagnostics.plan_trace import PlanTrace
import secrets

REASONS = frozenset(('arm_identity_invalid', 'idle_mode_invalid', 'muxed_mode_invalid',
    'arm_cancelled', 'arm_mode_changed', 'arm_inactive', 'arm_history_full', 'producer_busy',
    'producer_busy_or_closed', 'avatar_not_musetalk', 'runtime_not_listening', 'pipeline_pending',
    'runtime_not_ready', 'ready_wait_identity_invalid', 'ready_wait_source_changed', 'validation_unclassified'))
_MESSAGES = {'Invalid arm request identity': 'arm_identity_invalid',
    'Invalid ready wait identity':'ready_wait_identity_invalid',
    'Ready wait source changed':'ready_wait_source_changed',
    'Invalid idle chunk mode': 'idle_mode_invalid', 'Muxed trial requires uncached idle chunks': 'muxed_mode_invalid',
    'Arm request was cancelled': 'arm_cancelled', 'Arm mode changed within its identity': 'arm_mode_changed',
    'Arm request is no longer active': 'arm_inactive', 'Arm cancellation history full': 'arm_history_full',
    'Live trial busy': 'producer_busy', 'Live trial busy or closed': 'producer_busy_or_closed',
    'MuseTalk must be idle and initialized': 'runtime_not_ready'}
_trace = PlanTrace()


def rejection_reason(error):
    reason = getattr(error, 'diagnostic_reason', None)
    if isinstance(reason, str) and reason in REASONS:
        return reason
    return _MESSAGES.get(str(error), 'validation_unclassified')


def record_rejection(reason):
    try:
        _trace.observe(secrets.token_hex(16), 'backend.live_control.reject', reason, True, False)
    except Exception:
        pass
