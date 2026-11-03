from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from pythonosc import udp_client

from core import avatar_runtime

from . import body_animation
from .speech_bridge import SpeechBridge


class VSeeFaceAdapter(avatar_runtime.AvatarAdapter):
    """VSeeFace/VMC adapter implementation.

    The host injects mutable pose state so this addon owns the VSeeFace-specific
    behavior while legacy UI pose editing can continue to work during migration.
    """

    avatar_provider_id = "vseeface"

    EMOTION_MAP = {
        "neutral": "Neutral",
        "happy": "Fun",
        "angry": "Angry",
        "sad": "Sorrow",
        "surprised": "Surprised",
        "shy": "Joy",
    }
    FINGER_BONES = [
        "IndexProximal",
        "IndexIntermediate",
        "MiddleProximal",
        "MiddleIntermediate",
        "RingProximal",
        "RingIntermediate",
        "LittleProximal",
        "LittleIntermediate",
        "ThumbProximal",
        "ThumbIntermediate",
    ]

    def __init__(
        self,
        ip: str = "127.0.0.1",
        port: int = 39539,
        *,
        avatar_profile: dict | None = None,
        current_body_state: dict | None = None,
        edit_emotion_getter: Callable[[], str] | None = None,
        force_edit_mode_getter: Callable[[], bool] | None = None,
        hand_debug: dict | None = None,
        hand_calibration: dict | None = None,
        speech_bridge: SpeechBridge | None = None,
    ):
        self.client = udp_client.SimpleUDPClient(ip, port)
        self.current_emotion = "neutral"
        self.is_speaking = False
        self.running = False
        self.start_time = time.time()
        self._speech_bridge = speech_bridge

        self.last_anim_time = time.time()
        self.anim_phase = 0.0
        self.last_speaking_update = 0
        self.update_queue = queue.Queue()
        self.thread = threading.Thread(target=self._heartbeat_loop, daemon=True)

        self._avatar_profile = avatar_profile if avatar_profile is not None else {}
        self._current_body_state = current_body_state if current_body_state is not None else {}
        self._edit_emotion_getter = edit_emotion_getter or (lambda: "neutral")
        self._force_edit_mode_getter = force_edit_mode_getter or (lambda: False)
        self._hand_debug = hand_debug if hand_debug is not None else {"active": False}
        self._hand_calibration = hand_calibration if hand_calibration is not None else {
            "relaxed": {"finger_x": 0.0, "finger_y": 0.0, "finger_z": 0.0, "thumb_x": 0.0, "thumb_y": 0.0, "thumb_z": 0.0},
            "fist": {"finger_x": 0.0, "finger_y": 0.0, "finger_z": 0.0, "thumb_x": 0.0, "thumb_y": 0.0, "thumb_z": 0.0},
        }

    def disable_speech_bridge(self):
        # Retain the closed object until teardown: callbacks can safely race disable.
        if self._speech_bridge is not None:
            self._speech_bridge.close()

    def start(self):
        self.running = True
        self.thread.start()
        print(f"🔌 Connected to VSeeFace on port {self.client._port}")

    def stop(self):
        if self._speech_bridge is not None:
            self._speech_bridge.close()
        self.running = False
        if self.thread.is_alive():
            self.thread.join()
        print("🔌 Disconnected from VSeeFace.")

    def set_emotion(self, emotion_name: str):
        self.update_queue.put(("emotion", emotion_name))

    def set_speaking_state(self, is_speaking: bool):
        self.update_queue.put(("speaking", is_speaking))

    def on_audio_prepared(self, prepared):
        if self._speech_bridge is not None:
            self._speech_bridge.prepare(prepared)

    def on_playback_started(self, chunk):
        self.set_speaking_state(True)
        # Admission can precede actual device start. Only on_audio_started starts lip sync.

    def on_audio_started(self, chunk):
        if self._speech_bridge is not None:
            if chunk.audio_clock_sample is not None:
                self._speech_bridge.progress(chunk, chunk.audio_clock_sample)
            else:
                self._speech_bridge.start(chunk)

    def on_audio_progress(self, chunk, sample):
        if self._speech_bridge is not None:
            self._speech_bridge.progress(chunk, sample)

    def on_playback_paused(self, owner):
        self.set_speaking_state(False)
        if self._speech_bridge is not None:
            self._speech_bridge.pause(owner)

    def on_playback_finished(self, receipt):
        self.set_speaking_state(False)
        if self._speech_bridge is not None:
            self._speech_bridge.finish(receipt)

    def process_audio_chunk(self, audio_path: str, text: str, output_filename: str, dry_run_reply_id=None, cancel_check=None):
        # VSeeFace handles lip-sync via system audio loopback.
        return {"ok": True, "kind": "audio"}

    def _euler_to_quaternion(self, roll, pitch, yaw):
        return avatar_runtime.euler_to_quaternion(roll, pitch, yaw)

    def _heartbeat_loop(self):
        while self.running:
            try:
                while not self.update_queue.empty():
                    cmd, val = self.update_queue.get_nowait()
                    if cmd == "emotion":
                        self._update_internal_state(val)
                    elif cmd == "speaking":
                        self.is_speaking = val
                        if val:
                            self.last_speaking_update = time.time()
            except queue.Empty:
                pass

            if self._speech_bridge is not None:
                self._speech_bridge.tick()
            self._send_current_emotion()
            self._animate_body()
            self.client.send_message("/VMC/Ext/Blend/Apply", "")
            time.sleep(0.033)

    def _update_internal_state(self, emotion_name):
        clean_name = str(emotion_name or "").lower().strip()
        if clean_name in self.EMOTION_MAP:
            self.current_emotion = clean_name

    def _send_current_emotion(self):
        # Manual preview must own the face as well as the body pose. Keep the
        # latest chat emotion intact so turning Live Sync back on resumes it.
        selected = self._edit_emotion_getter() if self._force_edit_mode_getter() else self.current_emotion
        target_key = self.EMOTION_MAP.get(str(selected or '').strip().lower(), "Neutral")
        for _tag, key in self.EMOTION_MAP.items():
            value = 1.0 if key == target_key else 0.0
            self.client.send_message("/VMC/Ext/Blend/Val", [key, value])

    def _animate_body(self):
        if not self._avatar_profile or "neutral" not in self._avatar_profile:
            return
        body_animation.animate_vseeface_body(
            self,
            avatar_profile=self._avatar_profile,
            current_body_state=self._current_body_state,
            edit_emotion=self._edit_emotion_getter(),
            force_edit_mode=bool(self._force_edit_mode_getter()),
            hand_debug=self._hand_debug,
            hand_calibration=self._hand_calibration,
            now=time.time(),
        )
