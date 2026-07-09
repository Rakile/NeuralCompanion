from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import QtWidgets

from addons.spotify_sense.intent_router import infer_music_mood, route_music_intent
from addons.spotify_sense.settings import SpotifySenseSettings
from addons.spotify_sense.controller import SpotifySenseController
from addons.spotify_sense.spotify_client import SpotifySenseClient, _read_json_request
import addons.spotify_sense.spotify_client as spotify_client_module


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


class _FakeSpotifyResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def main():
    with tempfile.TemporaryDirectory() as temp_dir:
        settings = SpotifySenseSettings(_Storage(Path(temp_dir)))
        assert settings.data["enabled"] is False
        assert settings.data["require_confirmation"] is True
        assert settings.data["hidden_response_cooldown_seconds"] == 300
        assert settings.data["user_music_change_cooldown_seconds"] == 120
        assert settings.data["hidden_commentary_style_prompt"]
        assert isinstance(settings.data["hidden_sensory_quick_ids"], list)
        settings.update(story_mode_background_music=True, music_response_mode="companion")
        assert settings.data["music_response_mode"] == "story_soundtrack"
        settings.update(story_mode_background_music=False, music_response_mode="companion")
        assert settings.data["music_response_mode"] == "companion"
        settings.update(client_id="fake-client-id")
        client = SpotifySenseClient(settings)
        auth = client.build_authorization_url()
        assert auth["ok"] is True
        assert "accounts.spotify.com/authorize" in auth["url"]
        assert "code_challenge_method=S256" in auth["url"]

        original_urlopen = spotify_client_module.urllib.request.urlopen
        try:
            spotify_client_module.urllib.request.urlopen = lambda *_args, **_kwargs: _FakeSpotifyResponse(204, b"")
            parsed = _read_json_request(object())
            assert parsed["ok"] is True
            assert parsed["data"] == {}
            spotify_client_module.urllib.request.urlopen = lambda *_args, **_kwargs: _FakeSpotifyResponse(202, b"accepted")
            parsed = _read_json_request(object())
            assert parsed["ok"] is True
            assert parsed["data"]["raw_text"] == "accepted"
        finally:
            spotify_client_module.urllib.request.urlopen = original_urlopen

        disconnected = client.get_current_track()
        assert disconnected["ok"] is False
        assert disconnected["error_code"] == "not_connected"

        client.search = lambda query, types=None, limit=10: {
            "ok": True,
            "data": {
                "playlists": {"items": [None]},
                "tracks": {"items": [None, {"uri": "spotify:track:fallback"}]},
            },
        }
        client.api = lambda method, path, body=None, query=None: {
            "ok": True,
            "method": method,
            "path": path,
            "body": dict(body or {}),
            "query": dict(query or {}),
        }
        play_result = client.play(query="music")
        assert play_result["ok"] is True
        assert play_result["method"] == "PUT"
        assert play_result["path"] == "/me/player/play"
        assert play_result["body"]["uris"] == ["spotify:track:fallback"]
        client.search = lambda query, types=None, limit=10: {
            "ok": True,
            "data": {
                "playlists": {"items": [{"uri": "spotify:playlist:not-the-song", "name": "Master Metal Mix"}]},
                "tracks": {
                    "items": [
                        {
                            "uri": "spotify:track:master-of-puppets",
                            "name": "Master of Puppets",
                            "artists": [{"name": "Metallica"}],
                            "album": {"name": "Master of Puppets"},
                        }
                    ]
                },
            },
        }
        specific_song_result = client.play(query="master of puppets metallica", preferred_type="track")
        assert specific_song_result["ok"] is True
        assert specific_song_result["body"]["uris"] == ["spotify:track:master-of-puppets"]
        assert specific_song_result["selected_item"]["type"] == "track"

        routed = route_music_intent("play relaxing focus music")
        assert routed["matched"] is True
        assert routed["tool"] == "spotify.play_search"
        routed = route_music_intent("play master of puppets with metallica")
        assert routed["matched"] is True
        assert routed["tool"] == "spotify.play_search"
        assert routed["args"]["preferred_type"] == "track"
        assert routed["args"]["query"] == "master of puppets metallica"
        assert routed["args"]["display_query"] == "master of puppets with metallica"
        routed = route_music_intent("play ambient electronic")
        assert routed["matched"] is True
        assert routed["args"]["query"] == "ambient electronic"
        routed = route_music_intent("play ambient electronic and comment about it")
        assert routed["matched"] is True
        assert routed["args"]["query"] == "ambient electronic"
        assert routed["args"]["comment"] is True
        routed = route_music_intent("play Spotify music")
        assert routed["matched"] is True
        assert routed["args"]["query"] == "music"
        routed = route_music_intent("what song is this?")
        assert routed["tool"] == "spotify.current_track"
        routed = route_music_intent("the next song in the playlist and comment about it")
        assert routed["matched"] is True
        assert routed["tool"] == "spotify.next"
        assert routed["args"]["comment"] is True
        assert infer_music_mood({"name": "dark cyberpunk focus", "artists": ["Example"]}) in {"dark", "focus"}

        controller = SpotifySenseController(_Context(settings.storage))
        assert any(record["id"] == "builtin.natural_companion" for record in controller._hidden_sensory_preset_records())
        assert controller.collect_chat_context({}) is None
        assert controller.capture_sensory_snapshot({}) is None
        compact_with_art = controller._compact_track(
            {
                "ok": True,
                "data": {
                    "is_playing": True,
                    "progress_ms": 1,
                    "device": {"name": "Desktop"},
                    "item": {
                        "id": "track-art-1",
                        "name": "Cover Test",
                        "uri": "spotify:track:art",
                        "duration_ms": 1000,
                        "artists": [{"name": "Cover Artist"}],
                        "album": {
                            "name": "Cover Album",
                            "images": [
                                {"url": "https://example.invalid/640.jpg", "width": 640, "height": 640},
                                {"url": "https://example.invalid/64.jpg", "width": 64, "height": 64},
                                {"url": "https://example.invalid/300.jpg", "width": 300, "height": 300},
                            ],
                        },
                    },
                },
            }
        )
        assert compact_with_art["album_art_url"] == "https://example.invalid/64.jpg"
        assert controller._music_context_payload_from_track(compact_with_art)["album_art_url"].endswith("64.jpg")

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
        assert sensory is None
        blocked = controller.invoke_capability("spotify.next", {})
        assert blocked["ok"] is False
        assert blocked["error_code"] == "llm_control_disabled"

        assert controller.invoke_capability("chat.user_text_command", {"text": "tell me a joke"}) is None
        controller.client.pause = lambda device_id=None: {"ok": True}
        handled_direct_pause = controller.invoke_capability("chat.user_text_command", {"text": "pause music"})
        assert handled_direct_pause["handled"] is True
        assert handled_direct_pause["ok"] is True
        assert "Paused Spotify" in handled_direct_pause["response_text"]

        controller.client.next = lambda device_id=None: {"ok": True, "status_code": 204, "data": {}, "device_id": device_id}
        controller.client.get_current_track = lambda: {
            "ok": True,
            "data": {
                "is_playing": True,
                "progress_ms": 64000,
                "device": {"name": "Desktop"},
                "context": {"uri": "spotify:playlist:test"},
                "item": {
                    "id": "track-next-1",
                    "name": "Neon Drift",
                    "uri": "spotify:track:next1",
                    "duration_ms": 180000,
                    "artists": [{"name": "Example Artist"}],
                    "album": {"name": "Example Album"},
                },
            },
        }
        handled_next_comment = controller.invoke_capability(
            "chat.user_text_command",
            {"text": "the next song in the playlist and comment about it"},
        )
        assert handled_next_comment["handled"] is True
        assert handled_next_comment["ok"] is True
        assert handled_next_comment["use_llm_response"] is True
        assert "Neon Drift" in handled_next_comment["response_text"]
        command_context = controller.collect_chat_context({})
        assert command_context and "Fresh Spotify command result" in command_context["context"]
        assert "explicitly asked for a comment" in command_context["context"]
        assert "Neon Drift" in command_context["context"]

        controller.settings.update(comment_on_song_changes=True, proactive_comment_cooldown_seconds=30, hidden_response_cooldown_seconds=30)
        track_two = {"id": "track-2", "name": "calm night", "artists": ["Example"], "is_playing": True}
        controller._cache_music_context(track_two)
        controller._handle_track_monitor_change(track_two)
        assert controller._pending_track_change_context is not None
        sensory = controller.capture_sensory_snapshot({})
        assert sensory and sensory["source"] == "spotify_sense"
        assert sensory["content"] == sensory["content_text"]
        assert "should_speak=true" in sensory["content"]
        assert "proactive_candidate" in sensory["content"]
        assert "Commentary style:" in sensory["content"]
        assert "Suggested comment cue:" not in sensory["content"]
        assert "Song changed:" not in sensory["content"]
        assert "Song changed" not in sensory["metadata"].get("proactive_candidate", "")
        assert sensory["metadata"]["proactive_candidate"] == ""
        assert sensory["metadata"]["comment_angle"]
        assert sensory["metadata"]["comment_brief"]["track"] == "calm night"
        assert sensory["metadata"]["recent_comment_angles"]
        assert sensory["metadata"]["commentary_style_prompt"]
        assert sensory["metadata"]["metadata_only"] is True
        assert sensory["metadata"]["hidden_response_allowed"] is True
        assert controller.capture_sensory_snapshot({}) is None
        controller._last_hidden_response_snapshot_at = 0.0
        controller._pending_track_change_context = {
            "changed_at": time.time(),
            "response_allowed_at": time.time(),
            "track": controller._music_context_payload_from_track(track_two),
            "commentary": controller._commentary_for_track(track_two),
        }
        assert controller.capture_sensory_snapshot({}) is None
        controller._handle_track_monitor_change({"id": "track-3", "name": "calm morning", "artists": ["Example"]})
        assert controller._pending_track_change_context["track"]["track"] == "calm morning"
        assert controller.capture_sensory_snapshot({}) is None
        controller.settings.update(music_awareness_enabled=False)
        controller._last_track_comment_at = 0.0
        controller._last_hidden_response_snapshot_at = 0.0
        controller._handle_track_monitor_change({"id": "track-4", "name": "storm piano", "artists": ["Example"]})
        sensory_without_chat_awareness = controller.capture_sensory_snapshot({})
        assert sensory_without_chat_awareness and sensory_without_chat_awareness["source"] == "spotify_sense"
        assert "storm piano" in sensory_without_chat_awareness["content"]
        assert sensory_without_chat_awareness["metadata"]["hidden_response_allowed"] is True
        assert sensory_without_chat_awareness["metadata"]["comment_angle"] != sensory["metadata"]["comment_angle"]
        assert "Suggested comment cue:" not in sensory_without_chat_awareness["content"]
        assert "Song changed:" not in sensory_without_chat_awareness["content"]
        controller.settings.update(music_awareness_enabled=True)

        controller.settings.update(allow_llm_control=True, user_music_change_cooldown_seconds=120)
        controller._last_user_music_change_at = time.time()
        cooldown = controller.invoke_capability("spotify.pause", {"confirmed": True})
        assert cooldown["ok"] is False
        assert cooldown["error_code"] == "user_music_change_cooldown"
        controller._last_user_music_change_at = 0.0
        handled = controller.invoke_capability("chat.user_text_command", {"text": "pause music"})
        assert handled["handled"] is True
        assert handled["ok"] is True
        assert "Paused Spotify" in handled["response_text"]

        controller.client.play = lambda query=None, device_id=None, **_kwargs: {
            "ok": True,
            "query": query,
            "selected_item": {
                "type": "track",
                "id": "track-ambient-1",
                "name": "Synthetic Horizon",
                "artists": ["Example Artist"],
                "album": "Example Album",
                "uri": "spotify:track:ambient1",
            },
        }
        controller.client.get_current_track = lambda: {
            "ok": True,
            "data": {
                "is_playing": True,
                "progress_ms": 12000,
                "device": {"name": "Desktop"},
                "context": {"uri": "spotify:playlist:ambient"},
                "item": {
                    "id": "track-ambient-1",
                    "name": "Synthetic Horizon",
                    "uri": "spotify:track:ambient1",
                    "duration_ms": 210000,
                    "artists": [{"name": "Example Artist"}],
                    "album": {"name": "Example Album"},
                },
            },
        }
        play_handled = controller.invoke_capability("chat.user_text_command", {"text": "play ambient electronic"})
        assert play_handled["handled"] is True
        assert play_handled["ok"] is True
        assert play_handled["use_llm_response"] is True
        assert "Synthetic Horizon" in play_handled["response_text"]
        command_context = controller.collect_chat_context({})
        assert command_context and "Fresh Spotify command result" in command_context["context"]
        assert "The Spotify playback command has already been executed" in command_context["context"]
        assert "Synthetic Horizon" in command_context["context"]

        volume_calls = []
        controller.settings.update(
            enabled=True,
            duck_while_speaking=True,
            restore_volume_after_speech=True,
            default_device_id="device-2",
            duck_volume_percent=12,
            duck_fade_down_ms=0,
            duck_fade_up_ms=0,
        )
        controller.client.get_playback_state = lambda: {
            "ok": True,
            "data": {"device": {"id": "active-device", "volume_percent": 55}},
        }
        controller.client.set_volume = lambda percent, device_id=None: (
            volume_calls.append((int(percent), device_id)) or {"ok": True, "percent": int(percent), "device_id": device_id}
        )
        ducked = controller.invoke_capability("tts.duck.start", {"source": "smoke"})
        assert ducked["ok"] is True
        assert ducked["ducked"] is True
        assert volume_calls[-1] == (12, "device-2")
        restored = controller.invoke_capability("tts.duck.end", {"source": "smoke"})
        assert restored["ok"] is True
        assert restored["restored"] is True
        assert volume_calls[-1] == (55, "device-2")

        low_volume_calls = []
        controller.settings.update(
            enabled=True,
            duck_while_speaking=True,
            restore_volume_after_speech=True,
            default_device_id="quiet-device",
            default_volume=20,
            duck_volume_percent=30,
            duck_fade_down_ms=0,
            duck_fade_up_ms=0,
        )
        controller.client.get_playback_state = lambda: {
            "ok": True,
            "data": {"device": {"id": "quiet-device", "volume_percent": 10}},
        }
        controller.client.set_volume = lambda percent, device_id=None: (
            low_volume_calls.append((int(percent), device_id)) or {"ok": True, "percent": int(percent), "device_id": device_id}
        )
        low_duck = controller.invoke_capability("tts.duck.start", {"source": "smoke-low-volume"})
        assert low_duck["ok"] is True
        assert low_duck["ducked"] is True
        assert low_volume_calls[-1][0] < 10
        assert low_volume_calls[-1][1] == "quiet-device"
        controller.invoke_capability("tts.duck.end", {"source": "smoke-low-volume"})

        fallback_volume_calls = []
        controller.settings.update(
            enabled=True,
            duck_while_speaking=True,
            restore_volume_after_speech=True,
            default_device_id="fallback-device",
            default_volume=44,
            duck_volume_percent=12,
            duck_fade_down_ms=0,
            duck_fade_up_ms=0,
        )
        controller.client.get_playback_state = lambda: {
            "ok": False,
            "error_code": "no_active_device",
            "error": "No active Spotify device returned playback state.",
        }
        controller.client.set_volume = lambda percent, device_id=None: (
            fallback_volume_calls.append((int(percent), device_id)) or {"ok": True, "percent": int(percent), "device_id": device_id}
        )
        fallback_duck = controller.invoke_capability("tts.duck.start", {"source": "smoke-fallback"})
        assert fallback_duck["ok"] is True
        assert fallback_duck["ducked"] is True
        assert fallback_duck["previous_volume"] == 44
        assert fallback_volume_calls[-1] == (12, "fallback-device")
        fallback_restore = controller.invoke_capability("tts.duck.end", {"source": "smoke-fallback"})
        assert fallback_restore["ok"] is True
        assert fallback_restore["restored"] is True
        assert fallback_volume_calls[-1] == (44, "fallback-device")

        engine_source = (ROOT / "engine.py").read_text(encoding="utf-8")
        duck_start_index = engine_source.index("def _notify_addon_tts_duck_start")
        duck_end_index = engine_source.index("\ndef _notify_addon_tts_duck_end", duck_start_index)
        tts_volume_index = engine_source.index("\ndef _tts_playback_voice_volume", duck_end_index)
        duck_start_source = engine_source[duck_start_index:duck_end_index]
        duck_end_source = engine_source[duck_end_index:tts_volume_index]
        assert "_invoke_all_addon_capabilities" in duck_start_source
        assert "_invoke_all_addon_capabilities" in duck_end_source

        story_play_calls = []
        story_volume_calls = []
        controller.settings.update(
            enabled=True,
            allow_llm_control=True,
            require_confirmation=True,
            story_mode_background_music=True,
            autonomous_music="full",
            default_device_id="story-device",
            story_music_target_volume=34,
            story_music_transition_floor_volume=6,
            story_music_fade_down_ms=0,
            story_music_fade_up_ms=0,
            story_music_prefer_ambient=True,
        )
        controller.client.get_playback_state = lambda: {
            "ok": True,
            "data": {"device": {"id": "story-device", "volume_percent": 61}},
        }
        controller.client.set_volume = lambda percent, device_id=None: (
            story_volume_calls.append((int(percent), device_id)) or {"ok": True, "percent": int(percent), "device_id": device_id}
        )
        controller.client.play = lambda query=None, device_id=None, preferred_type=None, **_kwargs: (
            story_play_calls.append((query, device_id, preferred_type))
            or {
                "ok": True,
                "query": query,
                "device_id": device_id,
                "preferred_type": preferred_type,
                "selected_item": {"type": "playlist", "name": "Archive Atmospheres"},
            }
        )
        story_result = controller.invoke_capability(
            "spotify.story_hook",
            {
                "event": "story_turn",
                "mood": "tense curiosity",
                "scene": "A sealed door waits in a blue archive corridor.",
                "location": "Archive corridor",
                "tension_level": 6,
                "music_kind": "ambient",
                "prefer_ambient": True,
            },
        )
        assert story_result["ok"] is True
        assert story_result["started"] is True
        assert story_result["query"] == "mysterious cinematic ambient story ambience"
        assert story_result["fade"]["from"] == 61
        assert story_result["fade"]["floor"] == 6
        assert story_result["fade"]["target"] == 34
        assert story_play_calls[-1] == ("mysterious cinematic ambient story ambience", "story-device", "playlist")
        assert story_volume_calls[:2] == [(6, "story-device"), (34, "story-device")]

        story_play_calls.clear()
        story_volume_calls.clear()
        controller.settings.update(default_device_id="stale-story-device")
        controller.client.get_playback_state = lambda: {
            "ok": True,
            "data": {"device": {"id": "live-story-device", "volume_percent": 50}},
        }
        live_device_result = controller.invoke_capability(
            "spotify.story_hook",
            {
                "event": "story_turn",
                "mood": "tense curiosity",
                "scene": "The lantern reveals a hidden archive map.",
                "tension_level": 6,
                "music_kind": "ambient",
                "prefer_ambient": True,
            },
        )
        assert live_device_result["ok"] is True
        assert live_device_result["started"] is True
        assert story_play_calls[-1] == ("mysterious cinematic ambient story ambience", "live-story-device", "playlist")
        assert story_volume_calls[:2] == [(6, "live-story-device"), (34, "live-story-device")]

        story_race_play_calls = []
        story_race_volume_calls = []
        controller.settings.update(
            enabled=True,
            allow_llm_control=True,
            require_confirmation=True,
            duck_while_speaking=True,
            restore_volume_after_speech=True,
            duck_volume_percent=11,
            duck_fade_down_ms=0,
            duck_fade_up_ms=0,
            story_mode_background_music=True,
            autonomous_music="full",
            default_device_id="story-device",
            story_music_target_volume=33,
            story_music_transition_floor_volume=7,
            story_music_fade_down_ms=240,
            story_music_fade_up_ms=240,
            story_music_prefer_ambient=True,
        )
        controller.client.get_playback_state = lambda: {
            "ok": True,
            "data": {"device": {"id": "story-device", "volume_percent": 60}},
        }
        controller.client.set_volume = lambda percent, device_id=None: (
            story_race_volume_calls.append((int(percent), device_id)) or {"ok": True, "percent": int(percent), "device_id": device_id}
        )
        controller.client.play = lambda query=None, device_id=None, preferred_type=None, **_kwargs: (
            story_race_play_calls.append((query, device_id, preferred_type))
            or {"ok": True, "query": query, "device_id": device_id, "preferred_type": preferred_type}
        )
        transition = controller.invoke_capability(
            "spotify.story_hook",
            {
                "event": "story_turn",
                "mood": "tense curiosity",
                "scene": "The archive sigil reacts to the lantern.",
                "tension_level": 6,
                "music_kind": "ambient",
                "prefer_ambient": True,
            },
        )
        assert transition["ok"] is True
        assert transition["transitioning"] is True
        ducked_during_story = controller.invoke_capability("tts.duck.start", {"source": "smoke"})
        assert ducked_during_story["ok"] is True
        deadline = time.time() + 1.0
        while time.time() < deadline and not story_race_play_calls:
            time.sleep(0.02)
        assert story_race_play_calls[-1] == ("mysterious cinematic ambient story ambience", "story-device", "playlist")
        assert (33, "story-device") not in story_race_volume_calls
        restored_after_story = controller.invoke_capability("tts.duck.end", {"source": "smoke"})
        assert restored_after_story["ok"] is True
        assert restored_after_story["volume"] == 60
        assert story_race_volume_calls[-1] == (60, "story-device")

        story_overlap_play_calls = []
        story_overlap_volume_calls = []
        controller.settings.update(
            enabled=True,
            allow_llm_control=True,
            require_confirmation=True,
            duck_while_speaking=True,
            restore_volume_after_speech=True,
            duck_volume_percent=12,
            duck_fade_down_ms=0,
            duck_fade_up_ms=0,
            story_mode_background_music=True,
            autonomous_music="full",
            default_device_id="overlap-device",
            story_music_target_volume=45,
            story_music_transition_floor_volume=5,
            story_music_fade_down_ms=0,
            story_music_fade_up_ms=1200,
            story_music_prefer_ambient=True,
        )
        controller.client.get_playback_state = lambda: {
            "ok": True,
            "data": {"device": {"id": "overlap-device", "volume_percent": 70}},
        }
        controller.client.set_volume = lambda percent, device_id=None: (
            story_overlap_volume_calls.append((int(percent), device_id)) or {"ok": True, "percent": int(percent), "device_id": device_id}
        )
        controller.client.play = lambda query=None, device_id=None, preferred_type=None, **_kwargs: (
            story_overlap_play_calls.append((query, device_id, preferred_type))
            or {"ok": True, "query": query, "device_id": device_id, "preferred_type": preferred_type}
        )
        overlap_transition = controller.invoke_capability(
            "spotify.story_hook",
            {
                "event": "story_turn",
                "mood": "tense curiosity",
                "scene": "The hidden door hums as the floor lights wake up.",
                "tension_level": 6,
                "music_kind": "ambient",
                "prefer_ambient": True,
            },
        )
        assert overlap_transition["ok"] is True
        assert overlap_transition["transitioning"] is True
        deadline = time.time() + 1.0
        while time.time() < deadline and len(story_overlap_volume_calls) < 2:
            time.sleep(0.02)
        assert len(story_overlap_volume_calls) >= 2
        overlap_duck = controller.invoke_capability("tts.duck.start", {"source": "smoke-overlap"})
        assert overlap_duck["ok"] is True
        assert story_overlap_volume_calls[-1] == (12, "overlap-device")
        duck_call_count = len(story_overlap_volume_calls)
        time.sleep(0.35)
        assert story_overlap_volume_calls[duck_call_count - 1 :] == [(12, "overlap-device")]
        overlap_restore = controller.invoke_capability("tts.duck.end", {"source": "smoke-overlap"})
        assert overlap_restore["ok"] is True
        assert story_overlap_volume_calls[-1] == (70, "overlap-device")

        controller.settings.update(enabled=False, allow_llm_control=False, user_music_change_cooldown_seconds=120)
        controller._last_user_music_change_at = time.time()
        disabled_direct_play = controller.invoke_capability("chat.user_text_command", {"text": "play ambient electronic"})
        assert disabled_direct_play is None
        blocked_tool = controller.invoke_capability("spotify.pause", {"confirmed": True})
        assert blocked_tool["ok"] is False
        assert blocked_tool["error_code"] == "disabled"
        blocked_direct_tool = controller.invoke_capability("spotify.pause", {"confirmed": True, "direct_user_request": True})
        assert blocked_direct_tool["ok"] is False
        assert blocked_direct_tool["error_code"] == "disabled"
        controller.shutdown()

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        ui_controller = SpotifySenseController(_Context(settings.storage))
        ui_controller.client.get_devices = lambda: {"ok": True, "data": {"devices": []}}
        tab = ui_controller.build_tab()
        button_labels = {
            button.text()
            for button in tab.findChildren(QtWidgets.QPushButton)
        }
        for label in ("Current Track", "Play", "Pause", "Next", "Previous", "Volume 30%"):
            assert label in button_labels
        assert "Play / Pause" not in button_labels
        assert tab.findChild(QtWidgets.QPlainTextEdit, "spotify_sense_hidden_commentary_style") is not None
        assert tab.findChild(QtWidgets.QComboBox, "spotify_sense_hidden_preset_combo") is not None
        quick_boxes = tab.findChildren(QtWidgets.QCheckBox)
        assert any(box.objectName().startswith("spotify_sense_hidden_quick_") for box in quick_boxes)
        ui_controller.shutdown()
        app.processEvents()

    print("Spotify Sense smoke checks passed.")


if __name__ == "__main__":
    main()
