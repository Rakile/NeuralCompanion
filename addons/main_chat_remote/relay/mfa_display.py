"""Local-only authenticator QR rendering; no files or external services."""
from __future__ import annotations

import base64


def enrollment_qr(uri: str) -> str:
    if not uri.startswith("otpauth://totp/") or len(uri) > 4096:
        return ""
    try:
        import cv2
        matrix = cv2.QRCodeEncoder_create().encode(uri)
        # Quiet zone and integer scaling retain crisp, scannable modules.
        matrix = cv2.copyMakeBorder(matrix, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
        matrix = cv2.resize(matrix, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
        ok, png = cv2.imencode(".png", matrix)
        if ok:
            return "data:image/png;base64," + base64.b64encode(png.tobytes()).decode("ascii")
    except Exception:
        # The manual setup key remains available on minimal installations.
        pass
    return ""
