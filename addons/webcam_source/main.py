from __future__ import annotations

import json
import os
import time
from pathlib import Path

from core.addons.base import BaseAddon


DEVICE_KEY = "webcam_source_device_id"


def _load_metadata(root_dir: Path) -> dict:
    path = root_dir / "sensory_metadata.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def discover_camera_devices(*, cv2_module=None, max_devices: int = 8, logger=print) -> list[dict]:
    """Probe camera indices and release every handle before returning.

    OpenCV does not expose stable friendly camera names on every platform, so
    the persisted identifier is the backend camera index. Tests can inject a
    small cv2-compatible fake and never require physical hardware.
    """

    if cv2_module is None:
        try:
            import cv2 as cv2_module
        except Exception as exc:
            raise RuntimeError(f"OpenCV is unavailable for camera discovery: {exc}") from exc
    backend = getattr(cv2_module, "CAP_DSHOW", 0) if os.name == "nt" else 0
    limit = max(1, int(max_devices))
    logger(f"[Webcam discovery] Scanning camera indices 0-{limit - 1}. "
           "OpenCV warnings during this scan can refer to empty or unavailable slots, "
           "not necessarily the selected camera.")
    devices: list[dict] = []
    for index in range(limit):
        capture = None
        try:
            logger(f"[Webcam discovery] Probing index {index} (Camera {index + 1})...")
            capture = cv2_module.VideoCapture(index, backend)
            if capture is not None and bool(capture.isOpened()):
                devices.append(
                    {
                        "id": str(index),
                        "label": f"Camera {index + 1}",
                        "index": index,
                    }
                )
                logger(f"[Webcam discovery] Camera {index + 1}, index {index}: available.")
            else:
                logger(f"[Webcam discovery] Camera {index + 1}, index {index}: not opened "
                       "(no device at this slot, or the device is unavailable).")
        except Exception as exc:
            logger(f"[Webcam discovery] Camera {index + 1}, index {index}: "
                   f"probe failed: {type(exc).__name__}: {exc}")
        finally:
            try:
                if capture is not None:
                    capture.release()
            except Exception:
                pass
    found = ", ".join(f"{device['label']} (index {device['index']})" for device in devices) or "none"
    logger(f"[Webcam discovery] Finished: {len(devices)} camera(s) available: {found}.")
    return devices


class Addon(BaseAddon):
    PROVIDER_ID = "webcam"

    def initialize(self, context):
        super().initialize(context)
        self._metadata_payload = _load_metadata(context.manifest.root_dir)
        self._runtime_config = context.capabilities.runtime_config
        sensory_service = context.capabilities.sensory_targets
        self._sensory_service = sensory_service
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

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        request = dict(payload or {})
        if name == "runtime.webcam.discover_devices":
            return discover_camera_devices(
                max_devices=int(request.get("max_devices", 8) or 8),
                logger=self.context.logger.info,
            )
        if name == "runtime.webcam.status":
            selected = str(self._runtime_config.get(DEVICE_KEY, "0") or "0").strip()
            return {
                "selected_device_id": selected,
                "status": "configured" if selected else "not_configured",
            }
        return None

    def shutdown(self):
        sensory_service = getattr(self, "_sensory_service", None)
        if sensory_service is not None:
            try:
                sensory_service.unregister_provider(self.PROVIDER_ID)
            except Exception:
                pass
        self._sensory_service = None
        return None

    def _capture_webcam(self, output_path: Path):
        try:
            import cv2
        except Exception as exc:
            raise RuntimeError(f"OpenCV is unavailable for webcam capture: {exc}") from exc
        cap = None
        try:
            configured = str(self._runtime_config.get(DEVICE_KEY, "0") or "0").strip()
            try:
                device_index = int(configured)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"Configured webcam device '{configured}' is invalid. Refresh cameras and choose an available device."
                ) from exc
            cap = cv2.VideoCapture(
                device_index,
                cv2.CAP_DSHOW if os.name == "nt" else 0,
            )
            if not cap or not cap.isOpened():
                raise RuntimeError(
                    f"Configured Camera {device_index + 1} could not be opened. Refresh cameras and choose an available device."
                )
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
