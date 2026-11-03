"""Read-only first-watch readiness and the minimal, explicit permission changes."""
from __future__ import annotations

import hashlib
import json


def required_watch_settings(config: dict) -> dict:
    wanted = dict(companion_orb_vision_enabled=True, companion_orb_sensory_target_enabled=True,
                  sensory_pingpong_enabled=True, sensory_allow_hidden_proactive_speech=True)
    raw = config.get('sensory_feedback_source', '')
    values = list(raw) if isinstance(raw, (list, tuple)) else str(raw).split(',')
    sources = list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))
    changes = {k: v for k, v in wanted.items() if not config.get(k, False)}
    if 'companion_orb_target' not in sources:
        changes['sensory_feedback_source'] = ','.join([*sources, 'companion_orb_target'])
    return changes


def build_setup_snapshot(config: dict, facts: dict) -> dict:
    changes = required_watch_settings(config)
    scope = dict(facts.get('scope') or {})
    count = int(facts.get('watch_count') or 0)
    reasons, action = [], ''
    state = f'Watching ({count})' if count else 'Ready — no active watches'
    if not facts.get('addon_loaded'):
        state, action, reasons = 'Setup needed', 'addon', ['Enable the Companion Orb addon, then restart NeuralCompanion.']
    elif not config.get('companion_orb_enabled') or config.get('companion_orb_display_mode') == 'off':
        state, action, reasons = 'Orb off', 'start', ['Start the Orb to use its capture and watch tools.']
    elif not facts.get('system_running'):
        state, action, reasons = 'Setup needed', 'initialize', ['Initialize the conversation runtime.']
    elif not facts.get('model_ready'):
        state, action, reasons = 'Setup needed', 'model', [str(facts.get('model_reason') or 'Choose and verify a vision-capable model.')]
    elif not scope.get('available'):
        state, action, reasons = 'Choose a target', 'target', ['Drop the Orb on a window or region, or choose Entire screen.']
    elif changes:
        state, action, reasons = 'Setup needed', 'enable', ['Enable background watching to follow ongoing requests.']
    elif facts.get('paused_reasons'):
        state, action, reasons = 'Paused', 'settings', list(facts['paused_reasons'])
    affected = []
    if any(k in changes for k in ('sensory_pingpong_enabled', 'sensory_allow_hidden_proactive_speech')):
        affected = [s for s in facts.get('enabled_sources', []) if s != 'companion_orb_target']
    # Use only setup facts, never arbitrary config/credentials in a UI payload.
    payload = dict(state=state, action=action, reasons=reasons, scope=scope, watch_count=count,
                   changes=changes, image_recipients=list(facts.get('image_recipients') or []),
                   affected_sources=affected, ready=not reasons)
    consent = dict(scope=scope, changes=changes, image_recipients=payload['image_recipients'],
                   enabled_sources=facts.get('enabled_sources', []),
                   provider_signature=facts.get('provider_signature', ''),
                   prerequisite_action=action)
    payload['confirmation_key'] = hashlib.sha256(json.dumps(consent, sort_keys=True, default=str).encode()).hexdigest()
    return payload
