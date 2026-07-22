from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    from addons.companion_orb_overlay.companion_orb.external_runtime_client import _parse_event_line
    from addons.companion_orb_overlay.companion_orb import interaction_settings
    from addons.companion_orb_overlay.companion_orb import orb_palettes
    from addons.ai_presence_mode.mood_color_resolver import resolve_mood_colors
    from addons.companion_orb_overlay.companion_orb.companion_orb_bridge import CompanionOrbBridge

    drop_event = _parse_event_line('{"type":"orb.dropped","center":[10,20],"top_left":[1,2],"button":"left"}')
    if drop_event != {"type": "orb.dropped", "center": [10, 20], "top_left": [1, 2], "button": "left"}:
        raise AssertionError(f"External event parser returned unexpected payload: {drop_event!r}")
    if _parse_event_line("Companion Orb external runtime ready.") is not None:
        raise AssertionError("External event parser should ignore non-JSON log lines")

    bridge = CompanionOrbBridge()
    if bridge.clickThrough:
        raise AssertionError("Companion Orb bridge must not start click-through before settings arrive.")

    legacy_settings, migrated = interaction_settings.normalize_interaction_settings(
        {
            "companion_orb_click_through_default": True,
            "companion_orb_right_drag_focus_enabled": False,
        }
    )
    if not migrated:
        raise AssertionError("Legacy Companion Orb interaction defaults should be migrated.")
    if legacy_settings.get("companion_orb_click_through_default") is not False:
        raise AssertionError("Legacy Companion Orb click-through default should migrate to False.")
    if legacy_settings.get("companion_orb_right_drag_focus_enabled") is not True:
        raise AssertionError("Legacy Companion Orb right-drag focus should migrate to True.")
    if interaction_settings.effective_click_through(legacy_settings):
        raise AssertionError("Legacy migrated Companion Orb settings must not remain click-through.")

    explicit_settings, migrated = interaction_settings.normalize_interaction_settings(
        {
            "companion_orb_click_through_default": True,
            "companion_orb_right_drag_focus_enabled": False,
            "companion_orb_interaction_defaults_version": 2,
            "companion_orb_click_through_explicit": True,
        }
    )
    if migrated:
        raise AssertionError("Versioned explicit Companion Orb interaction settings should not be migrated again.")
    if not interaction_settings.effective_click_through(explicit_settings):
        raise AssertionError("Versioned explicit click-through settings should remain available.")

    palette_ids = [item.palette_id for item in orb_palettes.ORB_COLOR_PALETTES]
    expected_palette_ids = [
        "custom",
        "neural_prism",
        "aurora_rose",
        "ember_circuit",
        "deep_signal",
        "soft_focus",
    ]
    if palette_ids != expected_palette_ids:
        raise AssertionError(f"Unexpected Companion Orb color palettes: {palette_ids!r}")
    palette_options = orb_palettes.palette_options()
    if palette_options[0] != ("Custom colors", "custom"):
        raise AssertionError(f"Companion Orb palette dropdown should start with custom colors: {palette_options!r}")
    neural_prism = orb_palettes.palette_for_id("neural_prism")
    if neural_prism.as_color_settings() != {
        "companion_orb_primary_color": "#22d3ee",
        "companion_orb_secondary_color": "#8b5cf6",
        "companion_orb_accent_color": "#f59e0b",
        "companion_orb_glow_color": "#a5f3fc",
    }:
        raise AssertionError(f"Neural Prism palette produced unexpected settings: {neural_prism.as_color_settings()!r}")
    if orb_palettes.palette_for_id("missing").palette_id != "custom":
        raise AssertionError("Unknown Companion Orb palettes should fall back to the custom palette entry.")

    bridge.apply_settings(
        {
            "companion_orb_color_palette": "ember_circuit",
            "companion_orb_custom_colors_enabled": False,
        }
    )
    if not bridge.customColorsEnabled:
        raise AssertionError("Selecting a Companion Orb palette should enable custom color control.")
    ember = orb_palettes.palette_for_id("ember_circuit")
    if (
        bridge.primaryColor,
        bridge.secondaryColor,
        bridge.accentColor,
        bridge.glowColor,
    ) != (ember.primary, ember.secondary, ember.accent, ember.glow):
        raise AssertionError(
            "Companion Orb bridge should apply the selected palette colors, got "
            f"{(bridge.primaryColor, bridge.secondaryColor, bridge.accentColor, bridge.glowColor)!r}"
        )
    bridge.apply_settings(
        {
            "companion_orb_color_palette": "aurora_rose",
            "companion_orb_custom_colors_enabled": True,
            "companion_orb_primary_color": "#ff0000",
            "companion_orb_secondary_color": "#00ff00",
            "companion_orb_accent_color": "#0000ff",
            "companion_orb_glow_color": "#ffffff",
        }
    )
    if (
        bridge.primaryColor,
        bridge.secondaryColor,
        bridge.accentColor,
        bridge.glowColor,
    ) != ("#ff0000", "#00ff00", "#0000ff", "#ffffff"):
        raise AssertionError(
            "Companion Orb named palettes must remain editable after selection, got "
            f"{(bridge.primaryColor, bridge.secondaryColor, bridge.accentColor, bridge.glowColor)!r}"
        )
    bridge.apply_settings(
        {
            "companion_orb_custom_colors_enabled": False,
            "companion_orb_color_palette": "custom",
            "companion_orb_mood_color_mode": "manual",
            "companion_orb_manual_mood": "angry",
            "ai_presence_mood_color_mode": "manual",
            "ai_presence_manual_mood": "happy",
        }
    )
    angry = resolve_mood_colors("angry")
    if bridge.moodName != "angry" or bridge.primaryColor != angry["primaryColor"]:
        raise AssertionError(
            "Companion Orb mood color selection must be Orb-local and ignore AI Presence manual mood, got "
            f"{bridge.moodName!r} {bridge.primaryColor!r}"
        )
    bridge.apply_settings(
        {
            "companion_orb_custom_colors_enabled": False,
            "companion_orb_color_palette": "custom",
            "companion_orb_mood_color_mode": "off",
            "companion_orb_mood_color_intensity": 0.85,
            "ai_presence_mood_color_mode": "manual",
            "ai_presence_manual_mood": "happy",
        }
    )
    if bridge.moodColorIntensity != 0.0:
        raise AssertionError("Companion Orb mood color mode 'off' should disable Orb mood tint intensity.")

    external_runtime = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "external_orb_runtime.py"
    ).read_text(encoding="utf-8")
    runtime_client = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "external_runtime_client.py"
    ).read_text(encoding="utf-8")
    main_controller = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "companion_orb_controller.py"
    ).read_text(encoding="utf-8")
    runtime_defaults = (ROOT_DIR / "engine.py").read_text(encoding="utf-8")
    settings_controller = (ROOT_DIR / "addons" / "companion_orb_overlay" / "controller.py").read_text(encoding="utf-8")
    ai_presence_controller = (ROOT_DIR / "addons" / "ai_presence_mode" / "controller.py").read_text(encoding="utf-8")
    qml_source = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "qml"
        / "CompanionOrbOverlay.qml"
    ).read_text(encoding="utf-8")

    for fragment, description in {
        '"companion_orb_click_through_default": False': "Companion Orb must not be click-through by default",
        '"companion_orb_right_drag_focus_enabled": True': "Companion Orb right-drag focus must be available by default",
        '"companion_orb_color_palette": "custom"': "Companion Orb color palette should default to editable custom colors",
        '"companion_orb_mood_color_mode": "automatic"': "Companion Orb mood color mode should have an Orb-local default",
        '"companion_orb_manual_mood": "neutral"': "Companion Orb manual mood should have an Orb-local default",
    }.items():
        for source_name, source in {
            "engine defaults": runtime_defaults,
            "AI Presence defaults": ai_presence_controller,
        }.items():
            if fragment not in source:
                raise AssertionError(f"{source_name} missing default: {description}")

    ui_default_fragments = {
        '"Click-through by default", "companion_orb_click_through_default_checkbox", "companion_orb_click_through_default", False':
            "settings UI must show click-through disabled by default",
        '"Right-click drag changes focus", "companion_orb_right_drag_focus_enabled_checkbox", "companion_orb_right_drag_focus_enabled", True':
            "settings UI must show right-drag focus enabled by default",
        "ORB_COLOR_PALETTE_OPTIONS":
            "settings UI must expose Companion Orb palette presets",
        '"companion_orb_color_palette_combo"':
            "settings UI must include the Companion Orb palette dropdown",
        '"companion_orb_color_source_status"':
            "settings UI must show the active Companion Orb color source",
        '"companion_orb_mood_color_mode_combo"':
            "settings UI must expose Orb-local mood color mode",
        '"companion_orb_manual_mood_combo"':
            "settings UI must expose Orb-local manual mood",
        '"companion_orb_main_tabs"':
            "settings UI must organize the Companion Orb page into top-level MPRC-style tabs",
        '"Overview", "Look", "Behavior", "Eye Tracking", "Reading", "Awareness", "Hotkeys", "Advanced"':
            "settings UI must expose the approved Companion Orb top-level tab names",
        "def _build_companion_orb_main_tabs":
            "settings UI must build Companion Orb top-level tabs through one local helper",
        "_HORIZONTAL_PADDING = 10":
            "Companion Orb tab buttons should have 10px horizontal content padding",
        "QtGui.QFontMetrics(title_font).horizontalAdvance":
            "Companion Orb tab width must be calculated from the same bold label font it paints",
        "_TEXT_WIDTH_SAFETY = 8":
            "Companion Orb tab labels need a small width buffer so labels do not clip",
        "_INTER_TAB_GUTTER = 5":
            "Companion Orb tab cards should have MPRC-like space between buttons",
        "_STRIP_VERTICAL_GUTTER = 4":
            "Companion Orb tab cards should float inside the strip like MPRC tabs",
        "width + self._INTER_TAB_GUTTER":
            "Companion Orb tab size must reserve the painted right-side gutter",
        "self._HEIGHT + (self._STRIP_VERTICAL_GUTTER * 2)":
            "Companion Orb tab size must reserve vertical gutter around the painted button",
        "self.tabRect(index).adjusted(0, self._STRIP_VERTICAL_GUTTER, -self._INTER_TAB_GUTTER, -self._STRIP_VERTICAL_GUTTER)":
            "Companion Orb tab painter must leave visible space around each button",
        "padding-top: 4px;":
            "Companion Orb tab strip stylesheet should reserve visible vertical breathing room",
        "padding-bottom: 4px;":
            "Companion Orb tab strip stylesheet should reserve visible vertical breathing room",
        "left: 4px;":
            "Companion Orb tab strips should have a small left gutter like MPRC",
        "def _apply_companion_orb_custom_colors":
            "settings UI must expose one helper that applies/saves the current custom color fields",
        '"btn_companion_orb_apply_custom_colors"':
            "settings UI must include an explicit Apply Colors button for custom orb colors",
        '"btn_companion_orb_save_custom_colors"':
            "settings UI must include an explicit Save Colors button for custom orb colors",
        "class _CompanionOrbColorPreview":
            "settings UI must provide a static Companion Orb color preview widget",
        '"companion_orb_color_preview"':
            "settings UI must name the static Companion Orb color preview widget",
        "def _build_companion_orb_color_workbench":
            "settings UI must keep Orb color preview and palette controls in one local workbench helper",
        '"Preview & Palette", "companion_orb_color_workbench_group"':
            "settings UI must lead Orb tuning with a clear preview and palette group",
        '"Color Channels", "companion_orb_color_channels_group"':
            "settings UI must label the raw custom color fields as color channels",
        "def _refresh_orb_color_preview":
            "settings UI must refresh the static Orb preview from current color controls",
        "edit.textChanged.connect(lambda *_args: self._refresh_orb_color_preview())":
            "custom color edits should update the static Orb preview while typing",
        "self._orb_color_preview.set_colors(":
            "settings UI must push normalized colors into the static Orb preview widget",
        "def _push_companion_orb_runtime_settings":
            "settings UI must push live Companion Orb settings to the running orb controller",
        '"ai_presence.companion_orb"':
            "settings UI must find the registered Companion Orb controller service",
        "request_settings":
            "settings UI must call the existing Companion Orb request_settings API",
    }
    for fragment, description in ui_default_fragments.items():
        ui_sources = {"Companion Orb settings": settings_controller}
        if fragment.startswith('"Click-through') or fragment.startswith('"Right-click'):
            ui_sources["AI Presence settings"] = ai_presence_controller
        for source_name, source in ui_sources.items():
            if fragment not in source:
                raise AssertionError(f"{source_name} missing UI default: {description}")

    apply_start = (ROOT_DIR / "addons" / "companion_orb_overlay" / "companion_orb" / "companion_orb_bridge.py").read_text(encoding="utf-8")
    apply_body = apply_start[apply_start.index("    def apply_settings(self, settings):") :]
    if "payload.get(\"ai_presence_mood_color_mode\"" in apply_body or "payload.get(\"ai_presence_manual_mood\"" in apply_body:
        raise AssertionError("Companion Orb bridge must not read AI Presence mood keys for Orb color decisions.")

    setting_handler_start = settings_controller.index("    def _on_setting_changed(self, key, value):")
    setting_handler_end = settings_controller.index("    def _apply_companion_orb_palette(self, value):", setting_handler_start)
    setting_handler_body = settings_controller[setting_handler_start:setting_handler_end]
    if "_mark_companion_orb_palette_custom()" in setting_handler_body:
        raise AssertionError("Editing a Companion Orb color must not switch the selected palette back to Custom colors.")

    qml_palette_fragments = {
        "paletteHighlightColor": "QML should derive warm style highlights from the active palette",
        "paletteCoolColor": "QML should derive cool style highlights from the active palette",
        "var colors = [primary, secondary, accent, root.paletteHighlightColor(), root.paletteCoolColor()]":
            "Prismatic Pulse should use palette-derived ring colors",
    }
    missing_qml_palette = [
        description
        for fragment, description in qml_palette_fragments.items()
        if fragment not in qml_source
    ]
    if missing_qml_palette:
        raise AssertionError("Missing Companion Orb palette-driven QML support: " + ", ".join(missing_qml_palette))
    prismatic_start = qml_source.index("function drawPrismaticPulse")
    prismatic_end = qml_source.index("function drawAetherWisp", prismatic_start)
    prismatic_body = qml_source[prismatic_start:prismatic_end]
    for hardcoded in ('root.hexColor("#f97316")', 'root.hexColor("#22d3ee")'):
        if hardcoded in prismatic_body:
            raise AssertionError(f"Prismatic Pulse should not inject hardcoded palette colors: {hardcoded}")

    interactive_fragments = {
        "normalize_interaction_settings": "runtime migrates the old click-through defaults from saved sessions",
        "effective_click_through": "runtime resolves actual click-through through one shared helper",
        "right_drag_focus_enabled": "runtime resolves right-drag focus through one shared helper",
        "QtCore.Qt.OpenHandCursor": "runtime uses an obvious hover cursor over the interactive orb",
        "QtCore.Qt.ClosedHandCursor": "runtime uses a closed-hand cursor while dragging the orb",
        "unsetCursor()": "runtime clears the custom cursor when click-through is explicitly enabled",
    }
    for fragment, description in interactive_fragments.items():
        for source_name, source in {
            "external runtime": external_runtime,
            "main controller": main_controller,
        }.items():
            if fragment not in source:
                raise AssertionError(f"{source_name} missing interaction affordance: {description}")

    required_fragments = {
        "self.drag_offset": "external runtime keeps normal Qt drag state",
        "self.poll_drag_timer": "external runtime polls click-through drags",
        "def eventFilter(self, watched, event):": "external runtime handles direct mouse events",
        "def _poll_pointer_drag(self)": "external runtime handles click-through mouse drags",
        "window.grabMouse()": "external runtime captures mouse input for direct drags",
        "window.releaseMouse()": "external runtime releases mouse input after direct drags",
        "def _emit_position_changed(self)": "external runtime emits final position changes through a helper",
        "self._record_drag_position(point)": "dragged position updates the external runtime home point",
        "widget.installEventFilter(self)": "external runtime receives direct mouse events when click-through is off",
        "def _emit_event(": "external runtime can send structured events back to main NC",
        '"type": "orb.dropped"': "external runtime emits drop events",
        '"type": "orb.request_menu"': "external runtime emits menu request events",
        '"type": "orb.position_changed"': "external runtime emits position-change events",
        '"type": "orb.pointer_reached"': "external runtime emits pointer reach events for Snapshot at pointer",
        '"type": "orb.playful_nudge"': "external runtime emits playful nudge events for main-process speech/context handling",
        "companion_orb_harassment_enabled": "external runtime honors playful nudge enablement",
        "companion_orb_snapshot_on_pointer_reached": "external runtime honors snapshot-at-pointer enablement",
        'if msg_type == "cloak":': "external runtime supports main-process snapshot cloaking",
    }
    missing = [
        description
        for fragment, description in required_fragments.items()
        if fragment not in external_runtime
    ]
    if missing:
        raise AssertionError("Missing Companion Orb external interaction support: " + ", ".join(missing))

    record_start = external_runtime.index("def _record_drag_position")
    record_end = external_runtime.index("def _emit_position_changed", record_start)
    record_body = external_runtime[record_start:record_end]
    if '"type": "orb.position_changed"' in record_body:
        raise AssertionError("Per-frame drag recording must not emit bridge position events during drag")

    client_fragments = {
        "event_handler": "external runtime client accepts an event handler",
        "stdout=subprocess.PIPE": "external runtime client keeps stdout for JSON event lines",
        "stderr=self._log_handle": "external runtime client keeps stderr/logs out of stdout",
        "def _read_events_loop": "external runtime client reads events on a background thread",
        "_parse_event_line": "external runtime client parses event JSON lines safely",
    }
    missing_client = [
        description
        for fragment, description in client_fragments.items()
        if fragment not in runtime_client
    ]
    if missing_client:
        raise AssertionError("Missing Companion Orb external IPC client support: " + ", ".join(missing_client))

    controller_fragments = {
        "event_handler=self._queue_external_runtime_event": "main controller subscribes to external runtime events through the queued Qt bridge",
        "external_event_requested.connect(self._handle_external_runtime_event": "main controller routes external events on the Qt thread",
        "def _handle_external_runtime_event": "main controller has an external event dispatcher",
        "def _handle_external_orb_drop": "main controller handles external drop events",
        "def _handle_external_orb_menu_request": "main controller handles external menu request events",
        "def _handle_external_orb_position_changed": "main controller handles external position-change events",
        "def _handle_external_orb_pointer_reached": "main controller handles external pointer-reached events",
        "def _handle_external_orb_playful_nudge": "main controller handles external playful-nudge events",
        "_snapshot_capture_lock": "main controller serializes orb screenshot/OCR capture work",
        "snapshot_capture_busy_skipped": "main controller skips overlapping orb screenshot/OCR capture work",
        "acquire(blocking=False)": "main controller does not block worker threads while another capture is active",
        '"type": "cloak"': "main controller can cloak the external orb during snapshots",
    }
    missing_controller = [
        description
        for fragment, description in controller_fragments.items()
        if fragment not in main_controller
    ]
    if missing_controller:
        raise AssertionError("Missing Companion Orb main controller event bridge support: " + ", ".join(missing_controller))

    announce_start = main_controller.index("def _announce_harassment")
    announce_end = main_controller.index("def _tts_runtime_ready", announce_start)
    announce_body = main_controller[announce_start:announce_end]
    required_nudge_order = [
        "_nudge_should_defer_to_pointer_snapshot",
        "_queue_llm_harassment_candidate",
        "_speak_harassment_message",
    ]
    missing_nudge_order = [item for item in required_nudge_order if item not in announce_body]
    if missing_nudge_order:
        raise AssertionError(
            "Companion Orb playful nudge is missing single-route arbitration: "
            + ", ".join(missing_nudge_order)
        )
    positions = [announce_body.index(item) for item in required_nudge_order]
    if positions != sorted(positions):
        raise AssertionError("Companion Orb playful nudge must defer to snapshot, then hidden queue, then direct speech fallback")
    if "return bool(queue_candidate(" not in main_controller:
        raise AssertionError("Companion Orb hidden harassment queue must report whether it accepted the nudge")
    if "QtCore.QLockFile" not in external_runtime:
        raise AssertionError("External runtime must guard against duplicate Orb processes for one app root.")

    modes_start = external_runtime.index('if msg_type == "modes":')
    modes_end = external_runtime.index('if msg_type == "target_info":', modes_start)
    modes_body = external_runtime[modes_start:modes_end]
    if "effective_click_through" not in modes_body:
        raise AssertionError("External runtime mode updates must resolve click-through through effective settings.")
    if "_apply_click_through(bool(self.bridge.clickThrough))" in modes_body:
        raise AssertionError("External runtime mode updates must not apply raw bridge click-through.")

    apply_start = external_runtime.index("def _apply_click_through")
    apply_end = external_runtime.index("def _apply_orb_cursor", apply_start)
    apply_body = external_runtime[apply_start:apply_end]
    if "effective_click_through" not in apply_body:
        raise AssertionError("External native click-through updates must defensively resolve effective settings.")

    print("Companion Orb interaction smoke passed.")


if __name__ == "__main__":
    main()
