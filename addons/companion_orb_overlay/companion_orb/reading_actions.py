from __future__ import annotations

from dataclasses import dataclass
import re


DEFAULT_COMMENTARY_PROMPT = (
    "You are commenting on text the user intentionally selected for the Companion Orb. "
    "Keep the response short, natural, and useful. Do not mention OCR, clipboard, "
    "hidden sensory feedback, or memory. Do not quote long passages back. If the "
    "selection is code or an error, identify the likely issue and one practical next "
    "step. If the text appears personal or private, be discreet and avoid storing or "
    "reusing details."
)

READING_SETTINGS_DEFAULTS: dict[str, object] = {
    "companion_orb_reader_exclude_from_memory": True,
    "companion_orb_reader_commentary_prompt": DEFAULT_COMMENTARY_PROMPT,
}


@dataclass(frozen=True)
class ReadingMenuAction:
    action_id: str
    label: str
    text_source: str
    speaks_text: bool
    requests_comment: bool

    @property
    def requires_selection(self) -> bool:
        return self.text_source == "selection"

    @property
    def reads_selected_text(self) -> bool:
        return self.speaks_text


READING_MENU_ACTIONS = (
    ReadingMenuAction("read_clipboard", "Read Clipboard", "clipboard", True, False),
    ReadingMenuAction("select_area_read", "Select Area to Read", "selection", True, False),
    ReadingMenuAction("select_area_read_comment", "Select Area to Read + Comment", "selection", True, True),
    ReadingMenuAction("select_area_comment", "Select Area + Comment", "selection", False, True),
)

_ACTION_BY_ID = {item.action_id: item for item in READING_MENU_ACTIONS}
_ACTION_BY_LABEL = {item.label.lower(): item for item in READING_MENU_ACTIONS}


def normalize_action_id(value: str) -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    if lowered in _ACTION_BY_LABEL:
        return _ACTION_BY_LABEL[lowered].action_id
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return normalized if normalized in _ACTION_BY_ID else ""


def action_for_id(action_id: str) -> ReadingMenuAction | None:
    return _ACTION_BY_ID.get(normalize_action_id(action_id))


def clean_readable_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def chunk_text_for_tts(value: str, *, max_chars: int = 900) -> list[str]:
    text = clean_readable_text(value)
    if not text:
        return []
    limit = max(1, int(max_chars or 900))
    chunks: list[str] = []
    current = ""
    for paragraph in [part.strip() for part in text.split("\n") if part.strip()]:
        words = paragraph.split()
        for word in words:
            if len(word) > limit:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(word[index:index + limit] for index in range(0, len(word), limit))
                continue
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > limit:
                chunks.append(current)
                current = word
            else:
                current = candidate
        if current and len(current) >= limit:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks


def build_comment_messages(
    *,
    selected_text: str,
    behavior_prompt: str,
    response_style_label: str,
    exclude_from_memory: bool,
    mode: str,
) -> list[dict[str, str]]:
    prompt = clean_readable_text(behavior_prompt) or DEFAULT_COMMENTARY_PROMPT
    style = str(response_style_label or "Very friendly").strip() or "Very friendly"
    privacy = (
        "Do not store, memorize, archive, or refer back to the selected text after this one response."
        if exclude_from_memory
        else "Use the selected text only as context for this Companion Orb response."
    )
    mode_hint = (
        "The user chose read plus comment, so make only the comment part. The selected text is already being read aloud."
        if normalize_action_id(mode) == "select_area_read_comment"
        else "The user chose comment only, so summarize or react without reading the selected text aloud."
    )
    return [
        {
            "role": "system",
            "content": (
                f"{prompt}\n\n"
                f"Companion Orb reply style: {style}.\n"
                f"Privacy rule: {privacy}\n"
                f"Action mode: {mode_hint}\n"
                "Return only the short spoken Companion Orb comment. Do not include labels, markdown fences, JSON, or stage directions."
            ),
        },
        {
            "role": "user",
            "content": "Selected text for this one Companion Orb action:\n\n" + clean_readable_text(selected_text),
        },
    ]
