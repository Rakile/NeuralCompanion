"""Request-local drop presentation; never owns or writes capture settings."""
from __future__ import annotations

import threading
from copy import deepcopy
from pathlib import Path


class DropCapture:
    def __init__(self, inspection_id: int, target: dict, *, deadline: float) -> None:
        self.inspection_id = inspection_id
        self.target = deepcopy(target)
        self.deadline = deadline
        self._lock = threading.RLock()
        self._active = True
        self._submitted = False
        self._trace_id = ''
        self._image_path = ''

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def submitted(self, inspection_id: int, *, trace_id: str = '', image_path: str = '') -> None:
        with self._lock:
            if self._active and inspection_id == self.inspection_id:
                self._submitted = True
                self._trace_id = trace_id
                self._image_path = str(Path(image_path)) if image_path else self._image_path

    def response_completed(self, receipts: list[dict]) -> bool:
        with self._lock:
            if not self._active or not self._submitted:
                return False
            return any(
                (self._trace_id and row.get('trace_id') == self._trace_id)
                or (self._image_path and row.get('image_path') and str(Path(row['image_path'])) == self._image_path)
                for row in receipts if isinstance(row, dict))

    def finish(self, inspection_id: int) -> bool:
        with self._lock:
            if not self._active or inspection_id != self.inspection_id:
                return False
            self._active = False
            return True
