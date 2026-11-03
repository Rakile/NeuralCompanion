"""Bounded, optional scene decisions; never part of the speech completion gate."""
from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping, Sequence
from typing import Callable

from core.runtime.contracts import CancellationToken

_WORDS = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP = frozenset({'the', 'and', 'with', 'from', 'into', 'over', 'under', 'this', 'that',
                   'there', 'their', 'they', 'them', 'have', 'will', 'would', 'your',
                   'you', 'for', 'are', 'was', 'were', 'his', 'her', 'she', 'him',
                   'our', 'its', 'but', 'not', 'now', 'then', 'look', 'move', 'closer'})
_ALIASES = {
    'urban': 'city', 'downtown': 'city', 'alley': 'street', 'road': 'street',
    'cars': 'traffic', 'car': 'traffic', 'woodland': 'forest', 'woods': 'forest',
    'trees': 'forest', 'jungle': 'forest', 'insects': 'crickets',
    'rainfall': 'rain', 'stormy': 'storm', 'terrifying': 'horror',
    'terrified': 'horror', 'scary': 'horror', 'ominous': 'tense',
}


def _tokens(value: object) -> set[str]:
    words = set()
    for word in _WORDS.findall(str(value or '')[:12000].casefold()):
        if len(word) < 3 or word in _STOP:
            continue
        words.add(_ALIASES.get(word, word))
    return words


def _beat_text(plan: Mapping[str, object] | None) -> str:
    if not isinstance(plan, Mapping):
        return ''
    beats = plan.get('beats')
    index = plan.get('current_beat')
    if not isinstance(beats, list) or type(index) is not int or not 0 <= index < len(beats):
        return ''
    beat = beats[index]
    if isinstance(beat, Mapping):
        return ' '.join(str(beat.get(key) or '')[:1000] for key in ('title', 'summary', 'description'))
    return str(beat or '')[:1000]


def _asset_score(scene: set[str], item: Mapping[str, object]) -> int:
    title = _tokens(item.get('title'))
    tags = _tokens(' '.join(str(tag) for tag in (item.get('tags') or [])[:20]))
    if item.get('discarded') or not scene.intersection(tags):
        return 0
    category = _tokens(item.get('category'))
    description = _tokens(item.get('description'))
    return (3 * len(scene & title) + 3 * len(scene & tags)
            + 2 * len(scene & category) + len(scene & description))


def choose_scene(text: str, plan: Mapping[str, object] | None, assets: Sequence[Mapping[str, object]],
                 layers: Sequence[str]) -> dict[str, str]:
    """Fast metadata fallback when a low-priority model request cannot be admitted."""
    scene = _tokens(str(text or '')[-12000:]) | _tokens(_beat_text(plan))
    result = {}
    for layer in layers:
        if layer not in ('ambience', 'music', 'effect'):
            continue
        ranked: list[tuple[int, str]] = []
        for item in assets:
            if item.get('kind') != layer or not re.fullmatch(r'[0-9a-f]{32}', str(item.get('id') or '')):
                continue
            score = _asset_score(scene, item)
            if score >= 2:
                ranked.append((score, str(item['id'])))
        result[layer] = max(ranked)[1] if ranked else 'keep'
    return result


def parse_decision(raw: str, allowed: Mapping[str, set[str]]) -> dict[str, str] | None:
    """Accept only exact layer actions and library IDs from the request snapshot."""
    try:
        value = json.loads(str(raw or '').strip())
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or set(value) != set(allowed):
        return None
    if any(type(action) is not str or action not in {'keep', 'clear'} | ids
           for layer, ids in allowed.items() for action in (value[layer],)):
        return None
    return dict(value)


