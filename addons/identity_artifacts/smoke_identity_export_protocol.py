from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.identity_artifacts import controller
from PySide6 import QtWidgets


def test_protocol_loader() -> None:
    protocol = controller._read_identity_export_protocol()
    assert '"format": "NC_IDENTITY_EXPORT"' in protocol
    assert '"format_version": "1.1"' in protocol

    with tempfile.TemporaryDirectory(prefix="nc_identity_protocol_") as temp_dir:
        empty_path = Path(temp_dir) / "empty.txt"
        empty_path.write_text("", encoding="utf-8")
        try:
            controller._read_identity_export_protocol(empty_path)
        except ValueError:
            pass
        else:
            raise AssertionError("Empty protocol resources must be rejected")


class _Context:
    def __init__(self, app_root: Path) -> None:
        self.app_root = app_root
        self.storage = SimpleNamespace(addon_dir=app_root / "legacy")

    def get_service(self, _name: str):
        return None


def test_protocol_panel_and_clipboard() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    protocol = controller._read_identity_export_protocol()
    with tempfile.TemporaryDirectory(prefix="nc_identity_protocol_ui_") as temp_dir:
        parent = QtWidgets.QWidget()
        instance = controller.IdentityArtifactsController(_Context(Path(temp_dir)))
        instance.root_widget = parent

        panel = instance._build_export_protocol_panel(parent)
        labels = [item.text() for item in panel.findChildren(QtWidgets.QLabel)]
        buttons = {
            item.text(): item for item in panel.findChildren(QtWidgets.QPushButton)
        }
        assert any("external LLM" in text for text in labels)
        assert "View Export Protocol" in buttons
        assert "Copy Export Protocol" in buttons

        instance._copy_export_protocol()
        assert app.clipboard().text() == protocol
        assert "copied" in instance.export_protocol_status_label.text().lower()

        dialog = instance._build_export_protocol_dialog(protocol)
        assert dialog.windowTitle() == "ReflectAndExportIdentity v1.1 Protocol"
        viewer = dialog.findChild(QtWidgets.QPlainTextEdit)
        assert viewer is not None
        assert viewer.toPlainText() == protocol
        dialog.deleteLater()
        parent.deleteLater()


if __name__ == "__main__":
    test_protocol_loader()
    test_protocol_panel_and_clipboard()
    print("Identity export protocol smoke passed.")
