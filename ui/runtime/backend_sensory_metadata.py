import json

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

    def _normalize_sensory_provider_metadata_override_map(self, payload=None):
        raw = payload if payload is not None else _engine().RUNTIME_CONFIG.get("sensory_provider_metadata_overrides", {})
        if not isinstance(raw, dict):
            return {}
        result = {}
        for key, value in list(raw.items()):
            provider_id = str(key or "").strip().lower()
            if not provider_id or not isinstance(value, dict):
                continue
            item = {}
            for text_key in ("label", "instruction", "description"):
                if text_key in value:
                    item[text_key] = str(value.get(text_key) or "")
            metadata = value.get("metadata", {})
            if isinstance(metadata, dict):
                item["metadata"] = dict(metadata)
            result[provider_id] = item
        return result

    def _provider_sensory_default_payload(self, provider_id):
        provider_key = str(provider_id or "").strip().lower()
        provider = _sensory().get_provider(provider_key)
        metadata = dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}
        return {
            "label": str(getattr(provider, "label", provider_key) or provider_key),
            "instruction": str(getattr(provider, "instruction", "") or ""),
            "description": str(getattr(provider, "description", "") or ""),
            "metadata": metadata,
        }

    def _provider_sensory_effective_payload(self, provider_id):
        provider_key = str(provider_id or "").strip().lower()
        payload = self._provider_sensory_default_payload(provider_key)
        overrides = self._normalize_sensory_provider_metadata_override_map().get(provider_key, {})
        if isinstance(overrides, dict):
            for text_key in ("label", "instruction", "description"):
                if text_key in overrides:
                    payload[text_key] = str(overrides.get(text_key) or "")
            metadata_override = overrides.get("metadata", {})
            if isinstance(metadata_override, dict):
                metadata = dict(payload.get("metadata") or {})
                metadata.update(dict(metadata_override))
                payload["metadata"] = metadata
        legacy_prompt = self._normalize_sensory_pingpong_source_prompt_map().get(provider_key)
        if legacy_prompt is not None:
            metadata = dict(payload.get("metadata") or {})
            metadata["pingpong_prompt"] = str(legacy_prompt or "")
            payload["metadata"] = metadata
        return payload

    def _format_sensory_metadata_json(self, value):
        return json.dumps(value if value is not None else [], ensure_ascii=False, indent=2)

    def _read_sensory_metadata_json_editor(self, editor, fallback):
        if editor is None:
            return fallback
        text = str(editor.toPlainText() or "").strip()
        if not text:
            return []
        try:
            return json.loads(text)
        except Exception:
            return fallback

    def _current_sensory_provider_metadata_override_map(self):
        current_map = self._normalize_sensory_provider_metadata_override_map()
        editors_by_provider = getattr(self, "_sensory_source_metadata_editors", {}) or {}
        for provider_id, editors in editors_by_provider.items():
            provider_key = str(provider_id or "").strip().lower()
            if not provider_key or not isinstance(editors, dict):
                continue
            default_payload = self._provider_sensory_default_payload(provider_key)
            default_metadata = dict(default_payload.get("metadata") or {})
            metadata = {}
            prompt_editor = getattr(self, "_sensory_source_prompt_editors", {}).get(provider_key) if hasattr(self, "_sensory_source_prompt_editors") else None
            if prompt_editor is not None:
                metadata["pingpong_prompt"] = str(prompt_editor.toPlainText() or "").strip()
            for key in ("ping_payload", "pong_influences", "tag_subscriptions"):
                metadata[key] = self._read_sensory_metadata_json_editor(
                    editors.get(key),
                    default_metadata.get(key, []),
                )
            current_map[provider_key] = {
                "instruction": str(editors.get("instruction").toPlainText() if editors.get("instruction") is not None else default_payload.get("instruction", "")).strip(),
                "description": str(editors.get("description").toPlainText() if editors.get("description") is not None else default_payload.get("description", "")).strip(),
                "metadata": metadata,
            }
        return current_map

    def _provider_sensory_pingpong_prompt_default(self, provider_id):
        metadata = dict(self._provider_sensory_default_payload(provider_id).get("metadata") or {})
        return str(metadata.get("pingpong_prompt") or "").strip()

    def _provider_uses_source_prompt_fragment(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        return metadata.get("prompt_fragment_enabled", True) is not False

    def _provider_sensory_metadata(self, provider_id):
        return dict(self._provider_sensory_effective_payload(provider_id).get("metadata") or {})

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
        if hasattr(self, "_current_sensory_provider_metadata_override_map"):
            _engine().update_runtime_config("sensory_provider_metadata_overrides", self._current_sensory_provider_metadata_override_map())
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

    def _on_sensory_source_metadata_changed(self, provider_id):
        _engine().update_runtime_config("sensory_provider_metadata_overrides", self._current_sensory_provider_metadata_override_map())
        self.emit_tutorial_event("ui_changed", {"field": f"sensory_provider_metadata:{provider_id}", "value": "edited"})
        self.save_session()

    def _reset_sensory_source_metadata_to_default(self, provider_id):
        provider_key = str(provider_id or "").strip().lower()
        editors = (getattr(self, "_sensory_source_metadata_editors", {}) or {}).get(provider_key, {})
        if not isinstance(editors, dict):
            return
        default_payload = self._provider_sensory_default_payload(provider_key)
        default_metadata = dict(default_payload.get("metadata") or {})
        if editors.get("instruction") is not None:
            editors["instruction"].setPlainText(str(default_payload.get("instruction") or ""))
        if editors.get("description") is not None:
            editors["description"].setPlainText(str(default_payload.get("description") or ""))
        for key in ("ping_payload", "pong_influences", "tag_subscriptions"):
            if editors.get(key) is not None:
                editors[key].setPlainText(self._format_sensory_metadata_json(default_metadata.get(key, [])))
        prompt_editors = getattr(self, "_sensory_source_prompt_editors", {}) or {}
        if prompt_editors.get(provider_key) is not None:
            prompt_editors[provider_key].setPlainText(str(default_metadata.get("pingpong_prompt") or ""))
        self._on_sensory_source_metadata_changed(provider_key)
