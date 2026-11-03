"""Manual Speech Timing profiles over the existing performance-profile format."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

from PySide6 import QtCore

import dry_run
from core.chat_runtime_session_schema import GENERATION_DEFAULT_KEYS
from core.runtime.providers import infer_model_supports_images
from ui.shell_specs import UI_SHELL_CHUNKING_SPECS, UI_SHELL_DEFAULT_CHUNKING_VALUES

SETUP_KEYS = ('avatar_mode', 'tts_backend', 'chat_provider', 'model_name', 'stream_mode', 'model_supports_images')


def _timing(values):
    result = {}
    for key, spec in UI_SHELL_CHUNKING_SPECS.items():
        if key not in values:
            continue
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{key} must be a finite number.')
        if not float(spec['minimum']) <= value <= float(spec['maximum']):
            raise ValueError(f'{key} is outside its supported range.')
        if spec.get('is_int', True) and value != int(value):
            raise ValueError(f'{key} must be a whole number.')
        result[key] = int(value) if spec.get('is_int', True) else round(float(value), 2)
    if not result:
        raise ValueError('This profile contains no supported speech timing settings.')
    return result


def _setup(values):
    result = {}
    for key in SETUP_KEYS:
        if key not in values:
            continue
        value = values[key]
        if key in ('stream_mode', 'model_supports_images'):
            if type(value) is not bool:
                raise ValueError(f'Saved {key} must be on or off.')
        elif not isinstance(value, str) or len(value) > 512:
            raise ValueError(f'Invalid saved {key}.')
        result[key] = value
    return result


def _summary(setup):
    parts = [f"Avatar: {setup.get('avatar_mode') or 'not recorded'}",
             f"TTS: {setup.get('tts_backend') or 'not recorded'}",
             f"Language model: {setup.get('chat_provider') or 'provider not recorded'} / {setup.get('model_name') or 'not recorded'}"]
    if 'stream_mode' in setup:
        parts.append('Streaming: ' + ('on' if setup['stream_mode'] else 'off'))
    if setup.get('model_name') and not setup.get('chat_provider'):
        parts.append('Older profile: the language model will stay unchanged because its provider was not recorded.')
    return '\n'.join(parts)


class SpeechTimingProfileStore:
    def __init__(self, directory=None):
        self.directory = Path(directory if directory is not None else dry_run.PERFORMANCE_PROFILES_DIR)

    def _path(self, name):
        if (not isinstance(name, str) or not name or name != name.strip() or len(name) > 100
                or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith('.')
                or name in ('.', '..') or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', name, re.I)):
            raise ValueError('Use a profile name without path separators, reserved filenames or trailing dots/spaces.')
        path = self.directory / (name + '.json')
        if path.is_symlink():
            raise ValueError('A profile must be a regular file in the profiles folder.')
        return path

    def load(self, name):
        path = self._path(name)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('The profile is too large.')
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(payload, dict):
            raise ValueError('The profile must contain a JSON object.')
        # The existing profile format records effective values in settings_to_apply.
        raw = payload.get('settings_to_apply', payload.get('config_snapshot', {}))
        if not isinstance(raw, dict):
            raise ValueError('The profile settings must contain a JSON object.')
        setup = payload.get('speech_timing_setup', raw)
        if not isinstance(setup, dict):
            raise ValueError('The saved provider/model information must contain a JSON object.')
        return dict(name=name, timing=_timing(raw), setup=_setup(setup))

    def list(self):
        rows = []
        if not self.directory.exists():
            return rows
        for path in sorted(self.directory.glob('*.json'), key=lambda p: p.name.casefold()):
            try:
                profile = self.load(path.stem)
                rows.append(dict(name=path.stem, display_name=path.stem, summary=_summary(profile['setup']), error=''))
            except (OSError, ValueError, TypeError) as error:
                rows.append(dict(name=path.stem, display_name=path.stem + ' (unavailable)', summary='', error=str(error)))
        return rows

    def save(self, name, values, *, overwrite=False):
        path = self._path(name)
        timing = _timing(values)
        setup = _setup(values)
        if path.exists() and not overwrite:
            raise FileExistsError('That profile already exists. Confirm Replace to overwrite it.')
        payload = dict(profile_key='manual_chunking', hardware={}, updated_at=time.time(), sample_count=0,
            confidence=0.0, stability=0.0, completion_reason='manual_save', recommendation={}, summary={},
            config_snapshot=timing, settings_to_apply=timing, speech_timing_setup=setup, saved_name=name, saved_at=time.time())
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.directory, suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            if not overwrite and path.exists():
                raise FileExistsError('That profile already exists. Confirm Replace to overwrite it.')
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return self.load(name)

    def delete(self, name):
        self._path(name).unlink()


class SpeechTimingProfiles(QtCore.QObject):
    stateChanged = QtCore.Signal()
    profilesChanged = QtCore.Signal()
    applied = QtCore.Signal()

    def __init__(self, config, *, store=None, persist, catalog, runtime_active, parent=None):
        super().__init__(parent)
        self.config = config
        self.store = store if store is not None else SpeechTimingProfileStore()
        self.persist, self.catalog, self.runtime_active = persist, catalog, runtime_active
        self._state = dict(profiles=[], selectedName='', selectedSummary='', canLoad=False, error='', status='')
        self.refresh()

    @QtCore.Property('QVariantMap', notify=stateChanged)
    def state(self):
        return deepcopy(self._state)

    def _error(self, error):
        self._state.update(error=str(error), status='')
        self.stateChanged.emit()
        return False

    @QtCore.Slot()
    def refresh(self):
        try:
            self._state['profiles'] = self.store.list()
        except (OSError, ValueError, TypeError) as error:
            self._error(error)
            return
        self.stateChanged.emit()
        self.profilesChanged.emit()

    @QtCore.Slot(str, result=bool)
    def select(self, name):
        self._state.update(selectedName='', selectedSummary='', canLoad=False, error='', status='')
        try:
            profile = self.store.load(name)
            self._state.update(selectedName=name, selectedSummary=_summary(profile['setup']), canLoad=True)
        except (OSError, ValueError, TypeError) as error:
            return self._error(error)
        self.stateChanged.emit()
        return True

    @QtCore.Slot(str, bool, result=bool)
    def save(self, name, overwrite=False):
        try:
            values = dict(self.config.snapshot().values)
            timing = {key: values.get(key, default) for key, default in UI_SHELL_DEFAULT_CHUNKING_VALUES.items()}
            self.store.save(name, {**timing, **{key: values[key] for key in SETUP_KEYS if key in values}}, overwrite=overwrite)
            self.refresh()
            self.select(name)
            self._state.update(status='Saved current speech timing and provider/model selections.', error='')
            self.stateChanged.emit()
            return True
        except (OSError, ValueError, TypeError) as error:
            return self._error(error)

    @QtCore.Slot(bool, result=bool)
    def load(self, include_setup=False):
        before = dict(self.config.snapshot().values)
        updates, selection = {}, {}
        try:
            profile = self.store.load(self._state['selectedName'])
            updates = dict(profile['timing'])
            setup = profile['setup'] if include_setup else {}
            if include_setup:
                available = self.catalog()
                for key in ('avatar_mode', 'tts_backend', 'chat_provider'):
                    if key in setup and setup[key] not in available.get(key, ()):
                        raise ValueError(f"Saved {key} '{setup[key]}' is unavailable. Load timing only, or enable its addon first.")
                if self.runtime_active() and any(before.get(key) != value for key, value in setup.items()):
                    raise ValueError('Stop the chat before restoring different providers, model or streaming mode. Timing-only loading remains available.')
                updates.update({key:value for key,value in setup.items() if key not in ('chat_provider','model_name','model_supports_images')})
                if setup.get('chat_provider') and 'model_name' in setup:
                    provider = setup['chat_provider']
                    settings = {key:dict(value) for key,value in dict(before.get('chat_provider_settings') or {}).items() if isinstance(value, Mapping)}
                    supports_images = setup.get('model_supports_images', infer_model_supports_images(setup['model_name']))
                    settings.setdefault(provider, {}).update(model_name=setup['model_name'], model_supports_images=supports_images)
                    updates['chat_provider_settings'] = settings
                    provider_values = dict((before.get('chat_provider_generation_settings') or {}).get(provider) or {})
                    selection = {key:provider_values[key] for key in GENERATION_DEFAULT_KEYS if key in provider_values}
                    selection.update(chat_provider=provider, model_name=setup['model_name'],
                                     model_supports_images=supports_images)
            # Validation is complete before the first accepted update.
            previous = {key:before.get(key) for key in set(updates) | set(selection)}
            try:
                result = self.config.update_many(updates)
                if not result.accepted:
                    raise RuntimeError(getattr(result.failure, 'message', 'Could not apply timing settings.'))
                if selection:
                    result = self.config.update_provider_selection(selection)
                    if not result.accepted:
                        raise RuntimeError(getattr(result.failure, 'message', 'Could not apply provider/model selection.'))
                saved = self.persist()
                if saved is False:
                    raise OSError('The current session could not be saved.')
            except (OSError, RuntimeError, TypeError, ValueError):
                restore = {key:value for key,value in previous.items() if key in before and key not in ('chat_provider','model_name','model_supports_images')}
                self.config.update_many(restore)
                if selection:
                    self.config.update_provider_selection({key:previous[key] for key in selection if key in before})
                for key in set(previous) - set(before):
                    self.config.remove(key)
                raise
            self._state.update(error='', status=('Loaded timing, providers/model and streaming mode.' if include_setup
                                                else 'Loaded timing only. Provider/model selections are unchanged.'))
            self.stateChanged.emit()
            self.applied.emit()
            return True
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            return self._error(error)

    @QtCore.Slot(result=bool)
    def deleteSelected(self):
        try:
            self.store.delete(self._state['selectedName'])
            self._state.update(selectedName='', selectedSummary='', canLoad=False, error='', status='Profile deleted.')
            self.refresh()
            return True
        except (OSError, ValueError, TypeError) as error:
            return self._error(error)

