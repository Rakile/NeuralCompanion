"""Pure runtime telemetry normalization for the native QML shell."""

from __future__ import annotations

import time
import math
import re
from collections.abc import Mapping
from typing import Any
from core.runtime.conversation import ConversationSnapshot


def _speech_message_id(chunk: Mapping[str, Any], conversation: ConversationSnapshot) -> str:
    if chunk.get("speech_hidden") or chunk.get("speech_session_generation") != conversation.session_generation.value:
        return ""
    message_id = str(chunk.get("speech_message_id") or "")
    transaction_id = str(chunk.get("speech_transaction_id") or "")
    for message in conversation.messages:
        if message.role != "assistant":
            continue
        if message_id:
            if message.message_id == message_id:
                return message_id
        elif transaction_id and message.metadata.get("normal_chat_transaction_id") == transaction_id:
            return message.message_id
    return ""


def _ordered_chunks(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    chunks = [dict(item or {}) for item in snapshot.get("chunks", ())]
    return sorted(chunks, key=lambda item: int(item.get("sequence_index", 0) or 0))


def _has_reading_words(text: object) -> bool:
    # Match the display's exclusion of bracket controls, retaining link labels.
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(text or ""))
    value = re.sub(r"\[[^\]]*\]", "", value)
    return any(character.isalnum() for character in value)


def _waiting_reading_anchor(
    chunks: list[dict[str, Any]], conversation: ConversationSnapshot | None,
) -> Mapping[str, Any] | None:
    """Retain delivered words only while the same reply has a pending successor."""
    for index, successor in enumerate(chunks):
        state = str(successor.get("playback_state") or "").strip().lower()
        if state == "completed":
            continue
        if (state not in {"pending", "playing"}
                or successor.get("status") in {"failed", "error", "cancelled"}
                or successor.get("speech_hidden")
                or (state == "playing" and _has_reading_words(successor.get("text")))):
            return None
        message_id = _speech_message_id(successor, conversation) if conversation is not None else ""
        if conversation is not None and not message_id:
            return None
        for previous in reversed(chunks[:index]):
            if not _has_reading_words(previous.get("text")):
                continue
            if conversation is not None:
                same_owner = _speech_message_id(previous, conversation) == message_id
            else:
                same_owner = not previous.get("speech_hidden") and all(
                    previous.get(key) == successor.get(key) for key in (
                        "speech_session_generation", "speech_message_id", "speech_transaction_id"))
            return previous if same_owner else None
        return None
    return None


def _render_fraction(chunk: Mapping[str, Any]) -> float:
    if "progressive_render_complete" in chunk:
        expected = max(0, int(chunk.get("expected_frame_count", 0) or 0))
        rendered = max(0, int(chunk.get("rendered_frame_count", 0) or 0))
        fraction = min(rendered / expected, 1.) if expected > 0 else 0.
        return fraction if chunk.get("progressive_render_complete") is True else min(fraction, .99)
    status = str(chunk.get("status") or "").strip().lower()
    if status in {"rendered", "ready", "playing", "completed"}:
        return 1.0
    expected = max(0, int(chunk.get("expected_frame_count", 0) or 0))
    rendered = max(0, int(chunk.get("rendered_frame_count", 0) or 0))
    if expected <= 0:
        return 0.0
    return min(float(rendered) / float(expected), 1.0)


def _has_media_clock(chunk: Mapping[str, Any]) -> bool:
    return (chunk.get("frame_transport") == "shared_rgb"
        or chunk.get("progressive_audio") is True
        or any(key in chunk for key in ("audio_media_seconds", "audio_clock_monotonic",
               "audio_scheduled_through_seconds", "audio_clock_running")))


