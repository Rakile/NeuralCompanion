"""One bounded, private draft job using the existing provider capability.

The HTTP handlers only start/poll/cancel. Model work never runs on the Qt
thread, creates a conversation turn, or reaches a speech/addon action.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Callable

from core.conversation_command_definitions import WRITING
from core.runtime.contracts import CancellationToken
from .story_plan import STORY_PACE_REPLY_RANGES, validate_story_plan


logger = logging.getLogger(__name__)


def _parse_story_plan(text: str) -> dict[str, Any]:
    """Accept a valid plan even when a model adds prose or a code fence."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{', text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
            if isinstance(value, dict):
                constraints = value.get('constraints')
                if isinstance(constraints, list) and all(isinstance(item, str) for item in constraints):
                    value['constraints'] = '\n'.join(item.strip() for item in constraints if item.strip())
                if not str(value.get('constraints') or '').strip():
                    value['constraints'] = 'None specified.'
                return validate_story_plan(value)
        except (ValueError, TypeError):
            continue
    raise ValueError('No valid Story Plan object')


STORY_REFINE_PROMPT = (
    "Refine the user's long-story request into a paced Story Plan, not story prose. "
    "Preserve explicit characters, events, boundaries, tone and constraints. "
    "Make each beat broad enough to develop across several assistant replies. "
    "Return only one JSON object with title, premise, constraints, opening_cue, "
    "and beats (an array of 2 to 30 objects, each with title and summary). "
    "If the user gives no constraints, set constraints to 'None specified.'. "
    "The opening cue must request only the first scene. Do not pre-create character cards, "
    "invent factual claims or narrate the ending."
)


