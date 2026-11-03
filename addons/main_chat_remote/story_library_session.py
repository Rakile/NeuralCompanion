"""Guarded named-story capture and restore over the existing chat owners."""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from core import continuity_memory

from .story_library_scope import clone_chat_scope
from .story_library_store import StoryLibraryStore
from .story_plan import StoryPlanStore


class StoryLibrarySession:
    def __init__(self, store: StoryLibraryStore, chat: Any, plans: StoryPlanStore,
                 cast: Callable[[dict[str, object]], dict[str, object]],
                 scope: Callable[[], Mapping[str, object]], stop_playback: Callable[[], None],
                 refresh: Callable[[], None], transport: Any = None, soundscape: Any = None,
                 visual_auto: Any = None) -> None:
        self.store, self.chat, self.plans, self.cast = store, chat, plans, cast
        self.scope, self.stop_playback, self.refresh = scope, stop_playback, refresh
        self.transport = transport
        self.soundscape = soundscape
        self.visual_auto = visual_auto
        self.active_entry_id: str | None = None
        self._recovery_token: str | None = None
        self._lock = threading.RLock()
        self._receipts: OrderedDict[str, tuple[str, dict[str, object]]] = OrderedDict()

    @property
    def _plan_store(self) -> StoryPlanStore:
        return getattr(self.plans, 'store', self.plans)

    @staticmethod
    def _export_chat(chat: Any, target: Path) -> None:
        report = chat.export_story(target)
        if isinstance(report, Mapping) and report.get('missing'):
            raise ValueError('A chat image is missing; this story was not saved.')

    def _current(self, request: Mapping[str, object]) -> dict[str, object]:
        current = dict(self.scope())
        if (type(request.get('session_generation')) is not int
                or current.get('session_generation') != request['session_generation']
                or not current.get('conversation_id')):
            raise ValueError('The conversation changed. Refresh and try again.')
        return current

    def _capture_boundary(self, generation: int) -> dict[str, object]:
        deadline = time.monotonic() + 15
        while True:
            current = dict(self.scope())
            if current.get('session_generation') != generation:
                raise ValueError('The conversation changed while saving.')
            reason = str(current.get('disabled_reason') or '')
            plan = self._plan_store.snapshot(str(current['conversation_id']))
            completed_turn = (current.get('last_role', 'assistant') == 'assistant'
                              and current.get('latest_assistant_id'))
            if not reason and (completed_turn or (plan and plan['status'] == 'saved'
                                                   and not current.get('latest_assistant_id'))):
                if not self._wait_plan_assessment(str(current['conversation_id']),
                                                  str(current.get('latest_assistant_id') or ''), deadline):
                    raise TimeoutError('Story progress is still being checked. Try Save again.')
                return dict(self.scope())
            if time.monotonic() >= deadline:
                raise TimeoutError('Wait for the assistant reply to finish before saving.')
            time.sleep(.05)

    def _wait_plan_assessment(self, conversation_id: str, assistant_id: str,
                              deadline: float) -> bool:
        pending = getattr(self.plans, 'pending', None)
        wait = getattr(self.plans, 'wait_for_observation', None)
        if callable(pending) and callable(wait) and pending(conversation_id, assistant_id):
            return bool(wait(max(0, deadline - time.monotonic())))
        return True

    def _capture(self, folder: Path, boundary: Mapping[str, object]) -> dict[str, object]:
        conversation_id = str(boundary['conversation_id'])
        self._export_chat(self.chat, folder / 'chat_context.json')
        cast_dir = folder / 'cast'
        cast_meta = self.cast({'action': 'story-export', 'conversation_id': conversation_id,
                               'target_dir': str(cast_dir)})
        plan = self._plan_store.snapshot(conversation_id)
        (folder / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        if self.visual_auto:
            (folder / 'visual_auto.json').write_text(
                json.dumps(self.visual_auto.export(conversation_id), ensure_ascii=False), encoding='utf-8')
        sounds = self.soundscape.capture(conversation_id, folder) if self.soundscape else None
        payload = json.loads((folder / 'chat_context.json').read_text(encoding='utf-8'))
        if payload.get('continuity_memory_enabled'):
            memory = continuity_memory.load_memory(payload.get('continuity_memory_id'))
            (folder / 'memory.json').write_text(json.dumps(memory, ensure_ascii=False), encoding='utf-8')
        after = dict(self.scope())
        after_plan = self._plan_store.snapshot(conversation_id)
        after_cast = self.cast({'action': 'story-revision', 'conversation_id': conversation_id})
        if (after.get('conversation_id') != conversation_id
                or after.get('session_generation') != boundary.get('session_generation')
                or after.get('revision') != boundary.get('revision')
                or (after_plan or {}).get('revision') != (plan or {}).get('revision')
                or after_cast.get('revision') != cast_meta.get('revision')
                or (sounds is not None and self.soundscape.state.snapshot(conversation_id)['revision'] != sounds['state']['revision'])):
            raise ValueError('The conversation changed during Save. Try again.')
        return {'current_beat': plan['current_beat'] if plan else None,
                'beat_count': len(plan['beats']) if plan else 0,
                'character_names': list(cast_meta['character_names'])}

    def _save(self, request: Mapping[str, object], *, new: bool) -> dict[str, object]:
        generation = int(request['session_generation'])
        entry_id = None if new else self.active_entry_id
        if not new and entry_id is None:
            raise ValueError('Name this story with Save Story As first.')
        name = request.get('name') if new else next(
            (row['name'] for row in self.store.list_entries() if row['entry_id'] == entry_id), None)
        if name is None:
            raise ValueError('The active saved story was removed. Use Save Story As.')
        for attempt in range(2):
            boundary = self._capture_boundary(generation)
            try:
                result = self.store.write_version(entry_id, name,
                    lambda folder: self._capture(folder, boundary))
            except ValueError as exc:
                if 'changed during Save' in str(exc) and attempt == 0:
                    continue
                raise
            self.active_entry_id = str(result['entry_id'])
            return result
        raise ValueError('The conversation kept changing. Try Save again.')

    def _open(self, entry_id: str) -> dict[str, object]:
        folder = self.store.read_version(entry_id)
        saved_path = folder / 'chat_context.json'
        saved = json.loads(saved_path.read_text(encoding='utf-8'))
        plan = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
        self._plan_store.validate_snapshot(plan)
        auto_path = folder / 'visual_auto.json'
        auto_state = json.loads(auto_path.read_text(encoding='utf-8')) if auto_path.exists() else None
        if self.visual_auto and auto_state is not None:
            self.visual_auto.validate_snapshot(auto_state)
        # Preflight the cast before changing the current session.
        self.cast({'action': 'story-validate', 'bundle_dir': str(folder / 'cast')})
        if self.soundscape:
            self.soundscape.validate(folder)
        memory_path = folder / 'memory.json'
        memory = json.loads(memory_path.read_text(encoding='utf-8')) if memory_path.exists() else None
        if not isinstance(saved, dict) or (memory is not None and not isinstance(memory, dict)):
            raise ValueError('Saved story is invalid.')
        recovery = self.store.root / 'recovery' / uuid.uuid4().hex
        recovery.mkdir(parents=True)
        recovery_chat = recovery / 'chat_context.json'
        self._export_chat(self.chat, recovery_chat)
        old_scope = dict(self.scope())
        old_conversation_id = str(old_scope['conversation_id'])
        if self.soundscape:
            self.soundscape.capture(old_conversation_id, recovery)
        self.cast({'action': 'story-export', 'conversation_id': old_conversation_id,
                   'target_dir': str(recovery / 'cast')})
        old_plan = self._plan_store.snapshot(old_conversation_id)
        (recovery / 'plan.json').write_text(json.dumps(old_plan, ensure_ascii=False), encoding='utf-8')
        if self.visual_auto:
            (recovery / 'visual_auto.json').write_text(
                json.dumps(self.visual_auto.export(old_conversation_id), ensure_ascii=False), encoding='utf-8')
        previous_payload = json.loads(recovery_chat.read_text(encoding='utf-8'))
        if previous_payload.get('continuity_memory_enabled'):
            previous_memory = continuity_memory.load_memory(previous_payload.get('continuity_memory_id'))
            (recovery / 'memory.json').write_text(json.dumps(previous_memory, ensure_ascii=False), encoding='utf-8')
        new_conversation_id, new_memory_id = uuid.uuid4().hex, uuid.uuid4().hex
        staged = False
        staged_memory: Path | None = None
        self.stop_playback()
        try:
            cast_result = self.cast({'action': 'story-restore', 'conversation_id': new_conversation_id,
                                     'bundle_dir': str(folder / 'cast')})
            staged = True
            if self.soundscape:
                self.soundscape.restore(new_conversation_id, folder)
            if plan is not None:
                self._plan_store.restore(new_conversation_id, plan)
            if self.visual_auto and auto_state is not None:
                self.visual_auto.restore(new_conversation_id, auto_state)
            if memory is not None:
                memory_target = continuity_memory.memory_path(new_memory_id)
                if memory_target.exists():
                    raise ValueError('New story memory identity already exists. Retry Open.')
                staged_memory = continuity_memory.save_memory(memory, new_memory_id)
            restored = clone_chat_scope(saved, new_conversation_id, new_memory_id,
                                        cast_result['card_ids'])
            self.chat.import_story(restored, saved_path)
            self.refresh()
            self.active_entry_id = entry_id
            self._recovery_token = None
            try:
                shutil.rmtree(recovery)
            except OSError:
                pass  # A completed Open must not fail because recovery cleanup failed.
            return {'entry_id': entry_id, 'state': 'paused',
                    'conversation_id': new_conversation_id}
        except Exception:
            try:
                previous = json.loads(recovery_chat.read_text(encoding='utf-8'))
                self.chat.import_story(previous, recovery_chat)
                if self.soundscape:
                    self.soundscape.restore(old_conversation_id, recovery)
                self.refresh()
            except Exception as rollback_error:
                self._recovery_token = recovery.name
                raise RuntimeError('Story Open failed and automatic recovery failed. '
                                   f'Recovery snapshot: {recovery.name}') from rollback_error
            finally:
                if staged:
                    try:
                        if self.soundscape:
                            self.soundscape.forget(new_conversation_id)
                        if self.visual_auto:
                            self.visual_auto.forget(new_conversation_id)
                        self.cast({'action': 'story-remove', 'conversation_id': new_conversation_id})
                        current = self._plan_store.snapshot(new_conversation_id)
                        if current:
                            self._plan_store.remove(new_conversation_id, current['revision'])
                    except Exception:
                        pass  # Keep the original import/rollback error visible.
                if staged_memory is not None:
                    try:
                        Path(staged_memory).unlink(missing_ok=True)
                    except OSError:
                        pass
            raise

    def _recover(self, recovery_id: object) -> dict[str, object]:
        if not isinstance(recovery_id, str) or recovery_id != self._recovery_token:
            raise ValueError('No matching Story Library recovery is available.')
        recovery = self.store.root / 'recovery' / recovery_id
        source = recovery / 'chat_context.json'
        previous = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(previous, dict):
            raise ValueError('Story Library recovery snapshot is invalid.')
        self.stop_playback()
        self.chat.import_story(previous, source)
        auto_path = recovery / 'visual_auto.json'
        if self.visual_auto and auto_path.exists():
            self.visual_auto.restore(str(previous['chat_character_conversation_id']),
                                     json.loads(auto_path.read_text(encoding='utf-8')))
        if self.soundscape:
            self.soundscape.restore(str(previous['chat_character_conversation_id']), recovery)
        self.refresh()
        self._recovery_token = None
        try:
            shutil.rmtree(recovery)
        except OSError:
            pass
        return {'recovered': True, 'state': 'paused'}

    def handle(self, request: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(request, Mapping):
            raise ValueError('Story Library request is invalid.')
        action = request.get('action')
        with self._lock:
            if action == 'recover':
                return self._recover(request.get('recovery_id'))
            current = self._current(request)
            if action == 'list':
                return {'entries': self.store.list_entries(), 'active_entry_id': self.active_entry_id}
            if action == 'status':
                return {'active_entry_id': self.active_entry_id,
                        'playback_owned_by_phone': True}
            operation_id = request.get('operation_id')
            if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
                raise ValueError('An operation identity is required.')
            fingerprint = hashlib.sha256(json.dumps(dict(request), sort_keys=True).encode()).hexdigest()
            old = self._receipts.get(operation_id)
            if old is not None:
                if old[0] != fingerprint:
                    raise ValueError('Operation identity already used for another request.')
                return dict(old[1])
            if action == 'save_as':
                result = self._save(request, new=True)
            elif action == 'save':
                result = self._save(request, new=False)
            elif action == 'open':
                result = self._open(str(request.get('entry_id') or ''))
            elif action == 'rename':
                result = self.store.rename(str(request.get('entry_id') or ''), request.get('name'))
            elif action == 'delete':
                entry_id = str(request.get('entry_id') or '')
                self.store.delete(entry_id)
                if self.active_entry_id == entry_id:
                    self.active_entry_id = None
                result = {'deleted': True, 'entry_id': entry_id}
            elif action in {'play', 'pause', 'resume'} and self.transport is not None:
                result = self.transport.command(action, int(current['session_generation']),
                                                operation_id, self.active_entry_id)
            else:
                raise ValueError('Unknown Story Library action.')
            self._receipts[operation_id] = (fingerprint, dict(result))
            while len(self._receipts) > 256:
                self._receipts.popitem(last=False)
            return dict(result)
