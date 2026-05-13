"""Designer UI validation helpers for main.ui shell and real-runtime modes."""

from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET

from core.addons.contributions import known_addon_service_ids, ui_required_static_mount_targets, ui_target_for_area


UI_VALIDATION_REQUIRED_GROUPS = (
    (
        "Core Shell",
        (
            ("CompanionQtMainWindow", "QMainWindow"),
            ("workspace_central", "QWidget"),
            ("SystemShapingDock", "QDockWidget"),
            ("WorkspaceTabsDock", "QDockWidget"),
            ("OperationalViewDock", "QDockWidget"),
            ("PreviewDock", "QDockWidget"),
            ("VisualReplyDock", "QDockWidget"),
        ),
    ),
    (
        "Stable Tab Mounts",
        (
            ("host_settings_tabs", "QTabWidget"),
            ("left_tabs", "QTabWidget"),
            ("right_tabs", "QTabWidget"),
            ("sensory_feedback_tabs", "QTabWidget"),
        ),
    ),
    (
        "Dynamic Mount Points",
        (
            ("left_tabs", "QTabWidget"),
            ("host_settings_tabs", "QTabWidget"),
            ("right_tabs", "QTabWidget"),
            ("tts_runtime_addon_tabs", "QTabWidget"),
            ("sensory_feedback_tabs", "QTabWidget"),
            ("sensory_feedback_sources_widget", "QWidget"),
            ("chat_provider_fields_widget", "QWidget"),
            ("chat_provider_generation_fields_widget", "QWidget"),
            ("chat_provider_fields_layout", "QFormLayout"),
            ("chat_provider_generation_fields_layout", "QFormLayout"),
        ),
    ),
    (
        "Stable Runtime Controls",
        (
            ("listen_diode", "QFrame"),
            ("mic_diode", "QFrame"),
            ("mic_status_label", "QLabel"),
            ("audio_input_device_combo", "QComboBox"),
            ("audio_output_device_combo", "QComboBox"),
            ("engine_combo", "QComboBox"),
            ("input_mode_combo", "QComboBox"),
            ("input_role_combo", "QComboBox"),
            ("stream_mode_combo", "QComboBox"),
            ("tts_backend_combo", "QComboBox"),
            ("musetalk_vram_combo", "QComboBox"),
            ("musetalk_loop_fade_spin", "QSpinBox"),
            ("musetalk_avatar_pack_combo", "QComboBox"),
            ("preset_combo", "QComboBox"),
            ("chat_provider_combo", "QComboBox"),
            ("model_combo", "QComboBox"),
            ("sensory_feedback_source_combo", "QComboBox"),
            ("sensory_feedback_sources_widget", "QWidget"),
            ("console_status", "QLabel"),
            ("console_autoscroll_button", "QPushButton"),
            ("console_clear_button", "QPushButton"),
            ("console_edit", "QPlainTextEdit"),
            ("chat_status", "QLabel"),
            ("chat_font_size_combo", "QComboBox"),
            ("chat_quick_save_button", "QPushButton"),
            ("chat_quick_load_button", "QPushButton"),
            ("chat_edit_mode_button", "QPushButton"),
            ("chat_apply_edit_button", "QPushButton"),
            ("chat_cancel_edit_button", "QPushButton"),
            ("chat_autoscroll_button", "QPushButton"),
            ("chat_clear_button", "QPushButton"),
            ("chat_edit", "QTextEdit"),
            ("chat_message_input", "QLineEdit"),
            ("chat_send_button", "QPushButton"),
            ("btn_regenerate", "QPushButton"),
            ("btn_retry", "QPushButton"),
            ("btn_pause", "QPushButton"),
            ("btn_skip", "QPushButton"),
            ("btn_skip_user", "QPushButton"),
            ("btn_start_engine", "QPushButton"),
            ("btn_stop_engine", "QPushButton"),
            ("btn_reset_chat", "QPushButton"),
        ),
    ),
)

UI_VALIDATION_DYNAMIC_OWNED_PREFIXES = (
    "audio_story_",
)

