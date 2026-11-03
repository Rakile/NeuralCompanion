"""Bounded ownership cache for prepared Audio Story chapter payloads."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True)
class ChapterCacheKey:
    project_id: str
    manifest_revision: int
    chapter_id: str


class ChapterWorkingSet:
    def __init__(self, *, capacity: int = 2):
        self._capacity = max(1, int(capacity))
        self._payloads: OrderedDict[ChapterCacheKey, object] = OrderedDict()

    def __len__(self) -> int:
        return len(self._payloads)

    def keys(self) -> tuple[ChapterCacheKey, ...]:
        return tuple(self._payloads)

    def get(self, key: ChapterCacheKey) -> object | None:
        payload = self._payloads.get(key)
        if payload is not None:
            self._payloads.move_to_end(key)
        return payload

    def put(
        self,
        key: ChapterCacheKey,
        payload: object,
        *,
        protected_chapter_id: str = "",
    ) -> None:
        self._payloads[key] = payload
        self._payloads.move_to_end(key)
        protected = str(protected_chapter_id or "")
        while len(self._payloads) > self._capacity:
            evicted = False
            for candidate in tuple(self._payloads):
                if candidate.chapter_id == protected:
                    continue
                del self._payloads[candidate]
                evicted = True
                break
            if not evicted:
                self._payloads.popitem(last=False)

    def invalidate(self, project_id: str, manifest_revision: int) -> None:
        expected_project = str(project_id or "")
        expected_revision = int(manifest_revision)
        for key in tuple(self._payloads):
            if (
                key.project_id != expected_project
                or key.manifest_revision != expected_revision
            ):
                del self._payloads[key]

    def clear(self) -> None:
        self._payloads.clear()
