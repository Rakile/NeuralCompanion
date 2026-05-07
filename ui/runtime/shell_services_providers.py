"""Grouped shell-preview services extracted from shell_services.py."""

from collections import OrderedDict

from addons.hotkeys.shell_service import _UiShellHotkeyService
from addons.visual_reply.shell_service import _UiShellVisualReplyService


def configure_shell_services_providers_dependencies(namespace):
    globals().update(dict(namespace or {}))


class _UiShellSensoryService:
    """Shell-only sensory registry: accept metadata without capturing input."""

    def __init__(self):
        self._providers = OrderedDict()
        self._contributors = OrderedDict()

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        instruction: str = "",
        description: str = "",
        order: int = 1000,
        capture_handler=None,
        metadata: dict | None = None,
    ):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise RuntimeError("Sensory provider id is required.")
        summary = {
            "id": provider_id,
            "label": str(label or provider_id).strip() or provider_id,
            "instruction": str(instruction or "").strip(),
            "description": str(description or "").strip(),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "has_capture_handler": callable(capture_handler),
            "shell_mode": True,
        }
        self._providers[provider_id] = summary
        return dict(summary)

    def unregister_provider(self, provider_id: str) -> bool:
        return self._providers.pop(str(provider_id or "").strip(), None) is not None

    def list_providers(self):
        return [
            dict(item)
            for item in sorted(self._providers.values(), key=lambda row: (int(row.get("order", 1000)), str(row.get("label") or row.get("id") or "")))
        ]

    def register_prompt_contributor(
        self,
        *,
        contributor_id: str,
        source_id: str,
        label: str,
        prompt: str = "",
        order: int = 1000,
        metadata: dict | None = None,
    ):
        contributor_id = str(contributor_id or "").strip()
        if not contributor_id:
            raise RuntimeError("Sensory prompt contributor id is required.")
        summary = {
            "id": contributor_id,
            "source_id": str(source_id or "").strip(),
            "label": str(label or contributor_id).strip() or contributor_id,
            "prompt": str(prompt or ""),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "shell_mode": True,
        }
        self._contributors[contributor_id] = summary
        return dict(summary)

    def unregister_prompt_contributor(self, contributor_id: str) -> bool:
        return self._contributors.pop(str(contributor_id or "").strip(), None) is not None

    def list_prompt_contributors(self, source_id: str | None = None):
        source = str(source_id or "").strip()
        rows = list(self._contributors.values())
        if source:
            rows = [row for row in rows if str(row.get("source_id") or "").strip() == source]
        return [
            dict(item)
            for item in sorted(rows, key=lambda row: (int(row.get("order", 1000)), str(row.get("label") or row.get("id") or "")))
        ]


class _UiShellAvatarProviderService:
    """Shell-only avatar provider registry: keep factories inert."""

    def __init__(self):
        self._providers = OrderedDict()

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        factory,
        description: str = "",
        order: int = 1000,
        metadata: dict | None = None,
    ):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise RuntimeError("Avatar provider id is required.")
        summary = {
            "id": provider_id,
            "label": str(label or provider_id).strip() or provider_id,
            "description": str(description or "").strip(),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "has_factory": callable(factory),
            "shell_mode": True,
        }
        self._providers[provider_id] = summary
        return dict(summary)

    def unregister_provider(self, provider_id: str) -> bool:
        return self._providers.pop(str(provider_id or "").strip(), None) is not None

    def list_providers(self):
        return [
            dict(item)
            for item in sorted(self._providers.values(), key=lambda row: (int(row.get("order", 1000)), str(row.get("label") or row.get("id") or "")))
        ]


class _UiShellChatProviderRegistry:
    """Shell-only provider registry: accept addon metadata without invoking handlers."""

    def __init__(self):
        self._providers = OrderedDict()
        self._registrations = {}

    def register_provider(
        self,
        *,
        provider_id,
        label,
        description="",
        order=1000,
        client_factory=None,
        model_list_handler=None,
        completion_handler=None,
        stream_handler=None,
        connection_check_handler=None,
        api_key_getter=None,
        base_url_getter=None,
        metadata=None,
    ):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise RuntimeError("Chat provider id is required.")
        summary = {
            "id": provider_id,
            "label": str(label or provider_id).strip() or provider_id,
            "description": str(description or "").strip(),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "has_model_list_handler": callable(model_list_handler),
            "has_completion_handler": callable(completion_handler),
            "has_stream_handler": callable(stream_handler),
            "has_connection_check_handler": callable(connection_check_handler),
            "has_api_key_getter": callable(api_key_getter),
            "has_base_url_getter": callable(base_url_getter),
        }
        self._providers[provider_id] = summary
        self._registrations[provider_id] = {
            "client_factory": client_factory,
            "model_list_handler": model_list_handler,
            "completion_handler": completion_handler,
            "stream_handler": stream_handler,
            "connection_check_handler": connection_check_handler,
            "api_key_getter": api_key_getter,
            "base_url_getter": base_url_getter,
        }
        return dict(summary)

    def unregister_provider(self, provider_id):
        provider_id = str(provider_id or "").strip()
        existed = provider_id in self._providers
        self._providers.pop(provider_id, None)
        self._registrations.pop(provider_id, None)
        return existed

    def list_providers(self):
        return [
            dict(item)
            for item in sorted(
                self._providers.values(),
                key=lambda provider: (int(provider.get("order", 1000)), str(provider.get("label", ""))),
            )
        ]

    def provider_ids(self):
        return set(self._providers.keys())

    def get_provider_settings(self, provider_id=None):
        if provider_id:
            return {}
        return {provider_id: {} for provider_id in self._providers}

    def get_provider_setting(self, provider_id, field_id):
        return ""


class _UiShellShellService:
    """Shell-preview service: allow addon UI refresh notifications without saving state."""

    def open_local_path(self, path):
        return False

    def notify_settings_changed(self):
        return None
