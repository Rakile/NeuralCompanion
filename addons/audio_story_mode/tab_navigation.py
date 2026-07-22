from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets


class AudioStoryTabButton(QtWidgets.QFrame):
    clicked = QtCore.Signal(int)
    move_requested = QtCore.Signal(int, int)

    def __init__(
        self,
        stack_index: int,
        title: str,
        icon: QtGui.QIcon,
        color: str,
        tooltip: str,
        parent=None,
    ):
        super().__init__(parent)
        self.stack_index = int(stack_index)
        self.key = ""
        self._color = str(color or "#38bdf8")
        self._selected = False
        self._drag_start = QtCore.QPoint()
        self._dragging = False
        self.setObjectName("audio_story_inner_tab_button")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip((str(tooltip or "").strip() + "\nDrag to reorder this tab button.").strip())
        self.setMinimumSize(80, 68)
        self.setMaximumSize(96, 68)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(7, 4, 7, 5)
        layout.setSpacing(1)
        self.title_label = QtWidgets.QLabel(str(title or ""))
        self.title_label.setObjectName("audio_story_inner_tab_title")
        self.title_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.title_label.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        font = self.title_label.font()
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setMinimumHeight(16)
        self.icon_label = QtWidgets.QLabel()
        self.icon_label.setObjectName("audio_story_inner_tab_icon")
        self.icon_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.icon_label.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        self._icon_pixmap = icon.pixmap(QtCore.QSize(36, 36))
        self.icon_label.setPixmap(self._icon_pixmap)
        self.icon_label.setFixedHeight(38)
        layout.addWidget(self.title_label)
        layout.addWidget(self.icon_label)
        self._apply_style()

    def icon_pixmap_size(self) -> tuple[int, int]:
        return self._icon_pixmap.width(), self._icon_pixmap.height()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_style()

    def _apply_style(self) -> None:
        background = "#1c2d43" if self._selected else "#111b28"
        border = self._color if self._selected else "#36506d"
        self.setStyleSheet(
            f"""
            QFrame#audio_story_inner_tab_button {{
                background: {background};
                border: 1px solid {border};
                border-bottom-color: {border};
                border-radius: 9px;
            }}
            QLabel#audio_story_inner_tab_title {{
                color: {self._color};
                font-weight: 800;
                background: transparent;
                border: none;
            }}
            QLabel#audio_story_inner_tab_icon {{
                background: transparent;
                border: none;
            }}
            """
        )

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_start = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            position = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if (position - self._drag_start).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                self._dragging = True
                target = self._button_at_event(event)
                if target is not None and target is not self:
                    self.move_requested.emit(
                        self.parent_navigation_index(),
                        target.parent_navigation_index(),
                    )
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            if not self._dragging:
                self.clicked.emit(self.stack_index)
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def parent_navigation_index(self) -> int:
        navigation = self.parent()
        while navigation is not None and not isinstance(navigation, AudioStoryTabNavigation):
            navigation = navigation.parent()
        if isinstance(navigation, AudioStoryTabNavigation):
            try:
                return navigation.buttons.index(self)
            except ValueError:
                pass
        return -1

    @staticmethod
    def _button_at_event(event):
        try:
            global_position = event.globalPosition().toPoint()
        except Exception:
            global_position = event.globalPos()
        widget = QtWidgets.QApplication.widgetAt(global_position)
        while widget is not None:
            if isinstance(widget, AudioStoryTabButton):
                return widget
            widget = widget.parentWidget()
        return None


class AudioStoryCurrentPageStack(QtWidgets.QStackedWidget):
    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class AudioStoryTabNavScrollArea(QtWidgets.QScrollArea):
    def wheelEvent(self, event):
        event.ignore()


@dataclass
class _PageEntry:
    key: str
    page: QtWidgets.QWidget
    button: AudioStoryTabButton


