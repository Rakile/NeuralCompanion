"""Grouped shell-preview services extracted from shell_services.py."""

import json
from collections import OrderedDict
from pathlib import Path


def configure_shell_services_runtime_dependencies(namespace):
    globals().update(dict(namespace or {}))


class _UiShellRuntimeStatusService:
    """Read-only shell runtime status facade for Designer-bound UI code."""

    def __init__(self, window):
        self._window = window
        self._running = False
        self._session_overrides = {}

    def set_running(self, running):
        self._running = bool(running)

    def set_session_overrides(self, **values):
        for key, value in values.items():
            if value is None:
                self._session_overrides.pop(str(key), None)
            else:
                self._session_overrides[str(key)] = value

    def snapshot(self):
        binding_summary = _ui_shell_binding_summary(self._window)
        session = dict(_read_ui_shell_session_snapshot() or {})
        session.update(dict(self._session_overrides or {}))
        return build_runtime_status_snapshot(
            session,
            running=self._running,
            engine_connected=False,
            shell_mode=True,
            lifecycle_state="shell_running_preview" if self._running else "shell_preview",
            source="ui_shell",
            metadata={
                "bindings_checked": int(binding_summary.get("checked", 0) or 0),
                "bindings_bound": int(binding_summary.get("bound", 0) or 0),
                "binding_issues": bool(binding_summary.get("missing") or binding_summary.get("mismatched")),
            },
        )

    def status_line(self):
        return self.snapshot().status_line()


class _UiShellModelRefreshService:
    """Shell-safe model refresh facade.

    The Designer shell can bind refresh controls through the same host-service
    name as the real app, but this implementation never calls provider handlers.
    """

    def __init__(self, window):
        self._window = window
        self._last_requested_provider = ""

    def snapshot(self, provider_id=None):
        session = dict(_read_ui_shell_session_snapshot() or {})
        provider = str(provider_id or session.get("chat_provider", "") or "").strip().lower()
        model_name = str(session.get("model_name", "") or "").strip()
        models = [model_name] if model_name else []
        return {
            "provider": provider,
            "selected_model": model_name,
            "models": models,
            "in_flight": False,
            "refresh_available": False,
            "deferred": True,
            "last_requested_provider": self._last_requested_provider,
            "message": "Live model refresh is deferred in shell preview.",
            "source": "ui_shell",
        }

    def refresh(self, provider_id=None, *, quiet=True, wait_for_reachable=False):
        self._last_requested_provider = str(provider_id or "").strip().lower()
        return self.snapshot(provider_id)


class _UiShellEngineLifecycleService:
    """Shell-local lifecycle facade that never starts runtime systems."""

    def __init__(self, window):
        self._window = window
        self._running = False

    def snapshot(self):
        status = _ui_shell_runtime_status_service(self._window)
        return {
            "running": bool(self._running),
            "shell_mode": True,
            "engine_connected": False,
            "runtime_status": status.snapshot().to_dict(),
            "message": "Engine lifecycle is shell-local only.",
            "source": "ui_shell",
        }

    def start_engine(self, *, offline_replay_only=False):
        self._running = True
        _ui_shell_runtime_status_service(self._window).set_running(True)
        return self.snapshot()

    def stop_engine(self):
        self._running = False
        _ui_shell_runtime_status_service(self._window).set_running(False)
        return self.snapshot()

    def reset_chat_memory(self):
        return {
            "running": bool(self._running),
            "shell_mode": True,
            "engine_connected": False,
            "message": "Shell-local chat reset only.",
            "source": "ui_shell",
        }

    def start(self, **kwargs):
        return self.start_engine(**kwargs)

    def stop(self):
        return self.stop_engine()

    def reset(self):
        return self.reset_chat_memory()


class _UiShellRuntimeControlService:
    """Shell-safe runtime controls facade for Operational View buttons."""

    SUPPORTED_ACTIONS = (
        "regenerate_response",
        "retry_user_input",
        "pause_speech",
        "skip_speech",
        "skip_user_reply",
    )

    def __init__(self, window):
        self._window = window
        self._last_action = ""

    def snapshot(self):
        return {
            "actions": list(self.SUPPORTED_ACTIONS),
            "last_action": self._last_action,
            "shell_mode": True,
            "runtime_connected": False,
            "message": "Runtime control actions are shell-local only.",
            "source": "ui_shell",
        }

    def trigger(self, action: str):
        action_key = str(action or "").strip()
        if action_key in self.SUPPORTED_ACTIONS:
            self._last_action = action_key
            return {**self.snapshot(), "accepted": True, "action": action_key}
        return {**self.snapshot(), "accepted": False, "action": action_key}
