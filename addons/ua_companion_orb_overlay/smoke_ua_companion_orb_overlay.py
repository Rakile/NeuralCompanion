from __future__ import annotations

import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from addons.ua_companion_orb_overlay import named_pipe_transport, stream_runtime

    width = 1024
    height = 1024
    gray = bytes((index % 251 for index in range(width * height)))
    message = named_pipe_transport.pack_frame_message(
        gray,
        width=width,
        height=height,
        frame_index=7,
        timestamp_seconds=123.5,
    )
    header = message[: named_pipe_transport.FRAME_HEADER_SIZE]
    fields = struct.unpack(named_pipe_transport.FRAME_HEADER_FORMAT, header)
    assert fields[0] == named_pipe_transport.FRAME_MAGIC
    assert fields[1] == named_pipe_transport.FRAME_VERSION
    assert fields[2] == named_pipe_transport.FRAME_HEADER_SIZE
    assert fields[3] == width
    assert fields[4] == height
    assert fields[5] == width
    assert fields[6] == 7
    assert abs(fields[7] - 123.5) < 0.001
    assert fields[8] == width * height
    assert message[named_pipe_transport.FRAME_HEADER_SIZE :] == gray

    bgra = bytes((index % 251 for index in range(width * height * 4)))
    color_message = named_pipe_transport.pack_frame_message(
        bgra,
        width=width,
        height=height,
        frame_index=8,
        timestamp_seconds=124.5,
        pixel_format=named_pipe_transport.PIXEL_FORMAT_BGRA8,
    )
    color_fields = struct.unpack(
        named_pipe_transport.FRAME_HEADER_FORMAT,
        color_message[: named_pipe_transport.FRAME_HEADER_SIZE],
    )
    assert color_fields[5] == width * 4
    assert color_fields[8] == width * height * 4
    assert color_fields[9] == named_pipe_transport.PIXEL_FORMAT_BGRA8

    assert stream_runtime.is_enabled({}) is False
    assert stream_runtime.is_enabled({"ua_companion_orb_send_musetalk_face_mask": True}) is True
    assert stream_runtime.should_suppress_musetalk_preview({"ua_companion_orb_send_musetalk_face_mask": True}) is True

    captured = []

    class FakeWriter:
        def send_gray_frame(self, pixels, *, width, height, frame_index=0, timestamp_seconds=None):
            captured.append((bytes(pixels), width, height, frame_index, timestamp_seconds))
            return True

        def send_bgra_frame(self, pixels, *, width, height, frame_index=0, timestamp_seconds=None):
            captured.append((bytes(pixels), width, height, frame_index, timestamp_seconds, "bgra"))
            return True

    assert stream_runtime.publish_gray_frame(
        gray,
        width=width,
        height=height,
        frame_index=3,
        runtime_config={"ua_companion_orb_send_musetalk_face_mask": True},
        writer=FakeWriter(),
    )
    assert captured and captured[0][1:4] == (width, height, 3)
    assert not stream_runtime.publish_gray_frame(
        gray,
        width=width,
        height=height,
        runtime_config={"ua_companion_orb_send_musetalk_face_mask": False},
        writer=FakeWriter(),
    )

    frame_path = ROOT / "addons" / "ua_companion_orb_overlay" / "smoke_color_frame.png"
    try:
        from PySide6 import QtGui

        image = QtGui.QImage(2, 2, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor(12, 34, 56))
        image.save(str(frame_path))
        before_count = len(captured)
        assert stream_runtime.publish_frame_path(
            frame_path,
            frame_index=4,
            runtime_config={"ua_companion_orb_send_musetalk_face_mask": True, "ua_companion_orb_mask_size": 64},
            writer=FakeWriter(),
        )
        assert len(captured) == before_count + 1
        assert captured[-1][-1] == "bgra"

        portrait_path = ROOT / "addons" / "ua_companion_orb_overlay" / "smoke_portrait_frame.png"
        portrait = QtGui.QImage(120, 240, QtGui.QImage.Format_RGB32)
        portrait.fill(QtGui.QColor(90, 20, 160))
        portrait.save(str(portrait_path))
        before_count = len(captured)
        assert stream_runtime.publish_frame_path(
            portrait_path,
            frame_index=5,
            runtime_config={"ua_companion_orb_send_musetalk_face_mask": True, "ua_companion_orb_mask_size": 128},
            writer=FakeWriter(),
        )
        assert len(captured) == before_count + 1
        assert captured[-1][1:3] == (64, 128)
        assert captured[-1][-1] == "bgra"
    finally:
        try:
            frame_path.unlink()
        except OSError:
            pass
        try:
            portrait_path.unlink()
        except Exception:
            pass

    addon_root = ROOT / "addons"
    musetalk_addon_json = (addon_root / "musetalk_avatar" / "addon.json").read_text(encoding="utf-8")
    musetalk_preview_runtime = (addon_root / "musetalk_avatar" / "preview_runtime.py").read_text(encoding="utf-8")
    musetalk_preview_panel = (addon_root / "musetalk_avatar" / "preview_panel.py").read_text(encoding="utf-8")
    musetalk_real_ui = (addon_root / "musetalk_avatar" / "real_ui_bridge.py").read_text(encoding="utf-8")
    musetalk_host_service = (addon_root / "musetalk_avatar" / "host_service.py").read_text(encoding="utf-8")
    assert "ua_companion_orb_send_musetalk_face_mask" in musetalk_addon_json
    assert "addons.ua_companion_orb_overlay" in musetalk_preview_runtime
    assert "publish_frame_path" in musetalk_preview_runtime
    assert "should_suppress_musetalk_preview" in musetalk_preview_panel
    assert "Send MuseTalk face mask to Ua Companion Orb" in musetalk_real_ui
    assert "ua_companion_orb_send_musetalk_face_mask_checkbox" in musetalk_real_ui
    assert "ua_companion_orb_send_musetalk_face_mask" in musetalk_host_service
    print("[ua_companion_orb_overlay] smoke checks passed.")


if __name__ == "__main__":
    main()
