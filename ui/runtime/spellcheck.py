from __future__ import annotations

import importlib
import re
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']{2,}")
_DICT_CACHE: dict[str, Any | None] = {}
DEFAULT_LANGUAGE = "en_US"


class ChatMessageInput(QtWidgets.QPlainTextEdit):
    sendRequested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(False)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setMinimumHeight(32)
        self.setMaximumHeight(76)
        self.setFixedHeight(34)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.document().setDocumentMargin(4)
        self.textChanged.connect(self._sync_height_to_content)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(str(text or ""))

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            modifiers = event.modifiers()
            if not bool(modifiers & QtCore.Qt.ShiftModifier):
                event.accept()
                self.sendRequested.emit()
                return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        menu = self.createStandardContextMenu()
        dictionary = getattr(self, "_nc_spellcheck_dictionary", None)
        word_info = self._word_at_position(event.pos())
        if dictionary is not None and word_info is not None:
            start, end, word = word_info
            try:
                misspelled = not bool(dictionary.check(word))
            except Exception:
                misspelled = False
            if misspelled:
                suggestions = []
                try:
                    suggestions = [str(item) for item in dictionary.suggest(word)[:6]]
                except Exception:
                    suggestions = []
                first_action = menu.actions()[0] if menu.actions() else None
                menu.insertSeparator(first_action)
                if suggestions:
                    for suggestion in reversed(suggestions):
                        action = QtGui.QAction(f"Replace with {suggestion}", menu)
                        action.triggered.connect(
                            lambda _checked=False, value=suggestion, s=start, e=end: self._replace_word(s, e, value)
                        )
                        menu.insertAction(first_action, action)
                else:
                    action = QtGui.QAction(f"No suggestions for {word}", menu)
                    action.setEnabled(False)
                    menu.insertAction(first_action, action)
        menu.exec(event.globalPos())

    def _sync_height_to_content(self) -> None:
        try:
            line_count = max(1, min(3, int(self.document().blockCount())))
            height = 28 + ((line_count - 1) * 18)
            self.setFixedHeight(max(34, min(76, height)))
        except Exception:
            pass

    def _word_at_position(self, point: QtCore.QPoint) -> tuple[int, int, str] | None:
        return _word_at_text_edit_position(self, point)

    def _replace_word(self, start: int, end: int, value: str) -> None:
        _replace_text_edit_word(self, start, end, value)


def replace_line_edit_with_chat_input(line_edit: Any) -> ChatMessageInput | None:
    if isinstance(line_edit, ChatMessageInput):
        return line_edit
    if not isinstance(line_edit, QtWidgets.QLineEdit):
        return None
    parent = line_edit.parentWidget()
    if parent is None:
        return None
    layout = _find_layout_containing_widget(parent.layout(), line_edit)
    if layout is None:
        return None
    replacement = ChatMessageInput(parent)
    replacement.setObjectName(str(line_edit.objectName() or "chat_message_input"))
    replacement.setPlaceholderText(str(line_edit.placeholderText() or "Type a message..."))
    replacement.setToolTip(str(line_edit.toolTip() or ""))
    replacement.setEnabled(line_edit.isEnabled())
    replacement.setHidden(line_edit.isHidden())
    replacement.setStyleSheet(str(line_edit.styleSheet() or ""))
    replacement.setSizePolicy(line_edit.sizePolicy())
    layout.replaceWidget(line_edit, replacement)
    line_edit.setObjectName(f"{replacement.objectName()}_legacy")
    line_edit.hide()
    line_edit.deleteLater()
    return replacement


def _find_layout_containing_widget(layout: QtWidgets.QLayout | None, widget: QtWidgets.QWidget) -> QtWidgets.QLayout | None:
    if layout is None:
        return None
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if item.widget() is widget:
            return layout
        nested_layout = item.layout()
        if nested_layout is not None:
            found = _find_layout_containing_widget(nested_layout, widget)
            if found is not None:
                return found
    return None


def available_languages() -> list[str]:
    try:
        import enchant  # type: ignore

        return sorted(str(item) for item in enchant.list_languages())
    except Exception:
        return []


