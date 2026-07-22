from __future__ import annotations

import os
import sys
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6 import QtWidgets

from ui.runtime import spellcheck


class _Dictionary:
    def check(self, _word: str) -> bool:
        return True


def test_text_edit_spellcheck_tooltip_is_idempotent_and_restored_on_detach() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = QtWidgets.QPlainTextEdit()
    widget.setToolTip("Original editor help.")
    original_loader = spellcheck._load_dictionary
    try:
        spellcheck._load_dictionary = lambda _language: _Dictionary()
        for _ in range(12):
            assert spellcheck.attach_spellcheck(widget, language="en_US", enabled=True)
            assert widget.toolTip() == "Original editor help."
            spellcheck.detach_spellcheck(widget)
            assert widget.toolTip() == "Original editor help."
    finally:
        spellcheck._load_dictionary = original_loader
        widget.deleteLater()
        app.processEvents()


def main() -> int:
    test_text_edit_spellcheck_tooltip_is_idempotent_and_restored_on_detach()
    print("spellcheck tooltip smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
