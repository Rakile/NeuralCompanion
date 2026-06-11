import re
from pathlib import Path
import xml.etree.ElementTree as ET

from PySide6 import QtCore, QtGui, QtWidgets


def apply_inline_theme_styles(root, palette, *, theme_preset_widgets, canonicalize_stylesheet, replace_theme_colors):
    if root is None:
        return
    skip_object_names = {name for _preset, button_name, edit_name in theme_preset_widgets for name in (button_name, edit_name)}
    widgets = []
    find_children = getattr(root, "findChildren", None)
    if callable(find_children):
        try:
            widgets.extend(list(find_children(QtCore.QObject)))
        except Exception:
            pass
    for widget in widgets:
        if widget is None or not hasattr(widget, "styleSheet") or not hasattr(widget, "setStyleSheet"):
            continue
        try:
            object_name = str(widget.objectName() or "").strip()
        except Exception:
            object_name = ""
        if object_name in skip_object_names or object_name.startswith("theme_"):
            continue
        try:
            base_stylesheet = widget.property("nc_base_stylesheet")
        except Exception:
            base_stylesheet = None
        if not base_stylesheet:
            try:
                current_stylesheet = str(widget.styleSheet() or "")
            except Exception:
                current_stylesheet = ""
            if not current_stylesheet.strip():
                continue
            base_stylesheet = canonicalize_stylesheet(current_stylesheet)
            try:
                widget.setProperty("nc_base_stylesheet", base_stylesheet)
            except Exception:
                pass
        else:
            base_stylesheet = canonicalize_stylesheet(str(base_stylesheet or ""))
            try:
                widget.setProperty("nc_base_stylesheet", base_stylesheet)
            except Exception:
                pass
        themed_stylesheet = replace_theme_colors(str(base_stylesheet or ""), palette)
        try:
            if str(widget.styleSheet() or "") != themed_stylesheet:
                widget.setStyleSheet(themed_stylesheet)
        except Exception:
            continue


def apply_readable_input_palettes(root, palette):
    if root is None or not hasattr(root, "findChildren"):
        return
    window_bg = QtGui.QColor(str(palette.get("window_bg", "#11161d") or "#11161d"))
    text = QtGui.QColor(str(palette.get("text_strong", palette.get("text", "#f2f5f9")) or "#f2f5f9"))
    soft_text = QtGui.QColor(str(palette.get("text", "#e5e9f0") or "#e5e9f0"))
    disabled_text = QtGui.QColor(str(palette.get("text_muted", palette.get("text_disabled", "#b7c1ce")) or "#b7c1ce"))
    field_bg = QtGui.QColor(str(palette.get("field_bg", "#0f141b") or "#0f141b"))
    menu_bg = QtGui.QColor(str(palette.get("menu_bg", palette.get("field_bg", "#16202b")) or "#16202b"))
    border = str(palette.get("button_border", palette.get("surface_border", "#324b69")) or "#324b69")
    hover = str(palette.get("button_hover", palette.get("tab_selected_bg", "#223247")) or "#223247")
    highlight = QtGui.QColor(str(palette.get("accent_bg", "#4d8dff") or "#4d8dff"))
    highlighted_text = QtGui.QColor("#ffffff")
    popup_stylesheet = (
        "QListView { "
        f"background: {menu_bg.name()}; color: {text.name()}; "
        f"selection-background-color: {highlight.name()}; selection-color: {highlighted_text.name()}; "
        f"border: 1px solid {border}; outline: 0; "
        "}"
        "QListView::item { "
        f"background: {menu_bg.name()}; color: {text.name()}; "
        "min-height: 24px; padding: 4px 8px; "
        "}"
        "QListView::item:selected { "
        f"background: {highlight.name()}; color: {highlighted_text.name()}; "
        "}"
        "QListView::item:hover { "
        f"background: {hover}; color: {highlighted_text.name()}; "
        "}"
    )
    chrome_widgets = []
    try:
        chrome_widgets.extend(root.findChildren(QtWidgets.QMenuBar))
        chrome_widgets.extend(root.findChildren(QtWidgets.QMenu))
        chrome_widgets.extend(root.findChildren(QtWidgets.QStatusBar))
    except Exception:
        chrome_widgets = []
    for widget in chrome_widgets:
        try:
            is_popup_menu = isinstance(widget, QtWidgets.QMenu)
            bg = menu_bg if is_popup_menu else window_bg
            pal = widget.palette()
            for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive):
                pal.setColor(group, QtGui.QPalette.Window, bg)
                pal.setColor(group, QtGui.QPalette.Base, bg)
                pal.setColor(group, QtGui.QPalette.Button, bg)
                pal.setColor(group, QtGui.QPalette.Text, text)
                pal.setColor(group, QtGui.QPalette.WindowText, text)
                pal.setColor(group, QtGui.QPalette.ButtonText, text)
                pal.setColor(group, QtGui.QPalette.Highlight, highlight)
                pal.setColor(group, QtGui.QPalette.HighlightedText, highlighted_text)
            for role in (QtGui.QPalette.Text, QtGui.QPalette.WindowText, QtGui.QPalette.ButtonText):
                pal.setColor(QtGui.QPalette.Disabled, role, disabled_text)
            widget.setPalette(pal)
            if hasattr(widget, "setAutoFillBackground"):
                widget.setAutoFillBackground(True)
        except Exception:
            continue
    widgets = []
    try:
        widgets.extend(root.findChildren(QtWidgets.QComboBox))
        widgets.extend(root.findChildren(QtWidgets.QLineEdit))
        widgets.extend(root.findChildren(QtWidgets.QAbstractSpinBox))
    except Exception:
        return
    for widget in widgets:
        try:
            pal = widget.palette()
            for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive):
                pal.setColor(group, QtGui.QPalette.Text, text)
                pal.setColor(group, QtGui.QPalette.WindowText, soft_text)
                pal.setColor(group, QtGui.QPalette.ButtonText, text)
                pal.setColor(group, QtGui.QPalette.Base, field_bg)
                pal.setColor(group, QtGui.QPalette.Window, field_bg)
                pal.setColor(group, QtGui.QPalette.Highlight, highlight)
                pal.setColor(group, QtGui.QPalette.HighlightedText, highlighted_text)
                if hasattr(QtGui.QPalette, "PlaceholderText"):
                    pal.setColor(group, QtGui.QPalette.PlaceholderText, disabled_text)
            for role in (QtGui.QPalette.Text, QtGui.QPalette.WindowText, QtGui.QPalette.ButtonText):
                pal.setColor(QtGui.QPalette.Disabled, role, disabled_text)
            if hasattr(QtGui.QPalette, "PlaceholderText"):
                pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.PlaceholderText, disabled_text)
            widget.setPalette(pal)
            if isinstance(widget, QtWidgets.QComboBox):
                model = widget.model()
                if model is not None:
                    text_brush = QtGui.QBrush(text)
                    bg_brush = QtGui.QBrush(menu_bg)
                    for row in range(int(widget.count())):
                        try:
                            model.setData(model.index(row, 0), text_brush, QtCore.Qt.ForegroundRole)
                            model.setData(model.index(row, 0), bg_brush, QtCore.Qt.BackgroundRole)
                        except Exception:
                            continue
                view = widget.view()
                if view is not None:
                    view.setPalette(pal)
                    view.setStyleSheet(popup_stylesheet)
                line_edit = widget.lineEdit() if widget.isEditable() else None
                if line_edit is not None:
                    line_edit.setPalette(pal)
        except Exception:
            continue


