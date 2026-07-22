from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Condition, Thread
from time import monotonic
from typing import Any


@dataclass(frozen=True)
class SaveRequest:
    project_id: str
    revision: int
    snapshot: dict


class ProjectAutosaveQueue:
    """Serialize project saves while retaining each project's latest pending request."""

    def __init__(
        self,
        save: Callable[[dict], dict],
        on_saved: Callable[[dict], None],
        on_failed: Callable[[dict], None],
    ) -> None:
        self._save = save
        self._on_saved = on_saved
        self._on_failed = on_failed
        self._condition = Condition()
        self._pending: dict[str, SaveRequest] = {}
        self._active_count = 0
        self._shutdown_requested = False
        self._writer = Thread(
            target=self._run,
            name="ProjectAutosaveWriter",
            daemon=True,
        )
        self._writer.start()

    def request(self, request: SaveRequest) -> None:
        """Queue a save, replacing any pending request for the same project."""
        with self._condition:
            if self._shutdown_requested:
                raise RuntimeError("Project autosave queue is shut down")
            self._pending[request.project_id] = request
            self._condition.notify()

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait for all pending and active saves to finish within ``timeout`` seconds."""
        deadline = monotonic() + max(timeout, 0.0)
        with self._condition:
            while self._pending or self._active_count:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop accepting requests, drain queued work, and join the daemon writer briefly."""
        with self._condition:
            self._shutdown_requested = True
            self._condition.notify_all()
        self._writer.join(max(timeout, 0.0))

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._shutdown_requested:
                    self._condition.wait()
                if not self._pending:
                    return
                _, request = self._pending.popitem()
                self._active_count += 1

            try:
                result = self._save(request.snapshot)
            except Exception as exc:
                self._notify_failed(request, exc)
            else:
                self._rebase_pending_descendant(request, result)
                self._notify_saved(result)
            finally:
                with self._condition:
                    self._active_count -= 1
                    self._condition.notify_all()

    def _rebase_pending_descendant(self, request: SaveRequest, result: dict) -> None:
        """Advance only a queued snapshot sharing the just-published CAS base."""
        if not isinstance(result, Mapping):
            return
        try:
            base_revision = int(request.snapshot.get("manifest_revision", 0) or 0)
            published_revision = int(result.get("manifest_revision", 0) or 0)
        except (TypeError, ValueError):
            return
        if (
            str(result.get("project_id") or "") != request.project_id
            or published_revision <= base_revision
        ):
            return
        with self._condition:
            pending = self._pending.get(request.project_id)
            if pending is None:
                return
            try:
                pending_base = int(
                    pending.snapshot.get("manifest_revision", 0) or 0
                )
            except (TypeError, ValueError):
                return
            if pending_base != base_revision or pending.revision <= request.revision:
                return
            snapshot = copy.deepcopy(pending.snapshot)
            snapshot["manifest_revision"] = published_revision
            self._pending[request.project_id] = SaveRequest(
                pending.project_id, pending.revision, snapshot
            )

    def _notify_saved(self, result: dict) -> None:
        try:
            self._on_saved(result)
        except Exception:
            pass

    def _notify_failed(self, request: SaveRequest, error: Exception) -> None:
        failure: dict[str, Any] = {
            "project_id": request.project_id,
            "revision": request.revision,
            "snapshot": request.snapshot,
            "error": str(error),
        }
        try:
            self._on_failed(failure)
        except Exception:
            pass


def result_is_current(
    result: Mapping[str, object],
    *,
    project_id: str,
    generation_id: int,
    input_fingerprint: str,
) -> bool:
    """Return whether a worker result belongs to the exact current work generation."""
    if (
        type(project_id) is not str
        or not project_id
        or type(generation_id) is not int
        or type(input_fingerprint) is not str
        or not input_fingerprint
    ):
        return False
    return (
        type(result.get("project_id")) is str
        and result.get("project_id") == project_id
        and type(result.get("generation_id")) is int
        and result.get("generation_id") == generation_id
        and type(result.get("input_fingerprint")) is str
        and result.get("input_fingerprint") == input_fingerprint
    )
