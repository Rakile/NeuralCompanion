"""Explicit Stockfish setup, called only by the existing Chess worker."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys
import urllib.request

from PySide6.QtCore import QUrl


def _local_path(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Choose a local engine file or installation folder.')
    if value.lower().startswith('file:'):
        value = QUrl(value).toLocalFile()
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('Choose an absolute local path.')
    return path


def existing_engine(value: str) -> str:
    path = _local_path(value)
    if not path.is_file() or (sys.platform == 'win32' and path.suffix.lower() != '.exe'):
        raise ValueError('Choose an existing Stockfish executable.')
    return str(path)


def _check_cancelled(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise RuntimeError('Stockfish installation cancelled. Your engine selection was kept.')


def download_archive(url: str, destination: Path, expected_size: int,
                     cancelled: Callable[[], bool], progress: Callable[[str], None]) -> None:
    _check_cancelled(cancelled)
    request = urllib.request.Request(url, headers={'User-Agent': 'NeuralCompanion-CompanionChess'})
    # read1 returns available data instead of waiting to fill a large buffer;
    # short socket inactivity timeouts also bound stalls during shutdown.
    with urllib.request.urlopen(request, timeout=3) as response, destination.open('wb') as target:
        received = 0
        while True:
            _check_cancelled(cancelled)
            chunk = response.read1(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > expected_size:
                raise ValueError('Stockfish download exceeds the pinned archive size.')
            target.write(chunk)
            progress(f'Downloading Stockfish: {received * 100 // expected_size}%')
    _check_cancelled(cancelled)
    progress('Verifying and installing Stockfish…')


def install_engine(folder: str, app_root: Path, cancelled: Callable[[], bool],
                   progress: Callable[[str], None]) -> str:
    _check_cancelled(cancelled)
    parent = _local_path(folder)
    if not parent.is_dir():
        raise ValueError('Choose an existing folder for Stockfish.')
    from installer_stockfish import STOCKFISH_RELEASES, ensure_stockfish

    sizes = {release.url: release.size for release in STOCKFISH_RELEASES.values()}
    def download(url: str, destination: Path) -> None:
        download_archive(url, destination, sizes[url], cancelled, progress)

    executable = ensure_stockfish(app_root, download, destination=parent / 'Stockfish')
    _check_cancelled(cancelled)
    return str(executable)
