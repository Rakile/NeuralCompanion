"""Persistent presentation rows for conversation ListViews.

History and draft APIs remain list-valued. This model only translates their
projections into Qt row/data notifications without resetting visible delegates.
"""
from difflib import SequenceMatcher
from PySide6 import QtCore


class ConversationListModel(QtCore.QAbstractListModel):
    ModelDataRole = QtCore.Qt.UserRole + 1
    rowsUpdated = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    def roleNames(self):
        return {self.ModelDataRole: b'modelData'}

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        if role == self.ModelDataRole:
            return dict(self._rows[index.row()])
        if role == QtCore.Qt.DisplayRole:
            return str(self._rows[index.row()].get('content') or '')
        return None

    @QtCore.Slot(int, result='QVariantMap')
    def get(self, index):
        return dict(self._rows[index]) if 0 <= index < len(self._rows) else {}

    def _update_data(self, start, rows):
        changed = []
        for offset, row in enumerate(rows):
            index = start + offset
            if self._rows[index] != row:
                self._rows[index] = row
                changed.append(index)
        if changed:
            self.dataChanged.emit(self.index(changed[0]), self.index(changed[-1]),
                                  [self.ModelDataRole, QtCore.Qt.DisplayRole])
        return bool(changed)

    def update_row(self, index, row):
        """Publish a live draft keystroke without rescanning the transcript."""
        if 0 <= index < len(self._rows) and self._update_data(index, [dict(row)]):
            self.rowsUpdated.emit()

    def update_rows(self, rows):
        rows = [dict(row) for row in rows]
        if rows == self._rows:
            return
        old_keys = [str(row.get('messageId') or f'row:{i}') for i, row in enumerate(self._rows)]
        new_keys = [str(row.get('messageId') or f'row:{i}') for i, row in enumerate(rows)]
        # Work backwards so each opcode keeps its original row coordinates.
        for tag, start, end, new_start, new_end in reversed(
                SequenceMatcher(None, old_keys, new_keys, autojunk=False).get_opcodes()):
            if tag == 'equal':
                self._update_data(start, rows[new_start:new_end])
                continue
            # Canonical saves may reassign IDs without changing row positions.
            # Retain that span's delegates instead of removing and recreating it.
            common = min(end - start, new_end - new_start)
            self._update_data(start, rows[new_start:new_start + common])
            if end - start > common:
                self.beginRemoveRows(QtCore.QModelIndex(), start + common, end - 1)
                del self._rows[start + common:end]
                self.endRemoveRows()
            if new_end - new_start > common:
                extra = rows[new_start + common:new_end]
                self.beginInsertRows(QtCore.QModelIndex(), start + common, start + common + len(extra) - 1)
                self._rows[start + common:start + common] = extra
                self.endInsertRows()
        self.rowsUpdated.emit()
