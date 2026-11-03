"""PocketTTS addon-local defaults and file cleanup helpers."""

from __future__ import annotations

import os
from pathlib import Path
import time


def default_pocket_tts_python(app_root: str | Path) -> str:
    return str(Path(app_root) / ".venvs" / "pockettts" / "Scripts" / "python.exe")


def safe_delete_with_retry(file_path, *, retries: int = 5, delay: float = 0.1) -> bool:
    target = Path(file_path)
    for attempt in range(max(1, int(retries))):
        try:
            target.unlink(missing_ok=True)
            return True
        except OSError:
            if attempt + 1 < max(1, int(retries)):
                time.sleep(max(0.0, float(delay)))
    return not os.path.exists(target)
