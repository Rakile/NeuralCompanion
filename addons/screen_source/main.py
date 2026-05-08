from __future__ import annotations

import json
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
    PROVIDER_ID = "screen"

    def initialize(self, context):
        super().initialize(context)
        self._metadata_payload = _load_metadata(context.manifest.root_dir)
        sensory_service = context.get_service("qt.sensory")
        if sensory_service is not None:
            sensory_service.register_provider(
                provider_id=self.PROVIDER_ID,
                label=str(self._metadata_payload.get("label") or "Screen"),
                instruction=str(self._metadata_payload.get("instruction") or ""),
                description=str(self._metadata_payload.get("description") or ""),
                order=int(self._metadata_payload.get("order", 100) or 100),
                capture_handler=self._capture_sensory_snapshot,
                metadata=dict(self._metadata_payload.get("metadata") or {}),
            )
        context.logger.info("Screen source addon initialized.")

    def shutdown(self):
        sensory_service = self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None
        if sensory_service is not None:
            try:
                sensory_service.unregister_provider(self.PROVIDER_ID)
            except Exception:
                pass
        return None

    def _capture_screen(self, output_path: Path):
        try:
            from PIL import ImageGrab, Image
            image = ImageGrab.grab(all_screens=True)
        except Exception as exc:
            raise RuntimeError(f"Screen capture failed: {exc}") from exc
        image = image.convert("RGB")
        image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="JPEG", quality=85, optimize=True)
        return output_path

    def _capture_sensory_snapshot(self, context=None):
        timestamp = int(time.time() * 1000)
        output_root = Path(str((context or {}).get("output_dir") or (self.context.app_root / "runtime" / "sensory_feedback")))
        output_path = self._capture_screen(output_root / f"screen_{timestamp}.jpg")
        return {
            "captured_at": time.time(),
            "image_path": str(output_path),
            "source": self.PROVIDER_ID,
            "content_text": "Hidden sensory feedback only, not a user request. Source: screen. Use as ambient context only if relevant.",
        }
