"""Best-effort local sidecars describing the visible MuseTalk render frames."""
from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path
import re
import uuid
from core.diagnostics.plan_trace import PlanTrace

_plan_diagnostics = PlanTrace(component='desktop')
_ANTICIPATION_REJECTIONS = {
    'anticipation is invalid':'shape_invalid', 'anticipation keys are invalid':'keys_invalid',
    'anticipation identity is invalid':'identity_invalid',
    'anticipation identity does not match delivery':'delivery_identity_mismatch',
    'anticipation source frame count is invalid':'frame_count_invalid',
    'anticipation source indices are invalid':'indices_invalid',
    'anticipation source index is out of bounds':'index_bounds_invalid',
    'anticipation speech entry is invalid':'entry_invalid', 'anticipation exit is invalid':'exit_invalid',
    'anticipation repeat is invalid':'repeat_invalid', 'anticipation sync wait is invalid':'sync_wait_invalid',
}

_STATE_OBSERVATIONS = frozenset(('planner_selected', 'phone_owns_presentation',
                                 'handoff_pending', 'handoff_id_matches'))


def _trace_plan(chunk_id, condition, actual):
    try:
        _plan_diagnostics.observe(PlanTrace.source_id(chunk_id), 'desktop.anticipation.metadata',
                                  condition, True if isinstance(actual, bool) and condition not in _STATE_OBSERVATIONS else None,
                                  actual, chunk_id=chunk_id)
    except Exception:
        pass


def trace_planner_selection(chunk_id, first_reply_chunk, transition_render):
    # Observational only: no diagnostic result participates in planner admission.
    reason = ('selected' if first_reply_chunk and not transition_render else
              'not_first_reply_chunk_and_transition_render' if not first_reply_chunk and transition_render else
              'not_first_reply_chunk' if not first_reply_chunk else 'transition_render')
    _trace_plan(chunk_id, 'planner_selection_reason', reason)
    _trace_plan(chunk_id, 'planner_selected', first_reply_chunk and not transition_render)


SIDECAR_NAME = "phone-delivery.json"
FAILURE_SIDECAR_NAME = 'phone-delivery-failure.json'
_FAILURE_STAGES = frozenset(('avatar_preparation','directory_setup','audio_staging','worker_start','planning','overlap','render','merge','final_metadata'))
_FAILURE_TYPES = frozenset(('ValueError','RuntimeError','TimeoutError','OSError','FileNotFoundError',
                           'PermissionError','InterruptedError','other'))
_PLAN_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_ANTICIPATION_FRAMES = 1440


def _warning(message):
    print(f"⚠️ [MuseTalk] Delivery metadata skipped: {message}")


def _non_negative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validated_anticipation(anticipation, *, avatar_id, fps):
    if not isinstance(anticipation, dict):
        raise ValueError("anticipation is invalid")
    required_keys = {
        "version", "planId", "avatarId", "fps", "sourceFrameCount",
        "sourceIndices", "speechEntryFrame", "exitAfterFrame", "repeat",
    }
    optional_keys = {"syncWaitSeconds"}
    if set(anticipation) not in (required_keys, required_keys | optional_keys):
        raise ValueError("anticipation keys are invalid")
    plan_id = anticipation["planId"]
    source_frame_count = anticipation["sourceFrameCount"]
    source_indices = anticipation["sourceIndices"]
    speech_entry_frame = anticipation["speechEntryFrame"]
    exit_after_frame = anticipation["exitAfterFrame"]
    if anticipation["version"] != 1 or not isinstance(plan_id, str) or not _PLAN_ID.fullmatch(plan_id):
        raise ValueError("anticipation identity is invalid")
    if anticipation["avatarId"] != avatar_id or anticipation["fps"] != fps:
        raise ValueError("anticipation identity does not match delivery")
    if (not _non_negative_int(source_frame_count) or source_frame_count == 0
            or source_frame_count > _MAX_ANTICIPATION_FRAMES):
        raise ValueError("anticipation source frame count is invalid")
    if (not isinstance(source_indices, list) or not source_indices
            or len(source_indices) > _MAX_ANTICIPATION_FRAMES):
        raise ValueError("anticipation source indices are invalid")
    if any(not _non_negative_int(index) or index >= source_frame_count for index in source_indices):
        raise ValueError("anticipation source index is out of bounds")
    if not _non_negative_int(speech_entry_frame) or speech_entry_frame != source_indices[0]:
        raise ValueError("anticipation speech entry is invalid")
    if not _non_negative_int(exit_after_frame) or exit_after_frame != len(source_indices) - 1:
        raise ValueError("anticipation exit is invalid")
    if anticipation["repeat"] is not True:
        raise ValueError("anticipation repeat is invalid")
    sync_wait_seconds = anticipation.get("syncWaitSeconds")
    if "syncWaitSeconds" in anticipation and (
        isinstance(sync_wait_seconds, bool)
        or not isinstance(sync_wait_seconds, (int, float))
        or not math.isfinite(sync_wait_seconds)
        or not 0.0 <= sync_wait_seconds <= 2.5
    ):
        raise ValueError("anticipation sync wait is invalid")
    result = {
        "version": 1,
        "planId": plan_id,
        "avatarId": avatar_id,
        "fps": fps,
        "sourceFrameCount": source_frame_count,
        "sourceIndices": list(source_indices),
        "speechEntryFrame": speech_entry_frame,
        "exitAfterFrame": exit_after_frame,
        "repeat": True,
    }
    if "syncWaitSeconds" in anticipation:
        result["syncWaitSeconds"] = float(sync_wait_seconds)
    return result


