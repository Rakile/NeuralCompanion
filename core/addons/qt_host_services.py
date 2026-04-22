from __future__ import annotations

from pathlib import Path

from core import avatar_runtime, sensory, chat_providers
import shared_state
from PySide6 import QtCore, QtGui, QtWidgets


class QtDialogService:
    _last_directory: Path | None = None

    def __init__(self, window):
        self._window = window

    @classmethod
    def _resolve_start_dir(cls, start_dir: str | Path | None) -> str:
        if cls._last_directory is not None and cls._last_directory.exists():
            return str(cls._last_directory)
        candidate = Path(str(start_dir or "").strip() or Path.cwd())
        if candidate.is_file():
            candidate = candidate.parent
        return str(candidate if candidate.exists() else Path.cwd())

    @classmethod
    def _remember_path(cls, selected_path: str | Path | None) -> None:
        raw = str(selected_path or "").strip()
        if not raw:
            return
        try:
            candidate = Path(raw)
            remember = candidate if candidate.is_dir() else candidate.parent
            if remember.exists():
                cls._last_directory = remember.resolve()
        except Exception:
            pass

    def open_file(self, title: str, start_dir: str, file_filter: str):
        start = self._resolve_start_dir(start_dir)
        path, selected_filter = QtWidgets.QFileDialog.getOpenFileName(self._window, str(title), start, str(file_filter))
        self._remember_path(path)
        return path, selected_filter

    def save_file(self, title: str, start_path: str, file_filter: str):
        start = self._resolve_start_dir(start_path)
        path, selected_filter = QtWidgets.QFileDialog.getSaveFileName(self._window, str(title), start, str(file_filter))
        self._remember_path(path)
        return path, selected_filter

    def open_directory(self, title: str, start_dir: str):
        start = self._resolve_start_dir(start_dir)
        path = QtWidgets.QFileDialog.getExistingDirectory(self._window, str(title), start)
        self._remember_path(path)
        return path

    def warning(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.warning(self._window, str(title), str(message))

    def information(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.information(self._window, str(title), str(message))


class QtShellService:
    def __init__(self, window):
        self._window = window

    def open_local_path(self, path) -> bool:
        return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(path).resolve())))

    def notify_settings_changed(self) -> None:
        if hasattr(self._window, "_refresh_preset_dirty_state"):
            self._window._refresh_preset_dirty_state()
        if hasattr(self._window, "save_session"):
            self._window.save_session()


class QtHotkeyService:
    def __init__(self, window):
        self._window = window

    def list_bindings(self):
        return list(self._window.hotkey_catalog())

    def set_binding(self, action: str, binding: str):
        return self._window.set_hotkey_binding(str(action or "").strip(), str(binding or ""))

    def reset_defaults(self):
        return dict(self._window.reset_hotkey_bindings() or {})


