from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import QtWidgets

from ui.runtime.backend_addon_tab_mounts import BackendAddonTabMountMixin


class _Contribution:
    addon_id = "nc.smoke"
    area = "top_level"
    metadata = {}

    def __init__(self, tab_id: str, title: str) -> None:
        self.id = tab_id
        self.title = title
        self.tooltip = f"{title} tooltip"


class _Harness(BackendAddonTabMountMixin):
    def _set_addon_tab_icon(self, _tab_widget, _tab_index, _contribution) -> None:
        return None


def _app() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _tab_titles(tabs: QtWidgets.QTabWidget) -> list[str]:
    return [str(tabs.tabText(index) or "") for index in range(tabs.count())]


def test_addon_tab_context_menu_hides_and_unhides_tab_buttons() -> None:
    _app()
    harness = _Harness()
    tabs = QtWidgets.QTabWidget()
    tabs.setObjectName("left_tabs")
    tabs.addTab(QtWidgets.QWidget(), "Core")

    first = QtWidgets.QWidget()
    second = QtWidgets.QWidget()
    harness._install_addon_tab(tabs, _Contribution("first_addon_tab", "First"), first)
    harness._install_addon_tab(tabs, _Contribution("second_addon_tab", "Second"), second)

    assert bool(tabs.tabBar().property("_nc_addon_tab_context_menu_installed"))
    assert _tab_titles(tabs) == ["Core", "First", "Second"]
    assert harness._addon_tab_context_menu_action_labels(tabs, 1) == ["Hide tab button"]

    assert harness._hide_addon_tab_button_at(tabs, 1) is True

    assert tabs.isTabVisible(1) is False
    assert tabs.isTabVisible(2) is True
    assert harness._addon_tab_context_menu_action_labels(tabs, 2) == [
        "Hide tab button",
        "Unhide hidden tab buttons",
    ]

    assert harness._restore_hidden_addon_tab_buttons(tabs) == 1

    assert tabs.isTabVisible(1) is True
    assert tabs.isTabVisible(2) is True
    assert harness._addon_tab_context_menu_action_labels(tabs, 2) == ["Hide tab button"]


if __name__ == "__main__":
    test_addon_tab_context_menu_hides_and_unhides_tab_buttons()
    print("smoke_addon_tab_context_menu: ok")
