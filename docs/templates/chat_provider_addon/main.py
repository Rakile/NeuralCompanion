from __future__ import annotations

import os

from core.addons.base import BaseAddon


PROVIDER_ID = "my_provider"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._chat_service = context.get_service("qt.chat_providers")
        if self._chat_service is None:
            context.logger.warning("Chat provider service is unavailable.")
            return None

        self._chat_service.register_provider(
            provider_id=PROVIDER_ID,
            label="My Provider",
            description="Example external chat provider.",
            order=900,
            model_list_handler=self._list_models,
            completion_handler=self._complete_chat,
            stream_handler=self._stream_chat,
            connection_check_handler=self._check_connection,
            api_key_getter=self._api_key,
            base_url_getter=self._base_url,
            metadata={
                "config_fields": [
                    {"id": "api_key", "label": "API Key", "env": ["MY_PROVIDER_API_KEY"]},
                    {"id": "base_url", "label": "Base URL", "default": "https://api.example.com"},
                ],
                "hint": "Replace the template request handlers with your provider API calls.",
                "supports_hosted_runtime": True,
            },
        )
        return None

    def shutdown(self):
        if getattr(self, "_chat_service", None) is not None:
            self._chat_service.unregister_provider(PROVIDER_ID)
        return None

    def _setting(self, field_id: str) -> str:
        getter = getattr(self._chat_service, "get_provider_setting", None)
        return str(getter(PROVIDER_ID, field_id) or "").strip() if callable(getter) else ""

    def _api_key(self) -> str:
        return self._setting("api_key") or str(os.environ.get("MY_PROVIDER_API_KEY", "") or "").strip()

    def _base_url(self) -> str:
        return self._setting("base_url") or "https://api.example.com"

    def _list_models(self, quiet: bool = False):
        return ["example-chat-model"]

    def _check_connection(self):
        return {"ok": bool(self._api_key()), "detail": "API key configured." if self._api_key() else "API key is required."}

    def _complete_chat(self, params, additional_params=None) -> str:
        raise NotImplementedError("Call your provider API and return a complete assistant string.")

    def _stream_chat(self, params, additional_params=None):
        raise NotImplementedError("Call your provider streaming API and yield assistant text chunks.")