class AudioStoryTabNavigation(QtWidgets.QWidget):
    currentChanged = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("audio_story_inner_tabs")
        self.entries: list[_PageEntry] = []
        self.buttons: list[AudioStoryTabButton] = []
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(5, 5, 5, 5)
        root_layout.setSpacing(4)

        nav_row = QtWidgets.QWidget()
        nav_row.setObjectName("audio_story_inner_tab_nav_row")
        nav_row_layout = QtWidgets.QHBoxLayout(nav_row)
        nav_row_layout.setContentsMargins(0, 0, 0, 0)
        nav_row_layout.setSpacing(4)
        self.previous_button = QtWidgets.QToolButton()
        self.previous_button.setObjectName("audio_story_inner_tab_prev_button")
        self.previous_button.setText("<")
        self.previous_button.setToolTip("Show earlier Audio Story tabs")
        self.previous_button.setFixedSize(22, 58)
        self.next_button = QtWidgets.QToolButton()
        self.next_button.setObjectName("audio_story_inner_tab_next_button")
        self.next_button.setText(">")
        self.next_button.setToolTip("Show later Audio Story tabs")
        self.next_button.setFixedSize(22, 58)
        self.nav_scroll = AudioStoryTabNavScrollArea()
        self.nav_scroll.setObjectName("audio_story_inner_tab_scroll")
        self.nav_scroll.setWidgetResizable(False)
        self.nav_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.nav_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.nav_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.nav_scroll.setFixedHeight(84)
        self.nav_scroll.setFocusPolicy(QtCore.Qt.NoFocus)
        self.nav_scroll.viewport().setAutoFillBackground(False)
        self.nav_widget = QtWidgets.QWidget()
        self.nav_widget.setObjectName("audio_story_inner_tab_nav")
        self.nav_widget.setFixedHeight(80)
        self.nav_layout = QtWidgets.QHBoxLayout(self.nav_widget)
        self.nav_layout.setContentsMargins(0, 4, 0, 8)
        self.nav_layout.setSpacing(5)
        self.nav_scroll.setWidget(self.nav_widget)
        nav_row_layout.addWidget(self.previous_button)
        nav_row_layout.addWidget(self.nav_scroll, 1)
        nav_row_layout.addWidget(self.next_button)
        self.stack = AudioStoryCurrentPageStack()
        self.stack.setObjectName("audio_story_inner_tab_stack")
        self.stack.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        root_layout.addWidget(nav_row)
        root_layout.addWidget(self.stack, 1)
        self.previous_button.clicked.connect(lambda: self._scroll_navigation(-1))
        self.next_button.clicked.connect(lambda: self._scroll_navigation(1))
        self.previous_button.setVisible(False)
        self.next_button.setVisible(False)
        scrollbar = self.nav_scroll.horizontalScrollBar()
        scrollbar.valueChanged.connect(self._update_navigation_buttons)
        scrollbar.rangeChanged.connect(self._update_navigation_buttons)
        self.setStyleSheet(
            """
            QWidget#audio_story_inner_tabs,
            QWidget#audio_story_inner_tab_nav_row,
            QWidget#audio_story_inner_tab_nav {
                background: transparent;
                border: none;
            }
            QScrollArea#audio_story_inner_tab_scroll {
                background: transparent;
                border: none;
                border-radius: 10px;
            }
            QScrollArea#audio_story_inner_tab_scroll > QWidget,
            QScrollArea#audio_story_inner_tab_scroll > QWidget > QWidget {
                background: transparent;
                border: none;
            }
            QToolButton#audio_story_inner_tab_prev_button,
            QToolButton#audio_story_inner_tab_next_button {
                background: #1b2b40;
                color: #f4f7fb;
                border: 1px solid #416184;
                border-radius: 8px;
                font-weight: 800;
            }
            QToolButton#audio_story_inner_tab_prev_button:disabled,
            QToolButton#audio_story_inner_tab_next_button:disabled {
                color: #6f8298;
                border-color: #2b4058;
            }
            """
        )
        self._navigation_update_timer = QtCore.QTimer(self)
        self._navigation_update_timer.setSingleShot(True)
        self._navigation_update_timer.timeout.connect(
            self._update_navigation_buttons
        )
        self._navigation_update_timer.start(0)

    def add_page(
        self,
        key: str,
        page: QtWidgets.QWidget,
        title: str,
        tooltip: str,
        color: str,
    ) -> int:
        stack_index = self.stack.addWidget(page)
        button = AudioStoryTabButton(
            stack_index,
            title,
            _generated_icon(key, color),
            color,
            tooltip,
            self,
        )
        button.key = str(key)
        button.setProperty("audio_story_icon_key", str(key))
        button.clicked.connect(self.select_index)
        button.move_requested.connect(self.move_button)
        self.entries.append(_PageEntry(str(key), page, button))
        self.buttons.append(button)
        self.nav_layout.addWidget(button)
        self.nav_widget.adjustSize()
        self._update_navigation_buttons()
        if len(self.entries) == 1:
            self.select_index(stack_index)
        return stack_index

    def page_keys(self) -> list[str]:
        return [entry.key for entry in self.entries]

    def current_key(self) -> str:
        current = self.stack.currentWidget()
        for entry in self.entries:
            if entry.page is current:
                return entry.key
        return ""

    @QtCore.Slot(int)
    def select_index(self, stack_index: int) -> None:
        if stack_index < 0 or stack_index >= self.stack.count():
            return
        self.stack.setCurrentIndex(stack_index)
        for button in self.buttons:
            button.set_selected(button.stack_index == stack_index)
        self.currentChanged.emit(self.current_key())
        self._ensure_button_visible(stack_index)
        self._update_navigation_buttons()
        self.stack.updateGeometry()
        self.updateGeometry()

    def select_key(self, key: str) -> None:
        for entry in self.entries:
            if entry.key == str(key):
                self.select_index(entry.button.stack_index)
                return

    @QtCore.Slot(int, int)
    def move_button(self, source_index: int, target_index: int) -> None:
        if source_index == target_index:
            return
        if not (0 <= source_index < len(self.entries) and 0 <= target_index < len(self.entries)):
            return
        entry = self.entries.pop(source_index)
        self.entries.insert(target_index, entry)
        self.buttons = [item.button for item in self.entries]
        self.nav_layout.removeWidget(entry.button)
        self.nav_layout.insertWidget(target_index, entry.button)
        self.nav_widget.adjustSize()
        self._ensure_button_visible(entry.button.stack_index)
        self._update_navigation_buttons()

    def _scroll_navigation(self, direction: int) -> None:
        bar = self.nav_scroll.horizontalScrollBar()
        step = max(90, int(self.nav_scroll.viewport().width() * 0.65))
        bar.setValue(bar.value() + (step if direction > 0 else -step))
        self._update_navigation_buttons()

    def _ensure_button_visible(self, stack_index: int) -> None:
        button = next(
            (
                item
                for item in self.buttons
                if item.stack_index == int(stack_index)
            ),
            None,
        )
        if button is not None:
            self.nav_scroll.ensureWidgetVisible(button, 12, 0)

    def _update_navigation_buttons(self, *_args) -> None:
        try:
            scrollbar = self.nav_scroll.horizontalScrollBar()
        except RuntimeError:
            return
        has_overflow = scrollbar.maximum() > scrollbar.minimum()
        self.previous_button.setVisible(has_overflow)
        self.next_button.setVisible(has_overflow)
        self.previous_button.setEnabled(scrollbar.value() > scrollbar.minimum())
        self.next_button.setEnabled(scrollbar.value() < scrollbar.maximum())


