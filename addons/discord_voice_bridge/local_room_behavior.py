"""One room-owned behavior choice, translated to existing routing settings."""
import math
import uuid


DEFAULT_BEHAVIOR = {
    'speaker_selection': 'ai',
    'moderator_help': True,
    'silence_seconds': 0.0,
    'moderator_action': 'moderator_speaks_and_calls_next',
    'allow_repeat': False,
    'prepare_ahead': True,
    'trigger': 'no_route_after_any_speech',
    'cooldown_seconds': 0.0,
    'router_instructions': '',
}


def normalize_behavior(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(DEFAULT_BEHAVIOR):
        raise ValueError('Unknown Local room behavior setting.')
    result = {**DEFAULT_BEHAVIOR, **value}
    for key, options in (
        ('speaker_selection', {'ai', 'names', 'manual'}),
        ('moderator_action', {'moderator_speaks_and_calls_next', 'moderator_speaks_only', 'silent_call_next'}),
        ('trigger', {'no_route_after_any_speech', 'no_route_after_bot_speech'}),
    ):
        if not isinstance(result[key], str) or result[key] not in options:
            raise ValueError('Choose a valid Local room ' + key.replace('_', ' ') + '.')
    for key in ('moderator_help', 'allow_repeat', 'prepare_ahead'):
        if not isinstance(result[key], bool):
            raise ValueError('Choose on or off for ' + key.replace('_', ' ') + '.')
    for key in ('silence_seconds', 'cooldown_seconds'):
        number = result[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 <= number <= 3600:
            raise ValueError('Enter a delay between 0 and 3600 seconds.')
        result[key] = float(number)
    if not isinstance(result['router_instructions'], str) or len(result['router_instructions']) > 16000:
        raise ValueError('Speaker-selection instructions must be text of at most 16000 characters.')
    result['router_instructions'] = result['router_instructions'].strip()
    return result


def behavior_from_settings(settings):
    local = settings.get('local_room') or {}
    return normalize_behavior(local.get('behavior'))


def apply_behavior(settings, behavior, *, revision=None):
    """Modify only a session settings object; never write shared Discord settings."""
    behavior = normalize_behavior(behavior)
    automatic = behavior['speaker_selection'] != 'manual'
    router = settings.setdefault('room_router', {})
    router.update({
        'enabled': automatic,
        'human_to_bot_routing': automatic,
        'bot_to_bot_routing': automatic,
        'route_bot_replies_from_text': automatic,
        'mode': 'mention_or_question' if behavior['speaker_selection'] == 'names' else 'llm_router',
        'exclude_speaker_from_targets': not behavior['allow_repeat'],
        'self_route_policy': 'allow' if behavior['allow_repeat'] else 'ignore',
        'prepare_bot_replies_ahead': behavior['prepare_ahead'],
        'router_rules_prompt': behavior['router_instructions'],
        'default_when_uncertain': behavior['speaker_selection'] == 'ai',
        'local_room_behavior': dict(behavior),
        'local_room_behavior_revision': revision or router.get('local_room_behavior_revision') or uuid.uuid4().hex,
    })
    recovery = dict(router.get('dead_air_recovery') or {})
    recovery.update({
        'enabled': automatic and behavior['moderator_help'],
        'silence_timeout_seconds': behavior['silence_seconds'],
        'cooldown_seconds': behavior['cooldown_seconds'],
        'trigger_mode': behavior['trigger'],
        'action_mode': behavior['moderator_action'],
        # Handovers use the shared rule; no second participant-selection setting.
        'next_speaker_strategy': 'llm_choose',
        'selected_fallback_target': '',
    })
    router['dead_air_recovery'] = recovery
    settings.setdefault('local_room', {})['behavior'] = dict(behavior)
    return settings
