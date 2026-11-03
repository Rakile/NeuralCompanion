"""Resolve model-selected rules to authoritative configured assistant actions."""
from collections.abc import Mapping
import hashlib
import json
import re


def resolve_supervisor_action(registry, sources, tags, previous, summary):
    """Pure selection/cadence projection; delivery is recorded only after admission."""
    # Models may omit presentation brackets inside the JSON tags array.
    # Normalize known routing forms only; source/rule validation still follows.
    tags = tuple(f'[{tag}]' if re.fullmatch(
        r'(?:supervisor_rule|supervisor_subject|sensory_action):[^\[\]]+', str(tag))
        else tag for tag in tags)
    contributors = [c for c in registry.list_prompt_contributors()
                    if c.source_id in sources and c.metadata.get('type') == 'behavior_rule']
    managed = {c.source_id for c in contributors if c.metadata.get('action_contract') == 1}
    generic_sources = {c.source_id for c in contributors if c.source_id not in managed
                       and c.source_id != 'companion_orb_target'
                       and c.prompt and ('active_behaviors' not in c.metadata or c.metadata['active_behaviors'])}
    candidate_source = next((match.group(1) for tag in tags
                             if (match := re.fullmatch(r'\[sensory_action:([^\]]+)\]', str(tag)))
                             and match.group(1) in generic_sources), '')
    selected = None
    for tag in tags:
        match = re.fullmatch(r'\[supervisor_rule:([^:\]]+):([^\]]+)\]', str(tag))
        if not match:
            continue
        source, rule_id = match.groups()
        for contributor in contributors:
            if contributor.source_id != source:
                continue
            for rule in contributor.metadata.get('active_behaviors', ()):
                if (not isinstance(rule, Mapping) or str(rule.get('id', '')) != rule_id
                        or rule.get('enabled', True) is False or not str(rule.get('action', '')).strip()):
                    continue
                selected = (source, rule, contributor.metadata)
                break
            if selected:
                break
        if selected:
            break
    progress = {str(key): dict(value) for key, value in previous.items() if isinstance(value, Mapping)}
    for entry in progress.values():
        # An unmatched refresh ends a One-off episode, but it is not a match
        # and must not erase the Nth-match count or another rule's history.
        if (entry.get('source') in managed and entry.get('mode') == 'One-off'
                and (selected is None or entry['source'] != selected[0])):
            entry['delivered'] = False
    action = None
    due = False
    if selected:
        source, rule, metadata = selected
        action = {key: str(rule.get(key, '') or '') for key in
                  ('id', 'trigger', 'action', 'strictness', 'emotion')}
        action.update(source=source, persona_name=str(metadata.get('persona_name', '') or ''),
                      persona_style=str(metadata.get('persona_style', '') or ''))
        mode = str(rule.get('repeat_mode') or 'One-off')
        try:
            interval = max(1, min(999, int(rule.get('repeat_interval') or 1)))
        except (ValueError, TypeError):
            interval = 1
        signature = hashlib.sha256(json.dumps([action, mode, interval], sort_keys=True).encode()).hexdigest()
        progress_key = f'{source}:{action["id"]}'
        last = progress.get(progress_key, {})
        if last.get('signature') != signature:
            last = {}
        count = int(last.get('count', 0)) + 1
        subject = next((str(tag)[20:-1] for tag in tags
                        if str(tag).startswith('[supervisor_subject:') and str(tag).endswith(']')), '')
        subject = ' '.join((subject or str(summary)).lower().split())
        due = (count % interval == 0 if mode == 'Every Nth match' else
               not last.get('delivered') or subject != last.get('delivered_subject')
               if mode == 'Meaningful change only' else not last.get('delivered'))
        progress[progress_key] = {**last, 'source': source, 'mode': mode,
                                  'signature': signature, 'count': count, 'subject': subject}
    return {'managed': bool(selected) or bool(managed),
            'action': action, 'due': due, 'progress': progress, 'candidate_source': candidate_source,
            'tags': tuple(tag for tag in tags if not str(tag).startswith(
                ('[supervisor_rule:', '[supervisor_subject:', '[sensory_action:')))}