def _generated_icon(kind: str, color: str) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(50, 50)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    accent = QtGui.QColor(str(color or "#38bdf8"))
    painter.setPen(QtGui.QPen(accent, 3))
    painter.setBrush(QtGui.QColor(17, 27, 40))
    painter.drawRoundedRect(4, 4, 42, 42, 10, 10)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(accent)
    key = str(kind or "").strip().lower()
    if key == "project":
        painter.drawRoundedRect(10, 17, 30, 21, 3, 3)
        painter.drawPolyline(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(11, 18),
                    QtCore.QPointF(17, 18),
                    QtCore.QPointF(20, 14),
                    QtCore.QPointF(29, 14),
                    QtCore.QPointF(32, 18),
                    QtCore.QPointF(39, 18),
                ]
            )
        )
        painter.drawLine(15, 25, 35, 25)
        painter.drawLine(15, 31, 29, 31)
    elif key == "audio":
        painter.drawRect(12, 21, 7, 9)
        painter.drawPolygon(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(19, 21),
                    QtCore.QPointF(27, 15),
                    QtCore.QPointF(27, 36),
                    QtCore.QPointF(19, 30),
                ]
            )
        )
        painter.drawArc(25, 17, 12, 17, -55 * 16, 110 * 16)
        painter.drawArc(25, 13, 19, 25, -50 * 16, 100 * 16)
    elif key == "story":
        painter.drawLine(25, 14, 25, 37)
        painter.drawPolyline(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(25, 17),
                    QtCore.QPointF(20, 14),
                    QtCore.QPointF(12, 14),
                    QtCore.QPointF(12, 34),
                    QtCore.QPointF(20, 34),
                    QtCore.QPointF(25, 37),
                ]
            )
        )
        painter.drawPolyline(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(25, 17),
                    QtCore.QPointF(30, 14),
                    QtCore.QPointF(38, 14),
                    QtCore.QPointF(38, 34),
                    QtCore.QPointF(30, 34),
                    QtCore.QPointF(25, 37),
                ]
            )
        )
    elif key == "images":
        painter.drawRect(11, 14, 28, 22)
        painter.drawEllipse(29, 18, 5, 5)
        painter.drawLine(14, 33, 21, 26)
        painter.drawLine(21, 26, 27, 32)
        painter.drawLine(27, 32, 36, 23)
    elif key == "review":
        for y in (17, 26, 35):
            painter.drawLine(12, y, 15, y + 3)
            painter.drawLine(15, y + 3, 20, y - 3)
            painter.drawLine(24, y, 38, y)
    elif key == "play":
        painter.setBrush(accent)
        painter.drawPolygon(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(14, 14),
                    QtCore.QPointF(14, 34),
                    QtCore.QPointF(29, 24),
                ]
            )
        )
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawArc(25, 22, 15, 15, 0, 90 * 16)
        painter.drawArc(23, 18, 23, 23, 0, 90 * 16)
    else:
        painter.drawRoundedRect(14, 13, 22, 24, 5, 5)
        painter.drawLine(18, 20, 32, 20)
        painter.drawLine(18, 27, 32, 27)
    painter.end()
    return QtGui.QIcon(pixmap)


__all__ = [
    "AudioStoryCurrentPageStack",
    "AudioStoryTabButton",
    "AudioStoryTabNavigation",
    "AudioStoryTabNavScrollArea",
]