def apply_engine_action_button_accents(root):
    if root is None or not hasattr(root, "findChild"):
        return
    accent_styles = {
        "btn_start_engine": (
            "QPushButton { background: #1d6e52; border: 1px solid #2cc985; color: #f4fffa; "
            "border-radius: 10px; padding: 8px 12px; font-weight: 700; min-height: 44px; }"
            "QPushButton:hover { background: #238462; border-color: #46dda0; }"
            "QPushButton:pressed { background: #195d46; border-color: #22b679; }"
            "QPushButton:disabled { background: #1d3a31; border: 1px solid #355e51; color: #a9c6ba; }"
        ),
        "btn_stop_engine": (
            "QPushButton { background: #7a2626; border: 1px solid #d64a4a; color: #fff5f5; "
            "border-radius: 10px; padding: 8px 12px; font-weight: 700; min-height: 44px; }"
            "QPushButton:hover { background: #923131; border-color: #ef6767; }"
            "QPushButton:pressed { background: #671f1f; border-color: #c43d3d; }"
            "QPushButton:disabled { background: #402525; border: 1px solid #6f4848; color: #d2bbbb; }"
        ),
    }
    for object_name, stylesheet in accent_styles.items():
        try:
            button = root.findChild(QtWidgets.QPushButton, object_name)
        except Exception:
            button = None
        if button is None:
            continue
        try:
            button.setStyleSheet(stylesheet)
        except Exception:
            continue


def split_collapsible_section_text(text, fallback_title):
    raw = str(text or "").strip()
    if not raw:
        return str(fallback_title or "").strip(), ""
    separator = "  -  "
    if separator in raw:
        title, summary = raw.split(separator, 1)
        return str(title or fallback_title or "").strip(), str(summary or "").strip()
    return raw, ""


_runtime_config = {}
_slider_behavior_filter = None

def configure_theme_support(runtime_config=None):
    global _runtime_config
    _runtime_config = runtime_config if isinstance(runtime_config, dict) else {}

def _runtime_config_get(key, default=None):
    try:
        return _runtime_config.get(key, default)
    except Exception:
        return default


SLIDER_HANDLE_COLOR_DEFAULT = "#39d98a"
SLIDER_HANDLE_COLOR_PRESETS = (
    "#39d98a",
    "#82f06b",
    "#4d8dff",
    "#8b5cf6",
    "#ff9f1c",
    "#ff4d5e",
    "#00e5ff",
    "#f2d16b",
    "#f472b6",
    "#d8dee9",
)


def _normalize_slider_handle_color(value, fallback=SLIDER_HANDLE_COLOR_DEFAULT):
    color = QtGui.QColor(str(value or "").strip())
    if not color.isValid():
        color = QtGui.QColor(str(fallback or SLIDER_HANDLE_COLOR_DEFAULT))
    return color.name()


def _slider_handle_colors(handle_color):
    color = QtGui.QColor(str(handle_color or SLIDER_HANDLE_COLOR_DEFAULT))
    if not color.isValid():
        color = QtGui.QColor(SLIDER_HANDLE_COLOR_DEFAULT)
    return {
        "base": color.name(),
        "top": color.lighter(145).name(),
        "bottom": color.darker(135).name(),
        "border": color.lighter(165).name(),
        "pressed_top": color.lighter(125).name(),
        "pressed_bottom": color.darker(150).name(),
    }


def _slider_handle_color_for(slider):
    try:
        value = slider.property("nc_slider_handle_color")
    except Exception:
        value = None
    return _normalize_slider_handle_color(value, SLIDER_HANDLE_COLOR_DEFAULT)


def app_slider_stylesheet(handle_color=None):
    colors = _slider_handle_colors(_normalize_slider_handle_color(handle_color, SLIDER_HANDLE_COLOR_DEFAULT))
    return f"""
QSlider {{
    background: transparent;
    min-height: 26px;
}}
QSlider:vertical {{
    min-width: 26px;
}}
QSlider::groove:horizontal {{
    height: 8px;
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #0c1118, stop: 0.45 #202833, stop: 1 #111923);
    border: 1px solid #303a47;
    border-radius: 4px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #1b4f86, stop: 0.5 #164274, stop: 1 #0f2e52);
    border: 1px solid #2f6fc8;
    border-radius: 4px;
}}
QSlider::add-page:horizontal {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #0c1118, stop: 0.45 #202833, stop: 1 #111923);
    border: 1px solid #303a47;
    border-radius: 4px;
}}
QSlider::handle:horizontal {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {colors["top"]}, stop: 0.48 {colors["base"]}, stop: 1 {colors["bottom"]});
    border: 1px solid #07111f;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 10px;
}}
QSlider::handle:horizontal:hover {{
    border: 1px solid #ffffff;
}}
QSlider::handle:horizontal:pressed {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {colors["pressed_top"]}, stop: 1 {colors["pressed_bottom"]});
    border: 1px solid #ffffff;
}}
QSlider::groove:vertical {{
    width: 8px;
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #0c1118, stop: 0.45 #202833, stop: 1 #111923);
    border: 1px solid #303a47;
    border-radius: 4px;
}}
QSlider::sub-page:vertical {{
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #1b4f86, stop: 0.5 #164274, stop: 1 #0f2e52);
    border: 1px solid #2f6fc8;
    border-radius: 4px;
}}
QSlider::add-page:vertical {{
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #0c1118, stop: 0.45 #202833, stop: 1 #111923);
    border: 1px solid #303a47;
    border-radius: 4px;
}}
QSlider::handle:vertical {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {colors["top"]}, stop: 0.48 {colors["base"]}, stop: 1 {colors["bottom"]});
    border: 1px solid #07111f;
    width: 18px;
    height: 18px;
    margin: 0 -6px;
    border-radius: 10px;
}}
QSlider::handle:vertical:hover {{
    border: 1px solid #ffffff;
}}
QSlider::handle:vertical:pressed {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {colors["pressed_top"]}, stop: 1 {colors["pressed_bottom"]});
    border: 1px solid #ffffff;
}}
QSlider:disabled {{
    background: transparent;
}}
QSlider::sub-page:horizontal:disabled,
QSlider::sub-page:vertical:disabled {{
    background: #35445a;
    border-color: #40506a;
}}
QSlider::add-page:horizontal:disabled,
QSlider::add-page:vertical:disabled {{
    background: #1a2028;
    border-color: #27303b;
}}
QSlider::handle:horizontal:disabled,
QSlider::handle:vertical:disabled {{
    background: #5b6675;
    border-color: #7f8791;
}}
""".strip()


