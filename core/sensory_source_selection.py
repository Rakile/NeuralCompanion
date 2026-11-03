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


def set_source_enabled(sources, source, enabled):
    """Return a normalized source list with one provider enabled or disabled.

    ``off`` remains the exclusive empty selection. Enabling another provider
    preserves every source that is already selected so ambient providers can
    participate in the same sensory cycle.
    """

    selected = normalize_source_tokens(sources)
    token = str(source or "").strip().lower()
    if not token:
        return selected
    if token == "off":
        return []
    if bool(enabled):
        if token not in selected:
            selected.append(token)
        return selected
    return [item for item in selected if item != token]


def source_runtime_updates(sources, source, enabled):
    """Return the atomic runtime settings for one source activation change.

    A source selector represents operational background awareness, not only a
    stored source name.  The hidden loop therefore follows the normalized
    selection: it starts when at least one source is enabled and stops when the
    selection becomes empty.
    """

    selected = set_source_enabled(sources, source, enabled)
    return {
        "sensory_feedback_source": source_tokens_value(selected),
        "sensory_pingpong_enabled": bool(selected),
    }


def enabled_source_ids(sources, provider_ids):
    """Return configured source ids that have an explicitly registered adapter."""

    available = {
        str(provider_id or "").strip().lower()
        for provider_id in provider_ids
        if str(provider_id or "").strip()
    }
    return tuple(
        source
        for source in normalize_source_tokens(sources)
        if source in available
    )


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


def resolve_companion_orb_target_source_selection(sources, enabled, *, explicit):
    selected = normalize_source_tokens(sources)
    if bool(explicit):
        return selected
    return normalize_companion_orb_target_source_selection(selected, enabled)
