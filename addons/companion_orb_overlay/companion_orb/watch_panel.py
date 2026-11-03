"""Display-only projection of the current conversational watch."""
from datetime import datetime
import hashlib
from pathlib import Path


def panel_status(state):
    if state.get('schema_version') == 2:
        rows=[]
        for watch in state.get('watches',[]):
            if watch['spec'].get('version') == 3:
                task, evidence = watch['spec'], watch.get('latest_check') or {}
                label = {'each_check':'Each check','when_condition':'When condition is met',
                    'on_change':'When watched value changes'}[task['response_mode']]
                row = panel_status(dict(watch, active=True, paused_reasons=state.get('paused_reasons', [])))
                if watch['status'] in {'matched_pending','completed'}:
                    row['message'] = 'Alert pending delivery' if watch['status']=='matched_pending' else 'Completed — alert delivered'
                elif evidence.get('available') and not state.get('paused_reasons'):
                    row['message'] = 'Watching — ' + label.lower()
                row.update(instruction=task['instruction'], original_request=task['original_request'],
                    condition_label=label + (' · Once' if task['once'] else ''), session_key=state['session_key'],
                    observation_text=' · '.join(str(evidence[k]) for k in ('value','summary','limitation','decision') if evidence.get(k)))
                rows.append(row)
                continue
            task=watch['spec']; condition=task['condition']; status=watch['status']
            row=panel_status(dict(watch,active=True,mode=condition['mode'],paused_reasons=state.get('paused_reasons',[])))
            if status in {'matched_pending','completed','missed'}:
                row['message']={'matched_pending':'Alert pending delivery','completed':'Completed — alert delivered',
                    'missed':'Target minute not observed'}[status]
            label=(f"Visible clock {condition['clock_comparator']} {condition['clock_target']} · once" if condition['mode']=='visible_clock'
                else f"{condition['mode']} · {condition['repeat_policy']}")
            evidence=watch.get('latest_check') or {}
            if status == 'watching' and evidence.get('available') and not state.get('paused_reasons'):
                row['message']='Watching — ' + ('periodic commentary' if condition['repeat_policy']=='periodic'
                    else 'visible clock' if condition['mode']=='visible_clock' else 'requested changes')
            row.update(instruction=task['instruction'],original_request=task['original_request'],condition_label=label,
                session_key=state['session_key'],observation_text=' · '.join(str(evidence.get(k) or '') for k in
                    ('clock_text','title','summary','limitation','decision') if evidence.get(k)))
            rows.append(row)
        return dict(state,rows=rows,message=f'{sum(r["status"] in {"watching","matched_pending"} for r in rows)} active conversational watches')
    check = state.get('latest_check') or {}
    paused = state.get('paused_reasons') or []
    if not state.get('active'):
        message = 'No active conversational watch.'
    elif paused == ['waiting for a capture target']:
        message = 'Waiting for a capture target'
    elif paused:
        message = 'Paused: ' + '; '.join(paused)
    elif not check:
        message = 'Waiting for the first background check.'
    elif not check.get('available'):
        message = 'Watching — latest check unavailable.'
    elif not check.get('subject_confirmed'):
        message = 'Watching — subject not visible or not uniquely identified.'
    else:
        message = 'Watching — ' + ('video title changes' if state.get('mode') == 'title_change' else 'visible scene changes')
    stamp = check.get('captured_at')
    checked = 'Not checked yet'
    if isinstance(stamp, (float, int)):
        try:
            checked = datetime.fromtimestamp(stamp).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
        except (ValueError, OverflowError, OSError):
            pass
    capture = check.get('capture') or {}
    return dict(state, message=message, checked=checked,
        observation_text=str(check.get('summary') or ''),
        capture_available=bool(state.get('active') and capture.get('sha256')
            and Path(str(capture.get('image_path') or '')).is_file()))


def verified_capture_path(state):
    capture = (state.get('latest_check') or {}).get('capture') or {}
    path = Path(str(capture.get('image_path') or ''))
    try:
        if (state.get('active') and path.is_absolute() and path.suffix.lower() in {'.jpg', '.jpeg', '.png'}
                and hashlib.sha256(path.read_bytes()).hexdigest() == capture.get('sha256')):
            return str(path)
    except OSError:
        pass
    raise RuntimeError('The observed capture is no longer available. Wait for the next check.')