def _audio_fraction(chunk: Mapping[str, Any], now: float) -> float:
    shared_rgb = chunk.get("frame_transport") == "shared_rgb"
    if _has_media_clock(chunk):
        from core.continuous_audio import continuous_media_seconds
        if chunk.get("audio_start_pending") or chunk.get("playback_state") != "playing":
            return 0.0
        media = continuous_media_seconds(chunk, time.monotonic())
        try:
            duration = float(chunk.get("duration_seconds", 0.0) or 0.0)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if media is None or not math.isfinite(duration) or duration <= 0:
            return 0.0
        # A growing linguistic-duration estimate must not rewind the highlight.
        # The playback owner supplies this floor; normalization remains pure.
        floor = chunk.get("audio_progress_floor", 0.0)
        try:
            floor = float(floor) if type(floor) in (int, float) else 0.0
        except (ValueError, OverflowError):
            floor = 0.0
        if not math.isfinite(floor):
            floor = 0.0
        # Existing shared-RGB completed-file clocks retain their endpoint. New
        # audio-only clocks reserve completion for the actual logical END marker.
        ceiling = 1.0 if shared_rgb and chunk.get("audio_duration_estimated") is not True else 0.999999
        return min(max(media / duration, floor, 0.0), ceiling)
    if str(chunk.get("playback_state") or "").strip().lower() != "playing":
        return 0.0
    try:
        started_at = float(chunk.get("audio_started_at", 0.0) or 0.0)
        duration = float(chunk.get("duration_seconds", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if (not all(math.isfinite(value) for value in (started_at, duration, now))
            or started_at <= 0.0 or duration <= 0.0):
        return 0.0
    return min(max(now - started_at, 0.0) / duration, 1.0)


def normalize_pipeline_progress(
    snapshot: Mapping[str, Any] | None,
    preview_state: Mapping[str, Any] | None = None,
    *,
    now: float | None = None,
    include_speech_progress: bool = True,
    conversation: ConversationSnapshot | None = None,
    remote_presentation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert MuseTalk pipeline state to the bounded QML Buffer Race contract.

    Speech progress is conversation-only presentation data. Callers can omit it
    while another playback owner, such as tutorial narration, uses the shared
    TTS pipeline without losing render or playback telemetry.
    """

    pipeline = dict(snapshot or {})
    preview = dict(preview_state or {})
    chunks = _ordered_chunks(pipeline)
    total = len(chunks)
    remote = dict(remote_presentation or {})
    if remote.get('phone_owns_presentation') is True and 'orderedOutput' in remote:
        return _remote_pipeline_progress(pipeline, chunks, remote)
    if total <= 0:
        return {
            "active": bool(pipeline.get("active", False)),
            "renderProgress": 0.0,
            "playbackProgress": 0.0,
            "chunkCount": 0,
            "leadChunks": 0.0,
            "failed": False,
            "summary": "Waiting for TTS",
            "speechActive": False,
            "speechText": "",
            "speechProgress": 0.0,
            "speechMessageId": "",
        }

    ready_units = 0.0
    for chunk in chunks:
        fraction = _render_fraction(chunk)
        ready_units += fraction
        if fraction < 1.0:
            break

    completed_units = 0.0
    for chunk in chunks:
        if str(chunk.get("playback_state") or "").strip().lower() == "completed":
            completed_units += 1.0
            continue
        break

    playback_units = completed_units
    active_index = preview.get("sequence_index")
    try:
        active_index = int(active_index)
    except (TypeError, ValueError):
        active_index = None
    active_chunk = next((chunk for chunk in chunks
        if int(chunk.get("sequence_index", 0) or 0) == active_index), {})
    if active_index is not None and not _has_media_clock(active_chunk):
        frame_index = int(preview.get("preview_frame_index", -1) or -1)
        expected = int(
            preview.get("expected_frame_count", 0)
            or preview.get("frame_count", 0)
            or 0
        )
        if frame_index >= 0 and expected > 1:
            playback_units = max(
                playback_units,
                float(active_index) + min(float(frame_index) / float(expected - 1), 1.0),
            )
    current_time = time.time() if now is None else float(now)
    speech_active = False
    speech_text = ""
    speech_progress = 0.0
    speech_message_id = ""
    for chunk in chunks:
        if str(chunk.get("playback_state") or "").strip().lower() == "playing":
            sequence = int(chunk.get("sequence_index", 0) or 0)
            speech_active = True
            speech_text = str(chunk.get("text", "") or "")
            speech_progress = _audio_fraction(chunk, current_time)
            if conversation is not None:
                speech_message_id = _speech_message_id(chunk, conversation)
                speech_active = bool(speech_message_id)
            playback_units = max(
                playback_units,
                float(sequence) + speech_progress,
            )
            break

    if pipeline.get("active"):
        anchor = _waiting_reading_anchor(chunks, conversation)
        if anchor is not None:
            # This is a presentation hold, not additional playback progress.
            speech_active = True
            speech_text = str(anchor.get("text") or "")
            speech_progress = 1.0
            if conversation is not None:
                speech_message_id = _speech_message_id(anchor, conversation)

    failed = any(
        str(chunk.get("status") or "").strip().lower() == "failed"
        or str(chunk.get("playback_state") or "").strip().lower() == "failed"
        for chunk in chunks
    )
    active = bool(pipeline.get("active", False))
    lead = ready_units - playback_units
    summary = (
        "TTS buffer failure"
        if failed
        else f"Buffer lead {max(lead, 0.0):.1f} chunks"
        if active
        else "Waiting for TTS"
    )
    denominator = float(max(total, 1))
    render_progress = min(max(ready_units / denominator, 0.0), 1.0)
    playback_progress = min(max(playback_units / denominator, 0.0), 1.0)
    progressive_chunks = [chunk for chunk in chunks if "progressive_render_complete" in chunk]
    if progressive_chunks:
        # Whole-percent labels must not round an unfinished reply up to 100%.
        if any(chunk.get("progressive_render_complete") is not True for chunk in progressive_chunks):
            render_progress = min(render_progress, .99)
        if completed_units < total:
            playback_progress = min(playback_progress, .99)
    return {
        "active": active,
        "renderProgress": render_progress,
        "playbackProgress": playback_progress,
        "chunkCount": total,
        "leadChunks": lead,
        "failed": failed,
        "summary": summary,
        "speechActive": speech_active and include_speech_progress,
        "speechText": speech_text if include_speech_progress else "",
        "speechProgress": speech_progress if include_speech_progress else 0.0,
        "speechMessageId": speech_message_id if include_speech_progress else "",
    }


def _remote_pipeline_progress(pipeline, chunks, presentation):
    """Do not interpolate phone playback from the Desktop preview or wall clock.

    Playback is segment-boundary evidence; the active-segment label advances on
    native start, the filled bar only on native completion. Prepared fractional
    segments count only native-appended ranges, never just downloaded files.
    """
    progress = presentation.get('remoteProgress')
    identity = presentation.get('remoteProgressIdentity')
    age = presentation.get('remoteProgressAgeSeconds')
    current = (isinstance(progress, Mapping) and type(age) in (int, float) and 0 <= age <= 5
               and isinstance(identity, Mapping) and identity.get('audioId') == progress.get('firstSourceId')
               and bool(chunks) and identity.get('renderChunkId') == chunks[0].get('chunk_id'))
    desktop = presentation.get('desktopProgress')
    download_current = (isinstance(desktop, Mapping) and bool(desktop.get('firstRenderChunkId')) and bool(chunks)
        and desktop.get('generation') == presentation['orderedOutput'].get('generation')
        and desktop.get('firstRenderChunkId') == chunks[0].get('chunk_id'))
    download_units = float(desktop['preparedUnits']) if download_current else 0.0
    count = max(len(chunks), int(progress['knownSegments']) if current else 0)
    final = desktop.get('finalSegments') if download_current else None
    if final is None: final = progress.get('finalSegments') if current else None
    count = max(count, final or 0)
    denominator = max(count, 1)
    total_label = str(count) + ('' if final is not None else '+')
    rendered = 0.0
    for chunk in chunks:
        fraction = _render_fraction(chunk)
        rendered += fraction
        if fraction < 1: break
    prepared = float(progress['preparedUnits']) if current else 0.0
    completed = int(progress['completedSegments']) if current else 0
    playing = progress.get('playingSequence') if current else None
    ready = int(prepared)
    ready_ahead = max(0, ready-(playing+1 if playing is not None else completed))
    return dict(active=bool(pipeline.get('active')), phoneReadyVisible=True, downloadReadyVisible=True,
        downloadReadyProgress=min(download_units/denominator, 1),
        downloadReadyLabel=f"{desktop['readyChunks']} chunks · {int(download_units)} / {total_label} seg"
            if download_current else 'Waiting',
        renderProgress=min(rendered/denominator, 1), phoneReadyProgress=min(prepared/denominator, 1),
        playbackProgress=min(completed/denominator, 1), chunkCount=count, leadChunks=prepared-completed,
        renderLabel=f'{int(rendered)} / {total_label}',
        phoneReadyLabel=f'{ready} / {total_label}' if current else 'Waiting',
        playbackLabel=f'Segment {playing+1} / {total_label}' if playing is not None else
            f'{completed} / {total_label}' if current else 'Waiting',
        summary=(f'Playing segment {playing+1} of {total_label} · {ready_ahead} segments ready ahead'
                 if playing is not None else f'{ready_ahead} segments ready ahead' if current else
                 'Waiting for phone preparation/playback feedback'),
        failed=any(c.get('status') == 'failed' for c in chunks),
        speechActive=False, speechText='', speechProgress=0.0, speechMessageId='')