def _trusted_frame_dir(frame_dir, chunk_id, *, require_exists):
    target_dir = Path(frame_dir).resolve()
    if not isinstance(chunk_id, str) or not chunk_id or target_dir.name != chunk_id:
        raise ValueError("frame directory does not match chunk id")
    if not target_dir.parent.is_dir():
        raise ValueError("render parent directory is unavailable")
    if require_exists and not target_dir.is_dir():
        raise ValueError("frame directory is unavailable")
    return target_dir


def _initial_sidecar(target_dir, chunk_id):
    return target_dir.parent / f".phone-delivery-{chunk_id}.json"


def _validated_payload(
    *,
    frame_dir,
    chunk_id,
    fps,
    trim_start_frames,
    avatar_id,
    idle_frame_dir,
    source_start_index=None,
    frame_count=None,
    anticipation=None,
    source_timeline=None,
    ordered_output=None,
    remote_source=None,
    source_spans=None,
):
    target_dir = _trusted_frame_dir(frame_dir, chunk_id, require_exists=True)
    idle_dir = Path(idle_frame_dir).resolve()
    if not _non_negative_int(fps) or fps == 0:
        raise ValueError("fps is invalid")
    if not _non_negative_int(trim_start_frames):
        raise ValueError("trim count is invalid")
    if not isinstance(avatar_id, str) or not avatar_id:
        raise ValueError("avatar id is invalid")
    if not idle_dir.is_dir():
        raise ValueError("idle frame directory is unavailable")
    if source_start_index is not None and not _non_negative_int(source_start_index):
        raise ValueError("source start index is invalid")
    if frame_count is not None and not _non_negative_int(frame_count):
        raise ValueError("frame count is invalid")
    payload = {
        "version": 1,
        "chunkId": chunk_id,
        "fps": fps,
        "trimStartFrames": trim_start_frames,
        "avatarId": avatar_id,
        "sourceStartIndex": source_start_index,
        "idleFrameDir": str(idle_dir),
        "frameCount": frame_count,
    }
    if source_timeline is not None:
        payload["sourceTimeline"] = source_timeline
    if source_spans is not None:
        from core.avatar_output_contract import validate_source_spans
        payload['sourceSpans'] = validate_source_spans(source_spans,frame_count)
    if remote_source is not None:
        from core.avatar_output_contract import validate_remote_source
        payload['remoteSource'] = validate_remote_source(remote_source)
    if ordered_output is not None:
        from core.avatar_output_contract import validate_ordered_start, validate_ordered_render
        ordered = validate_ordered_start(ordered_output)
        first_motion=(payload['sourceSpans'][0]['timeline']['motionId'] if source_spans is not None
                      else hashlib.sha256(str(idle_dir).encode()).hexdigest())
        if fps != 24 or source_start_index is not None and ordered['motionId'] != first_motion:
            raise ValueError('ordered_output_source_mismatch')
        if source_start_index is not None:
            validate_ordered_render(ordered, source_timeline, frame_count, source_spans)
        payload['orderedOutput'] = ordered
    if anticipation is not None:
        try:
            payload["anticipation"] = _validated_anticipation(
                anticipation,
                avatar_id=avatar_id,
                fps=fps,
            )
            _trace_plan(chunk_id, 'validated', True)
        except ValueError as error:
            _trace_plan(chunk_id, _ANTICIPATION_REJECTIONS.get(str(error), 'unclassified_validation'), False)
            _warning(f"anticipation omitted: {error}")
    else:
        _trace_plan(chunk_id, 'not_supplied', False)
    return target_dir, payload


def _write_atomic(sidecar, payload):
    temporary = sidecar.parent / f".{sidecar.name}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, sidecar)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def validate_failure(value, chunk_id):
    from core.avatar_output_contract import validate_remote_source
    if (type(value) is not dict or set(value) != {'version','chunkId','stage','errorType','remoteSource'}
            or type(value['version']) is not int or value['version'] != 1 or value['chunkId'] != chunk_id
            or type(value['stage']) is not str or value['stage'] not in _FAILURE_STAGES
            or type(value['errorType']) is not str or value['errorType'] not in _FAILURE_TYPES):
        raise ValueError('ordered_speech_failure_invalid')
    return {**value,'remoteSource':validate_remote_source(value['remoteSource'])}


