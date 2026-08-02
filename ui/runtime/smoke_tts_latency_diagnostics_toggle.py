import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import QtWidgets

from ui.runtime.backend_workspace_addons import BackendWorkspaceAddonsMixin


class _Manager:
    def __init__(self):
        self.enabled = False
        self.changes = []

    def latency_diagnostics_enabled(self):
        return self.enabled

    def set_latency_diagnostics_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.changes.append(self.enabled)


class _Host(QtWidgets.QWidget, BackendWorkspaceAddonsMixin):
    def __init__(self):
        super().__init__()
        self._addon_manager = _Manager()
        self.save_count = 0

    def save_session(self):
        self.save_count += 1


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    group = host._build_tts_latency_diagnostics_controls()
    checkbox = host.tts_latency_diagnostics_enabled_checkbox

    assert group.title() == "Developer diagnostics"
    assert checkbox.text() == "Record TTS/addon latency diagnostics"
    assert checkbox.isChecked() is False

    checkbox.setChecked(True)
    assert host._addon_manager.enabled is True
    assert host._addon_manager.changes == [True]
    assert host.save_count == 1

    host._addon_manager.enabled = False
    host._refresh_tts_latency_diagnostics_controls()
    assert checkbox.isChecked() is False
    assert host._addon_manager.changes == [True]
    assert host.save_count == 1

    host.close()
    app.processEvents()
    print("TTS latency diagnostics UI toggle smoke passed.")


if __name__ == "__main__":
    main()
