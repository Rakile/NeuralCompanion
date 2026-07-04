"""Small helpers for normalizing sensory source selections."""

from __future__ import annotations


COMPANION_ORB_PROVIDER_ID = "companion_orb_target"


def normalize_source_tokens(sources):
    if isinstance(sources, str):
        raw_items = str(sources or "off").split(",")
    elif isinstance(sources, (list, tuple, set)):
        raw_items = list(sources or [])
    else:
        raw_items = []
    selected = []
    seen = set()
    for item in raw_items:
        token = str(item or "").strip().lower()
        if not token or token == "off" or token in seen:
            continue
        selected.append(token)
        seen.add(token)
    return selected


def source_tokens_value(sources):
    selected = normalize_source_tokens(sources)
    return ",".join(selected) if selected else "off"


def normalize_companion_orb_target_source_selection(sources, enabled):
    selected = normalize_source_tokens(sources)
    selected_set = set(selected)
    if bool(enabled):
        selected_set.add(COMPANION_ORB_PROVIDER_ID)
    else:
        selected_set.discard(COMPANION_ORB_PROVIDER_ID)
    ordered = [source for source in selected if source in selected_set]
    if bool(enabled) and COMPANION_ORB_PROVIDER_ID not in ordered:
        ordered.append(COMPANION_ORB_PROVIDER_ID)
    return ordered