def publish_failure(*, frame_dir, chunk_id, remote_source, stage, error):
    """Retain a remote terminal result independently of optional diagnostics.

    No exception message, speech text or source path crosses this boundary.
    Local/cached sidecar readers are unchanged; this does not authorize output.
    """
    try:
        target = _trusted_frame_dir(frame_dir,chunk_id,require_exists=False)
        target.mkdir(exist_ok=True)
        payload = validate_failure(dict(version=1,chunkId=chunk_id,remoteSource=remote_source,
            stage=stage,errorType=type(error).__name__ if type(error).__name__ in _FAILURE_TYPES else 'other'),chunk_id)
        _write_atomic(target / FAILURE_SIDECAR_NAME,payload)
        _trace_plan(chunk_id,'terminal_failure_written',True)
        return True
    except Exception:
        _trace_plan(chunk_id,'terminal_failure_written',False)
        return False


def publish(
    *,
    frame_dir,
    chunk_id,
    fps,
    trim_start_frames,
    avatar_id,
    idle_frame_dir,
    source_start_index=None,
    frame_count=None,
    anticipation=None,
    source_timeline=None,
    ordered_output=None,
    remote_source=None,
    source_spans=None,
):
    """Atomically publish metadata; failures deliberately never affect rendering."""
    try:
        target_dir, payload = _validated_payload(
            frame_dir=frame_dir,
            chunk_id=chunk_id,
            fps=fps,
            trim_start_frames=trim_start_frames,
            avatar_id=avatar_id,
            idle_frame_dir=idle_frame_dir,
            source_start_index=source_start_index,
            frame_count=frame_count,
            anticipation=anticipation,
            source_timeline=source_timeline,
            ordered_output=ordered_output,
            remote_source=remote_source,
            source_spans=source_spans,
        )
        _write_atomic(target_dir / SIDECAR_NAME, payload)
        _trace_plan(chunk_id, 'final_sidecar_written', True)
        return True
    except Exception as error:
        _trace_plan(chunk_id, 'final_sidecar_written', False)
        _warning(str(error))
        return False


def publish_initial(**kwargs):
    """Publish a pre-render sibling that survives worker frame-dir replacement."""
    try:
        target_dir, payload = _validated_payload(**kwargs)
        _write_atomic(_initial_sidecar(target_dir, kwargs["chunk_id"]), payload)
        _trace_plan(kwargs.get('chunk_id'), 'initial_sidecar_written', True)
        return True
    except Exception as error:
        _trace_plan(kwargs.get('chunk_id'), 'initial_sidecar_written', False)
        _warning(str(error))
        return False


def remove_initial(*, frame_dir, chunk_id):
    """Remove only the exact pre-render sibling, never a render directory."""
    try:
        target_dir = _trusted_frame_dir(frame_dir, chunk_id, require_exists=False)
        _initial_sidecar(target_dir, chunk_id).unlink(missing_ok=True)
        return True
    except Exception as error:
        _warning(str(error))
        return False


def publish_result(
    *,
    frame_dir,
    chunk_id,
    fps,
    trim_start_frames,
    avatar_id,
    idle_frame_dir,
    result,
    anticipation=None,
    ordered_output=None,
    remote_source=None,
):
    """Publish completed render information using its desktop-visible semantics."""
    try:
        source_start_index = result.get("start_index")
        if source_start_index is not None:
            source_start_index = int(source_start_index)
        render_frame_count = result.get("frame_count")
        if render_frame_count is not None:
            render_frame_count = max(int(render_frame_count) - trim_start_frames, 0)
    except Exception as error:
        _warning(f"invalid render result ({error})")
        return False
    return publish(
        frame_dir=frame_dir,
        chunk_id=chunk_id,
        fps=fps,
        trim_start_frames=trim_start_frames,
        avatar_id=avatar_id,
        idle_frame_dir=idle_frame_dir,
        source_start_index=source_start_index,
        frame_count=render_frame_count,
        anticipation=anticipation,
        source_timeline=_result_timeline(result, trim_start_frames, idle_frame_dir, fps),
        ordered_output=ordered_output,
        remote_source=remote_source,
        source_spans=result.get('source_spans'),
    )


def _result_timeline(result, trim, idle_frame_dir, fps):
    """Only exact producer indices; older render results remain unmapped."""
    count, indices = result.get('source_frame_count'), result.get('source_indices')
    if (fps != 24 or type(count) is not int or not 1 <= count <= 1440
            or type(trim) is not int or not isinstance(indices, list)
            or not 0 <= trim < len(indices) <= 1440
            or len(indices) != result.get('frame_count')
            or any(type(index) is not int or not 0 <= index < count for index in indices)):
        return None
    return dict(version=1, motionId=hashlib.sha256(str(Path(idle_frame_dir).resolve()).encode()).hexdigest(),
                sourceFrameCount=count, sourceFps=24, sourceIndices=list(indices[trim:]))
