"""Minimal compatibility entry point for the production desktop runtime."""

from __future__ import annotations

from collections.abc import Mapping

from core.runtime.production_desktop_process import (
    get_runtime_context as _get_runtime_context,
    request_shutdown as _request_shutdown,
    run_companion as _run_companion,
)


def get_runtime_context():
    """Return the single composed runtime context for compatibility callers."""

    return _get_runtime_context()


def run_companion(config_override: Mapping[str, object] | None = None):
    """Run the production companion synchronously."""

    return _run_companion(config_override)


def request_shutdown(reason: str = "user") -> None:
    """Request shutdown through the production stop owner."""

    _request_shutdown(reason)


def main():
    """Run the desktop companion from the command line."""

    try:
        return run_companion()
    except KeyboardInterrupt:
        request_shutdown("keyboard_interrupt")
        return None


if __name__ == "__main__":
    main()
