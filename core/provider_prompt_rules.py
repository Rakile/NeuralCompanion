"""Provider defaults and persona technical rules; pure, request-local resolution."""
from __future__ import annotations

from collections.abc import Mapping
import re

LEGACY_DEFAULT = """You have a graphical face and a voice. Use them to act out your responses vividly.
VISUAL MOODS (State-based):
Insert one of these tags to make your graphical avatar take on a specific facial expression at any given moment.
Valid Tags: [neutral], [sad], [angry]

VOICE SOUNDS (Action-based):
Insert one of these tags to express a vocal emotion at any given moment.
Valid Tags: [laugh], [chuckle], [sigh], [groan], [gasp], [clear throat], [sniff]

Example of how to use tags in a sentence:
"[angry] You did what? [laugh] [sad] Oh my god, are you okay? [neutral] Or just clumsy?"

Do NOT use emojis when speaking!"""

AVATAR_DEFAULT = """VISUAL MOODS (State-based):
Use the avatar's available expression tags when appropriate.
Default tags: [neutral], [sad], [angry]. Only use expressions available in the selected avatar package.
Visual tags set the expression until the next visual tag; they are not spoken words."""
VSEEFACE_AVATAR_DEFAULT = """VISUAL MOODS (State-based):
Use only these VSeeFace expression tags when appropriate: [neutral], [happy], [sad], [angry], [shy], [surprised].
Visual tags set the expression until the next visual tag; they are not spoken words."""
TTS_DEFAULT = """VOICE SOUNDS (Action-based):
Use supported vocal reactions when appropriate: [laugh], [chuckle], [sigh], [groan], [gasp], [clear throat], [sniff].
Only use tags supported by the selected voice provider and model. Do not read control tags aloud.
Do NOT use emojis when speaking!"""
MAX_RULE_LENGTH = 100_000


def provider_key(value: object) -> str:
    key = str(value or '').strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,127}', key):
        raise ValueError('Choose a valid provider.')
    return key


def rule_text(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_RULE_LENGTH:
        raise ValueError('Rules must be text of at most 100,000 characters.')
    return value


def normalize_rules(value: object) -> dict:
    source = value if isinstance(value, Mapping) else {}
    result = {'legacy_enabled': source.get('legacy_enabled') is not False, 'avatar': {}, 'tts': {}}
    for kind in ('avatar', 'tts'):
        entries = source.get(kind, {})
        if not isinstance(entries, Mapping):
            raise ValueError('Provider rules must be a mapping.')
        for key, entry in entries.items():
            if not isinstance(entry, Mapping):
                raise ValueError('Each provider rule must contain an enabled flag and text.')
            result[kind][provider_key(key)] = {
                'enabled': entry.get('enabled') is True,
                'text': rule_text(entry.get('text', '')),
            }
    return result


def has_legacy_custom(text: str) -> bool:
    return bool(text.strip()) and text.replace('\r\n', '\n').strip() != LEGACY_DEFAULT.strip()


def pack_avatar_default(config: Mapping, provider: str) -> str:
    """Use cached pack metadata only; prompt construction must not touch disk."""
    from core.text_tags import is_single_word_control_tag, is_sound_tag
    prefix = 'musetalk' if provider == 'musetalk' else 'ditto'
    pack_id = str(config.get(prefix + ('_avatar_pack_id' if provider == 'musetalk' else '_pack_id')) or '')
    catalogs = config.get('_avatar_rule_pack_catalog', {})
    packs = catalogs.get(provider, {}) if isinstance(catalogs, Mapping) else {}
    pack = packs.get(pack_id, {}) if isinstance(packs, Mapping) else {}
    mapping = pack.get('emotion_avatar_map', {})
    enabled_by_pack = config.get(prefix + '_enabled_pack_emotions', {})
    enabled = enabled_by_pack.get(pack_id) if isinstance(enabled_by_pack, Mapping) else None
    if isinstance(enabled, str):
        enabled = enabled.split(',')
    allowed = None if enabled is None else {str(tag).strip().strip('[]').lower() for tag in enabled}
    tags = sorted(tag for tag, avatar in mapping.items()
                  if is_single_word_control_tag(tag) and not is_sound_tag(tag)
                  and (allowed is None or tag in allowed
                       or provider == 'musetalk' and avatar == pack.get('default_avatar_id')))
    if not tags:
        return ('VISUAL MOODS (State-based):\n'
                'No enabled visual emotion tags are available for the selected pack. Do not emit visual emotion tags.')
    return ('VISUAL MOODS (State-based):\n'
            'Use only these enabled tags from the selected avatar pack: '
            + ', '.join('[' + tag + ']' for tag in tags) + '.\n'
            'Use visual tags when appropriate; they are not spoken words. '
            'The avatar follows these tags when reply-emotion selection is enabled.')


def provider_default(config: Mapping, kind: str, provider: str, *, factory: bool = False) -> str:
    if kind not in ('avatar', 'tts'):
        raise ValueError('Choose visual avatar or TTS rules.')
    key = provider_key(provider)
    defaults = config.get('provider_prompt_defaults', {})
    entries = defaults.get(kind, {}) if isinstance(defaults, Mapping) else {}
    pack_based = kind == 'avatar' and key in ('musetalk', 'ditto')
    if not factory and isinstance(entries, Mapping) and key in entries:
        saved = rule_text(entries[key])
        # Unedited old defaults follow the provider's current factory rules.
        if saved != AVATAR_DEFAULT or not (pack_based or kind == 'avatar' and key in ('vseeface', 'scenic')):
            return saved
    if pack_based:
        return pack_avatar_default(config, key)
    if kind == 'avatar' and key == 'vseeface':
        return VSEEFACE_AVATAR_DEFAULT
    if kind == 'avatar' and key == 'scenic':
        from core.text_tags import is_single_word_control_tag, is_sound_tag
        catalog = config.get('_scenic_rule_pack_catalog', {})
        selected = str(config.get('scenic_pack_id') or '')
        tags = catalog.get(selected, ()) if isinstance(catalog, Mapping) else ()
        tags = sorted({tag for tag in tags if is_single_word_control_tag(tag) and not is_sound_tag(tag)})
        return ('VISUAL MOODS (State-based):\nUse only these tags from the selected Scenic pack: '
                + ', '.join('[' + tag + ']' for tag in tags)
                + '. Visual tags select images; they are not spoken words.') if tags else (
                'VISUAL MOODS (State-based):\nNo image tags are available for the selected Scenic pack. Do not emit visual emotion tags.')
    if key in ('none', 'off'):
        return ''
    if kind == 'tts' and key in ('chatterbox_multilingual', 'pockettts', 'pocket_tts', 'pockettts_multilingual'):
        return 'Do NOT use emojis when speaking!'
    return AVATAR_DEFAULT if kind == 'avatar' else TTS_DEFAULT


def resolve_rules(config: Mapping) -> str:
    """Resolve once per accepted request; never overwrite stored legacy text."""
    legacy = str(config.get('emotional_instructions') or '')
    rules = normalize_rules(config.get('_persona_technical_rules'))
    if has_legacy_custom(legacy) and rules['legacy_enabled']:
        return legacy
    parts = []
    for kind, setting in (('avatar', 'avatar_mode'), ('tts', 'tts_backend')):
        provider = str(config.get(setting) or 'none').strip().lower()
        entry = rules[kind].get(provider, {})
        text = entry.get('text', '') if entry.get('enabled') else provider_default(config, kind, provider)
        if text:
            parts.append(text)
    return '\n\n'.join(parts)