UI_VALIDATION_DYNAMIC_OWNED_NAMES = {
    "story_mode_button",
    "visual_master_prompt_label",
    "visual_master_prompt_no_speech_bubbles_button",
    "visual_master_prompt_safe_button",
    "visual_master_prompt_text",
    "visual_reply_caption_button",
    "visual_reply_clear_button",
    "visual_reply_delete_all_button",
    "visual_reply_delete_button",
    "visual_reply_frame",
    "visual_reply_image_label",
    "visual_reply_load_button",
    "visual_reply_load_current_story_button",
    "visual_reply_next_button",
    "visual_reply_panel",
    "visual_reply_previous_button",
    "visual_reply_status",
    "visual_reply_storage_label",
    "visual_reply_story_max_images_spin",
    "visual_reply_use_current_style_button",
    "theme_anime",
    "theme_anime_edit",
    "theme_cartoon",
    "theme_cartoon_edit",
    "theme_cyberpunk",
    "theme_cyberpunk_edit",
    "theme_realistic",
    "theme_realistic_edit",
    "theme_retro",
    "theme_retro_edit",
    "theme_storybook",
    "theme_storybook_edit",
}

UI_REAL_PREVIEW_ONLY_ROOTS = (
    {
        "object_name": "audio_story_mode_tab",
        "adopted_target": "right_tabs",
        "adopted_title": "Audio Story Mode",
        "reason": "Static Designer Audio Story placeholder. The live addon-owned Audio Story surface is mounted here in --ui-real.",
    },
    {
        "object_name": "host_settings_visuals_tab",
        "adopted_target": "host_settings_tabs",
        "adopted_title": "Visuals",
        "reason": "Static Designer Visuals placeholder. The live addon-owned Visuals surface is mounted here in --ui-real.",
    },
    {
        "object_name": "host_settings_story_visuals_tab",
        "adopted_target": "host_settings_tabs",
        "adopted_title": "Story Visuals",
        "reason": "Static Designer Story Visuals placeholder. The live addon-owned Story Visuals surface is mounted here in --ui-real.",
    },
    {
        "object_name": "tts_chatterbox_tab",
        "adopted_target": "tts_runtime_addon_tabs",
        "adopted_title": "Chatterbox",
        "reason": "Static Designer Chatterbox placeholder. The live TTS runtime addon tab is mounted here in --ui-real.",
    },
    {
        "object_name": "tts_pockettts_tab",
        "adopted_target": "tts_runtime_addon_tabs",
        "adopted_title": "PocketTTS",
        "reason": "Static Designer PocketTTS placeholder. The live TTS runtime addon tab is mounted here in --ui-real.",
    },
    {
        "object_name": "visual_reply_panel_legacy",
        "runtime_flag": "_visual_reply_runtime_redirected",
        "reason": "Legacy Visual Reply Designer panel. The live Visual Reply runtime panel is mounted in the dock in --ui-real.",
    },
)

UI_SHELL_TAB_MOUNT_WIDGETS = ui_required_static_mount_targets()


def resolve_ui_path(raw_path, *, base_path=None):
    ui_path = Path(str(raw_path or "").strip() or "main.ui")
    if ui_path.is_absolute():
        return ui_path
    base = Path(base_path).resolve().parent if base_path else Path.cwd()
    return base / ui_path


def collect_ui_object_classes(ui_path):
    tree = ET.parse(ui_path)
    objects = {}
    duplicates = []
    seen = {}
    for element in tree.getroot().iter():
        if element.tag not in {"widget", "layout", "action"}:
            continue
        object_name = str(element.attrib.get("name") or "").strip()
        if not object_name:
            continue
        object_class = str(element.attrib.get("class") or element.tag or "").strip()
        if object_name in seen:
            duplicates.append((object_name, seen[object_name], object_class))
        else:
            seen[object_name] = object_class
        objects[object_name] = object_class
    return objects, duplicates


def ui_shell_tab_page_title(tab_page):
    for attribute_element in tab_page.findall("attribute"):
        if str(attribute_element.attrib.get("name") or "") != "title":
            continue
        string_element = attribute_element.find("string")
        if string_element is not None and string_element.text is not None:
            return str(string_element.text or "").strip()
    for property_element in tab_page.findall("property"):
        if str(property_element.attrib.get("name") or "") != "title":
            continue
        string_element = property_element.find("string")
        if string_element is not None and string_element.text is not None:
            return str(string_element.text or "").strip()
    for attribute_element in tab_page.findall("attribute"):
        if str(attribute_element.attrib.get("name") or "") != "toolTip":
            continue
        string_element = attribute_element.find("string")
        if string_element is not None and string_element.text is not None:
            return str(string_element.text or "").strip()
    return ""


