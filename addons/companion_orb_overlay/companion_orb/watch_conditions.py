"""Pure decisions over observed evidence; never substitute the host clock."""
from copy import deepcopy
import re


def parse_visible_time(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'\s*(\d{1,2}):(\d{2})\s*(AM|PM)?\s*', value, re.I)
    if not match:
        return None
    hour, minute = int(match[1]), int(match[2])
    suffix = match[3]
    if minute > 59 or (suffix and not 1 <= hour <= 12) or (not suffix and hour > 23):
        return None
    if suffix:
        hour = hour % 12 + (12 if suffix.upper() == 'PM' else 0)
    return hour * 60 + minute


def evaluate_condition(spec, baseline, check):
    if spec.get('version') == 3:
        return evaluate_free_condition(spec, baseline, check)
    previous = deepcopy(baseline)
    result = dict(available=False, baseline=previous, event_kind='', terminal_status='', reason='unknown')
    if check.get('available') is not True or check.get('subject_confirmed') is not True:
        return result
    condition = spec['condition']
    mode = condition['mode']
    if mode == 'visible_clock':
        minutes = parse_visible_time(check.get('clock_text'))
        target = parse_visible_time(condition.get('clock_target'))
        if minutes is None or target is None:
            return result
        day, old_day = check.get('local_date', ''), previous.get('local_date', '')
        if day and old_day and day > old_day:
            return dict(result, available=True, event_kind='clock_missed', terminal_status='missed', reason='watch day ended')
        if (day and old_day and day < old_day) or minutes < previous.get('clock_minutes', -1):
            return dict(result, reason='visible clock moved backwards; cannot infer another day')
        result.update(available=True, baseline=dict(clock_minutes=minutes, local_date=day or old_day), reason='not yet')
        if minutes == target or (condition['clock_comparator'] == 'at_or_after' and minutes >= target):
            result.update(event_kind='clock_match', reason='visible clock matched')
        elif minutes > target:
            result.update(event_kind='clock_missed', terminal_status='missed', reason='target minute not observed')
        return result
    field = 'title' if mode == 'title_change' else 'summary'
    value = ' '.join(str(check.get(field) or '').split())
    if not value:
        return result
    old = previous.get(field, '')
    result.update(available=True, baseline=dict(check, **{field: value}), reason='unchanged')
    if mode == 'title_change':
        if old and old != value:
            result.update(event_kind='title_change', reason='title changed')
    elif mode == 'visual_commentary':
        if condition['repeat_policy'] == 'periodic' or (old != value and (not old or check.get('meaningful_change') is True)):
            result.update(event_kind='commentary', reason='periodic check' if old == value else 'scene observed')
    return result


def evaluate_free_condition(spec, baseline, check):
    result = dict(available=False, baseline=deepcopy(baseline), event_kind='', terminal_status='', reason='unknown')
    if check.get('available') is not True or not isinstance(check.get('summary'), str) or not check['summary'].strip():
        return result
    mode = spec['response_mode']
    if mode == 'each_check':
        return dict(result, available=True, baseline={}, event_kind='commentary', reason='requested each check')
    if mode == 'on_change':
        value = check.get('value')
        if not isinstance(value, str) or not value.strip():
            return result
        value = ' '.join(value.split())
        changed = 'value' in baseline and value != baseline['value']
        return dict(result, available=True, baseline=dict(value=value),
            event_kind='value_change' if changed else '', reason='value changed' if changed else 'baseline' if not baseline else 'unchanged')
    if mode == 'when_condition':
        met = check.get('condition_met')
        if type(met) is not bool:
            return result
        due = met and baseline.get('condition_met') is not True
        return dict(result, available=True, baseline=dict(condition_met=met),
            event_kind='condition_match' if due else '', reason='condition met' if due else 'unchanged' if met else 'not met')
    return result
