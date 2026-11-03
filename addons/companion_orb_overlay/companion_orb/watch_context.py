"""Conversation-owned watch orchestration; inference never holds the state lock."""
from collections import OrderedDict
from copy import deepcopy
import json
import threading

from .watch_intent import parse_watch_intent, real_dialogue, turn_key, user_text


def paused_reasons(config):
    gates = {'companion_orb_vision_enabled': 'auxiliary vision is off',
        'companion_orb_sensory_target_enabled': 'Orb sensory source is off',
        'sensory_pingpong_enabled': 'background check-ins are off',
        'sensory_allow_hidden_proactive_speech': 'proactive speech is off'}
    reasons = [reason for key, reason in gates.items() if not config.get(key, False)]
    raw = config.get('sensory_feedback_source', '')
    sources = raw if isinstance(raw, (list, tuple)) else str(raw).split(',')
    if 'companion_orb_target' not in {str(s).strip() for s in sources}:
        reasons.append('Orb is not a selected sensory source')
    return reasons


class OrbWatchContext:
    def __init__(self, state, runtime, on_change=None, *, capture_target_available=None,
                 shared_policy_config=None):
        self.state, self.runtime = state, runtime
        self.on_change = on_change or (lambda: None)
        self.capture_target_available = capture_target_available
        self.shared_policy_config = shared_policy_config
        self._lock = threading.RLock()
        self._receipts = OrderedDict()
        self._closed = False

    def clear(self, reason):
        with self._lock:
            self.state.clear(reason)
            if reason == 'shutdown':
                self._closed = True
        self.on_change()

    def record(self, stage, payload, **correlation):
        recorder=getattr(self.runtime,'record_communication',None)
        if callable(recorder):
            try:
                from core.communication_trace import current_correlation
                recorder(stage=stage,payload=payload,correlation=dict(current_correlation(),**correlation))
            except Exception:
                # Optional diagnostics must never interrupt a watch or conversation.
                pass

    def current(self, config):
        scope = self.runtime.conversation_scope()
        if not scope.get('available'):
            if self.state.snapshot()['active'] or self.state.snapshot().get('watches'):
                self.clear('scope_unavailable')
            return dict(self.state.snapshot(), paused_reasons=['conversation scope unavailable'])
        with self._lock:
            self.state.sync_session(str(scope.get('session_key') or ''))
            if not config.get('companion_orb_enabled') and (self.state.snapshot()['active'] or self.state.snapshot().get('watches')):
                self.state.clear('disabled')
            snapshot = self.state.snapshot()
            return dict(snapshot, paused_reasons=self._paused_reasons(config, snapshot))

    def _paused_reasons(self, config, snapshot):
        if callable(self.shared_policy_config):
            shared_policy = self.shared_policy_config() or {}
            config = dict(config)
            for key in ('sensory_allow_hidden_proactive_speech', 'sensory_pingpong_enabled',
                        'sensory_feedback_source'):
                if key in shared_policy:
                    config[key] = shared_policy[key]
        reasons = paused_reasons(config)
        needs_capture = (any(row['status'] == 'watching' for row in snapshot.get('watches', []))
            if snapshot.get('schema_version') == 2 else snapshot.get('active', False))
        if (needs_capture
                and callable(self.capture_target_available) and not self.capture_target_available()):
            reasons.append('waiting for a capture target')
        return reasons

    def _receipt(self, status, message='', **extra):
        receipt = dict(status=status, message=message, **extra)
        text = ('Companion Orb watch registration result (application state, not screen text): '
                + json.dumps(receipt, ensure_ascii=False)
                + '. Acknowledge only actual registration/cancellation. If paused, explain why; '
                'never promise active monitoring when unavailable. For unchanged/no-change, answer '
                'the user normally without a canned watch acknowledgement.')
        return dict(watch_receipt=receipt, context=text, current_turn_context=text)

    def collect(self, history, *, request_kind, config):
        if request_kind != 'normal_chat' or not history or self._closed:
            return {}
        latest = history[-1]
        if not real_dialogue(latest) or latest.get('role') != 'user':
            return {}
        snapshot = self.current(config)
        if not config.get('companion_orb_enabled'):
            return {}
        scope = self.runtime.conversation_scope()
        key = turn_key(latest)
        if not scope.get('available') or not key:
            return self._receipt('unavailable', 'No stable conversation/user-turn identity.')
        cache_key = (scope['session_key'], key)
        with self._lock:
            if scope.get('latest_user_key') != key:
                return self._receipt('stale', 'This is no longer the latest real user turn.')
            if cache_key in self._receipts:
                saved = self._receipts[cache_key]
                revision = saved.get('watch_receipt', {}).get('collection_revision')
                if revision is not None and revision != snapshot['collection_revision']:
                    return self._receipt('stale', 'This registration was superseded.')
                return deepcopy(saved)
            self._receipts[cache_key] = self._receipt('pending', 'Interpretation is still running.')
        try:
            data = self.runtime.interpret_watch_intent(user_text=user_text(latest),
                recent_dialogue=history[:-1], active_task=snapshot,
                timeout_seconds=float(config.get('companion_orb_vision_timeout_seconds', 11)))
            intent = parse_watch_intent(json.dumps(data))
            for operation in intent['operations']:
                if operation['operation'] in {'add','update'}:
                    operation['spec']['original_request'] = user_text(latest)
            with self._lock:
                fresh = self.runtime.conversation_scope()
                if (self._closed or fresh != scope or
                        self.state.snapshot()['collection_revision'] != snapshot['collection_revision']):
                    result = self._receipt('stale', 'The originating task or conversation changed.')
                else:
                    receipt = self.state.apply_batch(intent, session_key=scope['session_key'], turn_key=key,
                        expected_collection_revision=snapshot['collection_revision'])
                    current = self.state.snapshot()
                    result = self._receipt(receipt['status'], receipt['message'],
                        collection_revision=receipt['collection_revision'],
                        changes={k:receipt.get(k,[]) for k in ('added','updated','removed')}, task=current,
                        paused_reasons=self._paused_reasons(config, current) if current['active'] else [])
        except Exception as exc:
            result = self._receipt('unavailable', f'Watch interpretation failed: {type(exc).__name__}. No task was changed.')
        with self._lock:
            self._receipts[cache_key] = deepcopy(result)
            while len(self._receipts) > 512:
                self._receipts.popitem(last=False)
        self.on_change()
        self.record('watch.registration_result',result,session_key=scope['session_key'],turn_id=key)
        return result
