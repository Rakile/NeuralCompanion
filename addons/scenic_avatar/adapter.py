from __future__ import annotations

from copy import deepcopy
import threading
import time
from pathlib import Path
from typing import Any

from core.avatar_runtime import AvatarAdapter
from core.avatar_runtime_context import ScenicAdapterInputs

from addons.scenic_avatar import pack_runtime


class ScenicAdapter(AvatarAdapter):
    avatar_provider_id = "scenic"
    supports_progressive_audio = True

    def __init__(self, construction_input: ScenicAdapterInputs):
        if not isinstance(construction_input, ScenicAdapterInputs):
            raise TypeError("ScenicAdapter requires ScenicAdapterInputs.")
        self.runtime_config = construction_input.runtime_config
        self.preview_actions = construction_input.preview_actions
        self.current_pack: pack_runtime.ScenicPack | None = None
        self.current_tag = ""
        self.current_image_path = ""
        self.pending_tag = ""
        self.pending_image_path = ""
        self._preview_lock = threading.RLock()
        self._preview_state: dict[str, Any] = {}

    def start(self):
        self.current_pack = pack_runtime.selected_pack(self.runtime_config)
        self.preview_actions.invalidate_available_emotion_names()
        self._publish_default_image()
        if self.current_pack is None:
            print("[Scenic] No Scenic Pack selected or available.")
        else:
            print(f"[Scenic] Loaded Scenic Pack: {self.current_pack.pack_name}")
        return True

    def stop(self):
        with self._preview_lock:
            self._preview_state = {}
        return None

    def preview_snapshot(self):
        """Return the displayed Scenic image without reading files or other addons."""
        with self._preview_lock:
            return deepcopy(self._preview_state)

    def set_emotion(self, emotion_name: str):
        resolved = self._resolve_image_for_emotion(emotion_name)
        if resolved is None:
            return None
        pack, image = resolved
        requested_tag = pack_runtime.normalize_tag(emotion_name)
        if image.tag != requested_tag and self.current_image_path:
            return None
        self._publish_image(pack, image)
        return None

    def prepare_emotion(self, emotion_name: str):
        resolved = self._resolve_image_for_emotion(emotion_name)
        if resolved is None:
            return None
        pack, image = resolved
        image_path = image.absolute_path(pack.root)
        if not image_path.exists():
            return None
        self.current_pack = pack
        self.pending_tag = image.tag
        self.pending_image_path = str(image_path)
        return {"tag": image.tag, "image_path": str(image_path)}

    def set_speaking_state(self, is_speaking: bool):
        return None

    def process_audio_stream(self, audio_source, text, *, work_lease,
                             emotion_name="neutral", chunk_index=0, cancel_check=None):
        """Still images follow playback receipts and do not gate streaming PCM."""
        return {"ok": True, "kind": "scenic", "progressive_audio": True}

    def process_audio_chunk(
        self,
        audio_path: str,
        text: str,
        output_filename: str,
        dry_run_reply_id=None,
        cancel_check=None,
    ):
        image_path = str(self.pending_image_path or self.current_image_path or "")
        image_tag = str(self.pending_tag or self.current_tag or "")
        if not image_path:
            self._publish_default_image()
            image_path = str(self.current_image_path or "")
            image_tag = str(self.current_tag or "")
        if image_path:
            self.current_image_path = image_path
        if image_tag:
            self.current_tag = image_tag
        self.pending_tag = ""
        self.pending_image_path = ""
        chunk_id = Path(str(output_filename or "")).stem or f"scenic_{int(time.time() * 1000)}"
        duration_seconds = 0.0
        try:
            import soundfile as sf

            duration_seconds = max(0.0, float(sf.info(audio_path).duration or 0.0))
        except Exception:
            duration_seconds = 0.0
        expected_frame_count = max(2, int(round(duration_seconds * 50.0)) if duration_seconds > 0 else 2)
        return {
            "ok": True,
            "kind": "scenic",
            "chunk_id": chunk_id,
            "avatar_id": f"scenic:{getattr(self.current_pack, 'pack_id', '') or 'pack'}",
            "frame_paths": [image_path] if image_path else [],
            "frame_dir": "",
            "fps": 1,
            "playback_duration_seconds": duration_seconds,
            "expected_frame_count": expected_frame_count,
            "scenic_tag": image_tag,
        }

    def _resolve_image_for_emotion(self, emotion_name: str):
        tag = pack_runtime.normalize_tag(emotion_name)
        if not tag:
            return None
        pack = pack_runtime.selected_pack(self.runtime_config)
        if pack is None:
            return None
        image = pack.image_for_tag(tag)
        if image is None:
            return None
        return pack, image

    def _publish_default_image(self):
        pack = self.current_pack or pack_runtime.selected_pack(self.runtime_config)
        if pack is None or not pack.images:
            return
        image = pack.image_for_tag("neutral") or pack.image_for_tag("default") or pack.images[0]
        self._publish_image(pack, image)

    def _publish_image(self, pack: pack_runtime.ScenicPack, image: pack_runtime.ScenicImage):
        image_path = image.absolute_path(pack.root)
        if not image_path.exists():
            return
        shown = self.preview_snapshot()
        if shown.get("scenic_tag") == image.tag and shown.get("frame_paths") == [str(image_path)]:
            return
        self.current_tag = image.tag
        self.current_image_path = str(image_path)
        print(f"[Scenic] Tag '{image.tag}' -> {image_path}")
        self._publish_preview_frame(pack, image, image_path)

    def _publish_preview_frame(self, pack: pack_runtime.ScenicPack, image: pack_runtime.ScenicImage, image_path: Path):
        now = time.time()
        chunk_id = f"scenic:{pack.pack_id}:{image.tag}:{int(now * 1000)}"
        frame_path = str(image_path)
        payload: dict[str, Any] = {
            "provider_id": "scenic",
            "frame_paths": [frame_path],
            "frame_dir": "",
            "fps": 1,
            "sync_time": now,
            "duration_seconds": 0.0,
            "expected_frame_count": 1,
            "trim_start_frames": 0,
            "chunk_id": chunk_id,
            "text": f"Scenic image for [{image.tag}]",
            "status": "ready",
            "loop": False,
            "avatar_id": f"scenic:{pack.pack_id}",
            "preview_chunk_id": chunk_id,
            "preview_frame_index": 0,
            "preview_source_index": 0,
            "scenic_pack_id": pack.pack_id,
            "scenic_tag": image.tag,
        }
        # Avatar Preview requests the selected provider's own state. Keep the
        # static image independent of MuseTalk's stream resets and availability.
        with self._preview_lock:
            self._preview_state = deepcopy(payload)
        try:
            self.preview_actions.set_current_frame_data(payload)
            self.preview_actions.write_preview_frame(
                {
                    "chunk_id": chunk_id,
                    "frame_path": frame_path,
                    "frame_index": 0,
                    "source_index": 0,
                    "fps": 1,
                    "status": "ready",
                    "loop": False,
                    "emitted_at": now,
                    "scenic_pack_id": pack.pack_id,
                    "scenic_tag": image.tag,
                }
            )
        except Exception:
            return
