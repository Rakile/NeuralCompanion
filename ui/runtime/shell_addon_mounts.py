"""Addon live-mount helpers for the Designer shell/runtime UI."""

import importlib.util
import re
from collections import OrderedDict
from pathlib import Path


def configure_shell_addon_mount_dependencies(namespace):
    """Inject qt_app-owned services/constants without importing qt_app here."""
    globals().update(dict(namespace or {}))


def _ui_shell_tab_title_exists(tab_widget, title):
    titles = _ui_shell_tab_titles(tab_widget)
    return str(title or "") in titles


def _ui_shell_tab_titles(tab_widget):
    titles = set()
    if tab_widget is None or not hasattr(tab_widget, "count"):
        return titles
    for index in range(tab_widget.count()):
        try:
            title = str(tab_widget.tabText(index) or "")
        except Exception:
            title = ""
        if title:
            titles.add(title)
    return titles


def _ui_shell_add_placeholder_tab(tab_widget, title, body_text):
    from PySide6 import QtWidgets as _QtWidgets

    if tab_widget is None or not hasattr(tab_widget, "addTab"):
        return False
    if _ui_shell_tab_title_exists(tab_widget, title):
        return False
    panel = _QtWidgets.QWidget()
    layout = _QtWidgets.QVBoxLayout(panel)
    layout.setContentsMargins(12, 12, 12, 12)
    heading = _QtWidgets.QLabel("Read-only addon mount preview")
    heading.setStyleSheet("font-weight: 700; color: #cbd5e1;")
    layout.addWidget(heading)
    text = _QtWidgets.QPlainTextEdit()
    text.setReadOnly(True)
    text.setPlainText(str(body_text or ""))
    text.setToolTip("Shell-only preview. Addon modules are not imported and no runtime systems are started.")
    layout.addWidget(text, 1)
    tab_widget.addTab(panel, title)
    if hasattr(tab_widget, "setVisible"):
        tab_widget.setVisible(True)
    return True


def _ui_shell_static_addon_placeholder_name(addon_id):
    addon_id = str(addon_id or "").strip().lower()
    if addon_id == "nc.chat_session_player":
        return "chat_player_tab"
    if addon_id == "nc.hotkeys":
        return "hotkeys_tab"
    if addon_id == "nc.visual_reply":
        return "host_settings_visuals_tab"
    if addon_id == "nc.audio_story_mode":
        return "audio_story_mode_tab"
    if addon_id == "nc.chatterbox_tts":
        return "tts_chatterbox_tab"
    if addon_id == "nc.pockettts":
        return "tts_pockettts_tab"
    return ""


def _ui_shell_replace_static_addon_placeholder(tab_widget, placeholder_name, widget, title, tooltip=""):
    if tab_widget is None or widget is None or not placeholder_name:
        return -1
    from PySide6 import QtWidgets as _QtWidgets

    placeholder = tab_widget.findChild(_QtWidgets.QWidget, str(placeholder_name))
    if placeholder is None:
        return -1
    index = tab_widget.indexOf(placeholder)
    if index < 0:
        return -1
    tab_icon = tab_widget.tabIcon(index)
    tab_text = str(tab_widget.tabText(index) or "").strip() or str(title or "").strip()
    tab_tooltip = str(tab_widget.tabToolTip(index) or "").strip() or str(tooltip or "").strip()
    tab_widget.removeTab(index)
    placeholder.setParent(None)
    placeholder.deleteLater()
    new_index = tab_widget.insertTab(index, widget, tab_text)
    if not tab_icon.isNull():
        tab_widget.setTabIcon(new_index, tab_icon)
    if tab_tooltip:
        tab_widget.setTabToolTip(new_index, tab_tooltip)
    return new_index


def _ui_shell_prepare_live_addon_widget(addon_id, widget):
    return


def _ui_shell_contribution_title(contribution, manifest):
    title = str(getattr(contribution, "title", "") or getattr(contribution, "id", "") or getattr(manifest, "name", "") or "Addon").strip()
    parent = str(getattr(contribution, "parent_tab_id", "") or "").strip().lower()
    parent_labels = {
        "screen": "Screen",
        "webcam": "Webcam",
        "clipboard": "Clipboard",
        "heart_rate": "Heart Rate",
    }
    if parent in parent_labels:
        return f"{parent_labels[parent]} / {title}"
    return title

def _ui_shell_contribution_icon(contribution, manifest):
    metadata = dict(getattr(contribution, "metadata", {}) or {})
    icon_path = str(metadata.get("icon_path") or "").strip()
    if not icon_path:
        return None
    try:
        from PySide6 import QtGui as _QtGui

        raw_path = Path(icon_path)
        root_dir = getattr(manifest, "root_dir", None)
        resolved_path = raw_path if raw_path.is_absolute() else Path(root_dir or "") / raw_path
        icon = _QtGui.QIcon(str(resolved_path))
        return icon if not icon.isNull() else None
    except Exception:
        return None

