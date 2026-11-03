"""Compact visual supervisor review and deterministic per-rule cadence."""
from collections.abc import Mapping, Sequence
import base64
import hashlib
import json
import mimetypes
from pathlib import Path

from core.sensory import DEFAULT_SENSORY_PINGPONG_PROMPT, resolve_pingpong_prompt


def screen_review_contributor(registry, sources, config):
    """Use the compact contract only for an isolated, opted-in image source."""
    if set(sources) not in ({'screen'}, {'clipboard'}):
        return None
    source = next(iter(sources))
    configured = resolve_pingpong_prompt(config.get('sensory_pingpong_prompt'))
    if configured.strip() != DEFAULT_SENSORY_PINGPONG_PROMPT.strip():
        return None  # Preserve an explicitly customized shared contract.
    provider = registry.get_provider(source)
    overrides = config.get('sensory_provider_metadata_overrides', {})
    override = overrides.get(source, {}) if isinstance(overrides, Mapping) else {}
    if isinstance(override, Mapping) and 'instruction' in override:
        if str(override['instruction'] or '') != str(getattr(provider, 'instruction', '') or ''):
            return None  # An explicit source instruction still belongs in its request.
    contributors = [c for c in registry.list_prompt_contributors()
                    if c.source_id in (source, 'all', '*') and c.prompt]
    if len(contributors) != 1:
        return None
    contributor = contributors[0]
    return contributor if contributor.metadata.get('review_contract') == f'{source}_matches' else None


def clipboard_image_is_new(snapshots):
    """Freshness comes from capture, not from the model's image interpretation."""
    return any(item.get('source') == 'clipboard' and item.get('image_is_new') is True
               for item in snapshots)


def rule_tags(rules):
    """Keep short generated IDs, without making imported IDs ambiguous."""
    identifiers = [str(rule.get('id', '')) for rule in rules]
    short = [identifier.removeprefix('behavior_') for identifier in identifiers]
    return short if len(set(short)) == len(short) else identifiers


def screen_images(snapshots):
    """Freeze image bytes from the supplied capture, never take another capture."""
    parts = []
    for snapshot in snapshots:
        message = snapshot.get('message')
        content = message.get('content') if isinstance(message, Mapping) else snapshot.get('content')
        if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
            for part in content:
                if not isinstance(part, Mapping) or part.get('type') != 'image_url':
                    continue
                image = part.get('image_url')
                url = image.get('url') if isinstance(image, Mapping) else image
                if isinstance(url, str) and url.startswith('data:image/'):
                    parts.append({'type': 'image_url', 'image_url': {'url': url}})
            continue
        paths = [snapshot.get('image_path')]
        paths.extend(tile.get('path') for tile in snapshot.get('image_tiles', ())
                     if isinstance(tile, Mapping))
        for raw_path in paths:
            if not raw_path:
                continue
            try:
                path = Path(raw_path)
                data = path.read_bytes()
            except (OSError, TypeError, ValueError):
                continue
            if data:
                mime = mimetypes.guess_type(str(path))[0] or 'image/jpeg'
                parts.append({'type': 'image_url', 'image_url': {
                    'url': f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'}})
    return parts


def resolve_screen_matches(contributor, result, previous, *, image_id=''):
    """Project cadence without side effects; admission marks due actions delivered."""
    rules = [dict(rule) for rule in contributor.metadata.get('active_behaviors', ())
             if isinstance(rule, Mapping) and rule.get('enabled', True)
             and rule.get('id') and rule.get('trigger') and rule.get('action')]
    known = dict(zip(rule_tags(rules), rules))
    matches = result.get('matches')
    if not isinstance(matches, (list, tuple)):
        return None
    selected = {}
    reasons = {}
    for match in matches:
        if (not isinstance(match, Mapping) or not isinstance(match.get('tag'), str)
                or match['tag'] not in known or type(match.get('needs_image')) is not bool):
            return None  # Invalid output is not an unmatched observation.
        selected[match['tag']] = selected.get(match['tag'], False) or match['needs_image']
        reason = match.get('reason')
        if isinstance(reason, str) and reason.strip():
            reasons[match['tag']] = ' '.join(reason.split())[:400]
    progress = {str(key): dict(value) for key, value in previous.items() if isinstance(value, Mapping)}
    actions = []
    for tag, rule in known.items():
        action = {key: str(rule.get(key, '') or '') for key in
                  ('id', 'trigger', 'action', 'strictness', 'emotion')}
        source = contributor.source_id
        action['source'] = source
        mode = str(rule.get('repeat_mode') or 'One-off')
        try:
            interval = max(1, min(999, int(rule.get('repeat_interval') or 1)))
        except (ValueError, TypeError):
            interval = 1
        signature = hashlib.sha256(json.dumps([action, mode, interval], sort_keys=True).encode()).hexdigest()
        key = f'{source}:{action["id"]}'
        last = progress.get(key, {})
        if last.get('signature') != signature:
            last = {}
        matched = tag in selected
        count = int(last.get('count', 0)) + int(matched)
        delivered = bool(last.get('delivered')) if matched else False
        if source == 'clipboard' and last.get('image_id') != image_id:
            delivered = False
        due = matched and (count % interval == 0 if mode == 'Every Nth match' else not delivered)
        progress[key] = {**last, 'source': source, 'mode': mode, 'signature': signature,
                         'count': count, 'matched': matched, 'delivered': delivered}
        if source == 'clipboard':
            progress[key]['image_id'] = image_id
        if due:
            actions.append({**action, 'needs_image': selected[tag]})
    return {'actions': actions, 'progress': progress, 'tags': tuple(selected), 'reasons': reasons}
