"""Optional, local dictionary support for the QML conversation composer."""
from functools import lru_cache
import re

from PySide6 import QtCore, QtGui


_WORDS = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
_SKIP = re.compile(r"https?://\S+|www\.\S+|\S+@\S+|\b\w*[\d_]\w*\b", re.UNICODE)


@lru_cache(maxsize=8)
def load_dictionary(language):
    language = str(language or "en_US").strip() or "en_US"
    try:
        import enchant
    except (ImportError, OSError) as error:
        return None, f"Spellcheck unavailable: PyEnchant could not load ({error})."
    try:
        return enchant.Dict(language), ""
    except Exception:
        return None, f"Spellcheck unavailable: dictionary '{language}' is not installed."


def check_text(text, language):
    dictionary, message = load_dictionary(language)
    result = dict(available=dictionary is not None, message=message, misspellings=[])
    if dictionary is None:
        return result
    ignored = list(_SKIP.finditer(text))
    ignored_index = 0
    previous_index = 0
    qt_start = 0
    checked = {}
    try:
        for match in _WORDS.finditer(text):
            word = match.group()
            # Count each intervening text segment once, including surrogate pairs.
            qt_start += len(text[previous_index:match.start()].encode("utf-16-le")) // 2
            previous_index = match.start()
            if len(word) < 2 or len(word) > 80 or word.isupper():
                continue
            while ignored_index < len(ignored) and ignored[ignored_index].end() <= match.start():
                ignored_index += 1
            if ignored_index < len(ignored) and ignored[ignored_index].start() <= match.start():
                continue
            if word not in checked:
                checked[word] = dictionary.check(word)
            if not checked[word]:
                result["misspellings"].append(dict(
                    start=qt_start,
                    length=len(word.encode("utf-16-le")) // 2, word=word))
    except Exception:
        return dict(available=False, message=f"Spellcheck unavailable: dictionary '{language}' failed.",
                    misspellings=[])
    return result


def suggestions(word, language):
    dictionary, _message = load_dictionary(language)
    if dictionary is None or not _WORDS.fullmatch(word) or len(word) > 80:
        return []
    try:
        return list(dict.fromkeys(str(value) for value in dictionary.suggest(word)))[:6]
    except Exception:
        return []


def replace_word(editor, original, start, length, replacement):
    """Commit one undoable native edit; never overwrite a changed draft or IME preedit."""
    if (editor is None or editor.property("text") != original
            or editor.property("readOnly") or not editor.property("enabled")
            or editor.property("inputMethodComposing")
            or start < 0 or length <= 0
            or start + length > len(original.encode("utf-16-le")) // 2):
        return False
    if not QtCore.QMetaObject.invokeMethod(editor, "select", QtCore.Qt.DirectConnection,
                                          QtCore.Q_ARG(int, start), QtCore.Q_ARG(int, start + length)):
        return False
    event = QtGui.QInputMethodEvent()
    event.setCommitString(replacement)
    QtCore.QCoreApplication.sendEvent(editor, event)
    return bool(event.isAccepted())
