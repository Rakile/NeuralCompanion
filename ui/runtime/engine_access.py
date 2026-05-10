"""Compatibility import for the shared engine access facade."""

from __future__ import annotations

from typing import Any

from core import engine_access as _engine_access
from core.engine_access import *  # noqa: F401,F403


def __getattr__(name: str) -> Any:
    return getattr(_engine_access, str(name))
