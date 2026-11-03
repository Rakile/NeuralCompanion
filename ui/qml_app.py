"""QML application-shell launcher for the NeuralCompanion redesign route."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtQml
from PySide6.QtQuickControls2 import QQuickStyle

from ui.qml_bridge import QmlApplicationBridge
from ui.qml_bridge.musetalk_creator import register_musetalk_creator_types


QML_ROOT = Path(__file__).resolve().parent / "qml"
_BUNDLED_CONVERSATION_FONT_PATHS = (
    QML_ROOT.parent / "assets" / "fonts" / "OpenDyslexic" / "OpenDyslexic-Regular.otf",
    QML_ROOT.parent / "assets" / "fonts" / "OpenDyslexic" / "OpenDyslexic-Bold.otf",
)
_bundled_conversation_font_families: tuple[str, ...] | None = None


def register_bundled_conversation_fonts() -> tuple[str, ...]:
    """Register optional reading-aid fonts and return their Qt family names."""

    global _bundled_conversation_font_families
    if _bundled_conversation_font_families is not None:
        return _bundled_conversation_font_families
    families: list[str] = []
    for font_path in _BUNDLED_CONVERSATION_FONT_PATHS:
        if not font_path.is_file():
            continue
        font_id = QtGui.QFontDatabase.addApplicationFont(str(font_path))
        if font_id < 0:
            continue
        for family in QtGui.QFontDatabase.applicationFontFamilies(font_id):
            if family not in families:
                families.append(family)
    _bundled_conversation_font_families = tuple(families)
    return _bundled_conversation_font_families


class _CreatorShutdownQuitFilter(QtCore.QObject):
    """Keep the Qt event loop available while tracked creator cleanup drains."""

    def __init__(self, bridge, parent=None) -> None:
        super().__init__(parent)
        self._bridge = bridge

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QtCore.QEvent.Quit:
            return not self._bridge.beginApplicationShutdown()
        return False


def _expected_addon_manifest_ids() -> set[str]:
    """Read the installed top-level addon inventory used by the runtime manager."""

    addon_root = QML_ROOT.parents[1] / "addons"
    expected: set[str] = set()
    for manifest_path in sorted(addon_root.glob("*/addon.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"Could not read addon manifest '{manifest_path}': {error}"
            ) from error
        addon_id = str(dict(payload or {}).get("id") or "").strip()
        if not addon_id:
            raise RuntimeError(f"Addon manifest '{manifest_path}' has no id.")
        if addon_id in expected:
            raise RuntimeError(f"Duplicate addon manifest id on disk: {addon_id}")
        expected.add(addon_id)
    return expected


def _validate_runtime_bridge_contract(bridge: QmlApplicationBridge) -> None:
    """Read-only integration assertions used by the opt-in runtime smoke."""

    if not bridge.providers:
        raise RuntimeError("QML bridge did not expose any language providers.")
    if not bridge.speechInputBackends or not bridge.speechOutputBackends:
        raise RuntimeError("QML bridge did not expose the composed speech backend catalogs.")
    if not bridge.addonWorkspaces or not bridge.allAddonWorkspaces or not bridge.addonRegistry:
        raise RuntimeError("QML bridge did not expose initialized addon workspaces.")
    registered_addons = [
        dict(addon or {})
        for category in bridge.addonRegistry
        for addon in list(dict(category or {}).get("addons") or ())
    ]
    registered_ids = {
        str(addon.get("id") or "").strip()
        for addon in registered_addons
        if str(addon.get("id") or "").strip()
    }
    expected_ids = _expected_addon_manifest_ids()
    if len(registered_addons) != len(registered_ids) or registered_ids != expected_ids:
        missing = sorted(expected_ids - registered_ids)
        unexpected = sorted(registered_ids - expected_ids)
        raise RuntimeError(
            "QML bridge addon registry does not match the installed manifest inventory: "
            f"entries={len(registered_addons)}, unique_ids={len(registered_ids)}, "
            f"expected={len(expected_ids)}, missing={missing}, unexpected={unexpected}."
        )
    if not bridge.tutorialCatalog:
        raise RuntimeError("QML bridge did not expose the tutorial library.")

    audited_surfaces: list[tuple[str, int, int, bool]] = []
    native_surfaces: list[str] = []
    section_audits: list[tuple[str, dict[str, int], list[str], list[str]]] = []
    layout_audits: list[tuple[str, int, dict[str, int]]] = []
    for item in bridge.allAddonWorkspaces:
        if bool(item.get("core")):
            continue
        contribution_id = str(item.get("id") or "")
        if bool(item.get("nativeSurface")):
            native_surfaces.append(contribution_id)
            native_adapter = bridge._native_surfaces.adapter(contribution_id)
            if native_adapter is None:
                raise RuntimeError(
                    f"Native addon surface '{contribution_id}' has no registered adapter."
                )
            try:
                native_adapter.snapshot()
            except (KeyError, RuntimeError, TypeError, ValueError) as error:
                raise RuntimeError(
                    f"Native addon surface '{contribution_id}' could not be read: {error}"
                ) from error
        bridge.viewAddon(contribution_id)
        live_count = len(bridge.liveAddonControls)
        section_counts: dict[str, int] = {}
        for control in bridge.liveAddonControls:
            section = str(control.get("section") or "Overview")
            section_counts[section] = section_counts.get(section, 0) + 1
        missing_layout_metadata = [
            str(control.get("id") or control.get("objectName") or "unknown")
            for control in bridge.liveAddonControls
            if not str(control.get("groupKey") or "").strip()
        ]
        if missing_layout_metadata:
            raise RuntimeError(
                f"Addon '{contribution_id}' exposed controls without placement metadata: "
                + ", ".join(missing_layout_metadata[:8])
            )
        type_counts: dict[str, int] = {}
        for control in bridge.liveAddonControls:
            kind = str(control.get("type") or "unknown")
            type_counts[kind] = type_counts.get(kind, 0) + 1
        layout_audits.append(
            (
                contribution_id,
                len(
                    {
                        str(control.get("groupKey") or "")
                        for control in bridge.liveAddonControls
                    }
                ),
                type_counts,
            )
        )
        declared_sections = [str(value) for value in list(item.get("sections") or [])]
        unexpected_sections = sorted(
            section for section in section_counts if section not in declared_sections
        )
        empty_declared_sections = (
            [
                section
                for section in declared_sections
                if section_counts.get(section, 0) <= 0
            ]
            if live_count > 0 and len(declared_sections) > 1
            else []
        )
        section_audits.append(
            (
                contribution_id,
                section_counts,
                unexpected_sections,
                empty_declared_sections,
            )
        )
        fallback_count = int(bridge.selectedAddonSettings.get("settingCount") or 0)
        checkable = bool(bridge.selectedAddon.get("contributionCheckable"))
        audited_surfaces.append((contribution_id, live_count, fallback_count, checkable))
    bridge.viewAddon("core.persona")
    live_surfaces = [item for item in audited_surfaces if item[1] > 0]
    fallback_surfaces = [item for item in audited_surfaces if item[2] > 0]
    checkable_surfaces = [item for item in audited_surfaces if item[3]]
    if not live_surfaces:
        raise RuntimeError("QML bridge could not discover controls on any initialized addon surface.")
    discovered_types = {
        kind
        for _contribution_id, _group_count, type_counts in layout_audits
        for kind, count in type_counts.items()
        if count > 0
    }
    missing_legacy_types = {"display", "list", "progress"} - discovered_types
    if missing_legacy_types:
        raise RuntimeError(
            "QML bridge omitted established addon display types: "
            + ", ".join(sorted(missing_legacy_types))
        )
    invalid_section_mappings = [
        f"{contribution_id}: {', '.join(unexpected)}"
        for contribution_id, _counts, unexpected, _empty in section_audits
        if unexpected
    ]
    if invalid_section_mappings:
        raise RuntimeError(
            "Addon controls mapped outside their declared tabs: "
            + "; ".join(invalid_section_mappings)
        )
    empty_addon_pages = [
        f"{contribution_id}: {', '.join(empty)}"
        for contribution_id, _counts, _unexpected, empty in section_audits
        if empty
    ]
    if empty_addon_pages:
        raise RuntimeError(
            "Addon tabs declared without their legacy controls: "
            + "; ".join(empty_addon_pages)
        )
    leaked_provider_surfaces = [
        str(item.get("id") or "")
        for item in bridge.addonWorkspaces
        if bool(item.get("providerSurface"))
    ]
    if leaked_provider_surfaces:
        raise RuntimeError(
            "Provider settings leaked back into Addons navigation: "
            + ", ".join(leaked_provider_surfaces)
        )
    provider_surfaces = [
        item for item in bridge.allAddonWorkspaces if bool(item.get("providerSurface"))
    ]
    if not provider_surfaces:
        raise RuntimeError("QML bridge did not classify any Runtime-owned provider surfaces.")
    stt_provider = next(
        (
            str(item.get("id") or "")
            for item in bridge.speechInputBackends
            if str(item.get("id") or "").lower() not in {"", "none", "disabled"}
        ),
        "none",
    )
    runtime_provider_checks = [
        ("stt", stt_provider),
        ("tts", "chatterbox"),
        ("avatar", "musetalk"),
        ("vision", "screen"),
    ]
    mounted_provider_controls: list[tuple[str, str, int]] = []
    for provider_kind, provider_id in runtime_provider_checks:
        bridge.viewRuntimeProviderSettings(provider_kind, provider_id)
        mounted = bridge.runtimeProviderSettings
        if (
            str(mounted.get("kind") or "") != provider_kind
            or str(mounted.get("providerId") or "") != provider_id
        ):
            raise RuntimeError(
                f"{provider_kind.upper()} provider settings did not remain in Runtime."
            )
        control_count = len(list(mounted.get("controls") or []))
        if control_count <= 0:
            raise RuntimeError(
                f"{provider_kind.upper()} provider '{provider_id}' exposed no inline controls."
            )
        mounted_provider_controls.append((provider_kind, provider_id, control_count))
    uncovered = [
        item[0]
        for item in audited_surfaces
        if item[1] == 0 and item[2] == 0 and not item[3]
    ]
    print(
        "[QML Smoke] Contract ready: "
        f"providers={len(bridge.providers)} "
        f"stt={len(bridge.speechInputBackends)} "
        f"tts={len(bridge.speechOutputBackends)} "
        f"addons={len(bridge.addonWorkspaces)} "
        f"provider_surfaces={len(provider_surfaces)} "
        f"mounted_provider_controls={sum(item[2] for item in mounted_provider_controls)} "
        f"audited_surfaces={len(audited_surfaces)} "
        f"native_surfaces={len(native_surfaces)} "
        f"live_surfaces={len(live_surfaces)} "
        f"fallback_surfaces={len(fallback_surfaces)} "
        f"checkable_surfaces={len(checkable_surfaces)} "
        f"live_controls={sum(item[1] for item in live_surfaces)} "
        f"uncovered={','.join(uncovered) or 'none'}"
    )
    if native_surfaces:
        print("[QML Smoke] Native surfaces: " + ", ".join(native_surfaces))
    for contribution_id, live_count, fallback_count, checkable in audited_surfaces:
        sections = next(
            counts
            for item_id, counts, _unexpected, _empty in section_audits
            if item_id == contribution_id
        )
        print(
            "[QML Smoke] Addon surface: "
            f"id={contribution_id} live_controls={live_count} "
            f"manifest_settings={fallback_count} checkable={checkable} "
            f"sections={json.dumps(sections, sort_keys=True)} "
            f"groups={next(group_count for item_id, group_count, _types in layout_audits if item_id == contribution_id)} "
            f"types={json.dumps(next(types for item_id, _groups, types in layout_audits if item_id == contribution_id), sort_keys=True)}"
        )


def run_qml_app(
    app: Any,
    application_facade: Any,
    *,
    component_gallery: bool = False,
    runtime_smoke: bool = False,
    visual_smoke: bool = False,
) -> int:
    """Run the production native-QML application shell."""

    register_musetalk_creator_types()
    register_bundled_conversation_fonts()
    QQuickStyle.setStyle("Basic")
    engine = QtQml.QQmlApplicationEngine()
    try:
        from addons.ditto_avatar.image_provider import register_image_provider
    except ImportError:
        pass  # Optional Ditto addon can be removed without breaking the shell.
    else:
        register_image_provider(engine)
    engine.addImportPath(str(QML_ROOT))

    bridge = None
    if not component_gallery:
        bridge = QmlApplicationBridge(
            application_facade,
            session_read_only=runtime_smoke or visual_smoke,
            parent=app,
        )
        engine.setInitialProperties({"bridge": bridge})

    entry = QML_ROOT / ("ComponentGallery.qml" if component_gallery else "Main.qml")
    engine.load(QtCore.QUrl.fromLocalFile(str(entry)))
    if not engine.rootObjects():
        if bridge is not None:
            bridge.close()
        raise RuntimeError(f"Could not load QML application entry: {entry}")

    root = engine.rootObjects()[0]
    root.destroyed.connect(app.quit)

    runtime_closed = False
    restart = None
    if bridge is not None:
        from ui.desktop_restart import RestartRequest

        restart = RestartRequest(
            close=root.close,
            closing=lambda: bridge.applicationClosing,
            complete=lambda: bool(runtime_closed and getattr(bridge, "_application_shutdown_ready", False) and bridge._closing),
            report=lambda message: bridge.notificationRaised.emit("error", "Restart was not started", message),
        )
        bridge.desktopRestartConfirmed.connect(restart.confirm)
        bridge.applicationClosingChanged.connect(restart.shutdown_changed)

    presence_controller = None
    if bridge is not None:
        from visual_presence.visual_presence_controller import install_visual_presence

        presence_controller = install_visual_presence(
            root,
            application=application_facade,
            persist=bridge._save_native_session,
        )

    if (runtime_smoke or visual_smoke) and bridge is not None:
        _validate_runtime_bridge_contract(bridge)

    def close_runtime() -> None:
        nonlocal runtime_closed
        if presence_controller is not None:
            presence_controller.shutdown()
        if bridge is not None:
            bridge.close()
        # Do not relaunch if any part of normal teardown raised an exception.
        runtime_closed = bridge is None or bool(bridge._closing)

    app.aboutToQuit.connect(close_runtime)
    if bridge is not None:
        creator_quit_filter = _CreatorShutdownQuitFilter(bridge, app)
        app.installEventFilter(creator_quit_filter)
        bridge.applicationShutdownReady.connect(app.quit)
    if visual_smoke and bridge is not None:
        output_dir = QML_ROOT.parent.parent / "docs" / "ui-redesign-screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)
        orb_workspace = next(
            (
                str(item.get("id") or "")
                for item in bridge.addonWorkspaces
                if str(item.get("addonId") or "") == "nc.companion_orb_overlay"
                and str(item.get("area") or "") == "top_level"
            ),
            "",
        )
        capture_steps = [
            ("runtime", "01-runtime-language.png", "", 1480, 920, "runtime", "language"),
            ("runtime", "02-runtime-speech-input.png", "", 1480, 920, "runtime", "speech"),
            ("runtime", "03-runtime-voice.png", "", 1480, 920, "runtime", "voice"),
            ("runtime", "04-runtime-visual-reply.png", "", 1480, 920, "runtime", "visual"),
            ("runtime", "05-runtime-avatar.png", "", 1480, 920, "runtime", "avatar"),
            ("runtime", "06-runtime-session-setup.png", "", 1480, 920, "runtime", "session"),
            ("runtime", "07-vision-sensors.png", "", 1480, 920, "vision", "language"),
            ("runtime", "08-chat-behavior.png", "", 1480, 920, "chat", "language"),
            ("runtime", "09-story-visuals.png", "", 1480, 920, "story", "language"),
            ("runtime", "10-document-memory.png", "", 1480, 920, "memory", "language"),
            ("runtime", "11-appearance-themes.png", "", 1480, 920, "themes", "language"),
            ("addons", "12-addons-persona.png", "core.persona", 1480, 920, "", ""),
            ("addons", "13-addons-companion-orb.png", orb_workspace, 1480, 920, "", ""),
            ("addons", "14-addons-tutorials.png", "core.tutorials", 1480, 920, "", ""),
            ("conversation", "15-conversation.png", "", 1480, 920, "", ""),
            ("visuals", "16-visuals.png", "", 1480, 920, "", ""),
            ("runtime", "17-runtime-minimum-size.png", "", 1120, 720, "runtime", "language"),
            ("addons", "18-addons-roleplay.png", "multi_persona_roleplay_tab", 1480, 920, "", ""),
            ("addons", "19-addons-audio-story.png", "audio_story_mode_runtime", 1480, 920, "", ""),
            ("addons", "20-addons-corsair.png", "corsair_visual_instrument_tab", 1480, 920, "", ""),
            ("addons", "21-addons-discord.png", "discord_voice_bridge_tab", 1480, 920, "", ""),
            ("addons", "22-addons-buddy-chat.png", "buddy_chat_tab", 1480, 920, "", ""),
            ("addons", "23-addons-main-chat-remote.png", "main_chat_remote_tab", 1480, 920, "", ""),
            ("addons", "24-addons-ai-presence.png", "ai_presence_mode_tab", 1480, 920, "", ""),
            ("addons", "25-addons-spotify.png", "spotify_sense_tab", 1480, 920, "", ""),
            ("addons", "26-addons-manager.png", "core.addons", 1480, 920, "", ""),
        ]
        capture_index = 0

        def capture_next() -> None:
            nonlocal capture_index
            if capture_index >= len(capture_steps):
                print(f"[QML Visual Smoke] Captured {capture_index} views in {output_dir}")
                app.quit()
                return
            (
                workspace,
                filename,
                addon_id,
                width,
                height,
                runtime_section,
                runtime_responsibility,
            ) = capture_steps[capture_index]
            root.setWidth(width)
            root.setHeight(height)
            if workspace == "runtime":
                root.openRuntimeView(runtime_section, runtime_responsibility)
            else:
                bridge.openWorkspace(workspace)
            if addon_id:
                bridge.viewAddon(addon_id)

            def grab_current() -> None:
                nonlocal capture_index
                image = root.grabWindow()
                destination = output_dir / filename
                if image.isNull() or not image.save(str(destination), "PNG"):
                    print(f"[QML Visual Smoke] ERROR: Could not capture {destination}")
                    app.exit(2)
                    return
                print(f"[QML Visual Smoke] Captured {destination}")
                capture_index += 1
                QtCore.QTimer.singleShot(180, capture_next)

            QtCore.QTimer.singleShot(650, grab_current)

        QtCore.QTimer.singleShot(1200, capture_next)
    elif runtime_smoke:
        QtCore.QTimer.singleShot(2200, app.quit)
    result = int(app.exec())
    return restart.exit_code(result) if restart is not None else result


__all__ = ["QML_ROOT", "run_qml_app"]
