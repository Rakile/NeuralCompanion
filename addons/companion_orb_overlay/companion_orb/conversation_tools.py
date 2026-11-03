"""Turn-owned Orb tools. The model proposes; the existing state owner commits."""
from __future__ import annotations

import json
import threading
import time
import uuid

from core.conversation_tools import ToolCall, ToolOutcome, plain_json, strict_arguments
from .conversation_context import OrbConversationContext
from .watch_intent import real_dialogue, user_text, turn_key as message_key


def tool_definitions():
    policy = dict(instruction={'type': 'string', 'description': 'The user’s task. Resolve references, but do not add restrictions from screenshots.'},
        observation_question={'type':'string','description':'For ongoing commentary, ask what the screenshot reader should describe; otherwise empty.'},
        response_mode={'type': 'string', 'enum': ['each_check', 'when_condition', 'on_change'],
            'description': 'each_check = keep commenting, including unchanged scenes; when_condition = alert if a condition becomes true; on_change = alert when a specific watched value changes.'},
        once={'type': 'boolean', 'description': 'True only when the user requests stopping after the first alert; otherwise false.'})
    def obj(properties):
        return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)
    def tool(name, description, properties):
        return dict(type='function', name=name, description=description, parameters=obj(properties))
    return [tool('inspect_desktop', 'Inspect the desktop NOW for a one-off screen question, unclear reference, or hover target. Clear watch requests need no inspection.',
                 {'question': {'type': 'string'}}),
        tool('focus_orb', 'Request the Orb, not the mouse cursor, to hover near a named visible target. The result confirms queued or rejected, not completed movement.',
             {'target': {'type': 'string','minLength':1,'maxLength':160}}),
        tool('start_watches', 'Register independent ongoing user requests. Acknowledge registration only; scheduled checks deliver observations and alerts. Answer separate one-off questions normally.',
             {'watches': {'type': 'array', 'minItems': 1, 'maxItems': 32, 'items': obj(policy)}}),
        tool('update_watch', 'Replace only one identified watch; preserve other watches.',
             {'watch_id': {'type': 'string'}, **policy}),
        tool('stop_watch', 'Stop one identified watch.', {'watch_id': {'type': 'string'}})]


def _watch_rows(state):
    return [dict(id=w['id'], instruction=w['spec']['instruction'], status=w['status'],
        **({k:w['spec'][k] for k in ('response_mode','once')} if w['spec'].get('version')==3
            else {'condition':w['spec']['condition']})) for w in state.get('watches',[])]