def apply_app_slider_style(slider, handle_color=None):
    if slider is None or not isinstance(slider, QtWidgets.QSlider):
        return
    try:
        color = _normalize_slider_handle_color(handle_color, _slider_handle_color_for(slider))
        next_style = app_slider_stylesheet(color)
        if str(slider.styleSheet() or "") != next_style:
            slider.setStyleSheet(next_style)
    except Exception:
        return


def apply_app_slider_styles(root):
    if root is None:
        return
    sliders = []
    if isinstance(root, QtWidgets.QSlider):
        sliders.append(root)
    if not hasattr(root, "findChildren"):
        for slider in sliders:
            apply_app_slider_style(slider)
        return
    try:
        sliders.extend(list(root.findChildren(QtWidgets.QSlider)))
    except Exception:
        return
    for slider in sliders:
        apply_app_slider_style(slider)


def _app_sliders_for_root(root):
    if root is None:
        return []
    sliders = []
    if isinstance(root, QtWidgets.QSlider):
        sliders.append(root)
    if hasattr(root, "findChildren"):
        try:
            sliders.extend(list(root.findChildren(QtWidgets.QSlider)))
        except Exception:
            pass
    return sliders


def _slider_display_value(slider):
    try:
        value = int(slider.sliderPosition())
    except Exception:
        try:
            value = int(slider.value())
        except Exception:
            value = 0
    suffix = ""
    try:
        name = str(slider.objectName() or "").lower()
    except Exception:
        name = ""
    if "percent" in name or "volume" in name or "strength" in name or "continuity" in name:
        suffix = "%"
    return f"{value}{suffix}"


def _slider_handle_rect(slider):
    option = QtWidgets.QStyleOptionSlider()
    slider.initStyleOption(option)
    return slider.style().subControlRect(
        QtWidgets.QStyle.CC_Slider,
        option,
        QtWidgets.QStyle.SC_SliderHandle,
        slider,
    )


def _show_slider_value_tip(slider):
    rect = _slider_handle_rect(slider)
    point = rect.center()
    if slider.orientation() == QtCore.Qt.Horizontal:
        point.setY(rect.top() - 22)
    else:
        point.setX(rect.right() + 14)
    QtWidgets.QToolTip.showText(slider.mapToGlobal(point), _slider_display_value(slider), slider)


def _slider_handle_hit(slider, position):
    return _slider_handle_rect(slider).adjusted(-4, -4, 4, 4).contains(position.toPoint())


def _apply_slider_handle_color_to_slider(slider, color):
    normalized = _normalize_slider_handle_color(color)
    if slider is None or not isinstance(slider, QtWidgets.QSlider):
        return normalized
    try:
        slider.setProperty("nc_slider_handle_color", normalized)
    except Exception:
        pass
    apply_app_slider_style(slider, normalized)
    return normalized


