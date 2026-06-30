from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "PySide6" not in sys.modules:
    pyside = types.ModuleType("PySide6")
    pyside.QtCore = types.SimpleNamespace(Qt=types.SimpleNamespace())
    pyside.QtGui = types.SimpleNamespace()
    pyside.QtWidgets = types.SimpleNamespace(QApplication=types.SimpleNamespace(focusWidget=lambda: None))
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = pyside.QtCore
    sys.modules["PySide6.QtGui"] = pyside.QtGui
    sys.modules["PySide6.QtWidgets"] = pyside.QtWidgets

from ui.runtime.real_ui_sync_frontend import RealUiSyncFrontendMixin


class _Backend:
    def __init__(self):
        self.calls = []

    def _invoke_all_addon_capabilities(self, capability, payload):
        self.calls.append((capability, dict(payload or {})))
        assert capability == "real_ui.sync_widget_names"
        kind = str((payload or {}).get("kind") or "")
        return [{kind: [f"addon_{kind}_widget"]}]


class _Bridge(RealUiSyncFrontendMixin):
    def __init__(self):
        self.backend = _Backend()


def test_addon_sync_widget_names_are_cached():
    bridge = _Bridge()

    assert bridge._addon_sync_widget_names("combo") == {"addon_combo_widget"}
    assert bridge._addon_sync_widget_names("combo") == {"addon_combo_widget"}
    assert bridge._addon_sync_widget_names("checkbox") == {"addon_checkbox_widget"}
    assert bridge._addon_sync_widget_names("checkbox") == {"addon_checkbox_widget"}

    assert bridge.backend.calls == [
        ("real_ui.sync_widget_names", {"bridge": bridge, "kind": "combo"}),
        ("real_ui.sync_widget_names", {"bridge": bridge, "kind": "checkbox"}),
    ]


def test_mprc_declines_real_ui_capabilities_without_state_lock():
    source = (ROOT / "addons" / "multi_persona_roleplay" / "controller.py").read_text(encoding="utf-8")
    marker = 'if name.startswith("real_ui."):\n            return None'
    assert marker in source


def test_mprc_session_export_is_non_blocking():
    source = (ROOT / "addons" / "multi_persona_roleplay" / "controller.py").read_text(encoding="utf-8")
    assert "_last_session_export_state" in source
    assert "_state_lock.acquire(blocking=False)" in source


if __name__ == "__main__":
    test_addon_sync_widget_names_are_cached()
    test_mprc_declines_real_ui_capabilities_without_state_lock()
    test_mprc_session_export_is_non_blocking()
    print("smoke_real_ui_addon_sync_cache: ok")