class OrbConversationTools:
    def __init__(self, watch_context, orb):
        self.watch_context, self.orb = watch_context, orb
        self.inspection = OrbConversationContext(orb)
        self._lock = threading.RLock()
        self._ticket = None
        self._last_focus_result = None

    def offer(self, *, history: list[dict], session_key: str, turn_key: str, is_current=None) -> dict:
        with self._lock:
            config = self.orb._last_runtime_config
            state = self.watch_context.current(config)
            scope = self.watch_context.runtime.conversation_scope()
            latest = history[-1] if history else {}
            if (self.watch_context._closed or not config.get('companion_orb_enabled') or not scope.get('available')
                    or scope.get('session_key') != session_key or scope.get('latest_user_key') != turn_key
                    or not real_dialogue(latest) or latest.get('role') != 'user' or message_key(latest) != turn_key):
                return dict(available=False, reason='No current Orb conversation turn.')
            ticket = uuid.uuid4().hex
            self._ticket = dict(id=ticket, session_key=session_key, turn_key=turn_key,
                revision=state['collection_revision'], original_request=user_text(latest),
                is_current=is_current or (lambda: True))
            if self._last_focus_result and self._last_focus_result[0] != session_key:
                self._last_focus_result = None
            focus_context = ('\nLatest hover request result (not current position; data): '
                + json.dumps(self._last_focus_result[1], ensure_ascii=False)) if self._last_focus_result else ''
            return dict(available=True, ticket=ticket, tools=tool_definitions(),
                watches=_watch_rows(state),
                context='Use tools for desktop questions, Orb focus and watch changes; saying it does not perform it. Clarify ambiguous requests. '
                'Register clear watches without inspecting; acknowledge registration only, leaving observations and alerts to scheduled checks. Inspect afresh for separate screen questions; answer other questions normally. '
                'Preserve the requested scope and timing, even when a target is invisible. Application receipts confirm actions; current watch state accompanies the latest user request.'
                + focus_context)

    def current(self, ticket: str) -> bool:
        with self._lock:
            saved = self._ticket
            if (not saved or saved['id'] != ticket or self.watch_context._closed
                    or not self.orb._last_runtime_config.get('companion_orb_enabled') or not saved['is_current']()):
                return False
            scope = self.watch_context.runtime.conversation_scope()
            state = self.watch_context.state.snapshot()
            return bool(scope.get('available') and scope.get('session_key') == saved['session_key']
                and scope.get('latest_user_key') == saved['turn_key']
                and state['session_key'] == saved['session_key'] and state['collection_revision'] == saved['revision'])

    def publish(self, ticket, publish):
        # Only a local caller can supply this callback. Never invoke it during inference.
        with self._lock:
            if not callable(publish) or not self.current(ticket):
                return None
            saved = self._ticket
            return self.watch_context.state.publish_tool_reply(saved['session_key'], saved['revision'], publish)

    def current_state(self, ticket):
        with self._lock:
            if not self.current(ticket):
                return dict(current=False, watches=[])
            state=self.watch_context.state.snapshot()
            if state['collection_revision']!=self._ticket['revision'] or state['session_key']!=self._ticket['session_key']:
                return dict(current=False, watches=[])
            return dict(current=True,watches=_watch_rows(state))

    def execute(self, ticket: str, call: ToolCall) -> ToolOutcome:
        def failure(message):
            return ToolOutcome(call.call_id, False, {'error': message}, message)
        if not self.current(ticket):
            return failure('This Orb request is no longer current. No action was taken.')
        with self._lock:
            correlation={key:self._ticket[key] for key in ('session_key','turn_key')}
        correlation['turn_id']=correlation.pop('turn_key')
        began=time.monotonic()
        self.watch_context.record('orb.tool.request', dict(name=call.name, arguments=call.arguments, call_id=call.call_id),**correlation)
        try:
            args = strict_arguments(call.arguments)
            # Accept older callers without letting registration inspect the screen.
            # Separate one-off questions use inspect_desktop; watches own results.
            initial_question = args.pop('initial_question', '') if call.name == 'start_watches' else ''
            if not isinstance(initial_question, str) or len(initial_question) > 6000:
                raise ValueError('Initial inspection question must be a string of at most 6000 characters.')
            if call.name == 'focus_orb':
                target=args.get('target')
                if set(args)!={'target'} or not isinstance(target,str) or not target.strip() or len(target)>160:
                    raise ValueError('Hover requires a named target of 1–160 characters, not coordinates.')
                with self._lock:
                    if not self.current(ticket):
                        return failure('This Orb request is no longer current. No action was taken.')
                    config=self.orb._last_runtime_config
                    handler=getattr(self.orb,'handle_assistant_focus',None)
                    if not config.get('companion_orb_vision_enabled') or not config.get('companion_orb_spatial_conversational_focus_enabled',True):
                        focused=dict(ok=False,reason='disabled')
                    elif not callable(handler):
                        focused=dict(ok=False,reason='unavailable')
                    else:
                        focused=handler(dict(region_id='locate',target=target.strip(),action='hover'),
                            is_current=lambda:self.current(ticket)) or {}
                queued=bool(focused.get('ok') and focused.get('queued'))
                reason=str(focused.get('reason') or 'localization could not be queued')
                result=ToolOutcome(call.call_id,queued,dict(queued=queued,moved=False,target=target.strip()),
                    f'Orb hover requested near {target.strip()}. Movement is not yet confirmed.' if queued else
                    f'The Orb could not start hovering near {target.strip()}: {reason}.')
            elif call.name == 'inspect_desktop':
                if (set(args) != {'question'} or not isinstance(args['question'], str)
                        or not args['question'].strip() or len(args['question']) > 6000):
                    raise ValueError('Inspection requires a nonempty question of at most 6000 characters.')
                observed = self.inspection.inspect(args['question'])
                if not self.current(ticket):
                    return failure('The turn changed during capture; its evidence was discarded.')
                result = ToolOutcome(call.call_id, bool(observed.get('available')), observed)
            else:
                with self._lock:
                    if not self.current(ticket):
                        return failure('This Orb request is no longer current. No action was taken.')
                    saved = self._ticket
                    applied = self.watch_context.state.apply_tool(call.name, args,
                        session_key=saved['session_key'], turn_key=saved['turn_key'], call_id=call.call_id,
                        expected_collection_revision=saved['revision'], original_request=saved['original_request'])
                    if applied['ok']:
                        saved['revision'] = applied['collection']['collection_revision']
                self.watch_context.on_change()
                receipt = applied['receipt']
                pauses = (self.watch_context.current(self.orb._last_runtime_config)['paused_reasons']
                    if applied['collection']['active'] else [])
                if applied['ok'] and pauses:
                    receipt += ' Monitoring paused: ' + '; '.join(pauses) + '.'
                result = ToolOutcome(call.call_id, applied['ok'], dict(ok=applied['ok'],
                    watch_ids=applied['watch_ids'], paused_reasons=pauses), receipt)
        except (TypeError, ValueError) as exc:
            result = failure(f'No Orb action was taken: {exc}')
        except Exception as exc:
            result = failure(f'The Orb operation failed ({type(exc).__name__}).')
        if call.name == 'focus_orb':
            with self._lock:
                if self.current(ticket):
                    self._last_focus_result = (self._ticket['session_key'], dict(
                        ok=result.ok, content=plain_json(result.content), receipt=result.receipt))
        self.watch_context.record('orb.tool.result', dict(call_id=call.call_id, ok=result.ok,
            receipt=result.receipt, seconds=time.monotonic()-began,
            content={k: v for k, v in result.content.items() if k != 'image'}),**correlation)
        return result