class SoundscapeDirector:
    """Keep one reply-scoped suggestion; an optional cloud model may refine it.

    Local-model inference is deliberately not admitted here: a second request
    would hold the same inference lock ahead of a new chat or Continuous turn.
    The metadata decision keeps Follow story useful without that contention.
    """

    def __init__(self, state: Callable[[str], dict], assets: Callable[[], list[dict]],
                 *, provider: object | None = None,
                 model: Callable[[], tuple[str, str]] | None = None, feedback=None) -> None:
        self._state = state
        self._assets = assets
        self._provider = provider
        self._model = model
        self._feedback = feedback
        self._lock = threading.RLock()
        self._cue: dict | None = None
        self._token = CancellationToken()
        self._thread: threading.Thread | None = None
        self._serial = 0
        self._observed: tuple[str, int, str, str] | None = None
        self._closed = False

    def observe(self, conversation_id: str, session_generation: int, assistant_id: str,
                reply_id: str, text: str, plan: Mapping[str, object] | None) -> None:
        if self._closed or not conversation_id or not reply_id or not assistant_id or not text.strip():
            return
        state = self._state(conversation_id)
        with self._lock:
            identity = (conversation_id, session_generation, assistant_id, reply_id)
            if self._observed == identity:
                return
            prior = self._cue
            if (prior is not None and prior['conversation_id'] == conversation_id
                    and prior['session_generation'] == session_generation
                    and prior['assistant_id'] == assistant_id and prior['reply_id'] == reply_id
                    and prior['revision'] == state['revision']):
                return
        layers = tuple(name for name in ('ambience', 'music') if state['enabled'] and not state['paused']
                       and state[name]['follow_story'])
        if state['enabled'] and not state['paused'] and state.get('effects',{}).get('enabled') and not state['effects'].get('muted'):
            layers += ('effect',)
        if not layers:
            self.invalidate(conversation_id)
            return
        assets = [item for item in self._assets() if item.get('kind') in layers and not item.get('discarded') and item.get('tags')]
        if not assets:
            self.invalidate(conversation_id)
            return
        actions = choose_scene(text, plan, assets, layers)
        scene = _tokens(text) | _tokens(_beat_text(plan))
        if self._feedback:
            for layer in layers:
                if self._feedback.suppressed(conversation_id,session_generation,reply_id,layer):
                    actions[layer]='keep'
                    continue
                ranked=[(_asset_score(scene,item)+self._feedback.bonus(item['id'],scene),item['id'])
                        for item in assets if item['kind']==layer and _asset_score(scene,item)>0]
                if ranked:actions[layer]=max(ranked)[1]
        effect_id=actions.pop('effect',None)
        effect=next((item for item in assets if item['id']==effect_id and item['kind']=='effect'),None)
        try:
            provider_id, model_id = self._model() if self._model is not None else ('', '')
        except (RuntimeError, ValueError):
            provider_id, model_id = '', ''
        with self._lock:
            self._token.cancel('superseded')
            self._token = CancellationToken()
            self._serial += 1
            serial = self._serial
            self._observed = identity
            self._cue = {'id': f'{assistant_id}:{serial}', 'conversation_id': conversation_id,
                         'session_generation': session_generation, 'assistant_id': assistant_id,
                         'reply_id': reply_id, 'revision': state['revision'],
                         'story_revision': plan.get('revision') if isinstance(plan, Mapping) else None,
                         'actions': actions,
                         'effect': {'asset_id':effect['id'],'asset_revision':effect.get('revision',0)} if effect else None,
                         'asset_revisions': {item['id']:item.get('revision',0) for item in assets},
                         'excerpt':text[:500], 'tokens':sorted(t[:32] for t in scene)[:128]}
            # Never create a backlog of optional calls; a prior provider call
            # may ignore cancellation until its own network timeout.
            if self._provider is None or (self._thread and self._thread.is_alive()):
                return
            if not provider_id or not model_id:
                return
            token = self._token
            self._thread = threading.Thread(
                target=self._refine, args=(serial, token, provider_id, model_id,
                                           conversation_id, state['revision'], text[-12000:],
                                           _beat_text(plan), assets, layers),
                name='nc-soundscape-director', daemon=True)
            self._thread.start()

    def _refine(self, serial: int, token: CancellationToken, provider_id: str, model_id: str,
                conversation_id: str, revision: int, text: str, beat: str,
                assets: list[dict], layers: tuple[str, ...]) -> None:
        timer = threading.Timer(5, lambda: token.cancel('selection_budget'))
        timer.daemon = True
        timer.start()
        try:
            scene = _tokens(text) | _tokens(beat)
            ordered = []
            for layer in layers:
                matches = (item for item in assets if item.get('kind') == layer and _asset_score(scene,item)>0)
                ordered.extend(sorted(matches, key=lambda item: _asset_score(scene, item),
                                      reverse=True)[:32 // len(layers)])
            candidates = [{'id': item['id'], 'kind': item['kind'],
                           'title': str(item.get('title') or '')[:80],
                           'description': str(item.get('description') or '')[:100],
                           'category': str(item.get('category') or '')[:40],
                           'tags': [str(tag)[:24] for tag in (item.get('tags') or [])[:5]]}
                          for item in ordered]
            prompt = {'opening_scene': text[-5000:], 'story_beat': beat[:500],
                      'saved_sounds': candidates}
            while candidates and len(json.dumps(prompt, ensure_ascii=False)) > 12000:
                candidates.pop()
            if not candidates or token.cancelled:
                return
            allowed = {layer: {str(item['id']) for item in candidates if item['kind'] == layer}
                       for layer in layers}
            result = self._provider.complete({
                'messages': [
                    {'role': 'system', 'content': 'Choose a saved background for the opening or dominant scene. '
                     'Return ONLY one JSON object with exactly the requested layer keys. '
                     'Each value is a listed sound id, "keep", or "clear". '
                     'Prefer keep when the scene is unclear. Never invent ids.'},
                    {'role': 'user', 'content': json.dumps(prompt, ensure_ascii=False)},
                ], 'max_tokens': 150}, provider_id=provider_id, model_id=model_id,
                cancellation=token, use_generation_fields=True)
            decision = parse_decision(str(result or ''), allowed)
            if decision is None or token.cancelled or self._state(conversation_id)['revision'] != revision:
                return
            with self._lock:
                if not self._closed and serial == self._serial and not token.cancelled and self._cue:
                    effect_id=decision.pop('effect',None)
                    effect=next((item for item in assets if item['id']==effect_id and item['kind']=='effect'),None)
                    self._cue['actions'] = decision
                    self._cue['effect'] = {'asset_id':effect['id'],'asset_revision':effect.get('revision',0)} if effect else None
                    self._cue['id'] = f'{self._cue["assistant_id"]}:{serial}:refined'
        except Exception:
            pass  # The fast metadata suggestion remains; chat never waits here.
        finally:
            timer.cancel()

    def snapshot(self, conversation_id: str, session_generation: int) -> dict | None:
        with self._lock:
            cue = dict(self._cue) if self._cue is not None else None
        if (cue is None or cue['conversation_id'] != conversation_id
                or cue['session_generation'] != session_generation
                or self._state(conversation_id)['revision'] != cue['revision']):
            return None
        return cue

    def invalidate(self, conversation_id: str, reason: str = 'changed') -> None:
        with self._lock:
            if self._cue is None or self._cue['conversation_id'] == conversation_id:
                self._token.cancel(reason)
                self._cue = None
                self._serial += 1

    def wait(self, timeout: float) -> bool:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._token.cancel('shutdown')
            self._cue = None
