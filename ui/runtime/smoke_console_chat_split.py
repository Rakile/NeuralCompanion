import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6 import QtWidgets

from ui.runtime.console_chat_split import install_console_chat_split


def _make_page(object_name, clear_name):
    page = QtWidgets.QWidget()
    page.setObjectName(object_name)
    layout = QtWidgets.QVBoxLayout(page)
    header = QtWidgets.QHBoxLayout()
    header.addWidget(QtWidgets.QLabel(object_name))
    header.addStretch(1)
    clear_button = QtWidgets.QPushButton("Clear")
    clear_button.setObjectName(clear_name)
    header.addWidget(clear_button)
    layout.addLayout(header)
    layout.addWidget(QtWidgets.QTextEdit())
    return page, clear_button


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(window)
    tabs = QtWidgets.QTabWidget()
    tabs.setObjectName("right_tabs")
    layout.addWidget(tabs)
    system_tab, console_clear = _make_page("system_console_tab", "console_clear_button")
    chat_tab, chat_clear = _make_page("chat_runtime_tab", "chat_clear_button")
    other_tab = QtWidgets.QWidget()
    tabs.addTab(system_tab, "System Console")
    tabs.addTab(chat_tab, "Chat")
    tabs.addTab(other_tab, "Other")
    window.show()
    app.processEvents()

    controller = install_console_chat_split(window)
    assert controller is not None
    console_toggle = window.findChild(QtWidgets.QPushButton, "console_chat_split_toggle_button")
    chat_toggle = window.findChild(QtWidgets.QPushButton, "chat_console_split_toggle_button")
    assert console_toggle is not None
    assert chat_toggle is not None
    assert console_toggle.text() == "Split: Off"
    assert chat_toggle.text() == "Split: Off"

    console_toggle.click()
    assert controller.split_enabled()
    assert tabs.count() == 3
    assert tabs.tabText(0) == "System Console"
    assert tabs.tabText(1) == "Chat"
    assert tabs.tabText(2) == "Other"
    assert tabs.currentIndex() == 0
    assert tabs.indexOf(system_tab) == -1
    assert tabs.indexOf(chat_tab) == -1
    assert system_tab.parentWidget().objectName() == "console_chat_splitter"
    assert chat_tab.parentWidget().objectName() == "console_chat_splitter"
    assert system_tab.isVisible()
    assert chat_tab.isVisible()
    assert console_toggle.isChecked()
    assert chat_toggle.isChecked()
    assert console_toggle.text() == "Split: On"
    assert chat_toggle.text() == "Split: On"

    tabs.setCurrentIndex(1)
    app.processEvents()
    assert tabs.currentIndex() == 1
    assert system_tab.parentWidget().objectName() == "console_chat_splitter"
    assert chat_tab.parentWidget().objectName() == "console_chat_splitter"
    assert system_tab.isVisible()
    assert chat_tab.isVisible()

    chat_toggle.click()
    assert not controller.split_enabled()
    assert tabs.count() == 3
    assert tabs.tabText(0) == "System Console"
    assert tabs.tabText(1) == "Chat"
    assert tabs.tabText(2) == "Other"
    assert tabs.indexOf(system_tab) == 0
    assert tabs.indexOf(chat_tab) == 1
    assert tabs.currentWidget() is chat_tab
    assert not console_toggle.isChecked()
    assert not chat_toggle.isChecked()
    assert console_toggle.text() == "Split: Off"
    assert chat_toggle.text() == "Split: Off"

    window.close()
    app.processEvents()
    print("[Smoke] Console/chat split toggle OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
