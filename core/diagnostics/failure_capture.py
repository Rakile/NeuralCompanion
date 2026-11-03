"""Worker-only, bounded evidence copies; protected captures are never auto-evicted."""
import json
import os
from pathlib import Path
from core.diagnostics.retention import DEFAULT_RETENTION

MAX_CAPTURES = DEFAULT_RETENTION.capture_slots
MAX_CAPTURE_BYTES = DEFAULT_RETENTION.capture_bytes
MAX_FILES = DEFAULT_RETENTION.capture_files


def capture_slots_full(path):
    root = Path(path).parent / 'failures'
    return all((root / f'capture-{slot:02d}').exists() for slot in range(MAX_CAPTURES))


def is_failure(event):
    if event.get('level') == 'error' or event.get('outcome') == 'failed':
        return True
    data = event.get('data', {})
    # Planner rejections are observations, not error-level events. Capture after
    # their detailed checks, rather than before position-shape evidence is written.
    return (data.get('site') == 'desktop.anticipation.metadata'
            and data.get('condition') in {
                'phone.ambiguous', 'phone.stale', 'phone.mismatch',
                'phone.handoff_unconfirmed'} and data.get('actual') is False)


def capture_failure(path, event, diagnostic_policies=None):
    """Copy local shared journals, not raw app logs/settings. No cross-process locks.

    Sources may rotate concurrently: omissions are recorded, never called complete.
    Atomic slot reservation bounds all processes together to eight 64 MiB captures
    (plus small manifests). Existing slots, including partial ones, are preserved.
    """
    path = Path(path)
    root = path.parent / 'failures'
    root.mkdir(parents=True, exist_ok=True)
    target = None
    for slot in range(MAX_CAPTURES):
        candidate = root / f'capture-{slot:02d}'
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        target = candidate
        break
    if target is None:
        return 'capacity_reached'
    manifest = dict(version=1, status='collecting', consistency='best_effort_live_files',
                    event_id=event['event_id'], trace_id=event['trace_id'],
                    wall_time_utc=event['wall_time_utc'], files=[], omitted=[],
                    diagnostic_policies=list(diagnostic_policies or [])[:32],policy_scope='observed_by_capturing_journal')
    def save():
        temporary = target / 'manifest.tmp'
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(manifest, handle, separators=(',', ':'))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target / 'manifest.json')
    save()
    try:
        own = [path, path.with_suffix(path.suffix + '.1')]
        peers = []
        for source in path.parent.glob('transactions-*.jsonl*'):
            if source in own or not (source.name.endswith('.jsonl') or source.name.endswith('.jsonl.1')):
                continue
            try:
                peers.append((source.stat().st_mtime_ns, source))
            except OSError:
                manifest['omitted'].append(dict(file=source.name, reason='source_unavailable'))
        sources = own + [source for _, source in sorted(peers, key=lambda item: item[0], reverse=True)]
        remaining = MAX_CAPTURE_BYTES
        for index, source in enumerate(sources):
            if index >= MAX_FILES:
                manifest['omitted'].append(dict(reason='file_limit', count=len(sources)-index))
                break
            if not source.exists() and source in own:
                continue
            try:
                with source.open('rb') as incoming:
                    size = os.fstat(incoming.fileno()).st_size
                    if size > remaining:
                        manifest['omitted'].append(dict(file=source.name, reason='byte_limit'))
                        continue
                    with (target / source.name).open('xb') as outgoing:
                        left = size
                        while left:
                            block = incoming.read(min(left, 256 * 1024))
                            if not block:
                                raise OSError('source shortened')
                            outgoing.write(block)
                            left -= len(block)
                        outgoing.flush()
                        os.fsync(outgoing.fileno())
                remaining -= size
                manifest['files'].append(dict(file=source.name, bytes=size))
            except OSError:
                # Partial bytes still count towards the hard budget.
                copied = target / source.name
                if copied.exists():
                    remaining -= copied.stat().st_size
                manifest['omitted'].append(dict(file=source.name, reason='copy_failed'))
        manifest['status'] = 'partial' if manifest['omitted'] else 'captured'
    except Exception:
        manifest['status'] = 'failed'
    save()
    return manifest['status']
