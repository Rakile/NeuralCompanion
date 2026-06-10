from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.spotify_sense.intent_router import infer_music_mood, route_music_intent
from addons.spotify_sense.settings import SpotifySenseSettings
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

    print("Spotify Sense smoke checks passed.")


if __name__ == "__main__":
    main()