def _open_slider_color_dialog(slider):
    dialog = QtWidgets.QDialog(slider)
    dialog.setWindowTitle("Slider Handle Color")
    dialog.setModal(True)
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(10)

    swatches = QtWidgets.QGridLayout()
    color_input = QtWidgets.QLineEdit(_slider_handle_color_for(slider))
    color_input.setPlaceholderText("#39d98a")

    def set_color_text(color):
        color_input.setText(_normalize_slider_handle_color(color))

    for index, color in enumerate(SLIDER_HANDLE_COLOR_PRESETS):
        button = QtWidgets.QPushButton()
        button.setFixedSize(30, 30)
        button.setToolTip(color)
        button.setStyleSheet(
            f"QPushButton {{ background: {color}; border: 1px solid #d8dee9; border-radius: 15px; }}"
            "QPushButton:hover { border: 2px solid #ffffff; }"
        )
        button.clicked.connect(lambda _checked=False, value=color: set_color_text(value))
        swatches.addWidget(button, index // 5, index % 5)
    layout.addLayout(swatches)
    layout.addWidget(color_input)

    buttons = QtWidgets.QHBoxLayout()
    buttons.addStretch(1)
    apply_button = QtWidgets.QPushButton("Apply")
    cancel_button = QtWidgets.QPushButton("Cancel")
    buttons.addWidget(apply_button)
    buttons.addWidget(cancel_button)
    layout.addLayout(buttons)

    def apply_color():
        color = QtGui.QColor(color_input.text().strip())
        if not color.isValid():
            color_input.setFocus()
            return
        _apply_slider_handle_color_to_slider(slider, color.name())
        dialog.accept()

    apply_button.clicked.connect(apply_color)
    cancel_button.clicked.connect(dialog.reject)
    dialog.exec()


class _AppSliderBehaviorFilter(QtCore.QObject):
    def eventFilter(self, obj, event):
        try:
            if isinstance(obj, QtWidgets.QSlider):
                if event.type() in (QtCore.QEvent.Polish, QtCore.QEvent.Show, QtCore.QEvent.EnabledChange):
                    self._attach_slider(obj)
                elif event.type() == QtCore.QEvent.MouseButtonDblClick and _slider_handle_hit(obj, event.position()):
                    _open_slider_color_dialog(obj)
                    return True
            elif event.type() == QtCore.QEvent.ChildAdded:
                child = event.child()
                if isinstance(child, QtWidgets.QSlider):
                    self._attach_slider(child)
        except Exception:
            pass
        return False

    def _attach_slider(self, slider):
        if slider is None:
            return
        try:
            slider.setTracking(False)
            if not bool(slider.property("nc_app_slider_behavior_connected")):
                slider.sliderMoved.connect(lambda _value, target=slider: _show_slider_value_tip(target))
                slider.sliderPressed.connect(lambda target=slider: _show_slider_value_tip(target))
                slider.sliderReleased.connect(lambda: QtWidgets.QToolTip.hideText())
                slider.setProperty("nc_app_slider_behavior_connected", True)
            apply_app_slider_style(slider)
        except Exception:
            pass


def install_app_wide_slider_styling(root=None):
    global _slider_behavior_filter
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    if _slider_behavior_filter is None:
        _slider_behavior_filter = _AppSliderBehaviorFilter(app)
        app.installEventFilter(_slider_behavior_filter)
    if root is not None:
        for slider in _app_sliders_for_root(root):
            _slider_behavior_filter._attach_slider(slider)
    for widget in app.topLevelWidgets():
        for slider in _app_sliders_for_root(widget):
            _slider_behavior_filter._attach_slider(slider)

APP_STYLESHEET_FALLBACK = """
QMainWindow { background: #11161d; }
QWidget { color: #e5e9f0; font-family: "Segoe UI"; font-size: 12px; }
QMenuBar {
    background: #11161d;
    color: #f2f5f9;
    border-bottom: 1px solid #273342;
    padding: 2px 6px;
}
QMenuBar::item {
    background: transparent;
    color: #f2f5f9;
    padding: 4px 10px;
    border-radius: 6px;
}
QMenuBar::item:selected {
    background: #223247;
    color: #f2f5f9;
}
QMenuBar::item:pressed {
    background: #233245;
    border: 1px solid #4d8dff;
}
QMenu {
    background: #16202b;
    color: #f2f5f9;
    border: 1px solid #273342;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    background: transparent;
    color: #f2f5f9;
    padding: 6px 24px 6px 10px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #223247;
    color: #f2f5f9;
}
QMenu::separator {
    height: 1px;
    background: #2c3a4b;
    margin: 6px 4px;
}
QStatusBar {
    background: #11161d;
    color: #8ea3b8;
    border-top: 1px solid #273342;
}
QCheckBox {
    color: #f2f5f9;
    spacing: 9px;
    min-height: 24px;
}
QCheckBox:disabled {
    color: #b7c1ce;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    image: url(ui/assets/checkbox_round_inactive.svg);
    background: transparent;
    border: 0px;
}
QCheckBox::indicator:hover {
    image: url(ui/assets/checkbox_round_inactive.svg);
    background: transparent;
    border: 0px;
}
QCheckBox::indicator:checked {
    width: 20px;
    height: 20px;
    image: url(ui/assets/checkbox_round_active.svg);
    background: transparent;
    border: 0px;
}
QCheckBox::indicator:checked:hover {
    width: 20px;
    height: 20px;
    image: url(ui/assets/checkbox_round_active.svg);
    background: transparent;
    border: 0px;
}
QCheckBox::indicator:disabled {
    width: 20px;
    height: 20px;
    image: url(ui/assets/checkbox_round_inactive.svg);
    background: transparent;
    border: 0px;
}
QCheckBox::indicator:checked:disabled {
    width: 20px;
    height: 20px;
    image: url(ui/assets/checkbox_round_active.svg);
    background: transparent;
    border: 0px;
}
QSlider {
    background: transparent;
    min-height: 26px;
}
QSlider:vertical {
    min-width: 26px;
}
QSlider::groove:horizontal {
    height: 8px;
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #0c1118, stop: 0.45 #202833, stop: 1 #111923);
    border: 1px solid #303a47;
    border-radius: 4px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #1b4f86, stop: 0.5 #164274, stop: 1 #0f2e52);
    border: 1px solid #2f6fc8;
    border-radius: 4px;
}
QSlider::add-page:horizontal {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #0c1118, stop: 0.45 #202833, stop: 1 #111923);
    border: 1px solid #303a47;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #76f4b1, stop: 0.48 #39d98a, stop: 1 #218f59);
    border: 1px solid #07111f;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 10px;
}
QSlider::handle:horizontal:hover {
    border: 1px solid #ffffff;
}
QSlider::handle:horizontal:pressed {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #55e699, stop: 1 #1b7549);
    border: 1px solid #ffffff;
}
QSlider::groove:vertical {
    width: 8px;
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #0c1118, stop: 0.45 #202833, stop: 1 #111923);
    border: 1px solid #303a47;
    border-radius: 4px;
}
QSlider::sub-page:vertical {
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #1b4f86, stop: 0.5 #164274, stop: 1 #0f2e52);
    border: 1px solid #2f6fc8;
    border-radius: 4px;
}
QSlider::add-page:vertical {
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #0c1118, stop: 0.45 #202833, stop: 1 #111923);
    border: 1px solid #303a47;
    border-radius: 4px;
}
QSlider::handle:vertical {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #76f4b1, stop: 0.48 #39d98a, stop: 1 #218f59);
    border: 1px solid #07111f;
    width: 18px;
    height: 18px;
    margin: 0 -6px;
    border-radius: 10px;
}
QSlider::handle:vertical:hover {
    border: 1px solid #ffffff;
}
QSlider::handle:vertical:pressed {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #55e699, stop: 1 #1b7549);
    border: 1px solid #ffffff;
}
QSlider:disabled {
    background: transparent;
}
QSlider::sub-page:horizontal:disabled,
QSlider::sub-page:vertical:disabled {
    background: #35445a;
    border-color: #40506a;
}
QSlider::add-page:horizontal:disabled,
QSlider::add-page:vertical:disabled {
    background: #1a2028;
    border-color: #27303b;
}
QSlider::handle:horizontal:disabled,
QSlider::handle:vertical:disabled {
    background: #5b6675;
    border-color: #7f8791;
}
QFrame#Panel { background: #18202a; border: 1px solid #283342; border-radius: 14px; padding: 8px; }
QFrame#HeaderCard { background: #131a23; border: 1px solid #243244; border-radius: 12px; padding: 4px; }
QScrollArea { background: #18202a; border: 1px solid #273342; border-radius: 10px; padding: 6px; }
QScrollArea > QWidget > QWidget { background: #18202a; color: #e5e9f0; }
QScrollBar:vertical {
    background: #131a23;
    border: 1px solid #273342;
    border-radius: 11px;
    width: 22px;
    margin: 2px 2px 2px 2px;
}
QScrollBar::handle:vertical {
    background: #3a516c;
    border: 1px solid #4b6889;
    border-radius: 9px;
    min-height: 52px;
    margin: 3px;
}
QScrollBar::handle:vertical:hover {
    background: #4a6788;
}
QScrollBar::handle:vertical:pressed {
    background: #5b7ca2;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    background: #1a2430;
    border: 0;
    height: 16px;
    subcontrol-origin: margin;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: #131a23;
    border: 1px solid #273342;
    border-radius: 11px;
    height: 22px;
    margin: 2px 2px 2px 2px;
}
QScrollBar::handle:horizontal {
    background: #3a516c;
    border: 1px solid #4b6889;
    border-radius: 9px;
    min-width: 52px;
    margin: 3px;
}
QScrollBar::handle:horizontal:hover {
    background: #4a6788;
}
QScrollBar::handle:horizontal:pressed {
    background: #5b7ca2;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    background: #1a2430;
    border: 0;
    width: 16px;
    subcontrol-origin: margin;
}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
QStackedWidget {
    background: transparent;
    padding: 4px;
}
QPushButton {
    background: #223247;
    border: 1px solid #324b69;
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton:hover { background: #29405b; }
QPushButton:disabled { color: #7f8791; background: #1a2028; border-color: #27303b; }
QComboBox, QTextEdit, QPlainTextEdit, QLineEdit, QListWidget, QSpinBox, QDoubleSpinBox, QGroupBox, QTabWidget::pane {
    background: #0f141b;
    border: 1px solid #273342;
    border-radius: 10px;
}
QGroupBox#chat_runtime_box, QGroupBox#stt_runtime_box, QGroupBox#tts_runtime_box, QGroupBox#visual_reply_runtime_box {
    margin-top: 6px;
    padding: 8px;
}
QGroupBox#chat_runtime_box::title, QGroupBox#stt_runtime_box::title, QGroupBox#tts_runtime_box::title, QGroupBox#visual_reply_runtime_box::title {
    height: 0px;
    margin: 0px;
    padding: 0px;
}
QGroupBox#chat_runtime_box::indicator, QGroupBox#stt_runtime_box::indicator, QGroupBox#tts_runtime_box::indicator, QGroupBox#visual_reply_runtime_box::indicator {
    width: 0px;
    height: 0px;
}
QToolButton#runtime_section_header_button, QToolButton#chat_runtime_header_button, QToolButton#stt_runtime_header_button, QToolButton#tts_runtime_header_button, QToolButton#visual_reply_runtime_header_button {
    font-weight: 700;
    border-radius: 8px;
    padding: 6px 12px;
    text-align: left;
}
QToolButton#runtime_section_header_button, QToolButton#chat_runtime_header_button {
    color: #fff7ff;
    background: #21122f;
    border: 1px solid #ff3fbf;
}
QToolButton#runtime_section_header_button:hover, QToolButton#chat_runtime_header_button:hover { background: #351a55; }
QToolButton#runtime_section_header_button:checked, QToolButton#chat_runtime_header_button:checked { background: #291641; }
QToolButton#stt_runtime_header_button {
    color: #f0fdff;
    background: #09283a;
    border: 1px solid #00e5ff;
}
QToolButton#stt_runtime_header_button:hover { background: #0d3d59; }
QToolButton#stt_runtime_header_button:checked { background: #0b3148; }
QToolButton#tts_runtime_header_button {
    color: #fbf8ff;
    background: #1a1644;
    border: 1px solid #8b5cf6;
}
QToolButton#tts_runtime_header_button:hover { background: #2a2375; }
QToolButton#tts_runtime_header_button:checked { background: #211b5d; }
QToolButton#visual_reply_runtime_header_button {
    color: #fff8ed;
    background: #2d1730;
    border: 1px solid #ff9f1c;
}
QToolButton#visual_reply_runtime_header_button:hover { background: #4a254f; }
QToolButton#visual_reply_runtime_header_button:checked { background: #3a1d3d; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    color: #f2f5f9;
    padding: 4px 8px;
    selection-background-color: #4d8dff;
    selection-color: #ffffff;
}
QComboBox QLabel,
QComboBox QLineEdit,
QAbstractSpinBox QLineEdit {
    color: #f2f5f9;
    background: transparent;
    selection-background-color: #4d8dff;
    selection-color: #ffffff;
}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #b7c1ce;
}
QComboBox:disabled QLabel,
QComboBox:disabled QLineEdit,
QAbstractSpinBox:disabled QLineEdit {
    color: #b7c1ce;
}
QLineEdit[readOnly="true"], QComboBox[editable="true"] QLineEdit[readOnly="true"] {
    color: #f2f5f9;
}
QLineEdit::placeholder, QComboBox QLineEdit::placeholder {
    color: #8ea3b8;
}
QComboBox {
    padding-right: 30px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    background: #17212c;
    border-left: 1px solid #273342;
    border-top-right-radius: 10px;
    border-bottom-right-radius: 10px;
}
QComboBox::drop-down:hover {
    background: #223247;
}
QComboBox::drop-down:pressed {
    background: #29405b;
}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button, QSpinBox::up-button, QSpinBox::down-button {
    background: #17212c;
    border-left: 1px solid #324055;
    width: 18px;
}
QDoubleSpinBox::up-button, QSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    border-top-right-radius: 10px;
    border-bottom: 1px solid #324055;
}
QDoubleSpinBox::down-button, QSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    border-bottom-right-radius: 10px;
}
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover, QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #223247;
}
QDoubleSpinBox::up-arrow, QSpinBox::up-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #d8dee9;
}
QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #d8dee9;
}
QDoubleSpinBox::up-arrow:disabled, QSpinBox::up-arrow:disabled {
    border-bottom-color: #7f8791;
}
QDoubleSpinBox::down-arrow:disabled, QSpinBox::down-arrow:disabled {
    border-top-color: #7f8791;
}
QComboBox QAbstractItemView, QListWidget {
    background: #16202b;
    color: #f2f5f9;
    selection-background-color: #29405b;
    selection-color: #ffffff;
    border: 1px solid #324b69;
    border-radius: 8px;
    outline: 0;
    alternate-background-color: #1b2836;
}
QListWidget::viewport, QTextEdit::viewport, QPlainTextEdit::viewport {
    background: transparent;
    border-radius: 8px;
}
QComboBox QAbstractItemView::item, QListWidget::item {
    color: #f2f5f9;
    background: transparent;
    min-height: 24px;
    padding: 4px 8px;
}
QComboBox QAbstractItemView::item:selected, QListWidget::item:selected {
    color: #ffffff;
    background: #29405b;
}
QComboBox QAbstractItemView::item:hover, QListWidget::item:hover {
    color: #ffffff;
    background: #223247;
}
QMenu {
    background: #16202b;
    color: #f2f5f9;
    border: 1px solid #324b69;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    background: transparent;
    color: #f2f5f9;
    padding: 6px 24px 6px 10px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #29405b;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #7f8791;
    background: transparent;
}
QMenu::separator {
    height: 1px;
    background: #2c3a4b;
    margin: 6px 4px;
}
QTabBar::tab {
    background: #18202a;
    border: 1px solid #2a3544;
    padding: 8px 12px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
    margin-right: 4px;
}
QTabBar::tab:selected { background: #233245; }
QTabBar {
    background: #11161d;
    border: 0;
    qproperty-drawBase: 0;
}
QMainWindow::separator {
    background: #273342;
    width: 1px;
    height: 1px;
}
QMainWindow::separator:hover {
    background: #324b69;
}
QTabWidget#sensory_feedback_tabs::tab-bar,
QTabWidget#vseeface_tabs::tab-bar,
QTabWidget#musetalk_tabs::tab-bar,
QTabWidget#tts_runtime_addon_tabs::tab-bar,
QTabWidget#vam_setup_tabs::tab-bar,
QTabWidget#right_tabs::tab-bar {
    left: 0px;
}
QTabWidget#sensory_feedback_tabs::tab-bar {
    left: 0px;
}
QTabWidget#sensory_feedback_tabs QTabBar::tab,
QTabWidget#vseeface_tabs QTabBar::tab,
QTabWidget#musetalk_tabs QTabBar::tab,
QTabWidget#tts_runtime_addon_tabs QTabBar::tab,
QTabWidget#vam_setup_tabs QTabBar::tab,
QTabWidget#right_tabs QTabBar::tab {
    background: #17212c;
    border: 1px solid #273342;
    min-width: 0px;
    max-width: 16777215px;
    min-height: 0px;
    padding: 8px 14px;
    margin-right: 4px;
    margin-bottom: -1px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}
QTabWidget#sensory_feedback_tabs QTabBar::tab:!selected,
QTabWidget#vseeface_tabs QTabBar::tab:!selected,
QTabWidget#musetalk_tabs QTabBar::tab:!selected,
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:!selected,
QTabWidget#vam_setup_tabs QTabBar::tab:!selected,
QTabWidget#right_tabs QTabBar::tab:!selected {
    margin-top: 3px;
}
QTabWidget#sensory_feedback_tabs::pane,
QTabWidget#vseeface_tabs::pane,
QTabWidget#musetalk_tabs::pane,
QTabWidget#tts_runtime_addon_tabs::pane,
QTabWidget#vam_setup_tabs::pane,
QTabWidget#right_tabs::pane {
    top: -1px;
    background: #0f141b;
    border: 1px solid #273342;
    border-top-left-radius: 0px;
    border-top-right-radius: 0px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
    padding: 12px 10px 10px 10px;
}
QTabWidget#sensory_feedback_tabs QStackedWidget,
QTabWidget#vseeface_tabs QStackedWidget,
QTabWidget#musetalk_tabs QStackedWidget,
QTabWidget#tts_runtime_addon_tabs QStackedWidget,
QTabWidget#vam_setup_tabs QStackedWidget,
QTabWidget#right_tabs QStackedWidget {
    padding: 8px;
    background: transparent;
}
QTabWidget#sensory_feedback_tabs QTabBar::tab:selected,
QTabWidget#vseeface_tabs QTabBar::tab:selected,
QTabWidget#musetalk_tabs QTabBar::tab:selected,
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:selected,
QTabWidget#vam_setup_tabs QTabBar::tab:selected,
QTabWidget#right_tabs QTabBar::tab:selected {
    background: #0f141b;
    border-color: #273342;
    border-bottom-color: #0f141b;
    border-right: 1px solid #273342;
    margin-bottom: -1px;
    padding-bottom: 11px;
}
QTabWidget#sensory_feedback_tabs QTabBar::tab:hover,
QTabWidget#vseeface_tabs QTabBar::tab:hover,
QTabWidget#musetalk_tabs QTabBar::tab:hover,
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:hover,
QTabWidget#vam_setup_tabs QTabBar::tab:hover,
QTabWidget#right_tabs QTabBar::tab:hover {
    background: #223247;
}
QTabWidget#tts_runtime_addon_tabs::tab-bar {
    left: 0px;
}
QTabWidget#tts_runtime_addon_tabs::pane {
    top: -1px;
    border: 1px solid #324055;
    border-top-left-radius: 0px;
    border-top-right-radius: 8px;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
    padding: 8px;
}
QTabWidget#tts_runtime_addon_tabs QStackedWidget {
    padding: 4px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar {
    qproperty-expanding: false;
}
QTabWidget#tts_runtime_addon_tabs QTabBar::tab {
    width: 150px;
    min-width: 150px;
    max-width: 150px;
    min-height: 24px;
    padding: 5px 10px 6px 10px;
    margin-right: 1px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:!selected {
    margin-top: 2px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:selected {
    border-bottom-color: #0f141b;
    padding-bottom: 6px;
}
QTabWidget#host_settings_tabs QTabBar::tab,
QTabWidget#left_tabs QTabBar::tab {
    background: #18202a;
    border: 1px solid #273342;
    width: 62px;
    height: 54px;
    min-width: 62px;
    max-width: 62px;
    min-height: 54px;
    max-height: 54px;
    padding: 0px;
    text-align: center;
    margin-bottom: 4px;
    margin-right: 0px;
    border-top-left-radius: 10px;
    border-bottom-left-radius: 10px;
    border-top-right-radius: 0px;
    border-bottom-right-radius: 0px;
}
QTabWidget#host_settings_tabs QTabBar::tab {
    padding: 0px;
}
QTabWidget#left_tabs QTabBar::tab {
    padding: 0px;
}
QTabWidget#host_settings_tabs::pane,
QTabWidget#left_tabs::pane {
    margin-left: -1px;
    background: #0f141b;
    border: 1px solid #273342;
    border-top-left-radius: 0px;
    border-top-right-radius: 10px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
    padding: 6px;
}
QTabWidget#host_settings_tabs QStackedWidget,
QTabWidget#left_tabs QStackedWidget {
    padding: 0px;
    background: transparent;
}
QTabWidget#host_settings_tabs QTabBar::tab:selected,
QTabWidget#left_tabs QTabBar::tab:selected {
    background: #0f141b;
    border-right: 0px;
    margin-right: -1px;
    padding: 0px;
}
QTabWidget#host_settings_tabs QTabBar::tab:selected {
    padding: 0px;
}
QTabWidget#host_settings_tabs QTabBar::tab:hover,
QTabWidget#left_tabs QTabBar::tab:hover {
    background: #223247;
}
QTabWidget#host_settings_tabs QTabBar,
QTabWidget#left_tabs QTabBar {
    background: #0f141b;
    border: 0;
}
QTabWidget#host_settings_tabs QTabBar {
    margin-top: 0px;
    padding-top: 4px;
}
QTabWidget#left_tabs QTabBar {
    margin-top: 0px;
    padding-top: 4px;
}
QTabWidget#left_tabs::pane {
    margin-top: 0px;
    border-top-left-radius: 0px;
    border-top-right-radius: 10px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}
QTabWidget#host_settings_tabs::pane {
    border-radius: 0px;
    border-top-left-radius: 0px;
    border-top-right-radius: 10px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}
QMessageBox, QDialog {
    background: #11161d;
}
QMessageBox QLabel, QDialog QLabel {
    color: #e5e9f0;
}
QMessageBox QPushButton, QDialog QPushButton {
    min-width: 90px;
}
QGroupBox {
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
"""


def load_qss_stylesheet(qss_path: Path, fallback: str) -> str:
    try:
        value = qss_path.read_text(encoding="utf-8")
        if str(value or "").strip():
            return str(value)
    except Exception:
        pass
    return str(fallback or "")


def load_main_ui_stylesheet(ui_path: Path, fallback: str) -> str:
    try:
        tree = ET.parse(str(ui_path))
        root = tree.getroot()
        widget = root.find("./widget[@class='QMainWindow']")
        if widget is None:
            return str(fallback or "")
        for prop in widget.findall("./property[@name='styleSheet']"):
            string_node = prop.find("string")
            if string_node is None:
                continue
            value = str(string_node.text or "")
            if value.strip():
                return value
    except Exception:
        pass
    return str(fallback or "")


APP_STYLESHEET = load_qss_stylesheet(
    Path(__file__).resolve().parent / "styles" / "app.qss",
    APP_STYLESHEET_FALLBACK,
)

APP_THEME_PRESET_LABELS = {
    "light_gray": "Light Gray",
    "gray": "Gray",
    "dark_gray": "Dark Gray",
    "slate_blue": "Slate Blue",
    "warm_sand": "Warm Sand",
    "forest": "Forest",
    "ocean": "Ocean",
    "rose_smoke": "Rose Smoke",
    "midnight": "Midnight",
}

APP_THEME_PRESET_WIDGETS = (
    ("light_gray", "theme_light_gray_button", "theme_light_gray_edit"),
    ("gray", "theme_gray_button", "theme_gray_edit"),
    ("dark_gray", "theme_dark_gray_button", "theme_dark_gray_edit"),
    ("slate_blue", "theme_slate_blue_button", "theme_slate_blue_edit"),
    ("warm_sand", "theme_warm_sand_button", "theme_warm_sand_edit"),
    ("forest", "theme_forest_button", "theme_forest_edit"),
    ("ocean", "theme_ocean_button", "theme_ocean_edit"),
    ("rose_smoke", "theme_rose_smoke_button", "theme_rose_smoke_edit"),
    ("midnight", "theme_midnight_button", "theme_midnight_edit"),
)

DEFAULT_APP_THEME_PRESET = "dark_gray"

APP_THEME_STYLESHEET_BASE_TOKENS = {
    "#11161d": "window_bg",
    "#18202a": "panel_bg",
    "#131a23": "header_bg",
    "#1a2430": "scroll_button_bg",
    "#283342": "panel_border",
    "#243244": "header_border",
    "#273342": "surface_border",
    "#223247": "button_bg",
    "#324b69": "button_border",
    "#29405b": "button_hover",
    "#1a2028": "disabled_bg",
    "#27303b": "disabled_border",
    "#17212c": "spin_bg",
    "#324055": "spin_border",
    "#16202b": "menu_bg",
    "#2c3a4b": "menu_separator",
    "#2a3544": "tab_border",
    "#233245": "tab_selected_bg",
    "#3a516c": "scroll_handle_bg",
    "#4b6889": "scroll_handle_border",
    "#4a6788": "scroll_handle_hover",
    "#5b7ca2": "scroll_handle_pressed",
    "#4d8dff": "accent_bg",
    "#6ea4ff": "accent_border",
    "#6a95ff": "accent_border",
    "#0f141b": "field_bg",
    "#e5e9f0": "text",
    "#f2f5f9": "text_strong",
    "#7f8791": "text_disabled",
    "#b7c1ce": "text_muted",
    "#5b6675": "status_neutral_bg",
    "#8ea3b8": "text_muted",
    "#9fb3c8": "text_soft",
    "#cbd5e1": "text_soft",
    "#d8dee9": "text_title",
    "#dfe3e8": "text_title",
    "#81a1c1": "text_soft",
    "#88c0d0": "accent_info",
}

def resolveapp_theme_palette(preset_id=None):
    resolved_preset = normalize_app_theme_preset_id(
        preset_id if preset_id is not None else _runtime_config_get("ui_theme_preset", DEFAULT_APP_THEME_PRESET)
    )
    palette = dict(APP_THEME_PRESET_PALETTES.get(DEFAULT_APP_THEME_PRESET, {}) or {})
    palette.update(dict(APP_THEME_PRESET_PALETTES.get(resolved_preset, {}) or {}))
    palette.setdefault("scroll_button_bg", palette.get("header_bg", "#131a23"))
    palette.setdefault("scroll_handle_bg", palette.get("button_bg", "#3a516c"))
    palette.setdefault("scroll_handle_border", palette.get("button_border", "#4b6889"))
    palette.setdefault("scroll_handle_hover", palette.get("button_hover", "#4a6788"))
    palette.setdefault("scroll_handle_pressed", palette.get("tab_selected_bg", "#5b7ca2"))
    palette.setdefault("status_neutral_bg", palette.get("spin_border", palette.get("text_disabled", "#5b6675")))
    palette.setdefault("text_muted", palette.get("text_disabled", "#8ea3b8"))
    palette.setdefault("text_soft", palette.get("text", "#9fb3c8"))
    palette.setdefault("text_title", palette.get("text_strong", "#d8dee9"))
    palette.setdefault("accent_bg", palette.get("button_border", "#4d8dff"))
    palette.setdefault("accent_border", palette.get("tab_selected_bg", palette.get("button_border", "#6a95ff")))
    palette.setdefault("accent_info", palette.get("button_border", "#88c0d0"))
    return palette


def replace_theme_colors_in_stylesheet(stylesheet, palette):
    themed = str(stylesheet or "")
    if not themed.strip():
        return themed
    for source, token_name in APP_THEME_STYLESHEET_BASE_TOKENS.items():
        replacement = str(palette.get(token_name, source) or source)
        themed = themed.replace(source, replacement)
        themed = themed.replace(source.upper(), replacement)
    return themed


def canonical_theme_base_stylesheet(stylesheet):
    canonical = str(stylesheet or "")
    if not canonical.strip():
        return canonical
    token_base_sources = {}
    for source, token_name in APP_THEME_STYLESHEET_BASE_TOKENS.items():
        token_base_sources.setdefault(str(token_name or ""), str(source or ""))
    replacement_pairs = []
    for token_name, base_source in token_base_sources.items():
        if not token_name or not base_source:
            continue
        for preset_id in APP_THEME_PRESET_LABELS:
            themed_value = str(resolveapp_theme_palette(preset_id).get(token_name, "") or "").strip()
            if themed_value and themed_value.lower() != base_source.lower():
                replacement_pairs.append((themed_value, base_source))
    seen_pairs = set()
    for themed_value, base_source in replacement_pairs:
        pair_key = (themed_value.lower(), base_source.lower())
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        canonical = re.sub(re.escape(themed_value), base_source, canonical, flags=re.IGNORECASE)
    return canonical






APP_THEME_PRESET_PALETTES = {
    "light_gray": {
        "window_bg": "#e7ebef",
        "panel_bg": "#f5f6f8",
        "header_bg": "#eef1f4",
        "panel_border": "#b9bec7",
        "header_border": "#c5cad2",
        "surface_border": "#c3c9d1",
        "button_bg": "#d8dde4",
        "button_border": "#aab2bc",
        "button_hover": "#cfd6de",
        "disabled_bg": "#dde1e6",
        "disabled_border": "#c2c8cf",
        "spin_bg": "#d7dde4",
        "spin_border": "#aab2bc",
        "menu_bg": "#edf1f5",
        "menu_separator": "#c7ced6",
        "tab_border": "#bcc4cd",
        "tab_selected_bg": "#dce2e9",
        "field_bg": "#ffffff",
        "preview_bg": "#f3f5f8",
        "text": "#20242a",
        "text_strong": "#111418",
        "text_disabled": "#717882",
    },
    "gray": {
        "window_bg": "#737780",
        "panel_bg": "#8b8e95",
        "header_bg": "#81858c",
        "panel_border": "#70737a",
        "header_border": "#6b6f76",
        "surface_border": "#7b7f87",
        "button_bg": "#d3d5d9",
        "button_border": "#7b7f87",
        "button_hover": "#c2c6cc",
        "disabled_bg": "#767981",
        "disabled_border": "#666a72",
        "spin_bg": "#c8ccd1",
        "spin_border": "#838892",
        "menu_bg": "#eceef1",
        "menu_separator": "#9ca1a9",
        "tab_border": "#6f737b",
        "tab_selected_bg": "#a0a4ab",
        "field_bg": "#eceef1",
        "preview_bg": "#e2e5ea",
        "text": "#1f2227",
        "text_strong": "#16181c",
        "text_disabled": "#5a5e66",
    },
    "dark_gray": {
        "window_bg": "#11161d",
        "panel_bg": "#18202a",
        "header_bg": "#131a23",
        "panel_border": "#283342",
        "header_border": "#243244",
        "surface_border": "#273342",
        "button_bg": "#223247",
        "button_border": "#324b69",
        "button_hover": "#29405b",
        "disabled_bg": "#1a2028",
        "disabled_border": "#27303b",
        "spin_bg": "#17212c",
        "spin_border": "#324055",
        "menu_bg": "#16202b",
        "menu_separator": "#2c3a4b",
        "tab_border": "#2a3544",
        "tab_selected_bg": "#233245",
        "field_bg": "#0f141b",
        "preview_bg": "#18202a",
        "text": "#e5e9f0",
        "text_strong": "#f2f5f9",
        "text_disabled": "#7f8791",
    },
    "slate_blue": {
        "window_bg": "#566376",
        "panel_bg": "#6d7789",
        "header_bg": "#627082",
        "panel_border": "#556071",
        "header_border": "#5c6778",
        "surface_border": "#6d7c93",
        "button_bg": "#dbe5f5",
        "button_border": "#6d7c93",
        "button_hover": "#cbd8ed",
        "disabled_bg": "#627081",
        "disabled_border": "#4d596b",
        "spin_bg": "#d4def0",
        "spin_border": "#6d7c93",
        "menu_bg": "#edf3fd",
        "menu_separator": "#8291a7",
        "tab_border": "#596578",
        "tab_selected_bg": "#7b8799",
        "field_bg": "#edf3fd",
        "preview_bg": "#dfe7f4",
        "text": "#172133",
        "text_strong": "#111824",
        "text_disabled": "#576579",
    },
    "warm_sand": {
        "window_bg": "#b9aa93",
        "panel_bg": "#c6b8a2",
        "header_bg": "#b7a690",
        "panel_border": "#9f927f",
        "header_border": "#a89882",
        "surface_border": "#a28f72",
        "button_bg": "#f4ead9",
        "button_border": "#a28f72",
        "button_hover": "#eadcbf",
        "disabled_bg": "#b7a890",
        "disabled_border": "#978772",
        "spin_bg": "#ebdfc9",
        "spin_border": "#a28f72",
        "menu_bg": "#fbf4ea",
        "menu_separator": "#b39f82",
        "tab_border": "#998a78",
        "tab_selected_bg": "#d2c2a8",
        "field_bg": "#fbf4ea",
        "preview_bg": "#efe2cf",
        "text": "#2f2417",
        "text_strong": "#2a2117",
        "text_disabled": "#6d6253",
    },
    "forest": {
        "window_bg": "#263830",
        "panel_bg": "#31463d",
        "header_bg": "#293d34",
        "panel_border": "#486256",
        "header_border": "#42594f",
        "surface_border": "#678677",
        "button_bg": "#496457",
        "button_border": "#678677",
        "button_hover": "#58786a",
        "disabled_bg": "#24342d",
        "disabled_border": "#3d554b",
        "spin_bg": "#3b5247",
        "spin_border": "#678677",
        "menu_bg": "#3a5147",
        "menu_separator": "#587468",
        "tab_border": "#42594f",
        "tab_selected_bg": "#415a4d",
        "field_bg": "#3a5147",
        "preview_bg": "#4a6457",
        "text": "#edf4ef",
        "text_strong": "#f5fbf6",
        "text_disabled": "#a4b6aa",
    },
    "ocean": {
        "window_bg": "#2c4e5e",
        "panel_bg": "#355d70",
        "header_bg": "#304f60",
        "panel_border": "#4a7f97",
        "header_border": "#426f84",
        "surface_border": "#69a1bc",
        "button_bg": "#47778e",
        "button_border": "#69a1bc",
        "button_hover": "#5689a2",
        "disabled_bg": "#2a4656",
        "disabled_border": "#3f6b81",
        "spin_bg": "#406d81",
        "spin_border": "#69a1bc",
        "menu_bg": "#3f6e82",
        "menu_separator": "#5f90a6",
        "tab_border": "#436f85",
        "tab_selected_bg": "#4a7c92",
        "field_bg": "#3f6e82",
        "preview_bg": "#4e8198",
        "text": "#eef8fb",
        "text_strong": "#ffffff",
        "text_disabled": "#b5c9d3",
    },
    "rose_smoke": {
        "window_bg": "#67575c",
        "panel_bg": "#7b686d",
        "header_bg": "#6f5d62",
        "panel_border": "#9a858b",
        "header_border": "#8e797f",
        "surface_border": "#bca4aa",
        "button_bg": "#a2868d",
        "button_border": "#bca4aa",
        "button_hover": "#b0939b",
        "disabled_bg": "#65555a",
        "disabled_border": "#896f77",
        "spin_bg": "#8c767d",
        "spin_border": "#bca4aa",
        "menu_bg": "#8c767d",
        "menu_separator": "#a28990",
        "tab_border": "#8b757d",
        "tab_selected_bg": "#947e86",
        "field_bg": "#8c767d",
        "preview_bg": "#a18b93",
        "text": "#fff5f7",
        "text_strong": "#ffffff",
        "text_disabled": "#d7c5ca",
    },
    "midnight": {
        "window_bg": "#10141b",
        "panel_bg": "#151b24",
        "header_bg": "#111720",
        "panel_border": "#283244",
        "header_border": "#223048",
        "surface_border": "#40536f",
        "button_bg": "#253247",
        "button_border": "#40536f",
        "button_hover": "#31425d",
        "disabled_bg": "#121820",
        "disabled_border": "#253347",
        "spin_bg": "#1a2330",
        "spin_border": "#40536f",
        "menu_bg": "#1d2837",
        "menu_separator": "#34465f",
        "tab_border": "#28374b",
        "tab_selected_bg": "#233245",
        "field_bg": "#1d2837",
        "preview_bg": "#253247",
        "text": "#edf2fb",
        "text_strong": "#ffffff",
        "text_disabled": "#9fa9b9",
    },
}


def normalize_app_theme_preset_id(preset_id):
    normalized = str(preset_id or "").strip().lower()
    if normalized in APP_THEME_PRESET_LABELS:
        return normalized
    return DEFAULT_APP_THEME_PRESET


def build_app_stylesheet_for_preset(preset_id):
    palette = resolveapp_theme_palette(preset_id)
    return replace_theme_colors_in_stylesheet(APP_STYLESHEET, palette)


def app_theme_palette(preset_id=None):
    return resolveapp_theme_palette(preset_id)
