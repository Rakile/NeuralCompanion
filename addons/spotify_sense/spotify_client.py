from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


SPOTIFY_SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
]


class SpotifySenseClient:
    AUTH_URL = "https://accounts.spotify.com/authorize"
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_URL = "https://api.spotify.com/v1"

    def __init__(self, settings):
        self.settings = settings
        self.pending_state = ""
        self.pending_verifier = ""

    def is_connected(self) -> bool:
        data = self.settings.data
        return bool(data.get("access_token") and data.get("refresh_token"))

    def build_authorization_url(self) -> dict[str, Any]:
        client_id = str(self.settings.data.get("client_id") or "").strip()
        if not client_id:
            return _error("not_configured", "Spotify Client ID is required before login.")
        self.pending_state = secrets.token_urlsafe(24)
        self.pending_verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.pending_verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "scope": " ".join(SPOTIFY_SCOPES),
                "redirect_uri": self.settings.data.get("redirect_uri"),
                "state": self.pending_state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
        )
        return {"ok": True, "url": f"{self.AUTH_URL}?{query}", "state": self.pending_state}

    def exchange_code(self, code: str, state: str) -> dict[str, Any]:
        if state != self.pending_state:
            return _error("state_mismatch", "Spotify OAuth state did not match. Try connecting again.")
        if not code:
            return _error("missing_code", "Spotify callback did not include an authorization code.")
        data = {
            "grant_type": "authorization_code",
            "code": str(code),
            "redirect_uri": self.settings.data.get("redirect_uri"),
            "client_id": self.settings.data.get("client_id"),
            "code_verifier": self.pending_verifier,
        }
        result = self._post_token(data)
        if not result.get("ok"):
            return result
        self._store_token_result(result.get("data") or {})
        profile = self.get_current_user()
        return {"ok": True, "status": "connected", "profile": profile.get("data", {}) if profile.get("ok") else {}}

    def refresh_access_token(self) -> dict[str, Any]:
        refresh = str(self.settings.data.get("refresh_token") or "").strip()
        if not refresh:
            return _error("not_connected", "Spotify is not connected.")
        result = self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": self.settings.data.get("client_id"),
            }
        )
        if not result.get("ok"):
            return result
        payload = dict(result.get("data") or {})
        if "refresh_token" not in payload:
            payload["refresh_token"] = refresh
        self._store_token_result(payload)
        return {"ok": True, "status": "refreshed"}

    def _store_token_result(self, payload: dict[str, Any]) -> None:
        expires_in = int(payload.get("expires_in") or 3600)
        scopes = str(payload.get("scope") or "").split()
        self.settings.update(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=str(payload.get("refresh_token") or self.settings.data.get("refresh_token") or ""),
            expires_at=int(time.time() + max(60, expires_in) - 30),
            scopes=scopes,
        )

    def _post_token(self, data: dict[str, Any]) -> dict[str, Any]:
        body = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(self.TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        return _read_json_request(request)

    def _ensure_token(self) -> dict[str, Any]:
        if not self.is_connected():
            return _error("not_connected", "Spotify is not connected.")
        if int(self.settings.data.get("expires_at") or 0) <= int(time.time()):
            return self.refresh_access_token()
        return {"ok": True}

    def api(self, method: str, path: str, body: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> dict[str, Any]:
        token_result = self._ensure_token()
        if not token_result.get("ok"):
            return token_result
        url = f"{self.API_URL}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.settings.data.get('access_token')}", "Content-Type": "application/json"}
        request = urllib.request.Request(url, data=payload, headers=headers, method=str(method or "GET").upper())
        return _read_json_request(request)

    def get_current_user(self):
        return self.api("GET", "/me")

    def get_current_track(self):
        result = self.api("GET", "/me/player/currently-playing")
        if result.get("status_code") == 204:
            return {"ok": True, "data": {}, "message": "Nothing is currently playing."}
        return result

    def get_playback_state(self):
        result = self.api("GET", "/me/player")
        if result.get("status_code") == 204:
            return {"ok": True, "data": {}, "message": "No active Spotify playback state."}
        return result

    def get_devices(self):
        return self.api("GET", "/me/player/devices")

    def transfer_device(self, device_id: str, play=False):
        if not str(device_id or "").strip():
            return _error("invalid_device", "device_id is required.")
        return self.api("PUT", "/me/player", {"device_ids": [str(device_id)], "play": bool(play)})

    def play(self, context_uri=None, uris=None, query=None, device_id=None, preferred_type=None):
        selected_item = {}
        if query:
            preference = str(preferred_type or "auto").strip().lower()
            requested_types = ["playlist", "track"] if preference == "playlist" else ["track", "playlist"]
            search = self.search(str(query), types=requested_types, limit=5)
            if not search.get("ok"):
                return search
            data = search.get("data") or {}
            playlists = ((data.get("playlists") or {}).get("items") or [])
            tracks = ((data.get("tracks") or {}).get("items") or [])
            playlist_item = _first_spotify_item(playlists)
            track_item = _first_spotify_item(tracks)
            if preference == "track" and track_item:
                track_uri = str(track_item.get("uri") or "")
                uris = [track_uri]
                selected_item = _spotify_item_summary(track_item, "track")
            elif playlist_item:
                context_uri = str(playlist_item.get("uri") or "")
                selected_item = _spotify_item_summary(playlist_item, "playlist")
            elif track_item:
                track_uri = str(track_item.get("uri") or "")
                uris = [track_uri]
                selected_item = _spotify_item_summary(track_item, "track")
            elif playlist_item:
                context_uri = str(playlist_item.get("uri") or "")
                selected_item = _spotify_item_summary(playlist_item, "playlist")
            else:
                return _error("not_found", f"No Spotify result found for '{query}'.")
        body = {}
        if context_uri:
            body["context_uri"] = str(context_uri)
        if uris:
            body["uris"] = [str(item) for item in list(uris or []) if str(item or "").strip()]
        path = "/me/player/play"
        query_params = {"device_id": device_id} if device_id else None
        result = self.api("PUT", path, body, query_params)
        if isinstance(result, dict):
            if query:
                result["query"] = str(query)
            if preferred_type:
                result["preferred_type"] = str(preferred_type)
            if selected_item:
                result["selected_item"] = dict(selected_item)
        return result

    def pause(self, device_id=None):
        return self.api("PUT", "/me/player/pause", {}, {"device_id": device_id} if device_id else None)

    def next(self, device_id=None):
        return self.api("POST", "/me/player/next", {}, {"device_id": device_id} if device_id else None)

    def previous(self, device_id=None):
        return self.api("POST", "/me/player/previous", {}, {"device_id": device_id} if device_id else None)

    def set_volume(self, percent, device_id=None):
        try:
            value = max(0, min(100, int(percent)))
        except Exception:
            return _error("invalid_volume", "Volume percent must be a number from 0 to 100.")
        query = {"volume_percent": value}
        if device_id:
            query["device_id"] = device_id
        return self.api("PUT", "/me/player/volume", {}, query)

    def shuffle(self, enabled, device_id=None):
        query = {"state": "true" if bool(enabled) else "false"}
        if device_id:
            query["device_id"] = device_id
        return self.api("PUT", "/me/player/shuffle", {}, query)

    def repeat(self, mode, device_id=None):
        value = str(mode or "off").strip().lower()
        if value not in {"track", "context", "off"}:
            return _error("invalid_repeat", "Repeat mode must be track, context, or off.")
        query = {"state": value}
        if device_id:
            query["device_id"] = device_id
        return self.api("PUT", "/me/player/repeat", {}, query)

    def search(self, query, types=None, limit=10):
        text = str(query or "").strip()
        if not text:
            return _error("invalid_query", "Search query is required.")
        requested_types = list(types or ["track", "album", "artist", "playlist"])
        safe_types = [item for item in requested_types if item in {"track", "album", "artist", "playlist"}]
        return self.api("GET", "/search", query={"q": text, "type": ",".join(safe_types or ["track"]), "limit": max(1, min(50, int(limit or 10)))})

    def add_to_queue(self, uri, device_id=None):
        if not str(uri or "").strip():
            return _error("invalid_uri", "Spotify URI is required.")
        query = {"uri": str(uri)}
        if device_id:
            query["device_id"] = device_id
        return self.api("POST", "/me/player/queue", {}, query)

    def spotify_get_current_track(self):
        return self.get_current_track()

    def spotify_get_playback_state(self):
        return self.get_playback_state()

    def spotify_get_devices(self):
        return self.get_devices()

    def spotify_transfer_device(self, device_id, play=False):
        return self.transfer_device(device_id, play=play)

    def spotify_play(self, context_uri=None, uris=None, query=None, device_id=None, preferred_type=None):
        return self.play(context_uri=context_uri, uris=uris, query=query, device_id=device_id, preferred_type=preferred_type)

    def spotify_pause(self, device_id=None):
        return self.pause(device_id=device_id)

    def spotify_next(self, device_id=None):
        return self.next(device_id=device_id)

    def spotify_previous(self, device_id=None):
        return self.previous(device_id=device_id)

    def spotify_set_volume(self, percent, device_id=None):
        return self.set_volume(percent, device_id=device_id)

    def spotify_shuffle(self, enabled, device_id=None):
        return self.shuffle(enabled, device_id=device_id)

    def spotify_repeat(self, mode, device_id=None):
        return self.repeat(mode, device_id=device_id)

    def spotify_search(self, query, types=None, limit=10):
        return self.search(query, types=types, limit=limit)

    def spotify_add_to_queue(self, uri, device_id=None):
        return self.add_to_queue(uri, device_id=device_id)


def _first_spotify_item(items) -> dict[str, Any]:
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "").strip()
        if uri:
            return dict(item)
    return {}


