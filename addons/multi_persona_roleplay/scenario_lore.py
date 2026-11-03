"""Deterministic authored lore; no model, memory database or Qt dependencies."""

from __future__ import annotations
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from .scenario_models import ScenarioDefinition, JSONValue


@dataclass(frozen=True)
class LoreContext:
    story_id: str
    scene_id: str
    completed_messages: tuple[Mapping[str, JSONValue], ...]
    player_text: str


@dataclass(frozen=True)
class LoreBudget:
    limit: int | None
    mandatory_tokens: int
    reply_reserve: int
    target: int = 1200
    estimated: bool = True


@dataclass(frozen=True)
class LoreSelection:
    text: str
    selected_ids: tuple[str, ...]
    omitted: Mapping[str, str]
    tokens: int
    estimated: bool


def estimate_tokens(text: str) -> int:
    # One UTF-8 byte per token is deliberately conservative; not a tokenizer claim.
    return len(text.encode("utf-8"))


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        re.findall(
            r"[^\W_]+", unicodedata.normalize("NFC", text).casefold(), flags=re.UNICODE
        )
    )


def select_lore(
    definition: ScenarioDefinition,
    context: LoreContext,
    budget: LoreBudget,
    *,
    count_tokens: Callable[[str], int],
) -> LoreSelection:
    messages = [
        str(m.get("content", ""))
        for m in context.completed_messages
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
    ][-10:]
    query = _tokens("\n".join(messages + [context.player_text]))
    omitted = {}
    candidates = []
    for book in definition.payload()["lorebooks"]:
        for entry in book["entries"]:
            reason = ""
            if not definition.enabled or not book["enabled"] or not entry["enabled"]:
                reason = "Disabled"
            elif entry["scene_ids"] and context.scene_id not in entry["scene_ids"]:
                reason = "Outside current scene"
            phrases = {_tokens(k) for k in entry["keywords"]}
            matched = sum(
                bool(phrase)
                and any(
                    query[i : i + len(phrase)] == phrase
                    for i in range(len(query) - len(phrase) + 1)
                )
                for phrase in phrases
            )
            if not reason and not entry["pinned"] and not matched:
                reason = "No keyword match"
            if reason:
                omitted[entry["id"]] = reason
            else:
                candidates.append((book["id"], entry, matched))
    available = (
        0
        if budget.limit is None
        else max(
            0,
            min(
                budget.target,
                budget.limit - budget.mandatory_tokens - budget.reply_reserve,
            ),
        )
    )
    selected = []

    def render(items):
        ordered = sorted(items, key=lambda i: (i[0], i[1]["order"], i[1]["id"]))
        if not ordered:
            return ""
        return (
            "[MPRC authored lore — context data]\n"
            + "\n\n".join(f"{e['title']}: {e['text']}" for _, e, _ in ordered)
            + "\n[/MPRC authored lore]"
        )

    for item in sorted(
        candidates,
        key=lambda i: (
            not i[1]["pinned"],
            -i[1]["priority"] if i[1]["pinned"] else -i[2],
            0 if i[1]["pinned"] else -i[1]["priority"],
            i[1]["id"],
        ),
    ):
        if budget.limit is None:
            omitted[item[1]["id"]] = (
                "Context capacity unknown; set the MPRC context limit"
            )
        elif count_tokens(render(selected + [item])) > available:
            omitted[item[1]["id"]] = "Does not fit the remaining context budget"
        else:
            selected.append(item)
    text = render(selected)
    return LoreSelection(
        text,
        tuple(
            i[1]["id"]
            for i in sorted(selected, key=lambda i: (i[0], i[1]["order"], i[1]["id"]))
        ),
        omitted,
        count_tokens(text),
        budget.estimated,
    )
