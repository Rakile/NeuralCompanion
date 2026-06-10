from __future__ import annotations

import re


def route_music_intent(text: str) -> dict[str, object]:
    value = str(text or "").strip().lower()
    if not value:
        return {"matched": False, "tool": "", "args": {}, "confidence": 0.0}

    if re.search(r"\b(what|which)\s+(song|track|music)\b|\bnow playing\b|\bwhat is playing\b", value):
        return {"matched": True, "tool": "spotify.current_track", "args": {}, "confidence": 0.92}
    if re.search(r"\b(skip|next song|next track)\b", value):
        return {"matched": True, "tool": "spotify.next", "args": {}, "confidence": 0.9}
    if re.search(r"\b(previous|back one|last song|last track)\b", value):
        return {"matched": True, "tool": "spotify.previous", "args": {}, "confidence": 0.86}
    if re.search(r"\b(pause|stop)\s+(spotify|music|song|track)\b|\bpause spotify\b", value):
        return {"matched": True, "tool": "spotify.pause", "args": {}, "confidence": 0.93}
    if re.search(r"\b(resume|continue)\s+(spotify|music|song|track)\b|\bresume spotify\b", value):
        return {"matched": True, "tool": "spotify.resume", "args": {}, "confidence": 0.9}
    if re.search(r"\b(turn|lower|bring)\s+(it|music|spotify).*\bdown\b", value):
        return {"matched": True, "tool": "spotify.volume", "args": {"relative": -10}, "confidence": 0.82}
    if re.search(r"\b(turn|raise|bring)\s+(it|music|spotify).*\bup\b", value):
        return {"matched": True, "tool": "spotify.volume", "args": {"relative": 10}, "confidence": 0.82}

    play_match = re.search(r"\b(play|put on|start)\s+(?P<query>.+)", value)
    if play_match and any(term in value for term in ("music", "song", "playlist", "spotify", "calm", "focus", "epic", "cyberpunk", "ambient")):
        query = play_match.group("query").strip()
        query = re.sub(r"\b(on|through)\s+spotify\b", "", query).strip()
        return {"matched": True, "tool": "spotify.play_search", "args": {"query": query}, "confidence": 0.78}

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
