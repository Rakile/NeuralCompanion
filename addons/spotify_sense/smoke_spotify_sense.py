from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.spotify_sense.intent_router import infer_music_mood, route_music_intent
from addons.spotify_sense.settings import SpotifySenseSettings
from addons.spotify_sense.controller import SpotifySenseController
from addons.spotify_sense.spotify_client import SpotifySenseClient


class _Storage:
    def __init__(self, root: Path):
        self.root = root

    def resolve(self, relative_path=""):
        return self.root / str(relative_path or "")

    def read_text(self, relative_path, encoding="utf-8"):
        return self.resolve(relative_path).read_text(encoding=encoding)

    def write_text(self, relative_path, content, encoding="utf-8"):
        target = self.resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding=encoding)
        return target

    def read_json(self, relative_path):
        return json.loads(self.read_text(relative_path))

    def write_json(self, relative_path, payload):
        return self.write_text(relative_path, json.dumps(payload, indent=2))


class _Logger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def exception(self, *_args, **_kwargs):
        return None


class _Events:
    def __init__(self):
        self.published = []

    def publish(self, event_name, payload=None):
        self.published.append((event_name, payload or {}))


class _Context:
    def __init__(self, storage):
        self.storage = storage
        self.logger = _Logger()
        self.events = _Events()

    def get_service(self, _name, default=None):
        return default


def main():
    with tempfile.TemporaryDirectory() as temp_dir:
        settings = SpotifySenseSettings(_Storage(Path(temp_dir)))
        assert settings.data["enabled"] is False
        assert settings.data["require_confirmation"] is True
        settings.update(client_id="fake-client-id")
        client = SpotifySenseClient(settings)
        auth = client.build_authorization_url()
        assert auth["ok"] is True
        assert "accounts.spotify.com/authorize" in auth["url"]
        assert "code_challenge_method=S256" in auth["url"]

        disconnected = client.get_current_track()
        assert disconnected["ok"] is False
        assert disconnected["error_code"] == "not_connected"

        routed = route_music_intent("play relaxing focus music")
        assert routed["matched"] is True
        assert routed["tool"] == "spotify.play_search"
        routed = route_music_intent("what song is this?")
        assert routed["tool"] == "spotify.current_track"
        assert infer_music_mood({"name": "dark cyberpunk focus", "artists": ["Example"]}) in {"dark", "focus"}

        controller = SpotifySenseController(_Context(settings.storage))
        assert controller.collect_chat_context({}) is None
        assert controller.capture_sensory_snapshot({}) is None

        controller.settings.update(
            enabled=True,
            music_awareness_enabled=True,
            include_paused_track_context=False,
            music_response_mode="companion",
            access_token="secret-access-token",
            refresh_token="secret-refresh-token",
            client_id="secret-client-id",
            expires_at=int(time.time()) + 3600,
        )
        controller._cache_music_context(
            {
                "id": "track-1",
                "name": "dark cyberpunk focus",
                "artists": ["Example Artist"],
                "album": "Example Album",
                "uri": "spotify:track:track-1",
                "is_playing": True,
                "progress_ms": 82000,
                "duration_ms": 210000,
                "device": "Desktop",
                "context": "spotify:playlist:example",
            }
        )
        context = controller.collect_chat_context({})
        assert context and "Hidden Spotify music awareness" in context["context"]
        assert "dark cyberpunk focus" in context["context"]
        assert "secret-access-token" not in context["context"]
        assert "secret-refresh-token" not in context["context"]
        assert "secret-client-id" not in context["context"]
        sensory = controller.capture_sensory_snapshot({})
        assert sensory and sensory["source"] == "spotify_sense"
        assert sensory["metadata"]["metadata_only"] is True
        blocked = controller.invoke_capability("spotify.next", {})
        assert blocked["ok"] is False
        assert blocked["error_code"] == "llm_control_disabled"
        controller.settings.update(comment_on_song_changes=True, proactive_comment_cooldown_seconds=30)
        controller._handle_track_monitor_change({"id": "track-2", "name": "calm night", "artists": ["Example"]})
        assert controller._pending_track_change_context is not None
        controller._handle_track_monitor_change({"id": "track-3", "name": "calm morning", "artists": ["Example"]})
        assert controller._pending_track_change_context["track"]["track"] == "calm night"
        controller.shutdown()

    print("Spotify Sense smoke checks passed.")


if __name__ == "__main__":
    main()
