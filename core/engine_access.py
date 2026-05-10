"""Shared engine access facade for host/runtime adapter modules."""

from __future__ import annotations

import importlib
from typing import Any


def engine_module():
    return importlib.import_module("engine")


def runtime_config() -> dict:
    return getattr(engine_module(), "RUNTIME_CONFIG", {}) or {}


def update_runtime_config(key, value):
    return engine_module().update_runtime_config(key, value)


def get_chat_models(provider=None, quiet=True):
    return engine_module().get_chat_models(provider=provider, quiet=quiet)


def replace_chat_conversation_history(entries, *, allow_pending_loaded_user):
    return engine_module().replace_chat_conversation_history(
        entries,
        allow_pending_loaded_user=allow_pending_loaded_user,
    )


def __getattr__(name: str) -> Any:
    return getattr(engine_module(), str(name))
