"""Free-form watch specifications and tool proposals; no inference or IO."""
from __future__ import annotations


def validate_free_watch(value: dict, *, original_request: str) -> dict:
    required = {'instruction', 'response_mode', 'once'}
    if (not isinstance(value, dict) or not required <= set(value)
            or set(value) - required - {'observation_question'}):
        raise ValueError('Invalid watch fields.')
    instruction = value['instruction']
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 1000:
        raise ValueError('Watch instruction must contain 1–1000 characters.')
    if not isinstance(value['response_mode'], str) or value['response_mode'] not in {'each_check', 'when_condition', 'on_change'}:
        raise ValueError('Invalid watch response timing.')
    if type(value['once']) is not bool:
        raise ValueError('Watch once must be a boolean.')
    if not isinstance(original_request, str) or len(original_request) > 6000:
        raise ValueError('Invalid originating user instruction.')
    question = value.get('observation_question', '')
    if not isinstance(question, str) or len(question) > 1000:
        raise ValueError('Observation question must be a string of at most 1000 characters.')
    return dict(version=3, instruction=instruction.strip(), original_request=original_request,
                response_mode=value['response_mode'], once=value['once'],
                **({'observation_question':question.strip()} if 'observation_question' in value else {}))


def watch_identity(spec):
    return spec['instruction'].strip(), spec['response_mode'], spec['once']


def tool_operations(name, arguments, watches, original_request):
    """Validate the whole call before returning operations for the state owner."""
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be an object.')
    operations, existing_ids = [], []
    if name == 'start_watches':
        if (set(arguments) != {'watches'} or not isinstance(arguments['watches'], list)
                or not 1 <= len(arguments['watches']) <= 32):
            raise ValueError('Start requires 1–32 independent watches.')
        specs = [validate_free_watch(v, original_request=original_request) for v in arguments['watches']]
        active = {watch_identity(w['spec']): w['id'] for w in watches
                  if w['status'] in {'watching', 'matched_pending'} and w['spec'].get('version') == 3}
        seen = set()
        for spec in specs:
            identity = watch_identity(spec)
            if identity in seen:
                continue
            seen.add(identity)
            if identity in active:
                existing_ids.append(active[identity])
            else:
                operations.append(dict(operation='add', watch_id='', expected_revision=0, spec=spec))
    elif name in {'update_watch', 'stop_watch'}:
        keys = {'watch_id'} if name == 'stop_watch' else {'watch_id', 'instruction', 'response_mode', 'once'}
        supplied = set(arguments) - ({'observation_question'} if name == 'update_watch' else set())
        if supplied != keys or not isinstance(arguments['watch_id'], str) or not arguments['watch_id']:
            raise ValueError('Invalid watch target fields.')
        row = next((w for w in watches if w['id'] == arguments['watch_id']), None)
        if row is None:
            raise ValueError('That watch does not exist.')
        spec = {} if name == 'stop_watch' else validate_free_watch(
            {k: v for k, v in arguments.items() if k != 'watch_id'}, original_request=original_request)
        operations.append(dict(operation='remove' if name == 'stop_watch' else 'update',
            watch_id=row['id'], expected_revision=row['revision'], spec=spec))
    else:
        raise ValueError('Unsupported watch action.')
    return operations, existing_ids