def dependency_status() -> dict[str, Any]:
    try:
        import enchant  # type: ignore
    except Exception as exc:
        return {
            "available": False,
            "installable": True,
            "message": f"PyEnchant is not installed in this NC environment ({exc}).",
        }
    try:
        languages = sorted(str(item) for item in enchant.list_languages())
    except Exception as exc:
        return {
            "available": False,
            "installable": False,
            "message": f"PyEnchant is installed, but dictionaries are not available ({exc}).",
        }
    if not languages:
        return {
            "available": False,
            "installable": False,
            "message": "PyEnchant is installed, but no dictionaries are visible in this NC environment.",
        }
    return {
        "available": True,
        "installable": False,
        "message": "Spellcheck is available.",
        "languages": languages,
    }


def clear_spellcheck_cache() -> None:
    importlib.invalidate_caches()
    _DICT_CACHE.clear()


def _runtime_spellcheck_settings(enabled: bool | None = None, language: str | None = None) -> tuple[bool, str]:
    if enabled is not None:
        resolved_enabled = bool(enabled)
    else:
        resolved_enabled = True
        try:
            from ui.runtime.engine_access import engine_module

            resolved_enabled = bool((engine_module().RUNTIME_CONFIG or {}).get("spellcheck_enabled", True))
        except Exception:
            resolved_enabled = True
    if language is not None:
        resolved_language = str(language or DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE
    else:
        resolved_language = DEFAULT_LANGUAGE
        try:
            from ui.runtime.engine_access import engine_module

            resolved_language = str((engine_module().RUNTIME_CONFIG or {}).get("spellcheck_language", DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE
        except Exception:
            resolved_language = DEFAULT_LANGUAGE
    return resolved_enabled, resolved_language


def _load_dictionary(language: str = DEFAULT_LANGUAGE) -> Any | None:
    key = str(language or DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE
    if key in _DICT_CACHE:
        return _DICT_CACHE[key]
    try:
        import enchant  # type: ignore

        candidates = [key, DEFAULT_LANGUAGE, "en_GB", "en"]
        available = set()
        try:
            available = {str(item) for item in enchant.list_languages()}
        except Exception:
            available = set()
        for candidate in candidates:
            try:
                if available and candidate not in available:
                    continue
                dictionary = enchant.Dict(candidate)
                _DICT_CACHE[key] = dictionary
                return dictionary
            except Exception:
                continue
    except Exception:
        pass
    _DICT_CACHE[key] = None
    return None


def _word_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for match in _WORD_RE.finditer(str(text or "")):
        word = match.group(0).strip("'")
        if _should_check_word(word):
            spans.append((match.start(), match.end(), word))
    return spans


def _should_check_word(word: str) -> bool:
    value = str(word or "").strip()
    if len(value) <= 2:
        return False
    if any(ch.isdigit() for ch in value):
        return False
    if value.isupper():
        return False
    return True


def _misspelled_words(text: str, dictionary: Any | None, *, limit: int = 8) -> list[str]:
    if dictionary is None:
        return []
    words: list[str] = []
    seen = set()
    for _start, _end, word in _word_spans(text):
        lowered = word.lower()
        if lowered in seen:
            continue
        try:
            ok = bool(dictionary.check(word))
        except Exception:
            ok = True
        if not ok:
            seen.add(lowered)
            words.append(word)
            if len(words) >= limit:
                break
    return words


def _qt_offset_from_python_index(text: str, index: int) -> int:
    prefix = str(text or "")[: max(0, int(index))]
    return len(prefix.encode("utf-16-le")) // 2


def _python_index_from_qt_offset(text: str, offset: int) -> int:
    value = str(text or "")
    target = max(0, int(offset))
    units = 0
    for index, char in enumerate(value):
        next_units = units + (len(char.encode("utf-16-le")) // 2)
        if next_units > target:
            return index
        units = next_units
    return len(value)


def _word_at_text_edit_position(widget: QtWidgets.QPlainTextEdit | QtWidgets.QTextEdit, point: QtCore.QPoint) -> tuple[int, int, str] | None:
    cursor = widget.cursorForPosition(point)
    block = cursor.block()
    block_text = block.text()
    block_position = int(block.position())
    index = _python_index_from_qt_offset(block_text, int(cursor.position()) - block_position)
    for start, end, word in _word_spans(block_text):
        if start <= index <= end:
            return (
                block_position + _qt_offset_from_python_index(block_text, start),
                block_position + _qt_offset_from_python_index(block_text, end),
                word,
            )
    return None


def _replace_text_edit_word(widget: QtWidgets.QPlainTextEdit | QtWidgets.QTextEdit, start: int, end: int, value: str) -> None:
    cursor = QtGui.QTextCursor(widget.document())
    cursor.setPosition(int(start))
    cursor.setPosition(int(end), QtGui.QTextCursor.KeepAnchor)
    cursor.insertText(str(value))
    widget.setTextCursor(cursor)


class SpellCheckHighlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, document: QtGui.QTextDocument, dictionary: Any):
        super().__init__(document)
        self._dictionary = dictionary
        self._format = QtGui.QTextCharFormat()
        self._format.setUnderlineColor(QtGui.QColor("#ff6b6b"))
        self._format.setUnderlineStyle(QtGui.QTextCharFormat.SpellCheckUnderline)

    def highlightBlock(self, text: str) -> None:
        for start, end, word in _word_spans(text):
            try:
                ok = bool(self._dictionary.check(word))
            except Exception:
                ok = True
            if not ok:
                self.setFormat(start, end - start, self._format)


class SpellCheckLineEditHelper(QtCore.QObject):
    def __init__(self, line_edit: QtWidgets.QLineEdit, dictionary: Any):
        super().__init__(line_edit)
        self._line_edit = line_edit
        self._dictionary = dictionary
        self._base_tooltip = str(line_edit.toolTip() or "").strip()
        self._base_stylesheet = str(line_edit.styleSheet() or "")
        self._previous_context_policy = line_edit.contextMenuPolicy()
        icon = line_edit.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning)
        self._warning_action = line_edit.addAction(icon, QtWidgets.QLineEdit.TrailingPosition)
        self._warning_action.setVisible(False)
        line_edit.textChanged.connect(self._update_tooltip)
        line_edit.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        line_edit.customContextMenuRequested.connect(self._show_context_menu)
        self._update_tooltip(line_edit.text())

    def _update_tooltip(self, text: str) -> None:
        misses = _misspelled_words(text, self._dictionary, limit=5)
        base = self._base_tooltip or "Type a chat message. Press Enter or Send to queue it."
        if misses:
            message = "Possible spelling issue(s): " + ", ".join(misses)
            self._line_edit.setToolTip(base + "\n" + message)
            self._warning_action.setToolTip(message + "\nRight-click the word for suggestions.")
            self._warning_action.setVisible(True)
            self._line_edit.setStyleSheet(
                self._base_stylesheet
                + "\nQLineEdit { border: 1px solid #ff6b6b; padding-right: 22px; }"
            )
        else:
            self._line_edit.setToolTip(base)
            self._warning_action.setVisible(False)
            self._line_edit.setStyleSheet(self._base_stylesheet)

    def _show_context_menu(self, point: QtCore.QPoint) -> None:
        menu = self._line_edit.createStandardContextMenu()
        word_info = self._word_at_point(point)
        if word_info is not None:
            start, end, word = word_info
            try:
                misspelled = not bool(self._dictionary.check(word))
            except Exception:
                misspelled = False
            if misspelled:
                suggestions = []
                try:
                    suggestions = [str(item) for item in self._dictionary.suggest(word)[:6]]
                except Exception:
                    suggestions = []
                menu.insertSeparator(menu.actions()[0] if menu.actions() else None)
                if suggestions:
                    for suggestion in reversed(suggestions):
                        action = QtGui.QAction(f"Replace with {suggestion}", menu)
                        action.triggered.connect(
                            lambda _checked=False, value=suggestion, s=start, e=end: self._replace_word(s, e, value)
                        )
                        menu.insertAction(menu.actions()[0] if menu.actions() else None, action)
                else:
                    action = QtGui.QAction(f"No suggestions for {word}", menu)
                    action.setEnabled(False)
                    menu.insertAction(menu.actions()[0] if menu.actions() else None, action)
        menu.exec(self._line_edit.mapToGlobal(point))

    def _word_at_point(self, point: QtCore.QPoint) -> tuple[int, int, str] | None:
        try:
            index = int(self._line_edit.cursorPositionAt(point))
        except Exception:
            index = int(self._line_edit.cursorPosition())
        text = self._line_edit.text()
        for start, end, word in _word_spans(text):
            if start <= index <= end:
                return start, end, word
        return None

    def _replace_word(self, start: int, end: int, value: str) -> None:
        text = self._line_edit.text()
        self._line_edit.setText(text[:start] + value + text[end:])
        self._line_edit.setCursorPosition(start + len(value))


def attach_spellcheck(widget: Any, language: str | None = None, *, enabled: bool | None = None) -> bool:
    resolved_enabled, resolved_language = _runtime_spellcheck_settings(enabled=enabled, language=language)
    if not resolved_enabled:
        detach_spellcheck(widget)
        return False
    dictionary = _load_dictionary(resolved_language)
    if dictionary is None or widget is None:
        detach_spellcheck(widget)
        return False
    if isinstance(widget, (QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
        current_language = str(getattr(widget, "_nc_spellcheck_language", "") or "")
        if getattr(widget, "_nc_spellcheck_highlighter", None) is not None and current_language == resolved_language:
            setattr(widget, "_nc_spellcheck_dictionary", dictionary)
            return True
        detach_spellcheck(widget)
        highlighter = SpellCheckHighlighter(widget.document(), dictionary)
        setattr(widget, "_nc_spellcheck_highlighter", highlighter)
        setattr(widget, "_nc_spellcheck_dictionary", dictionary)
        setattr(widget, "_nc_spellcheck_language", resolved_language)
        tooltip = str(widget.toolTip() or "").strip()
        if tooltip:
            widget.setToolTip(tooltip + "\nSpellcheck is enabled.")
        else:
            widget.setToolTip("Spellcheck is enabled.")
        return True
    if isinstance(widget, QtWidgets.QLineEdit):
        current_language = str(getattr(widget, "_nc_spellcheck_language", "") or "")
        if getattr(widget, "_nc_spellcheck_helper", None) is not None and current_language == resolved_language:
            return True
        detach_spellcheck(widget)
        helper = SpellCheckLineEditHelper(widget, dictionary)
        setattr(widget, "_nc_spellcheck_helper", helper)
        setattr(widget, "_nc_spellcheck_language", resolved_language)
        return True
    return False


def detach_spellcheck(widget: Any) -> None:
    highlighter = getattr(widget, "_nc_spellcheck_highlighter", None)
    if highlighter is not None:
        try:
            highlighter.setDocument(None)
        except Exception:
            pass
    helper = getattr(widget, "_nc_spellcheck_helper", None)
    if helper is not None:
        try:
            helper.deleteLater()
        except Exception:
            pass
    for attr_name in ("_nc_spellcheck_highlighter", "_nc_spellcheck_dictionary", "_nc_spellcheck_helper", "_nc_spellcheck_language"):
        try:
            delattr(widget, attr_name)
        except Exception:
            pass


def refresh_spellcheck(widget: Any, language: str | None = None, *, enabled: bool | None = None) -> bool:
    return attach_spellcheck(widget, language=language, enabled=enabled)


def add_spellcheck_suggestions_to_menu(widget: Any, menu: QtWidgets.QMenu, point: QtCore.QPoint) -> bool:
    if not isinstance(widget, (QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
        return False
    try:
        if bool(widget.isReadOnly()):
            return False
    except Exception:
        return False
    dictionary = getattr(widget, "_nc_spellcheck_dictionary", None)
    if dictionary is None:
        return False
    word_info = _word_at_text_edit_position(widget, point)
    if word_info is None:
        return False
    start, end, word = word_info
    try:
        misspelled = not bool(dictionary.check(word))
    except Exception:
        misspelled = False
    if not misspelled:
        return False
    suggestions = []
    try:
        suggestions = [str(item) for item in dictionary.suggest(word)[:6]]
    except Exception:
        suggestions = []
    first_action = menu.actions()[0] if menu.actions() else None
    menu.insertSeparator(first_action)
    if suggestions:
        for suggestion in reversed(suggestions):
            action = QtGui.QAction(f"Replace with {suggestion}", menu)
            action.triggered.connect(
                lambda _checked=False, value=suggestion, s=start, e=end: _replace_text_edit_word(widget, s, e, value)
            )
            menu.insertAction(first_action, action)
    else:
        action = QtGui.QAction(f"No suggestions for {word}", menu)
        action.setEnabled(False)
        menu.insertAction(first_action, action)
    return True