class QtVisualReplyService:
    def __init__(self, window):
        self._window = window

    def settings_snapshot(self):
        import engine

        runtime = getattr(engine, "RUNTIME_CONFIG", {}) or {}
        theme_presets = list(getattr(engine, "VISUAL_REPLY_STORY_THEME_PRESETS", ()) or ())
        raw_theme_prompts = runtime.get("visual_reply_story_theme_prompts", {})
        if not isinstance(raw_theme_prompts, dict):
            raw_theme_prompts = {}
        raw_theme_enabled = runtime.get("visual_reply_story_theme_enabled", [])
        if isinstance(raw_theme_enabled, (str, bytes)):
            raw_theme_enabled = [raw_theme_enabled]
        if not isinstance(raw_theme_enabled, (list, tuple, set)):
            raw_theme_enabled = []
        theme_enabled = {str(item or "").strip().lower() for item in raw_theme_enabled}
        try:
            story_max_images = max(1, int(runtime.get("visual_reply_story_max_images", 3) or 3))
        except Exception:
            story_max_images = 3
        try:
            story_continuity_strength = float(runtime.get("visual_reply_story_continuity_strength", 0.8) or 0.8)
        except Exception:
            story_continuity_strength = 0.8
        if story_continuity_strength > 1.0:
            story_continuity_strength = story_continuity_strength / 100.0
        story_continuity_strength = max(0.0, min(1.0, story_continuity_strength))
        return {
            "mode_value": str(runtime.get("visual_reply_mode", "auto") or "auto"),
            "provider_value": str(runtime.get("visual_reply_provider", "openai") or "openai"),
            "size_value": str(runtime.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "model_name": str(runtime.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "auto_show": bool(runtime.get("visual_reply_auto_show_dock", True)),
            "master_prompt_safe": bool(runtime.get("visual_reply_master_prompt_safe", False)),
            "master_prompt_no_speech_bubbles": bool(runtime.get("visual_reply_master_prompt_no_speech_bubbles", False)),
            "story_mode": bool(runtime.get("visual_reply_story_mode", False)),
            "story_max_images": story_max_images,
            "story_continuity_strength": story_continuity_strength,
            "story_themes": [
                {
                    "id": str(theme.get("id") or "").strip().lower(),
                    "label": str(theme.get("label") or theme.get("id") or "").strip(),
                    "prompt": str(raw_theme_prompts.get(str(theme.get("id") or "").strip().lower(), theme.get("prompt", "")) or theme.get("prompt", "")).strip(),
                    "enabled": str(theme.get("id") or "").strip().lower() in theme_enabled,
                }
                for theme in theme_presets
                if str(theme.get("id") or "").strip()
            ],
        }

    def mode_labels(self):
        return ["Off", "Auto"]

    def provider_labels(self):
        return ["OpenAI", "xAI / Grok"]

    def size_labels(self):
        return ["Auto", "1024x1024", "1024x1536", "1536x1024"]

    def mode_label_from_value(self, value: str):
        return self._window._visual_reply_mode_label_from_value(value)

    def provider_label_from_value(self, value: str):
        return self._window._visual_reply_provider_label_from_value(value)

    def size_label_from_value(self, value: str):
        return self._window._visual_reply_size_label_from_value(value)

    def normalize_size(self, value: str):
        return self._window._normalize_visual_reply_size(value)

    def attach_settings_widgets(
        self,
        *,
        mode_combo,
        provider_combo,
        size_combo,
        model_edit,
        auto_show_checkbox,
        hint_label,
        story_mode_button=None,
        story_max_images_spin=None,
        story_continuity_slider=None,
        story_continuity_value_label=None,
        story_theme_buttons=None,
        story_theme_edits=None,
    ) -> None:
        self._window.visual_reply_mode_combo = mode_combo
        self._window.visual_reply_provider_combo = provider_combo
        self._window.visual_reply_size_combo = size_combo
        self._window.visual_reply_model_edit = model_edit
        self._window.visual_reply_auto_show_checkbox = auto_show_checkbox
        self._window.visual_reply_hint = hint_label
        if story_mode_button is not None:
            self._window.visual_reply_story_mode_button = story_mode_button
        if story_max_images_spin is not None:
            self._window.visual_reply_story_max_images_spin = story_max_images_spin
        if story_continuity_slider is not None:
            self._window.visual_reply_story_continuity_slider = story_continuity_slider
        if story_continuity_value_label is not None:
            self._window.visual_reply_story_continuity_value_label = story_continuity_value_label
        if story_theme_buttons is not None:
            self._window.visual_reply_story_theme_buttons = dict(story_theme_buttons or {})
        if story_theme_edits is not None:
            self._window.visual_reply_story_theme_edits = dict(story_theme_edits or {})

    def apply_mode(self, choice: str) -> None:
        self._window.on_visual_reply_mode_changed(choice)

    def apply_provider(self, choice: str) -> None:
        self._window.on_visual_reply_provider_changed(choice)

    def apply_size(self, choice: str) -> None:
        self._window.on_visual_reply_size_changed(choice)

    def apply_model(self) -> None:
        self._window.on_visual_reply_model_changed()

    def apply_auto_show(self, checked: bool) -> None:
        self._window.on_visual_reply_auto_show_changed(bool(checked))

    def apply_story_mode(self, checked: bool) -> None:
        self._window.on_visual_reply_story_mode_changed(bool(checked))

    def apply_story_max_images(self, value: int) -> None:
        self._window.on_visual_reply_story_max_images_changed(int(value))

    def apply_story_continuity_strength(self, value: int) -> None:
        self._window.on_visual_reply_story_continuity_strength_changed(int(value))

    def apply_story_theme_toggle(self, theme_id: str, checked: bool) -> None:
        self._window.on_visual_reply_story_theme_toggled(str(theme_id or ""), bool(checked))

    def apply_story_theme_text(self, theme_id: str, text: str) -> None:
        self._window.on_visual_reply_story_theme_text_changed(str(theme_id or ""), str(text or ""))

    def refresh_hint(self) -> None:
        self._window._refresh_visual_reply_hint()

    def replace_panel(self, panel) -> bool:
        dock = getattr(self._window, "visual_reply_dock", None)
        if dock is None or panel is None:
            return False
        old_widget = dock.widget()
        try:
            load_signal = getattr(panel, "loadRequested", None)
            if load_signal is not None:
                load_signal.connect(self._window.prompt_visual_reply_image)
        except Exception:
            pass
        try:
            caption_signal = getattr(panel, "captionRequested", None)
            if caption_signal is not None:
                caption_signal.connect(self._window.prompt_visual_reply_caption)
        except Exception:
            pass
        try:
            clear_signal = getattr(panel, "clearRequested", None)
            if clear_signal is not None:
                clear_signal.connect(lambda: self._window.clear_visual_reply(auto_show=False))
        except Exception:
            pass
        dock.setWidget(panel)
        self._window.visual_reply_panel = panel
        if old_widget is not None and old_widget is not panel:
            try:
                old_widget.deleteLater()
            except Exception:
                pass
        return True

    def show(self) -> None:
        self._window.show_visual_reply_dock()

    def hide(self) -> None:
        dock = getattr(self._window, 'visual_reply_dock', None)
        if dock is not None:
            dock.hide()

    def clear(self, status_text: str = "Visual Reply idle", detail_text: str = "No visual reply yet.\nWhen NC creates an image, it will appear here.", auto_show: bool = False) -> bool:
        return bool(self._window.clear_visual_reply(status_text=status_text, detail_text=detail_text, auto_show=auto_show))

    def set_loading(self, status_text: str = "Visual Reply generating...", detail_text: str = "Preparing image...", auto_show: bool = True) -> bool:
        return bool(self._window.set_visual_reply_loading(status_text=status_text, detail_text=detail_text, auto_show=auto_show))

    def show_image(self, image_path: str, caption: str = "", status_text: str = "Visual Reply", auto_show: bool = True) -> bool:
        return bool(self._window.show_visual_reply_image(image_path, caption=caption, status_text=status_text, auto_show=auto_show))



class QtSensoryService:
    def __init__(self, window):
        self._window = window

    def _refresh_ui(self):
        if hasattr(self._window, "refresh_sensory_feedback_source_options"):
            selected_value = None
            try:
                import engine
                selected_value = str(getattr(engine, "RUNTIME_CONFIG", {}).get("sensory_feedback_source", "off") or "off")
            except Exception:
                selected_value = None
            self._window.refresh_sensory_feedback_source_options(selected_value=selected_value)
        elif hasattr(self._window, "_refresh_sensory_feedback_source_tabs"):
            self._window._refresh_sensory_feedback_source_tabs()

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
        provider = sensory.register_provider(
            provider_id=provider_id,
            label=label,
            instruction=instruction,
            description=description,
            order=order,
            capture_handler=capture_handler,
            metadata=metadata,
        )
        if hasattr(self._window, "refresh_sensory_feedback_source_options"):
            self._window.refresh_sensory_feedback_source_options(selected_value=getattr(provider, "id", ""))
        return provider.to_summary()

    def unregister_provider(self, provider_id: str) -> bool:
        removed = bool(sensory.unregister_provider(provider_id))
        if removed and hasattr(self._window, "refresh_sensory_feedback_source_options"):
            self._window.refresh_sensory_feedback_source_options()
        return removed

    def list_providers(self):
        return [provider.to_summary() for provider in sensory.list_providers()]


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
        contributor = sensory.register_prompt_contributor(
            contributor_id=contributor_id,
            source_id=source_id,
            label=label,
            prompt=prompt,
            order=order,
            metadata=metadata,
        )
        return contributor.to_summary()

    def unregister_prompt_contributor(self, contributor_id: str) -> bool:
        removed = bool(sensory.unregister_prompt_contributor(contributor_id))
        return removed

    def list_prompt_contributors(self, source_id: str | None = None):
        return [item.to_summary() for item in sensory.list_prompt_contributors(source_id)]


class QtChatProviderService:
    def __init__(self, window):
        self._window = window

    def _refresh_ui(self, selected_provider_id: str | None = None):
        if hasattr(self._window, "_populate_chat_provider_combo"):
            self._window._populate_chat_provider_combo(selected_provider_id)

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        description: str = "",
        order: int = 1000,
        client_factory=None,
        model_list_handler=None,
        completion_handler=None,
        stream_handler=None,
        connection_check_handler=None,
        api_key_getter=None,
        base_url_getter=None,
        metadata: dict | None = None,
    ):
        provider = chat_providers.register_provider(
            provider_id=provider_id,
            label=label,
            description=description,
            order=order,
            client_factory=client_factory,
            model_list_handler=model_list_handler,
            completion_handler=completion_handler,
            stream_handler=stream_handler,
            connection_check_handler=connection_check_handler,
            api_key_getter=api_key_getter,
            base_url_getter=base_url_getter,
            metadata=metadata,
        )
        self._refresh_ui(getattr(provider, "id", ""))
        return provider.to_summary()

    def unregister_provider(self, provider_id: str) -> bool:
        removed = bool(chat_providers.unregister_provider(provider_id))
        if removed:
            self._refresh_ui()
        return removed

    def list_providers(self):
        return [provider.to_summary() for provider in chat_providers.list_providers()]

    def get_provider_settings(self, provider_id: str | None = None):
        return chat_providers.get_provider_settings(provider_id)

    def get_provider_setting(self, provider_id: str, field_id: str):
        return chat_providers.get_provider_setting(provider_id, field_id)


class QtAvatarProviderService:
    def __init__(self, window):
        self._window = window

    def _refresh_ui(self, selected_provider_id: str | None = None):
        refresh = getattr(self._window, "refresh_avatar_engine_options", None)
        if callable(refresh):
            refresh(selected_provider_id=selected_provider_id)

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
        provider = avatar_runtime.register_provider(
            provider_id=provider_id,
            label=label,
            factory=factory,
            description=description,
            order=order,
            metadata=metadata,
        )
        self._refresh_ui(getattr(provider, "id", ""))
        return provider.to_summary()

    def unregister_provider(self, provider_id: str) -> bool:
        removed = bool(avatar_runtime.unregister_provider(provider_id))
        if removed:
            self._refresh_ui()
        return removed

    def list_providers(self):
        return [provider.to_summary() for provider in avatar_runtime.list_providers()]


class QtChatReplayService:
    def __init__(self, window):
        self._window = window

    def snapshot_chat_session(self):
        import engine

        return dict(engine.export_chat_session_state() or {})

    def replayable_assistant_entries(self):
        import engine

        return list(engine.collect_replayable_assistant_entries())

    def replayable_assistant_messages(self):
        import engine

        return list(engine.collect_replayable_assistant_messages())

    def is_engine_running(self) -> bool:
        thread = getattr(self._window, "thread", None)
        return bool(thread and thread.is_alive())

    def is_offline_replay_only(self) -> bool:
        checker = getattr(self._window, "_engine_is_offline_replay_only", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return False

    def trigger_control_action(self, action: str) -> None:
        self._window.trigger_control_action(str(action or "").strip())

    def replay_latest_reply(self) -> None:
        self.trigger_control_action("replay_last_assistant")

    def replay_chat_session(self) -> None:
        self.trigger_control_action("replay_chat_session")

    def replay_chat_session_from_index(self, start_index: int) -> None:
        import engine

        self.trigger_control_action(engine.build_replay_chat_session_from_action(start_index))

    def load_chat_context(self) -> None:
        self._window.load_chat_context()

    def quick_load_chat_context(self) -> None:
        self._window.quick_load_chat_context()

    def save_chat_context(self) -> None:
        self._window.save_chat_context()

    def quick_save_chat_context(self) -> None:
        self._window.quick_save_chat_context()


class AddonCapabilityBridgeService:
    def __init__(self, manager_getter):
        self._manager_getter = manager_getter

    def invoke(self, capability: str, payload=None):
        manager = self._manager_getter()
        if manager is None:
            return None
        return manager.invoke_capability(str(capability or ""), dict(payload or {}))


class QtMuseTalkUIService:
    def __init__(self, window):
        self._window = window

    def _preview_widget(self):
        return getattr(self._window, "embedded_musetalk_preview", None)

    def publish_preview_frame(self, *, frame_path: str, avatar_id: str, mode_label: str) -> bool:
        import time

        publish_time = time.time()
        frame_identity = Path(frame_path).stem if frame_path else "frame"
        chunk_id = f"first_frame_test:{avatar_id}:{frame_identity}"
        shared_state.set_current_musetalk_frame_data({
            "frame_paths": [frame_path] if frame_path else [],
            "frame_dir": str(Path(frame_path).parent) if frame_path else "",
            "fps": 24,
            "sync_time": publish_time,
            "duration_seconds": 0.0,
            "expected_frame_count": 1,
            "trim_start_frames": 0,
            "chunk_id": chunk_id,
            "text": f"{mode_label} for {avatar_id}",
            "status": "ready",
            "loop": False,
            "start_index": 0,
            "source_indices": [0],
            "avatar_id": avatar_id,
            "published_at": publish_time,
        })
        shared_state.write_musetalk_preview_frame({
            "chunk_id": chunk_id,
            "status": "ready",
            "loop": False,
            "frame_path": frame_path,
            "frame_index": 0,
            "source_index": 0,
            "fps": 24,
            "emitted_at": publish_time,
        })
        preview_loaded = False
        preview_dock = getattr(self._window, "preview_dock", None)
        if preview_dock is not None:
            preview_dock.show()
            preview_dock.raise_()
        preview_widget = self._preview_widget()
        if preview_widget is not None:
            preview_loaded = bool(
                preview_widget.show_static_frame(
                    frame_path,
                    f"MuseTalk {mode_label.lower()}: {avatar_id}",
                )
            )
        return preview_loaded

    def configure_debug_mask_editor(self, *, base_frame_path: str, mask_frame_path: str, bbox, crop_box, modified_mask_path: str | None = None) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "configure_debug_mask_editor"):
            return False
        return bool(
            preview_widget.configure_debug_mask_editor(
                base_frame_path=base_frame_path,
                mask_frame_path=mask_frame_path,
                bbox=bbox,
                crop_box=crop_box,
                modified_mask_path=modified_mask_path,
            )
        )

    def set_debug_mask_brush(self, *, radius: int | None = None, feather: int | None = None) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "set_debug_mask_brush"):
            return False
        return bool(preview_widget.set_debug_mask_brush(radius=radius, feather=feather))

    def adjust_preview_zoom(self, factor_delta: float) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "adjust_zoom"):
            return False
        return bool(preview_widget.adjust_zoom(factor_delta))

    def reset_preview_zoom(self) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "reset_zoom"):
            return False
        return bool(preview_widget.reset_zoom())

    def clear_debug_mask_editor(self) -> None:
        preview_widget = self._preview_widget()
        if preview_widget is not None and hasattr(preview_widget, "clear_debug_mask_editor"):
            preview_widget.clear_debug_mask_editor()