def _ui_shell_set_contribution_icon(tab_widget, tab_index, contribution, manifest):
    if tab_widget is None or tab_index is None or int(tab_index) < 0:
        return
    icon = _ui_shell_contribution_icon(contribution, manifest)
    if icon is None:
        return
    try:
        tab_widget.setTabIcon(int(tab_index), icon)
    except Exception:
        pass


def _apply_ui_shell_addon_placeholders(window, report, exclude_addon_ids=None, live_chat_providers=None):
    placeholders = {
        "left_tabs": "Addon Mounts",
        "host_settings_tabs": "Addon Preview",
        "right_tabs": "Addon Preview",
        "musetalk_tabs": "Addon Preview",
        "tts_runtime_addon_tabs": "Addon Preview",
        "sensory_feedback_tabs": "Addon Preview",
    }
    added = []
    for target, title in placeholders.items():
        rows = _ui_shell_rows_for_target(report, target, exclude_addon_ids=exclude_addon_ids)
        if not rows:
            continue
        tab_widget = _ui_shell_find_object(window, target)
        if _ui_shell_add_placeholder_tab(tab_widget, title, _ui_shell_addon_rows_text(rows)):
            added.append(target)

    live_provider_text = _ui_shell_chat_provider_rows_text(live_chat_providers)
    chat_provider_rows = _ui_shell_rows_for_target(report, "chat_provider_combo", exclude_addon_ids=exclude_addon_ids)
    if live_provider_text or chat_provider_rows:
        parts = []
        if live_provider_text:
            parts.append(live_provider_text)
        if chat_provider_rows:
            parts.append(
                "Read-only shell preview. Placeholder-only chat provider addons discovered:\n"
                + _ui_shell_addon_rows_text(chat_provider_rows)
            )
        text = "\n\n".join(parts)
        for object_name in ("chat_provider_fields_placeholder", "chat_provider_generation_fields_placeholder"):
            placeholder = _ui_shell_find_object(window, object_name)
            if placeholder is not None and hasattr(placeholder, "setText"):
                placeholder.setText(text)
                if hasattr(placeholder, "setToolTip"):
                    placeholder.setToolTip("Shell-only provider addon preview. Registered provider handlers are not invoked.")
                added.append(object_name)
    return sorted(set(added))


