from __future__ import annotations

import json
import os
import time
from pathlib import Path

from core.addons.base import BaseAddon


def _load_metadata(root_dir: Path) -> dict:
    path = root_dir / "sensory_metadata.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


class Addon(BaseAddon):
    PROVIDER_ID = "webcam"

    def initialize(self, context):
        super().initialize(context)
        self._metadata_payload = _load_metadata(context.manifest.root_dir)
        sensory_service = context.get_service("qt.sensory")
        if sensory_service is not None:
            sensory_service.register_provider(
                provider_id=self.PROVIDER_ID,
                label=str(self._metadata_payload.get("label") or "Webcam"),
                instruction=str(self._metadata_payload.get("instruction") or ""),
                description=str(self._metadata_payload.get("description") or ""),
                order=int(self._metadata_payload.get("order", 110) or 110),
                capture_handler=self._capture_sensory_snapshot,
                metadata=dict(self._metadata_payload.get("metadata") or {}),
            )
        context.logger.info("Webcam source addon initialized.")

    def shutdown(self):
        sensory_service = self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None
        if sensory_service is not None:
            try:
                sensory_service.unregister_provider(self.PROVIDER_ID)
            except Exception:
                pass
        return None

    def _capture_webcam(self, output_path: Path):
        try:
            import cv2
        except Exception as exc:
            raise RuntimeError(f"OpenCV is unavailable for webcam capture: {exc}") from exc
        cap = None
        try:
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW if os.name == "nt" else 0)
            if not cap or not cap.isOpened():
                raise RuntimeError("Webcam could not be opened.")
            ok, frame = cap.read()
            if not ok or frame is None:
                raise RuntimeError("Webcam returned no frame.")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(output_path), frame)
            return output_path
        finally:
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass

    def _capture_sensory_snapshot(self, context=None):
        timestamp = int(time.time() * 1000)
        output_root = Path(str((context or {}).get("output_dir") or (self.context.app_root / "runtime" / "sensory_feedback")))
        output_path = self._capture_webcam(output_root / f"webcam_{timestamp}.jpg")
        return {
            "captured_at": time.time(),
            "image_path": str(output_path),
            "source": self.PROVIDER_ID,
            "content_text": "Hidden sensory feedback only, not a user request. Source: webcam. Use as ambient context only if relevant.",
        }
