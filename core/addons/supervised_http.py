"""Addon-facing HTTP concurrency owned by an addon task supervisor."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol

from core.runtime.lifecycle import WorkerHandle


class AddonTaskPort(Protocol):
    def spawn(
        self,
        name: str,
        target: Callable[[object], None],
        *,
        daemon: bool = True,
        on_cancel: Callable[[str], None] | None = None,
    ) -> WorkerHandle: ...

    def cancel_worker(self, handle: WorkerHandle, reason: str) -> None: ...

    def join_worker(self, handle: WorkerHandle) -> None: ...


class TaskSupervisedThreadingHTTPServer(ThreadingHTTPServer):
    """Run each accepted request as exact-owner supervised work."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        tasks: AddonTaskPort,
        request_task_name: str,
    ) -> None:
        self._tasks = tasks
        self._request_task_name = str(request_task_name)
        self._request_handles: set[WorkerHandle] = set()
        self._request_handles_lock = threading.Lock()
        super().__init__(server_address, handler_class)

    def process_request(self, request, client_address) -> None:
        registered = threading.Event()
        handle_holder: list[WorkerHandle] = []
        close_lock = threading.Lock()
        closed = False

        def close_request(_reason: str = "") -> None:
            nonlocal closed
            with close_lock:
                if closed:
                    return
                closed = True
            try:
                self.shutdown_request(request)
            except Exception:
                pass

        def run_request(cancellation) -> None:
            registered.wait()
            if not handle_holder:
                close_request()
                return
            handle = handle_holder[0]
            try:
                if cancellation.cancelled:
                    return
                try:
                    self.finish_request(request, client_address)
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as error:
                    logging.getLogger(__name__).info(
                        'http_request_disconnected error_type=%s errno=%s',
                        type(error).__name__, error.errno,
                    )
                except Exception:
                    self.handle_error(request, client_address)
            finally:
                close_request()
                with self._request_handles_lock:
                    self._request_handles.discard(handle)

        try:
            handle = self._tasks.spawn(
                self._request_task_name,
                run_request,
                on_cancel=close_request,
            )
        except Exception:
            registered.set()
            close_request()
            return
        handle_holder.append(handle)
        with self._request_handles_lock:
            self._request_handles.add(handle)
        registered.set()

    def cancel_requests(self, reason: str) -> None:
        with self._request_handles_lock:
            handles = tuple(self._request_handles)
            self._request_handles.clear()
        for handle in handles:
            self._tasks.cancel_worker(handle, reason)
        for handle in handles:
            self._tasks.join_worker(handle)