class PhoneCommandDrafts:
    def __init__(self, provider: Any, scope: Callable[[], object | None], *, clock=time.monotonic,
                 model_resolver: Callable[[str, str], tuple[str, str]] | None = None,
                 extension_context: Callable[[dict[str, Any]], str] | None = None):
        self._provider = provider
        self._scope = scope
        self._model_resolver = model_resolver
        self._extension_context = extension_context
        self._clock = clock
        self._lock = threading.RLock()
        self._job: dict[str, Any] | None = None
        self._thread: threading.Thread | None = None
        self._closed = False

    @property
    def available(self) -> bool:
        return not self._closed and callable(getattr(self._provider, 'complete', None))

    def choices(self) -> list[dict[str, str]]:
        return ([{'name': name, 'description': definition[0]} for name, definition in WRITING.items()]
                + [{'name': 'story_refine', 'description': 'Turn a long story prompt into a paced Story Plan'}]) if self.available else []

    def _retire(self, job: dict[str, Any]) -> None:
        job['token'].cancel('phone_draft_cancelled')
        job['result'] = {'id': job['id'], 'status': 'cancelled'}
        job.pop('text', None)
        job['timer'].cancel()

    def handle(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        key = payload.get('id')
        if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}', key):
            raise ValueError('A private draft id is required.')
        if action not in {'start', 'status', 'cancel'}:
            raise ValueError('Unknown draft action.')
        scope = self._scope()
        with self._lock:
            if not self.available:
                raise ValueError('Phone writing drafts are unavailable.')
            job = self._job
            if job and (scope is None or job['scope'] != scope or self._clock() >= job['deadline']):
                self._retire(job)
            if action != 'start':
                if not job or job['id'] != key:
                    raise ValueError('Draft unavailable or expired.')
                if action == 'cancel':
                    self._retire(job)
                return dict(job['result'])
            command, text = payload.get('command'), payload.get('text')
            if not isinstance(command, str) or command not in {*WRITING, 'story_refine', 'story_extend'}:
                raise ValueError('Unknown writing command.')
            if not isinstance(text, str) or not text.strip() or len(text) > 8000:
                raise ValueError('Enter between 1 and 8000 characters for the draft.')
            if scope is None:
                raise ValueError('Start the desktop runtime before drafting.')
            options = self._story_options(payload.get('options'), extension=command == 'story_extend') if command in {'story_refine', 'story_extend'} else {}
            if job and job['id'] == key:
                if job['command'] != command or job.get('text') != text or job['options'] != options:
                    raise ValueError('This draft id has already been used.')
                return dict(job['result'])
            if self._thread and self._thread.is_alive():
                raise ValueError('A draft is still finishing. Please wait.')
            token = CancellationToken()
            job = {'id': key, 'command': command, 'text': text, 'scope': scope, 'options': options,
                   'deadline': self._clock() + 180, 'token': token,
                   'result': {'id': key, 'status': 'working'}}
            if self._job:
                self._job['timer'].cancel()
            timer = threading.Timer(180, lambda: self._expire(job))
            timer.daemon = True
            job['timer'] = timer
            self._job = job
            timer.start()
            self._thread = threading.Thread(target=self._generate, args=(job,), name='nc-phone-draft', daemon=True)
            self._thread.start()
            return dict(job['result'])

    @staticmethod
    def _story_options(value: object, *, extension: bool = False) -> dict[str, Any]:
        if value is None:
            if extension:
                raise ValueError('Refresh the story before extending it.')
            return {}  # Older phone clients retain their original behavior.
        allowed = {'beat_count', 'pace', 'provider_id', 'model_id'} | (
            {'plan_id', 'revision'} if extension else
            {'temperature', 'follow_prompt', 'beat_detail', 'reference_plan'})
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError('Invalid Story Refine options.')
        count, pace = value.get('beat_count', 8), value.get('pace', 'medium')
        if type(count) is not int or not 2 <= count <= 30:
            raise ValueError('Choose between 2 and 30 story beats.')
        if extension and (not 5 <= count <= 20 or type(value.get('revision')) is not int
                          or not isinstance(value.get('plan_id'), str)
                          or not re.fullmatch(r'[a-f0-9]{32}', value['plan_id'])):
            raise ValueError('Choose 5–20 extra beats from the current story.')
        if not isinstance(pace, str) or pace not in STORY_PACE_REPLY_RANGES:
            raise ValueError('Choose Slow, Medium or Fast story pace.')
        provider, model = value.get('provider_id', ''), value.get('model_id', '')
        if (not isinstance(provider, str) or not isinstance(model, str)
                or bool(provider) != bool(model) or len(provider) > 128 or len(model) > 200):
            raise ValueError('Choose a configured refinement model.')
        settings: dict[str, Any] = {}
        if not extension:
            if 'temperature' in value:
                temperature = value['temperature']
                if type(temperature) not in (float, int) or not 0 <= temperature <= 2:
                    raise ValueError('Choose a temperature between 0 and 2.')
                settings['temperature'] = float(temperature)
            for key, choices in (('follow_prompt', {'closely', 'balanced', 'flexible'}),
                                 ('beat_detail', {'short', 'standard', 'detailed'})):
                if key in value:
                    if not isinstance(value[key], str) or value[key] not in choices:
                        raise ValueError('Invalid Story Refine setting.')
                    settings[key] = value[key]
            if 'reference_plan' in value:
                reference = validate_story_plan(value['reference_plan'])
                if len(json.dumps(reference)) > 32000:
                    raise ValueError('The current plan is too long to use as a reference.')
                settings['reference_plan'] = reference
        return {'beat_count': count, 'pace': pace, 'provider_id': provider, 'model_id': model,
                **settings, **({'plan_id': value['plan_id'], 'revision': value['revision']} if extension else {})}

    def _generate(self, job: dict[str, Any]) -> None:
        stage = 'provider'
        try:
            story = job['command'] in {'story_refine', 'story_extend'}
            instruction = STORY_REFINE_PROMPT if story else WRITING[job['command']][1]
            options = job['options']
            model_kwargs: dict[str, str] = {}
            if story and options:
                low, high = STORY_PACE_REPLY_RANGES[options['pace']]
                instruction += (f" Return exactly {options['beat_count']} beats. Use {options['pace']} progression: "
                                f"each beat should develop over roughly {low}–{high} assistant replies. "
                                "Keep beat summaries concise (under 500 characters each).")
                if options['provider_id']:
                    if not self._model_resolver:
                        raise ValueError('Model selection is unavailable.')
                    provider, model = self._model_resolver(options['provider_id'], options['model_id'])
                    model_kwargs = {'provider_id': provider, 'model_id': model}
            if job['token'].cancelled:
                return
            text_input = job['text']
            if job['command'] == 'story_extend':
                stage = 'context'
                if not self._extension_context:
                    raise ValueError('Story extension is unavailable.')
                text_input = self._extension_context(options) + '\nNext-direction request: ' + text_input
                instruction += (' This is a continuation of the existing story. Return new beats only; '
                    'do not repeat the earlier outline, restart the story or overwrite established events. '
                    'Keep the original premise and constraints. Use distinct new beat titles. '
                    'The opening cue should request the first new scene, not the original opening.')
                if self._scope() != job['scope'] or job['token'].cancelled:
                    return
            elif job['command'] == 'story_refine' and options.get('reference_plan'):
                instruction += (' Use the current edited plan as a reference. Preserve deliberate edits and established '
                                'constraints, but return one complete replacement draft for review; do not continue the story.')
                text_input += '\nCurrent edited plan for reference:\n' + json.dumps(options['reference_plan'])
            if job['command'] == 'story_refine':
                instruction += {
                    'closely': ' Follow the supplied story prompt closely; avoid introducing unrelated turns.',
                    'balanced': ' Follow the supplied story prompt while allowing coherent connective events.',
                    'flexible': ' Allow creative connective events while preserving explicit constraints.',
                }.get(options.get('follow_prompt'), '')
                instruction += {
                    'short': ' Keep each beat summary brief and focused.',
                    'standard': ' Give each beat enough detail to guide multiple replies.',
                    'detailed': ' Give each beat a concrete scene goal, progression, and transition.',
                }.get(options.get('beat_detail'), '')
            params = {'messages': [
                {'role': 'system', 'content': instruction +
                 " Preserve explicit constraints and the user's intent. Return only the requested draft, without a preamble. Do not invent factual claims."},
                {'role': 'user', 'content': text_input},
            ]}
            if story:
                params['max_tokens'] = max(3200, 1200 + options.get('beat_count', 8) * 200)
            if 'temperature' in options:
                params['temperature'] = options['temperature']
            stage = 'provider'
            text = str(self._provider.complete(params, cancellation=job['token'],
                use_generation_fields=True, **model_kwargs) or '').strip()
            stage = 'output'
            if not text or len(text) > 32000:
                raise ValueError('Invalid draft length')
            if story:
                plan = _parse_story_plan(text)
                if options:
                    if len(plan['beats']) != options['beat_count']:
                        raise ValueError('Incorrect beat count')
                    plan['pace'] = options['pace']
                result = {'id': job['id'], 'status': 'ready', 'plan': plan}
            else:
                result = {'id': job['id'], 'status': 'ready', 'text': text}
        except Exception as exc:
            # Provider exceptions and model text may contain private data.
            logger.warning('Phone draft failed at %s stage (%s)', stage, type(exc).__name__)
            result = {'id': job['id'], 'status': 'error',
                      'error': ('The story changed or its history is unavailable. Close this draft, refresh Story Plan and try again.'
                                if stage == 'context' else
                                'The desktop model did not return a valid Story Plan. Try again or choose a different model.'
                                if stage == 'output' and job['command'] in {'story_refine', 'story_extend'} else
                                'Draft generation failed. Check the desktop provider and try again.')}
        with self._lock:
            if self._job is job and not job['token'].cancelled:
                job['result'] = result

    def _expire(self, job: dict[str, Any]) -> None:
        with self._lock:
            if self._job is job:
                self._retire(job)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._job:
                self._retire(self._job)
