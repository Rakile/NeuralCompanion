from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path

from core import long_term_memory


class _TrackingConnection(sqlite3.Connection):
    opened: list["_TrackingConnection"] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.was_closed = False
        self.opened.append(self)

    def close(self) -> None:
        self.was_closed = True
        super().close()


def test_long_term_memory_operations_close_connections_explicitly() -> None:
    original_connect = long_term_memory.sqlite3.connect

    def tracking_connect(*args, **kwargs):
        kwargs["factory"] = _TrackingConnection
        return original_connect(*args, **kwargs)

    _TrackingConnection.opened = []
    long_term_memory.sqlite3.connect = tracking_connect
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "lifecycle.sqlite3"
            long_term_memory.init_store(db_path)
            long_term_memory.store_content_format_version(db_path)
            long_term_memory.list_archived_chunks(path=db_path)
    finally:
        long_term_memory.sqlite3.connect = original_connect

    assert _TrackingConnection.opened
    assert all(connection.was_closed for connection in _TrackingConnection.opened), (
        "Long-Term Memory SQLite connections must be explicitly closed instead of "
        "depending on garbage collection."
    )


def test_release_store_closes_a_retained_connection() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "retained.sqlite3"
        connection = long_term_memory._connect(db_path)
        connection.execute("CREATE TABLE retained(value TEXT)")
        assert long_term_memory.release_store(db_path) == 1
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            pass
        else:
            raise AssertionError("release_store() left a tracked SQLite connection open")


def test_release_store_closes_a_worker_thread_connection() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "worker.sqlite3"
        opened = threading.Event()
        released = threading.Event()
        result: dict[str, object] = {}

        def worker() -> None:
            connection = long_term_memory._connect(db_path)
            result["connection"] = connection
            opened.set()
            released.wait(timeout=5.0)
            try:
                connection.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                result["closed"] = True

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert opened.wait(timeout=5.0)
        assert long_term_memory.release_store(db_path) == 1
        released.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert result.get("closed") is True


if __name__ == "__main__":
    test_long_term_memory_operations_close_connections_explicitly()
    test_release_store_closes_a_retained_connection()
    test_release_store_closes_a_worker_thread_connection()
    print("Long-Term Memory SQLite lifecycle smoke test passed.")