def collect_ui_shell_static_tabs(ui_path):
    try:
        tree = ET.parse(ui_path)
    except Exception:
        return {}
    tab_widgets = {}
    for widget in tree.getroot().iter("widget"):
        if str(widget.attrib.get("class") or "") != "QTabWidget":
            continue
        object_name = str(widget.attrib.get("name") or "").strip()
        if object_name not in UI_SHELL_TAB_MOUNT_WIDGETS:
            continue
        pages = []
        for child in list(widget):
            if child.tag != "widget":
                continue
            page_name = str(child.attrib.get("name") or "").strip()
            page_title = ui_shell_tab_page_title(child) or page_name or "(untitled)"
            pages.append({"object_name": page_name, "title": page_title})
        tab_widgets[object_name] = pages
    return tab_widgets


def collect_legacy_addon_tab_registrations(ui_path):
    app_root = Path(ui_path).resolve().parent
    addons_root = app_root / "addons"
    if not addons_root.exists():
        return []
    findings = []
    for main_path in sorted(addons_root.glob("*/main.py")):
        try:
            lines = main_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as exc:
            findings.append((str(main_path.relative_to(app_root)), 0, f"could not read: {exc}"))
            continue
        for line_number, line in enumerate(lines, start=1):
            stripped = str(line or "").strip()
            if "context.ui.register_tab(" in stripped or ".ui.register_tab(" in stripped:
                findings.append((str(main_path.relative_to(app_root)), line_number, stripped))
    return findings


def collect_direct_addon_designer_tab_registrations(ui_path):
    app_root = Path(ui_path).resolve().parent
    addons_root = app_root / "addons"
    if not addons_root.exists():
        return []
    findings = []
    for main_path in sorted(addons_root.glob("*/main.py")):
        try:
            lines = main_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line_number, line in enumerate(lines, start=1):
            stripped = str(line or "").strip()
            if "register_designer_tab(" in stripped and "register_manifest_designer_tab(" not in stripped:
                findings.append((str(main_path.relative_to(app_root)), line_number, stripped))
    return findings


def collect_addon_designer_fallback_registrations(ui_path):
    app_root = Path(ui_path).resolve().parent
    addons_root = app_root / "addons"
    if not addons_root.exists():
        return []
    findings = []
    for main_path in sorted(addons_root.glob("*/main.py")):
        try:
            lines = main_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line_number, line in enumerate(lines, start=1):
            stripped = str(line or "").strip()
            if "fallback_factory=" in stripped:
                findings.append((str(main_path.relative_to(app_root)), line_number, stripped))
    return findings


