"""Display-only provenance for a watch reply; never an input image attachment."""
from collections.abc import Mapping
import hashlib
from pathlib import Path


def watch_capture_reference(image_path, captured_at, observation_id):
    result = dict(image_path=str(image_path or ''), captured_at=captured_at,
                  observation_id=observation_id, sha256='')
    try:
        result['sha256'] = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()
    except (OSError, TypeError, ValueError):
        pass
    return result


def retain_watch_capture(payload):
    """Pin the accepted frame before inference/rolling sensory cleanup can replace it.

    Bytes are copied unchanged to a content-addressed display-asset folder. Failure
    only disables the preview; it must not break conversation or show another frame.
    """
    if not isinstance(payload, Mapping) or payload.get('source') != 'companion_orb_target':
        return None
    watch = payload.get('orb_watch')
    if not isinstance(watch, Mapping) or watch.get('active') is not True or watch.get('eligible') is not True:
        return None
    capture = watch.get('capture')
    if not isinstance(capture, Mapping):
        return None
    result = {key: capture.get(key) for key in ('captured_at', 'observation_id', 'sha256')}
    result.update(image_path='', available=False)
    try:
        source = Path(str(capture.get('image_path') or ''))
        if not source.is_absolute() or source.suffix.lower() not in {'.jpg', '.jpeg', '.png'}:
            return result
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != capture.get('sha256'):
            return result
        asset_dir = source.parent if source.parent.name == 'orb_watch_replies' else source.parent / 'orb_watch_replies'
        destination = asset_dir / (digest + source.suffix.lower())
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            # Exclusive creation: never overwrite an image held by another reply.
            try:
                with destination.open('xb') as handle:
                    handle.write(data)
            except FileExistsError:
                pass
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            return result
        result.update(image_path=str(destination), available=True)
    except (OSError, ValueError):
        pass
    return result


def retain_watch_captures(payload):
    if not isinstance(payload,Mapping) or payload.get('source')!='companion_orb_target':
        return []
    watch=payload.get('orb_watch')
    if not isinstance(watch,Mapping) or watch.get('schema_version')!=2 or not watch.get('eligible'):
        return []
    pinned={}
    for event in watch.get('events',()):
        capture=event.get('capture') or {}
        key=capture.get('sha256') or event.get('watch_id')
        if key not in pinned:
            result=retain_watch_capture(dict(source='companion_orb_target',orb_watch=dict(active=True,eligible=True,capture=capture)))
            if result is None:
                continue
            pinned[key]=dict(result,watch_ids=[])
        pinned[key]['watch_ids'].append(event.get('watch_id'))
    return list(pinned.values())
