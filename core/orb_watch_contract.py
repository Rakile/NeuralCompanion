"""Pure watch-envelope admission; no addon/controller dependencies."""
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class WatchReplyPublication:
    """Synchronous host command, never model input or serializable event data."""
    bundle: Mapping
    publish: object
    result: object = None
    claimed: bool = False


def current_watch_events(bundle, collection):
    if (not isinstance(bundle,Mapping) or not isinstance(collection,Mapping) or
            bundle.get('schema_version')!=2 or collection.get('schema_version')!=2 or
            not bundle.get('session_key') or bundle.get('session_key')!=collection.get('session_key') or
            bundle.get('active') is not True or bundle.get('eligible') is not True):
        return []
    events,rows=bundle.get('events'),collection.get('watches')
    if not isinstance(events,(list,tuple)) or not isinstance(rows,(list,tuple)):
        return []
    by_id={r.get('id'):r for r in rows if isinstance(r,Mapping)}
    found,seen=[],set()
    for event in events:
        if not isinstance(event,Mapping):
            return []
        identity=event.get('watch_id')
        if not isinstance(identity,str) or identity in seen:
            return []
        seen.add(identity)
        row=by_id.get(identity)
        pending=row.get('pending_event') if row else None
        if (isinstance(pending,Mapping) and type(event.get('revision')) is int and
                event['revision']==row.get('revision') and event.get('event_id') and
                event['event_id']==pending.get('event_id') and event.get('kind')==pending.get('kind') and
                row.get('status') in {'watching','matched_pending'}):
            found.append(event)
    return found


def watch_bundle_is_current(bundle, collection):
    events=bundle.get('events') if isinstance(bundle,Mapping) else None
    return bool(isinstance(events,(list,tuple)) and events and
        len(current_watch_events(bundle,collection))==len(events))
