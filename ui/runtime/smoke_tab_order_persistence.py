from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import QtWidgets

from ui.runtime.main_window_session import MainWindowSessionMixin


class _Harness(MainWindowSessionMixin):
    def __init__(self) -> None:
        self._persisted_tab_orders = {}
        self._suspend_tab_order_save = False
        self.saved = 0

    def save_session(self) -> None:
        self.saved += 1


def _app() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _make_tabs(object_name: str, names: list[str]) -> QtWidgets.QTabWidget:
    tabs = QtWidgets.QTabWidget()
    tabs.setObjectName(object_name)
    for name in names:
        widget = QtWidgets.QWidget()
        widget.setObjectName(f"{name}_page")
        tabs.addTab(widget, name.title())
    return tabs


def _tab_object_names(tabs: QtWidgets.QTabWidget) -> list[str]:
    return [tabs.widget(index).objectName() for index in range(tabs.count())]


def _move_by_object_name(tabs: QtWidgets.QTabWidget, object_name: str, target_index: int) -> None:
    for index in range(tabs.count()):
        if str(tabs.widget(index).objectName() or "") == object_name:
            tabs.tabBar().moveTab(index, target_index)
            return
    raise AssertionError(f"missing tab {object_name!r}")


def test_tab_order_session_uses_readable_aliases_and_restores_order() -> None:
    _app()
    harness = _Harness()
    addons = _make_tabs("left_tabs", ["chat", "discord", "identity"])
    host = _make_tabs("host_settings_tabs", ["host", "vision", "chat"])

    addons.tabBar().setTabData(1, "Discord Voice Bridge")
    addons.setTabText(1, "")

    session = {}
    harness.left_tabs = addons
    harness.host_settings_tabs = host
    harness._save_persisted_tab_orders(session)

    assert session["ui"]["layout"]["tab_order"]["addons"] == [
        "widget:chat_page",
        "widget:discord_page",
        "widget:identity_page",
    ]
    assert session["ui"]["layout"]["tab_order"]["host"] == [
        "label:Host",
        "label:Vision",
        "label:Chat",
    ]

    fresh_addons = _make_tabs("left_tabs", ["identity", "chat", "new", "discord"])
    harness.left_tabs = fresh_addons
    harness._restore_persisted_tab_orders(session)
    harness._apply_persisted_tab_orders()

    assert _tab_object_names(fresh_addons) == [
        "chat_page",
        "discord_page",
        "identity_page",
        "new_page",
    ]


def test_tab_order_reapplies_before_post_restore_save() -> None:
    _app()
    harness = _Harness()
    host = _make_tabs("host_settings_tabs", ["host", "vision", "chat"])
    _move_by_object_name(host, "chat_page", 0)
    harness.host_settings_tabs = host
    session = {}
    harness._save_persisted_tab_orders(session)

    fresh_host = _make_tabs("host_settings_tabs", ["host", "vision", "chat"])
    harness.host_settings_tabs = fresh_host
    harness._restore_persisted_tab_orders(session)

    save_payload = {}
    harness._save_persisted_tab_orders(save_payload)
    assert save_payload["ui"]["layout"]["tab_order"]["host"] == [
        "label:Host",
        "label:Vision",
        "label:Chat",
    ]

    harness._apply_persisted_tab_orders()
    save_payload = {}
    harness._save_persisted_tab_orders(save_payload)

    assert save_payload["ui"]["layout"]["tab_order"]["host"] == [
        "label:Chat",
        "label:Host",
        "label:Vision",
    ]


def test_tab_move_triggers_session_save_after_install() -> None:
    _app()
    harness = _Harness()
    tabs = _make_tabs("left_tabs", ["first", "second"])
    harness._install_persisted_tab_order("left_tabs", tabs)

    tabs.tabBar().moveTab(0, 1)

    assert harness.saved == 1


def test_hidden_addon_tabs_session_uses_readable_alias_and_restores_visibility() -> None:
    _app()
    harness = _Harness()
    addons = _make_tabs("left_tabs", ["chat", "discord", "identity"])
    addons.widget(1).setProperty("addon_id", "nc.discord_voice_bridge")
    addons.widget(1).setProperty("addon_tab_id", "discord_voice_bridge_tab")
    addons.setTabVisible(1, False)
    harness.left_tabs = addons

    session = {}
    harness._save_persisted_hidden_tabs(session)

    assert session["ui"]["layout"]["hidden_tabs"]["addons"] == [
        "addon:nc.discord_voice_bridge:discord_voice_bridge_tab",
    ]

    fresh_addons = _make_tabs("left_tabs", ["chat", "discord", "identity"])
    fresh_addons.widget(1).setProperty("addon_id", "nc.discord_voice_bridge")
    fresh_addons.widget(1).setProperty("addon_tab_id", "discord_voice_bridge_tab")
    harness.left_tabs = fresh_addons
    harness._restore_persisted_hidden_tabs(session)
    harness._apply_persisted_hidden_tabs()

    assert fresh_addons.isTabVisible(0)
    assert not fresh_addons.isTabVisible(1)
    assert fresh_addons.isTabVisible(2)


def test_unhide_clears_hidden_addon_tab_session_state() -> None:
    _app()
    harness = _Harness()
    addons = _make_tabs("left_tabs", ["chat", "discord"])
    addons.widget(1).setProperty("addon_id", "nc.discord_voice_bridge")
    addons.widget(1).setProperty("addon_tab_id", "discord_voice_bridge_tab")
    addons.setTabVisible(1, False)
    harness.left_tabs = addons

    session = {"ui": {"layout": {"hidden_tabs": {"addons": ["addon:nc.discord_voice_bridge:discord_voice_bridge_tab"]}}}}
    harness._save_persisted_hidden_tabs(session)
    assert session["ui"]["layout"]["hidden_tabs"]["addons"]

    addons.setTabVisible(1, True)
    harness._save_persisted_hidden_tabs(session)

    assert "hidden_tabs" not in session["ui"]["layout"]


if __name__ == "__main__":
    test_tab_order_session_uses_readable_aliases_and_restores_order()
    test_tab_order_reapplies_before_post_restore_save()
    test_tab_move_triggers_session_save_after_install()
    test_hidden_addon_tabs_session_uses_readable_alias_and_restores_visibility()
    test_unhide_clears_hidden_addon_tab_session_state()
    print("smoke_tab_order_persistence: ok")
