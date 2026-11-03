"""Desktop-only chat presentation; never routes speech or changes personas."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PySide6 import QtCore


def local_image_url(value: object) -> str:
    """Load saved local portraits asynchronously in QML, never fetch remote URLs."""
    text = str(value or "").strip()
    if not text or text.startswith(("\\\\", "//")):
        return ""
    url = QtCore.QUrl(text)
    if url.scheme() and len(url.scheme()) > 1:
        if not url.isLocalFile() or url.host():
            return ""
        text = url.toLocalFile()
    path = Path(text)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return QtCore.QUrl.fromLocalFile(str(path)).toString(QtCore.QUrl.FullyEncoded)


def authored_rows(
    controller: Any, speaker: str, text: str, role: str
) -> list[dict[str, str]]:
    """Freeze author IDs when a line is appended; later selection/renames cannot steal it."""
    if role == "assistant" and speaker in {"Story", "Restored Beat"}:
        segments = controller._remote_story_segments(text)
        # The existing story parser ignores a preamble before its first tag.
        first_tag = re.search(
            r"\[(?:NARRATOR|CHARACTER:|CHOICES|(?:AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO):)",
            text,
            re.IGNORECASE,
        )
        if first_tag and text[: first_tag.start()].strip():
            segments.insert(
                0,
                {
                    "speaker_id": "narrator",
                    "speaker_name": "Narrator",
                    "role": "narrator",
                    "text": text[: first_tag.start()].strip(),
                },
            )
        choices = re.search(r"\[CHOICES\](.*)", text, re.IGNORECASE | re.DOTALL)
        if choices and choices.group(1).strip():
            segments.append(
                {
                    "speaker_id": "",
                    "speaker_name": "Choices",
                    "role": "note",
                    "text": choices.group(1).strip(),
                }
            )
    else:
        persona_id = (
            controller._remote_persona_id_for_name(speaker)
            if role == "assistant"
            else ""
        )
        segments = [
            {
                "speaker_id": persona_id,
                "speaker_name": speaker,
                "role": role,
                "text": text,
            }
        ]
    result = []
    for segment in segments:
        persona_id = str(segment.get("speaker_id") or "")
        if segment.get("role") == "narrator":
            persona_id = controller.selected_narrator_persona_id()
        elif segment.get("role") not in {"assistant", "character"}:
            persona_id = ""
        result.append(
            {
                "personaId": persona_id,
                "name": str(segment.get("speaker_name") or speaker),
                "text": str(segment.get("text") or ""),
                "role": str(segment.get("role") or role),
            }
        )
    return result


def chat_presentation(controller: Any) -> dict[str, object]:
    """Called under the controller lock. Playing denotes an active playback route."""
    personas = {persona.id: persona for persona in controller.personas}

    def decorate(row: dict[str, str]) -> dict[str, str]:
        persona = personas.get(row.get("personaId", ""))
        return {
            **row,
            "imageUrl": local_image_url(getattr(persona, "character_image_path", "")),
        }

    rows = []
    for index, line in enumerate(controller._native_chat_transcript):
        stored = line.get("avatar_rows")
        if stored is None:
            stored = [
                {
                    "personaId": "",
                    "name": str(line.get("speaker") or ""),
                    "text": str(line.get("text") or ""),
                    "role": str(line.get("role") or "note"),
                }
            ]
        for offset, row in enumerate(stored):
            rows.append(
                decorate({**row, "id": f"{line.get('line_id', index)}:{offset}"})
            )

    playback = controller._engine_speech_status()
    record = controller._native_chat_speaker
    active = bool(playback.get("speech_playing") or playback.get("speech_paused"))
    if record and (
        not active or controller._shutting_down or not controller.session.enabled
    ):
        record["armed"] = False
    state = "idle"
    if active and record.get("armed"):
        state = "paused" if playback.get("speech_paused") else "speaking"
    persona_id = str(record.get("personaId") or "")
    persona = personas.get(persona_id)
    speaker = decorate(
        {
            "personaId": persona_id,
            "name": str(
                getattr(persona, "display_name", "")
                or ("Unknown speaker" if record else "No speaker yet")
            ),
            "text": str(record.get("text") or ""),
            "state": state,
        }
    )
    return {"rows": rows, "speaker": speaker}
