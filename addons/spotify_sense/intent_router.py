from __future__ import annotations

import re


def _wants_music_comment(value: str) -> bool:
    return bool(
        re.search(
            r"\b(comment|commentary|talk about|tell me about|say something about|describe|react to)\b",
            value,
        )
    )


def _clean_play_query(query: str) -> str:
    value = str(query or "").strip()
    value = re.sub(r"\b(on|through)\s+spotify\b", "", value).strip()
    value = re.sub(r"^spotify\s+", "", value).strip()
    value = re.sub(
        r"\s+(and\s+)?(comment|commentary|talk about|tell me about|say something about|describe|react to)\b.*$",
        "",
        value,
    ).strip()
    return value


def _track_search_query(query: str) -> str:
    value = str(query or "").strip()
    match = re.match(r"^(?P<title>.+?)\s+(?:by|with)\s+(?P<artist>[^,]+)$", value, flags=re.IGNORECASE)
    if not match:
        return value
    title = re.sub(r"\b(the\s+)?song\b|\btrack\b", "", match.group("title"), flags=re.IGNORECASE).strip()
    artist = match.group("artist").strip()
    if title and artist:
        return f"{title} {artist}"
    return value


def route_music_intent(text: str) -> dict[str, object]:
    value = str(text or "").strip().lower()
    if not value:
        return {"matched": False, "tool": "", "args": {}, "confidence": 0.0}
    wants_comment = _wants_music_comment(value)

    if re.search(r"\b(what|which)\s+(song|track|music)\b|\bnow playing\b|\bwhat is playing\b", value):
        return {"matched": True, "tool": "spotify.current_track", "args": {"comment": wants_comment}, "confidence": 0.92}
    if re.search(r"\b(skip|next\s+(song|track|music)|next\s+.*\bplaylist)\b", value):
        return {"matched": True, "tool": "spotify.next", "args": {"comment": wants_comment}, "confidence": 0.9}
    if re.search(r"\b(previous|back one|last song|last track)\b", value):
        return {"matched": True, "tool": "spotify.previous", "args": {"comment": wants_comment}, "confidence": 0.86}
    if re.search(r"\b(pause|stop)\s+(the\s+)?(spotify|music|song|track)\b|\bpause spotify\b|\bstop spotify\b", value):
        return {"matched": True, "tool": "spotify.pause", "args": {}, "confidence": 0.93}
    if re.search(r"\b(resume|continue|start)\s+(the\s+)?(spotify|music|song|track)\b|\bresume spotify\b|\bstart spotify\b", value):
        return {"matched": True, "tool": "spotify.resume", "args": {"comment": wants_comment}, "confidence": 0.9}
    if re.search(r"\b(turn|lower|bring)\s+(it|music|spotify).*\bdown\b", value):
        return {"matched": True, "tool": "spotify.volume", "args": {"relative": -10}, "confidence": 0.82}
    if re.search(r"\b(turn|raise|bring)\s+(it|music|spotify).*\bup\b", value):
        return {"matched": True, "tool": "spotify.volume", "args": {"relative": 10}, "confidence": 0.82}

    play_match = re.search(r"\b(play|put on|start)\s+(?P<query>.+)", value)
    if play_match:
        query = _clean_play_query(play_match.group("query"))
        if not query:
            return {"matched": False, "tool": "", "args": {}, "confidence": 0.0}
        playlist_requested = "playlist" in query
        specific_track_requested = bool(
            re.search(r"\b(song|track)\b", query)
            or re.search(r"\s+(by|with)\s+[\w '&.-]+$", query)
        )
        generic_music_requested = any(
            term in value
            for term in ("music", "song", "playlist", "spotify", "calm", "focus", "epic", "cyberpunk", "ambient")
        )
        if generic_music_requested or specific_track_requested:
            args = {
                "query": _track_search_query(query) if specific_track_requested and not playlist_requested else query,
                "display_query": query,
                "comment": wants_comment,
                "preferred_type": "playlist" if playlist_requested else ("track" if specific_track_requested else "auto"),
            }
            return {"matched": True, "tool": "spotify.play_search", "args": args, "confidence": 0.82 if specific_track_requested else 0.78}

    return {"matched": False, "tool": "", "args": {}, "confidence": 0.0}


def infer_music_mood(track: dict[str, object] | None) -> str:
    payload = track or {}
    text = " ".join(
        str(payload.get(key) or "")
        for key in ("name", "album", "context", "artists")
    ).lower()
    if any(word in text for word in ("calm", "sleep", "lofi", "ambient", "relax")):
        return "calm"
    if any(word in text for word in ("focus", "study", "code", "coding")):
        return "focus"
    if any(word in text for word in ("dark", "cyberpunk", "noir", "shadow")):
        return "dark"
    if any(word in text for word in ("epic", "battle", "trailer", "hero")):
        return "epic"
    if any(word in text for word in ("sad", "blue", "rain", "melancholy")):
        return "sad"
    if any(word in text for word in ("fantasy", "magic", "dungeon", "tavern")):
        return "fantasy"
    if any(word in text for word in ("dance", "party", "energy", "workout")):
        return "energetic"
    return "neutral"