def collect_addon_legacy_tab_builders(ui_path):
    app_root = Path(ui_path).resolve().parent
    addons_root = app_root / "addons"
    if not addons_root.exists():
        return []
    findings = []
    for path in sorted(addons_root.glob("*/*.py")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for line_number, line in enumerate(lines, start=1):
            stripped = str(line or "").strip()
            if re.match(r"def\s+build_tab\s*\(", stripped):
                findings.append((str(path.relative_to(app_root)), line_number, stripped))
    return findings


def collect_invalid_addon_designer_tabs(ui_path):
    app_root = Path(ui_path).resolve().parent
    addons_root = app_root / "addons"
    if not addons_root.exists():
        return []
    findings = []
    for main_path in sorted(addons_root.glob("*/main.py")):
        try:
            text = main_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            findings.append((str(main_path.relative_to(app_root)), 0, f"could not read: {exc}"))
            continue
        addon_root = main_path.parent
        for match in re.finditer(r"register_designer_tab\s*\(", text):
            body = text[match.start(): match.start() + 2000]
            line_number = text[: match.start()].count("\n") + 1
            path_match = re.search(r"ui_path\s*=\s*[\"']([^\"']+)[\"']", body)
            if not path_match:
                findings.append((str(main_path.relative_to(app_root)), line_number, "missing ui_path"))
                continue
            raw_path = str(path_match.group(1) or "").strip()
            resolved = Path(raw_path)
            if not resolved.is_absolute():
                resolved = addon_root / resolved
            if not resolved.exists():
                findings.append((str(main_path.relative_to(app_root)), line_number, f"ui_path not found: {raw_path}"))
            icon_match = re.search(r"icon_path\s*=\s*[\"']([^\"']+)[\"']", body)
            if icon_match:
                raw_icon_path = str(icon_match.group(1) or "").strip()
                resolved_icon = Path(raw_icon_path)
                if not resolved_icon.is_absolute():
                    resolved_icon = addon_root / resolved_icon
                if not resolved_icon.exists():
                    findings.append((str(main_path.relative_to(app_root)), line_number, f"icon_path not found: {raw_icon_path}"))
    return findings


def collect_invalid_addon_manifest_ui(ui_path, objects):
    app_root = Path(ui_path).resolve().parent
    addons_root = app_root / "addons"
    if not addons_root.exists():
        return []
    known_service_ids = set(known_addon_service_ids())
    findings = []
    for manifest_path in sorted(addons_root.glob("*/addon.json")):
        relative_path = str(manifest_path.relative_to(app_root))
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            findings.append((relative_path, 0, f"could not read manifest: {exc}"))
            continue
        addon_root = manifest_path.parent
        addon_id = str(manifest.get("id") or addon_root.name).strip()
        ui_entries = manifest.get("ui") or []
        if not isinstance(ui_entries, list):
            findings.append((relative_path, 0, "'ui' must be a list when present"))
            continue
        ui_entries_valid = [entry for entry in ui_entries if isinstance(entry, dict)]
        services = manifest.get("services") or []
        services_valid = []
        if not isinstance(services, list):
            findings.append((relative_path, 0, "'services' must be a list when present"))
        else:
            seen_services = set()
            for service_index, service in enumerate(services, start=1):
                if not isinstance(service, dict):
                    findings.append((relative_path, service_index, "service entry must be an object"))
                    continue
                service_id = str(service.get("id") or "").strip()
                if not service_id:
                    findings.append((relative_path, service_index, "service entry missing id"))
                    continue
                if service_id not in known_service_ids:
                    findings.append((relative_path, service_index, f"unknown service id: {service_id}"))
                services_valid.append(service)
                service_key = (service_id, str(service.get("provider_id") or service.get("backend_id") or service.get("service_name") or "").strip())
                if service_key in seen_services:
                    findings.append((relative_path, service_index, f"duplicate service entry: {service_id}"))
                seen_services.add(service_key)

        category = str(manifest.get("category") or "").strip().lower()
        if category in {"avatar", "chat"} and not ui_entries_valid and not services_valid:
            findings.append((relative_path, 0, f"provider-style category '{category}' needs a manifest services entry when it has no UI"))

        seen_ids = set()
        for index, entry in enumerate(ui_entries, start=1):
            if not isinstance(entry, dict):
                findings.append((relative_path, index, "ui entry must be an object"))
                continue
            ui_id = str(entry.get("id") or "").strip()
            if not ui_id:
                findings.append((relative_path, index, "ui entry missing id"))
            elif ui_id in seen_ids:
                findings.append((relative_path, index, f"duplicate ui id: {ui_id}"))
            seen_ids.add(ui_id)

            area = str(entry.get("area") or "").strip()
            target = str(entry.get("target") or entry.get("mount_target") or "").strip()
            if not target:
                target = ui_target_for_area(area)
            if area and not target:
                findings.append((relative_path, index, f"unknown ui area: {area}"))

            raw_ui_path = str(entry.get("ui_path") or "").strip()
            if raw_ui_path:
                resolved_ui = Path(raw_ui_path)
                if not resolved_ui.is_absolute():
                    resolved_ui = addon_root / resolved_ui
                if not resolved_ui.exists():
                    findings.append((relative_path, index, f"ui_path not found: {raw_ui_path}"))

            raw_icon_path = str(entry.get("icon_path") or "").strip()
            if raw_icon_path:
                resolved_icon = Path(raw_icon_path)
                if not resolved_icon.is_absolute():
                    resolved_icon = addon_root / resolved_icon
                if not resolved_icon.exists():
                    findings.append((relative_path, index, f"icon_path not found: {raw_icon_path}"))

            if raw_ui_path and not ui_id:
                findings.append((relative_path, index, f"designer ui entry for addon '{addon_id}' needs a stable id"))
    return findings


def validate_ui_file(raw_path, *, base_path=None):
    ui_path = resolve_ui_path(raw_path, base_path=base_path)
    print(f"[UI Validation] File: {ui_path}")
    if not ui_path.exists():
        print("[UI Validation] ERROR: UI file not found.")
        return 2
    try:
        objects, duplicates = collect_ui_object_classes(ui_path)
    except Exception as exc:
        print(f"[UI Validation] ERROR: Could not parse UI file: {exc}")
        return 2

    missing = []
    mismatched = []
    required_names = {
        object_name
        for _group_name, requirements in UI_VALIDATION_REQUIRED_GROUPS
        for object_name, _expected_class in requirements
    }
    print(f"[UI Validation] Object names: {len(objects)}")
    if duplicates:
        print("[UI Validation] Duplicate widget/layout/action objectNames:")
        for object_name, first_class, duplicate_class in duplicates:
            print(f"  - {object_name}: {first_class} and {duplicate_class}")
    else:
        print("[UI Validation] Duplicate widget/layout/action objectNames: none")

    for group_name, requirements in UI_VALIDATION_REQUIRED_GROUPS:
        group_missing = []
        group_mismatched = []
        for object_name, expected_class in requirements:
            actual_class = objects.get(object_name)
            if actual_class is None:
                group_missing.append((object_name, expected_class))
                missing.append((group_name, object_name, expected_class))
            elif actual_class != expected_class:
                group_mismatched.append((object_name, expected_class, actual_class))
                mismatched.append((group_name, object_name, expected_class, actual_class))
        print(f"[UI Validation] {group_name}:")
        if not group_missing and not group_mismatched:
            print("  OK")
        for object_name, expected_class in group_missing:
            print(f"  MISSING {object_name} ({expected_class})")
        for object_name, expected_class, actual_class in group_mismatched:
            print(f"  TYPE {object_name}: expected {expected_class}, found {actual_class}")

    dynamic_owned = []
    for object_name in sorted(objects):
        if object_name in required_names:
            continue
        if object_name in UI_VALIDATION_DYNAMIC_OWNED_NAMES or any(
            object_name.startswith(prefix) for prefix in UI_VALIDATION_DYNAMIC_OWNED_PREFIXES
        ):
            dynamic_owned.append((object_name, objects[object_name]))
    print("[UI Validation] Addon-owned preview/non-target UI intentionally present in main.ui; keep these as Designer preview surfaces and do not wire them directly in --ui-real:")
    if dynamic_owned:
        for object_name, object_class in dynamic_owned:
            print(f"  - {object_name} ({object_class})")
    else:
        print("  none")

    legacy_addon_tabs = collect_legacy_addon_tab_registrations(ui_path)
    direct_designer_tabs = collect_direct_addon_designer_tab_registrations(ui_path)
    designer_fallback_tabs = collect_addon_designer_fallback_registrations(ui_path)
    legacy_tab_builders = collect_addon_legacy_tab_builders(ui_path)
    print("[UI Validation] Bundled addon Designer-tab migration:")
    if legacy_addon_tabs or direct_designer_tabs or designer_fallback_tabs or legacy_tab_builders:
        for relative_path, line_number, line in legacy_addon_tabs:
            location = f"{relative_path}:{line_number}" if line_number else relative_path
            print(f"  LEGACY {location}: {line}")
        for relative_path, line_number, line in direct_designer_tabs:
            location = f"{relative_path}:{line_number}" if line_number else relative_path
            print(f"  DIRECT {location}: use register_manifest_designer_tab(...) instead of {line}")
        for relative_path, line_number, line in designer_fallback_tabs:
            location = f"{relative_path}:{line_number}" if line_number else relative_path
            print(f"  FALLBACK {location}: remove Python-built addon UI fallback from Designer registration: {line}")
        for relative_path, line_number, line in legacy_tab_builders:
            location = f"{relative_path}:{line_number}" if line_number else relative_path
            print(f"  BUILDER {location}: rename/remove legacy addon tab builder: {line}")
    else:
        print("  OK")

    invalid_designer_tabs = collect_invalid_addon_designer_tabs(ui_path)
    invalid_manifest_ui = collect_invalid_addon_manifest_ui(ui_path, objects)
    print("[UI Validation] Bundled addon Designer UI files:")
    if invalid_designer_tabs or invalid_manifest_ui:
        for relative_path, line_number, message in [*invalid_designer_tabs, *invalid_manifest_ui]:
            location = f"{relative_path}:{line_number}" if line_number else relative_path
            print(f"  INVALID {location}: {message}")
    else:
        print("  OK")

    if missing or mismatched or duplicates or legacy_addon_tabs or direct_designer_tabs or designer_fallback_tabs or legacy_tab_builders or invalid_designer_tabs or invalid_manifest_ui:
        print("[UI Validation] Result: NOT READY for safe real-logic binding.")
    else:
        print("[UI Validation] Result: READY for the checked Phase 1 binding prerequisites.")
    return 0
