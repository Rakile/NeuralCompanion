"""User Identity addon entry point."""

from __future__ import annotations

from addons.user_identity.profile import UserIdentityProfile
from core.addons import BaseAddon


class Addon(BaseAddon):
    def initialize(self, context) -> None:
        super().initialize(context)
        self.profile = UserIdentityProfile(context)
        context.logger.info("User Identity local profile initialized.")

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        request = dict(payload or {})
        if name == "runtime.user_identity.snapshot":
            return self.profile.snapshot()
        if name == "runtime.user_identity.update":
            return self.profile.update(dict(request.get("patch") or {}))
        if name == "runtime.user_identity.import_avatar":
            return self.profile.import_avatar(request.get("path"))
        if name == "runtime.user_identity.clear_avatar":
            return self.profile.clear_avatar()
        if name == "runtime.user_identity.refine_prompt":
            return self.profile.refine_identity_prompt()
        if name == "runtime.user_identity.generate_portrait":
            return self.profile.generate_portrait()
        if name == "chat_context.collect":
            return self.profile.collect_chat_context(request)
        return None

    def shutdown(self) -> None:
        profile = getattr(self, "profile", None)
        self.profile = None
        if profile is not None:
            profile.shutdown()


__all__ = ["Addon"]
