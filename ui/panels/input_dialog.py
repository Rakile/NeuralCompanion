"""Small text input dialog used by the Qt app."""

from PySide6 import QtWidgets


class QtInputDialog(QtWidgets.QDialog):
    def __init__(self, title, label, parent=None, default_text=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(320, 120)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(label))
        self.line_edit = QtWidgets.QLineEdit()
        self.line_edit.setText(str(default_text or ""))
        layout.addWidget(self.line_edit)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def get_text(title, label, parent=None, default_text=""):
        dialog = QtInputDialog(title, label, parent, default_text=default_text)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            return dialog.line_edit.text().strip()
        return None
