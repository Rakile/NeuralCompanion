"""Designer UI validation helpers for main.ui shell and real-runtime modes."""

from pathlib import Path
import xml.etree.ElementTree as ET


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
            ("musetalk_tabs", "QTabWidget"),
            ("sensory_feedback_tabs", "QTabWidget"),
            ("vseeface_tabs", "QTabWidget"),
        ),
    ),
    (
        "Dynamic Mount Points",
        (
            ("left_tabs", "QTabWidget"),
            ("host_settings_tabs", "QTabWidget"),
            ("right_tabs", "QTabWidget"),
            ("musetalk_tabs", "QTabWidget"),
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
            ("visual_reply_mode_combo", "QComboBox"),
            ("visual_reply_provider_combo", "QComboBox"),
            ("visual_reply_size_combo", "QComboBox"),
            ("visual_reply_model_edit", "QLineEdit"),
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

UI_SHELL_TAB_MOUNT_WIDGETS = (
    "left_tabs",
    "host_settings_tabs",
    "right_tabs",
    "musetalk_tabs",
    "tts_runtime_addon_tabs",
    "sensory_feedback_tabs",
    "vseeface_tabs",
)


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

    if missing or mismatched or duplicates:
        print("[UI Validation] Result: NOT READY for safe real-logic binding.")
    else:
        print("[UI Validation] Result: READY for the checked Phase 1 binding prerequisites.")
    return 0