def _spotify_item_summary(item: dict[str, Any], item_type: str) -> dict[str, Any]:
    payload = dict(item or {})
    artists = []
    for artist in list(payload.get("artists") or []):
        if isinstance(artist, dict):
            name = str(artist.get("name") or "").strip()
            if name:
                artists.append(name)
    album = payload.get("album") if isinstance(payload.get("album"), dict) else {}
    owner = payload.get("owner") if isinstance(payload.get("owner"), dict) else {}
    return {
        "type": str(item_type or "").strip(),
        "id": str(payload.get("id") or ""),
        "name": str(payload.get("name") or ""),
        "uri": str(payload.get("uri") or ""),
        "artists": artists,
        "album": str(album.get("name") or ""),
        "owner": str(owner.get("display_name") or owner.get("id") or ""),
    }


def _read_json_request(request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            status = int(getattr(response, "status", 200) or 200)
            raw = response.read()
            text = raw.decode("utf-8", errors="replace").strip() if raw else ""
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = {"raw_text": text[:1000]} if text else {}
            return {"ok": 200 <= status < 300, "status_code": status, "data": data}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            data = {"error": raw.decode("utf-8", errors="replace") if raw else str(exc)}
        message = _spotify_error_message(data, exc.code)
        return {"ok": False, "status_code": int(exc.code), "error": message, "data": data}
    except Exception as exc:
        return _error("network_error", str(exc))


def _spotify_error_message(data: dict[str, Any], status_code: int) -> str:
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("reason") or error)
    else:
        message = str(error or data or "Spotify request failed.")
    if status_code == 403:
        message = f"{message} This action may require Spotify Premium or additional scopes."
    if status_code == 404:
        message = f"{message} No active Spotify device may be available."
    return message


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error_code": str(code), "error": str(message)}
