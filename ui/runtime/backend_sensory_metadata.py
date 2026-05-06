from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import NoWheelTabWidget


def _engine():
    import engine

    return engine


def _sensory():
    from core import sensory

    return sensory

class BackendSensoryMetadataMixin:
    def _normalize_sensory_pingpong_source_prompt_map(self, payload=None):
        raw = payload if payload is not None else _engine().RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {})
        if not isinstance(raw, dict):
            return {}
        result = {}
        for key, value in list(raw.items()):
            provider_id = str(key or "").strip().lower()
            if not provider_id:
                continue
            result[provider_id] = str(value or "").strip()
        return result

    def _current_sensory_pingpong_source_prompt_map(self):
        editors = getattr(self, "_sensory_source_prompt_editors", {}) or {}
        current_map = self._normalize_sensory_pingpong_source_prompt_map()
        for provider_id, editor in editors.items():
            current_map[str(provider_id or "").strip().lower()] = str(editor.toPlainText() or "").strip()
        return current_map

    def _provider_sensory_pingpong_prompt_default(self, provider_id):
        provider = _sensory().get_provider(str(provider_id or "").strip().lower())
        metadata = dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}
        return str(metadata.get("pingpong_prompt") or "").strip()

    def _provider_uses_source_prompt_fragment(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        return metadata.get("prompt_fragment_enabled", True) is not False

    def _provider_sensory_metadata(self, provider_id):
        provider = _sensory().get_provider(str(provider_id or "").strip().lower())
        return dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}

    def _provider_declared_ping_payload(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        raw = metadata.get("ping_payload", [])
        payload_lines = []
        if isinstance(raw, (list, tuple, set)):
            for item in list(raw):
                if isinstance(item, dict):
                    field_name = str(item.get("field") or "").strip()
                    description = str(item.get("description") or "").strip()
                    text = field_name
                    if field_name and description:
                        text = f"{field_name}: {description}"
                    elif description:
                        text = description
                else:
                    text = str(item or "").strip()
                if text and text not in payload_lines:
                    payload_lines.append(text)
        return payload_lines

    def _provider_declared_pong_influences(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        raw = metadata.get("pong_influences", metadata.get("pong_outputs", []))
        outputs = []
        if isinstance(raw, (list, tuple, set)):
            for item in list(raw):
                if isinstance(item, dict):
                    field_name = str(item.get("field") or "").strip()
                    description = str(item.get("description") or "").strip()
                    text = field_name
                    if field_name and description:
                        text = f"{field_name}: {description}"
                    elif description:
                        text = description
                else:
                    text = str(item or "").strip()
                if text and text not in outputs:
                    outputs.append(text)
        return outputs

    def _provider_prompt_contributors(self, provider_id):
        provider_key = str(provider_id or "").strip().lower()
        items = []
        for contributor in _sensory().list_prompt_contributors(provider_key):
            if hasattr(contributor, "to_summary"):
                items.append(contributor.to_summary())
            elif isinstance(contributor, dict):
                items.append(dict(contributor))
        return items

    def _provider_declared_tag_subscriptions(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        raw = metadata.get("tag_subscriptions", [])
        tags = []
        if isinstance(raw, (list, tuple, set)):
            for item in list(raw):
                if isinstance(item, dict):
                    tag_name = str(item.get("tag") or "").strip()
                    action = str(item.get("action") or "").strip()
                    text = tag_name
                    if tag_name and action:
                        text = f"{tag_name}: {action}"
                    elif action:
                        text = action
                else:
                    text = str(item or "").strip()
                if text and text not in tags:
                    tags.append(text)
        return tags

    def _on_sensory_source_prompt_changed(self, provider_id):
        prompt_map = self._current_sensory_pingpong_source_prompt_map()
        _engine().update_runtime_config("sensory_pingpong_source_prompts", prompt_map)
        self.emit_tutorial_event("ui_changed", {"field": f"sensory_pingpong_source_prompt:{provider_id}", "value": "edited"})
        self.save_session()

    def _reset_sensory_source_prompt_to_default(self, provider_id):
        editors = getattr(self, "_sensory_source_prompt_editors", {}) or {}
        editor = editors.get(str(provider_id or "").strip().lower())
        if editor is None:
            return
        default_prompt = self._provider_sensory_pingpong_prompt_default(provider_id)
        editor.setPlainText(default_prompt)
        self._on_sensory_source_prompt_changed(provider_id)