def _ui_shell_load_addon_module(manifest):
    root = Path(str(manifest.get("root") or "")).resolve()
    entry_point = str(manifest.get("entry_point") or "main.py").strip() or "main.py"
    entry_path = root / entry_point
    module_name = "nc_ui_shell_addon_" + re.sub(r"[^a-zA-Z0-9_]", "_", str(manifest.get("id") or root.name))
    spec = importlib.util.spec_from_file_location(module_name, entry_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load addon entry point: {entry_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ui_shell_mount_live_addons(window, report):
    from PySide6 import QtWidgets as _QtWidgets
    from core.addons.context import AddonContext, AddonEventBus, AddonServiceRegistry
    from core.addons.manifest import AddonManifest

    _ui_shell_enable_stdio_unicode_fallback()
    configure_shell_service_dependencies(globals())

    mounted = []
    mounted_ids = []
    failures = []
    live_refs = []
    live_tabs = []
    tts_backends_by_id = OrderedDict()
    app_root = Path(__file__).resolve().parents[2]
    storage_root = app_root / "runtime" / "addons" / "ui_shell"
    event_bus = AddonEventBus()
    service_registry = AddonServiceRegistry()
    chat_provider_registry = _UiShellChatProviderRegistry()
    sensory_registry = _UiShellSensoryService()
    avatar_provider_registry = _UiShellAvatarProviderService()
    host_services = {
        "qt.avatar_providers": avatar_provider_registry,
        "qt.chat_providers": chat_provider_registry,
        "qt.chat_context": _ui_shell_chat_context_service(window),
        "qt.chat_replay": _ui_shell_chat_replay_service(window),
        "qt.dialogs": _UiShellDialogService(window),
        "qt.dry_run": _ui_shell_dry_run_service(window),
        "qt.engine_lifecycle": _ui_shell_engine_lifecycle_service(window),
        "qt.hotkeys": _UiShellHotkeyService(),
        "qt.input_actions": _ui_shell_input_actions_service(window),
        "qt.input_settings": _ui_shell_input_settings_service(window),
        "qt.persona_avatar": _ui_shell_persona_avatar_service(window),
        "qt.performance_profiles": _ui_shell_performance_profile_service(window),
        "qt.model_refresh": _ui_shell_model_refresh_service(window),
        "qt.runtime_controls": _ui_shell_runtime_controls_service(window),
        "qt.runtime_status": _ui_shell_runtime_status_service(window),
        "qt.sensory": sensory_registry,
        "qt.shell": _UiShellShellService(),
        "qt.tutorials": _ui_shell_tutorial_service(window),
        "qt.visual_reply": _UiShellVisualReplyService(window),
        "qt.audio_story_mode_shell_preview": True,
        "qt.chatterbox_tts_shell_preview": True,
        "qt.pockettts_shell_preview": True,
        "qt.clipboard_source_shell_preview": True,
        "qt.gemini_tts_preview_shell_preview": True,
        "qt.musetalk_preprocess_shell_preview": True,
        "qt.shell_session_snapshot": _read_ui_shell_session_snapshot,
    }

    rows_by_id = {
        str(row.get("id") or "").strip(): row
        for row in report.get("addons", [])
    }
    for addon_id in sorted(UI_SHELL_LIVE_ADDON_IDS):
        row = rows_by_id.get(addon_id)
        if not row or not row.get("enabled"):
            continue
        try:
            manifest_path = Path(str(row.get("root") or "")) / "addon.json"
            manifest = AddonManifest.from_file(manifest_path)
            context = AddonContext(
                manifest=manifest,
                app_root=app_root,
                event_bus=event_bus,
                service_registry=service_registry,
                storage_root=storage_root,
                llm_snapshot_getter=lambda: {},
                tts_snapshot_getter=lambda: {},
                avatar_snapshot_getter=lambda: {},
                host_services=host_services,
            )
            provider_ids_before = chat_provider_registry.provider_ids()
            avatar_provider_ids_before = {str(item.get("id") or "").strip() for item in avatar_provider_registry.list_providers()}
            sensory_provider_ids_before = {str(item.get("id") or "").strip() for item in sensory_registry.list_providers()}
            service_names_before = {str(item.get("name") or "").strip() for item in service_registry.list_entries()}
            module = _ui_shell_load_addon_module(row)
            addon_cls = getattr(module, "Addon", None)
            if addon_cls is None:
                raise RuntimeError("Addon class is missing.")
            addon = addon_cls()
            addon.initialize(context)
            provider_ids_after = chat_provider_registry.provider_ids()
            added_provider_ids = sorted(provider_ids_after - provider_ids_before)
            avatar_provider_ids_after = {str(item.get("id") or "").strip() for item in avatar_provider_registry.list_providers()}
            sensory_provider_ids_after = {str(item.get("id") or "").strip() for item in sensory_registry.list_providers()}
            service_entries_after = service_registry.list_entries()
            service_names_after = {str(item.get("name") or "").strip() for item in service_entries_after}
            added_avatar_provider_ids = sorted(avatar_provider_ids_after - avatar_provider_ids_before)
            added_sensory_provider_ids = sorted(sensory_provider_ids_after - sensory_provider_ids_before)
            added_tts_backend_summaries = []
            for entry in service_entries_after:
                service_name = str(entry.get("name") or "").strip()
                if not service_name or service_name not in (service_names_after - service_names_before):
                    continue
                metadata = dict(entry.get("metadata") or {})
                if str(metadata.get("kind") or "").strip().lower() != "tts":
                    continue
                backend_id = str(metadata.get("backend_id") or service_name).strip()
                if not backend_id:
                    continue
                summary = {
                    "id": backend_id,
                    "service_name": service_name,
                    "label": str(metadata.get("label") or backend_id).strip() or backend_id,
                    "provider": str(metadata.get("provider") or "").strip(),
                    "supports_streaming": bool(metadata.get("supports_streaming", False)),
                    "owner_addon_id": str(entry.get("owner_addon_id") or "").strip(),
                    "metadata": metadata,
                }
                tts_backends_by_id[backend_id] = summary
                added_tts_backend_summaries.append(dict(summary))
            contributions = sorted(context.ui.get_tab_contributions(), key=lambda item: (int(item.order), str(item.title or item.id)))
            added_tabs = []
            for contribution in contributions:
                target = _ui_shell_mount_target_for_area(str(contribution.area or "top_level"))
                if not target:
                    continue
                tab_widget = _ui_shell_find_object(window, target)
                if tab_widget is None or not hasattr(tab_widget, "addTab"):
                    failures.append(f"{addon_id}: mount point unavailable for area {contribution.area!r}")
                    continue
                widget = contribution.factory(context)
                if not isinstance(widget, _QtWidgets.QWidget):
                    raise RuntimeError(f"Tab factory for {contribution.id} did not return a QWidget.")
                _ui_shell_prepare_live_addon_widget(addon_id, widget)
                title = _ui_shell_contribution_title(contribution, manifest)
                placeholder_name = _ui_shell_static_addon_placeholder_name(addon_id)
                tab_index = _ui_shell_replace_static_addon_placeholder(
                    tab_widget,
                    placeholder_name,
                    widget,
                    title,
                    str(contribution.tooltip or ""),
                )
                replaced_static_placeholder = tab_index >= 0
                if tab_index < 0:
                    tab_widget.addTab(widget, title)
                    tab_index = tab_widget.indexOf(widget)
                _ui_shell_set_contribution_icon(tab_widget, tab_index, contribution, manifest)
                if tab_index >= 0 and contribution.tooltip:
                    tab_widget.setTabToolTip(tab_index, str(contribution.tooltip or ""))
                if hasattr(tab_widget, "setVisible"):
                    tab_widget.setVisible(True)
                added_tabs.append(f"{target}/{title}")
                live_tabs.append({
                    "addon_id": addon_id,
                    "target": target,
                    "title": title,
                    "replaced_static_placeholder": replaced_static_placeholder,
                    "placeholder_name": placeholder_name,
                })
            added_provider_summaries = [
                provider
                for provider in chat_provider_registry.list_providers()
                if str(provider.get("id") or "").strip() in set(added_provider_ids)
            ]
            added_avatar_provider_summaries = [
                provider
                for provider in avatar_provider_registry.list_providers()
                if str(provider.get("id") or "").strip() in set(added_avatar_provider_ids)
            ]
            added_sensory_provider_summaries = [
                provider
                for provider in sensory_registry.list_providers()
                if str(provider.get("id") or "").strip() in set(added_sensory_provider_ids)
            ]
            if added_tabs or added_provider_summaries or added_avatar_provider_summaries or added_sensory_provider_summaries or added_tts_backend_summaries:
                details = []
                if added_tabs:
                    details.append(", ".join(added_tabs))
                if added_provider_summaries:
                    labels = ", ".join(
                        f"chat_provider/{provider.get('label') or provider.get('id')}"
                        for provider in added_provider_summaries
                    )
                    details.append(labels)
                if added_avatar_provider_summaries:
                    labels = ", ".join(
                        f"avatar_provider/{provider.get('label') or provider.get('id')}"
                        for provider in added_avatar_provider_summaries
                    )
                    details.append(labels)
                if added_sensory_provider_summaries:
                    labels = ", ".join(
                        f"sensory_provider/{provider.get('label') or provider.get('id')}"
                        for provider in added_sensory_provider_summaries
                    )
                    details.append(labels)
                if added_tts_backend_summaries:
                    labels = ", ".join(
                        f"tts_backend/{backend.get('label') or backend.get('id')}"
                        for backend in added_tts_backend_summaries
                    )
                    details.append(labels)
                mounted.append(f"{addon_id}: {'; '.join(details)}")
                mounted_ids.append(addon_id)
                live_refs.append({
                    "addon": addon,
                    "context": context,
                    "tabs": added_tabs,
                    "providers": added_provider_ids,
                    "avatar_providers": added_avatar_provider_ids,
                    "sensory_providers": added_sensory_provider_ids,
                    "tts_backends": [str(item.get("id") or "").strip() for item in added_tts_backend_summaries],
                })
            else:
                context.close()
                failures.append(f"{addon_id}: no supported top-level tabs registered")
        except Exception as exc:
            failures.append(f"{addon_id}: {exc}")
    setattr(window, "_nc_ui_shell_live_addons", live_refs)
    setattr(window, "_nc_ui_shell_live_services", {
        "chat_provider_registry": chat_provider_registry,
        "avatar_provider_registry": avatar_provider_registry,
        "sensory_registry": sensory_registry,
    })
    return {
        "mounted": mounted,
        "failures": failures,
        "mounted_ids": sorted(set(mounted_ids)),
        "chat_providers": chat_provider_registry.list_providers(),
        "avatar_providers": avatar_provider_registry.list_providers(),
        "sensory_providers": sensory_registry.list_providers(),
        "tts_backends": list(tts_backends_by_id.values()),
        "live_tabs": live_tabs,
    }


def _ui_shell_cleanup_live_addons(window):
    refs = list(getattr(window, "_nc_ui_shell_live_addons", []) or [])
    setattr(window, "_nc_ui_shell_live_addons", [])
    setattr(window, "_nc_ui_shell_live_services", {})
    for ref in refs:
        addon = ref.get("addon")
        context = ref.get("context")
        try:
            if addon is not None and hasattr(addon, "shutdown"):
                addon.shutdown()
        except Exception:
            pass
        try:
            if context is not None and hasattr(context, "close"):
                context.close()
        except Exception:
            pass
