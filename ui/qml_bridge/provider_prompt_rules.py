"""Small bridge helpers for provider defaults and saved persona rule editing."""
from __future__ import annotations

from collections.abc import Mapping
from core.provider_prompt_rules import has_legacy_custom, normalize_rules, provider_default, provider_key, rule_text


def catalog(bridge, persona_id: str = '') -> dict:
    record = bridge.personaOverrideRecord(persona_id) if persona_id else {}
    rules = normalize_rules((record.get('overrides') or {}).get('technical_rules'))
    legacy = str(record.get('emotional_instructions') or '')
    result = {'personaId': persona_id, 'available': bool(record), 'name': record.get('name', ''),
              'rules': rules, 'legacyText': legacy}
    result.update(phone_catalog(bridge, {'technical_rules': rules, 'technical_prompt': legacy}))
    return result


def phone_catalog(bridge, record: Mapping) -> dict:
    """GUI-owned cached defaults only; the HTTP worker supplies the saved record."""
    config = bridge._application.config.snapshot().values
    rules = normalize_rules(record.get('technical_rules'))
    result = {'hasLegacy': has_legacy_custom(record.get('technical_prompt', '')),
              'activeAvatar': str(config.get('avatar_mode') or 'none'),
              'activeTts': str(config.get('tts_backend') or 'none')}
    stored = config.get('provider_prompt_defaults', {})
    for kind, rows in (('avatar', bridge.avatarOptions), ('tts', bridge.speechOutputBackends)):
        choices = {str(row['id']): str(row.get('label') or row['id']) for row in rows}
        entries = stored.get(kind, {}) if isinstance(stored, Mapping) else {}
        for key in set(rules[kind]) | set(entries):
            choices.setdefault(key, key + ' (saved provider)')
        active = result['activeAvatar' if kind == 'avatar' else 'activeTts']
        choices.setdefault(active, active)
        result[kind] = [{'id': key, 'label': label, 'defaultText': provider_default(config, kind, key),
                         'factoryText': provider_default(config, kind, key, factory=True)}
                        for key, label in choices.items()]
    return result


def save_persona(bridge, persona_id: str, draft: dict) -> dict:
    try:
        if bridge.quickPersonaReorderBusy:
            raise ValueError('Wait for persona reordering to finish.')
        bridge._quick_personas.save_technical_rules(persona_id, draft)
    except (OSError, ValueError) as error:
        return {'accepted': False, 'message': str(error)}
    bridge.quickPersonaChanged.emit()
    return {'accepted': True, 'message': 'Persona rules saved. They apply to the next reply.'}


def save_default(bridge, kind: str, provider: str, text: str) -> dict:
    try:
        if kind not in ('avatar', 'tts'):
            raise ValueError('Choose visual avatar or TTS rules.')
        provider = provider_key(provider)
        text = rule_text(text)
        previous = bridge._application.config.get('provider_prompt_defaults', {})
        defaults = {key: dict(value) for key, value in dict(previous).items()}
        entries = defaults.setdefault(kind, {})
        if kind == 'avatar' and provider in ('musetalk', 'ditto') and text == provider_default(
                bridge._application.config.snapshot().values, kind, provider, factory=True):
            entries.pop(provider, None)
        else:
            entries[provider] = text
        result = bridge._application.config.update('provider_prompt_defaults', defaults)
        if not result.accepted:
            raise ValueError(str(getattr(result.failure, 'message', 'Could not save provider rules.')))
        try:
            bridge._save_native_session_or_raise()
        except Exception:
            bridge._application.config.update('provider_prompt_defaults', previous)
            raise
    except (OSError, ValueError, RuntimeError) as error:
        return {'accepted': False, 'message': str(error)}
    bridge.configurationChanged.emit()
    return {'accepted': True, 'message': 'Provider defaults saved. They apply to the next reply.'}
