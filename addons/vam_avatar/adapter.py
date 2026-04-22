from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from addons.vseeface_avatar.adapter import VSeeFaceAdapter


class VaMAdapter(VSeeFaceAdapter):
    avatar_provider_id = "vam"

    """Virt-A-Mate avatar bridge adapter.

    VaM-specific file bridge and VMC relay behavior lives here; the host injects
    runtime config and helper functions while the monolith is being sliced.
    """

    def __init__(
        self,
        *,
        runtime_config: dict,
        normalize_vam_root,
        derive_vam_bridge_root,
        default_vam_root: str,
        default_emotion_preset_map: dict,
        default_timeline_clip_map: dict,
        audio_segment_cls,
        avatar_profile: dict,
        current_body_state: dict,
        edit_emotion_getter,
        force_edit_mode_getter,
        hand_debug: dict,
        hand_calibration: dict,
    ):
        vmc_host = str(runtime_config.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
        vmc_port = int(runtime_config.get("vam_vmc_port", 39539) or 39539)
        super().__init__(
            ip=vmc_host,
            port=vmc_port,
            avatar_profile=avatar_profile,
            current_body_state=current_body_state,
            edit_emotion_getter=edit_emotion_getter,
            force_edit_mode_getter=force_edit_mode_getter,
            hand_debug=hand_debug,
            hand_calibration=hand_calibration,
        )
        self._audio_segment_cls = audio_segment_cls
        self.vmc_enabled = bool(runtime_config.get("vam_vmc_enabled", True))
        self.bridge_enabled = bool(runtime_config.get("vam_bridge_enabled", True))
        self.vam_root = normalize_vam_root(
            runtime_config.get(
                "vam_root",
                runtime_config.get("vam_bridge_root", default_vam_root),
            )
        )
        self.bridge_root = derive_vam_bridge_root(self.vam_root)
        self.play_audio_in_vam = bool(runtime_config.get("vam_play_audio_in_vam", False))
        self.target_atom_uid = str(runtime_config.get("vam_target_atom_uid", "Person") or "Person").strip() or "Person"
        self.target_storable_id = str(runtime_config.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge").strip()
        self.timeline_auto_resume = bool(runtime_config.get("vam_timeline_auto_resume", True))
        self.emotion_preset_map = self._coerce_mapping_dict(
            runtime_config.get("vam_emotion_preset_map"),
            default_emotion_preset_map,
        )
        self.timeline_clip_map = self._coerce_mapping_dict(
            runtime_config.get("vam_timeline_clip_map"),
            default_timeline_clip_map,
        )
        self.session_id = uuid.uuid4().hex[:12]
        self._vmc_started = False
        self._bridge_inbox_dir = os.path.join(self.bridge_root, "inbox")
        self._bridge_outbox_dir = os.path.join(self.bridge_root, "outbox")
        self._bridge_audio_dir = os.path.join(self.bridge_root, "audio")

    def _coerce_mapping_dict(self, value, default):
        if isinstance(value, dict):
            return {str(key).strip().lower(): str(item or "").strip() for key, item in value.items() if str(key).strip()}
        return {str(key).strip().lower(): str(item or "").strip() for key, item in dict(default).items()}

    def _ensure_bridge_dirs(self):
        os.makedirs(self._bridge_inbox_dir, exist_ok=True)
        os.makedirs(self._bridge_outbox_dir, exist_ok=True)
        os.makedirs(self._bridge_audio_dir, exist_ok=True)

    def _emotion_key(self, emotion_name):
        clean = str(emotion_name or "").strip().lower()
        return clean or "neutral"

    def _mapped_value(self, mapping, emotion_name, fallback_key="default"):
        clean = self._emotion_key(emotion_name)
        if clean in mapping:
            return str(mapping.get(clean) or "").strip()
        for key, value in mapping.items():
            if key and key in clean:
                return str(value or "").strip()
        return str(mapping.get(fallback_key, "") or "").strip()

    def _build_payload(self, **overrides):
        emotion_name = overrides.get("emotion", self.current_emotion)
        return {
            "target_atom_uid": self.target_atom_uid,
            "target_storable_id": self.target_storable_id,
            "emotion": self._emotion_key(emotion_name),
            "speaking": bool(overrides.get("speaking", self.is_speaking)),
            "timeline_auto_resume": bool(overrides.get("timeline_auto_resume", self.timeline_auto_resume)),
            "expression_preset": overrides.get("expression_preset", self._mapped_value(self.emotion_preset_map, emotion_name)),
            "timeline_clip": overrides.get("timeline_clip", self._mapped_value(self.timeline_clip_map, emotion_name)),
            "audio_path": str(overrides.get("audio_path", "") or ""),
            "audio_duration_seconds": float(overrides.get("audio_duration_seconds", 0.0) or 0.0),
            "text": str(overrides.get("text", "") or ""),
            "play_audio_in_vam": bool(overrides.get("play_audio_in_vam", self.play_audio_in_vam)),
            "enabled": bool(overrides.get("enabled", True)),
        }

    def _send_bridge_command(self, action, payload=None):
        if not self.bridge_enabled:
            return None
        self._ensure_bridge_dirs()
        command_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        final_path = os.path.join(self._bridge_inbox_dir, f"{command_id}_{action}.json")
        tmp_path = f"{final_path}.tmp"
        body = {
            "session_id": self.session_id,
            "command_id": command_id,
            "sent_at": time.time(),
            "action": str(action or "").strip(),
            "payload": payload or {},
        }
        Path(tmp_path).write_text(json.dumps(body, indent=2), encoding="utf-8")
        os.replace(tmp_path, final_path)
        return final_path

    def start(self):
        if not self.vmc_enabled and not self.bridge_enabled:
            raise RuntimeError("VaM mode is enabled, but both VMC relay and file bridge are disabled.")
        if self.vmc_enabled:
            self.running = True
            if not self.thread.is_alive():
                self.thread.start()
            self._vmc_started = True
            print(f"🔌 Connected to VaM VMC relay on {self.client._address}:{self.client._port}")
        else:
            print("🔌 VaM VMC relay disabled; using file bridge only.")
        if self.bridge_enabled:
            self._ensure_bridge_dirs()
            self._send_bridge_command("session_start", self._build_payload(speaking=False, play_audio_in_vam=False))
            print(f"🪄 [VaM] Bridge root: {self.bridge_root}")

    def stop(self):
        if self.bridge_enabled:
            try:
                self._send_bridge_command("session_stop", self._build_payload(speaking=False, play_audio_in_vam=False))
            except Exception as exc:
                print(f"⚠️ [VaM] Could not send session_stop: {exc}")
        if self._vmc_started:
            self.running = False
            if self.thread.is_alive():
                self.thread.join()
            print("🔌 Disconnected from VaM VMC relay.")

    def set_emotion(self, emotion_name: str):
        self.current_emotion = self._emotion_key(emotion_name)
        if self.vmc_enabled:
            super().set_emotion(self.current_emotion)
        if self.bridge_enabled:
            try:
                self._send_bridge_command("set_emotion", self._build_payload(emotion=self.current_emotion, speaking=self.is_speaking, play_audio_in_vam=False))
            except Exception as exc:
                print(f"⚠️ [VaM] Could not send set_emotion: {exc}")

    def set_speaking_state(self, is_speaking: bool):
        self.is_speaking = bool(is_speaking)
        if self.vmc_enabled:
            super().set_speaking_state(self.is_speaking)
        if self.bridge_enabled:
            try:
                self._send_bridge_command("set_speaking", self._build_payload(speaking=self.is_speaking, play_audio_in_vam=False))
            except Exception as exc:
                print(f"⚠️ [VaM] Could not send set_speaking: {exc}")

    def _stage_bridge_audio(self, audio_path, output_filename):
        self._ensure_bridge_dirs()
        chunk_id = os.path.splitext(os.path.basename(output_filename or ""))[0] or f"speech_{uuid.uuid4().hex[:8]}"
        staged_audio_path = os.path.join(self._bridge_audio_dir, f"{chunk_id}.wav")
        shutil.copy2(audio_path, staged_audio_path)
        return staged_audio_path

    def process_audio_chunk(self, audio_path: str, text: str, output_filename: str, dry_run_reply_id=None):
        duration_seconds = 0.0
        try:
            duration_seconds = max(0.0, float(self._audio_segment_cls.from_file(audio_path).duration_seconds or 0.0))
        except Exception:
            duration_seconds = 0.0

        if not self.bridge_enabled:
            return {"ok": True, "kind": "audio"}

        staged_audio_path = ""
        play_audio_in_vam = self.play_audio_in_vam
        if play_audio_in_vam:
            try:
                staged_audio_path = self._stage_bridge_audio(audio_path, output_filename)
            except Exception as exc:
                print(f"⚠️ [VaM] Audio staging failed; falling back to local playback: {exc}")
                play_audio_in_vam = False

        payload = self._build_payload(
            emotion=self.current_emotion,
            speaking=True,
            text=text,
            audio_path=staged_audio_path,
            audio_duration_seconds=duration_seconds,
            play_audio_in_vam=play_audio_in_vam,
        )

        result = {
            "ok": True,
            "kind": "vam",
            "skip_local_playback": play_audio_in_vam,
            "playback_duration_seconds": duration_seconds,
            "payload_path": staged_audio_path or audio_path,
            "bridge_payload": payload,
            "expected_frame_count": max(2, int(round(duration_seconds * 50.0))) if duration_seconds > 0 else 2,
            "chunk_id": os.path.splitext(os.path.basename(staged_audio_path or output_filename or audio_path))[0],
        }
        if play_audio_in_vam:
            print(
                f"🎧 [VaM] Prepared speech chunk for VaM head audio "
                f"({duration_seconds:.2f}s, {os.path.basename(staged_audio_path)})"
            )
        return result

    def begin_chunk_playback(self, chunk_result):
        if not self.bridge_enabled:
            return False
        payload = dict((chunk_result or {}).get("bridge_payload", {}) or {})
        if not payload:
            return False
        try:
            self._send_bridge_command("speech_chunk", payload)
            if bool(payload.get("play_audio_in_vam")):
                print(
                    f"🎧 [VaM] Delegating speech chunk to VaM head audio "
                    f"({float(payload.get('audio_duration_seconds', 0.0) or 0.0):.2f}s, "
                    f"{os.path.basename(str(payload.get('audio_path', '') or ''))})"
                )
            return bool(payload.get("play_audio_in_vam"))
        except Exception as exc:
            print(f"⚠️ [VaM] Could not send speech_chunk: {exc}")
            return False
