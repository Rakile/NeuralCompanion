"""Addon manifest reporting helpers for the lightweight Designer UI shell."""

import json
import re
from pathlib import Path

from addons.visual_reply.session_schema import with_flat_visual_reply_settings
from core.chat_runtime_session_schema import with_flat_chat_runtime_settings
from core.chunking_session_schema import with_flat_chunking_settings
from core.dry_run_session_schema import with_flat_dry_run_settings
from core.musetalk_session_schema import with_flat_musetalk_settings
from core.persona_session_schema import with_flat_persona_settings
from core.runtime_controls_session_schema import with_flat_runtime_controls_settings
from core.sensory_session_schema import with_flat_sensory_settings
from core.tts_session_schema import with_flat_tts_runtime_settings
from core.ui_session_schema import with_flat_ui_settings
from core.vam_session_schema import with_flat_vam_settings
from core.addons.contributions import (
    ui_fallback_targets_for_manifest,
    ui_mount_targets,
    ui_target_for_area,
    ui_target_is_deferred,
    ui_targets_for_service_id,
)

_APP_FILE = None


def configure_shell_addon_report_dependencies(namespace):
    """Inject qt_app-owned constants/helpers without importing the heavy app module."""
    global _APP_FILE
    namespace = dict(namespace or {})
    globals().update(namespace)
    _APP_FILE = namespace.get("__file__", _APP_FILE)


def _app_root():
    if _APP_FILE:
        return Path(_APP_FILE).resolve().parent
    return Path.cwd()


def _read_ui_shell_session_snapshot():
    session_path = _app_root() / "qt_session.json"
    try:
        with session_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
            if not isinstance(payload, dict):
                return {}
            return with_flat_chat_runtime_settings(
                with_flat_sensory_settings(
                    with_flat_musetalk_settings(
                        with_flat_tts_runtime_settings(
                            with_flat_visual_reply_settings(
                                with_flat_persona_settings(
                                    with_flat_runtime_controls_settings(
                                        with_flat_dry_run_settings(
                                            with_flat_chunking_settings(
                                                with_flat_ui_settings(with_flat_vam_settings(payload))
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )
    except Exception:
        return {}

def _ui_shell_addon_registry_state(session=None):
    payload = dict(session or _read_ui_shell_session_snapshot() or {})
    registry = payload.get("addon_registry_state")
    if isinstance(registry, dict):
        return registry
    registry_path = _app_root() / "runtime" / "addons" / "addon_registry.json"
    try:
        with registry_path.open("r", encoding="utf-8") as handle:
            registry = json.load(handle)
            return registry if isinstance(registry, dict) else {}
    except Exception:
        return {}

def _ui_shell_addon_effectively_enabled(manifest, registry_state):
    addon_id = str(manifest.get("id", "") or "").strip()
    category = str(manifest.get("category", "") or "other").strip().lower() or "other"
    manifest_enabled = bool(manifest.get("enabled", True))
    category_overrides = dict((registry_state or {}).get("categories", {}) or {})
    addon_overrides = dict((registry_state or {}).get("addons", {}) or {})
    category_enabled = bool(category_overrides.get(category, True))
    addon_enabled = bool(addon_overrides.get(addon_id, manifest_enabled))
    return bool(category_enabled and addon_enabled)

def _ui_shell_manifest_tab_areas(manifest):
    areas = []
    for item in list(dict(manifest or {}).get("ui", []) or []):
        if not isinstance(item, dict):
            continue
        area = str(item.get("area") or "top_level").strip()
        if area:
            areas.append(area)
    return sorted(set(areas))

def _ui_shell_static_tab_areas(addon_dir, manifest=None):
    main_path = Path(addon_dir) / "main.py"
    areas = list(_ui_shell_manifest_tab_areas(manifest))
    try:
        text = main_path.read_text(encoding="utf-8")
    except Exception:
        return sorted(set(item for item in areas if item))
    for match in re.finditer(r"register_(?:designer_)?tab\s*\(", text):
        body = text[match.start(): match.start() + 2000]
        area_match = re.search(r"area\s*=\s*[\"']([^\"']+)[\"']", body)
        if area_match:
            areas.append(area_match.group(1).strip())
    return sorted(set(item for item in areas if item))

def _ui_shell_static_service_hints(addon_dir, manifest):
    manifest_services = []
    for item in list(dict(manifest or {}).get("services", []) or []):
        if not isinstance(item, dict):
            continue
        service_id = str(item.get("id") or item.get("service") or item.get("kind") or "").strip()
        if service_id:
            manifest_services.append(service_id)
    if manifest_services:
        return sorted(set(manifest_services))

    addon_id = str(manifest.get("id", "") or "").strip().lower()
    name = str(manifest.get("name", "") or "").strip().lower()
    hints = []
    if "chat provider" in name:
        hints.append("chat_provider_registry")
    if addon_id.endswith("_avatar") or "avatar provider" in name:
        hints.append("avatar_provider_registry")
    main_path = Path(addon_dir) / "main.py"
    try:
        text = main_path.read_text(encoding="utf-8")
    except Exception:
        text = ""
    if "qt.sensory" in text:
        hints.append("sensory_registry")
    if "services.register" in text:
        if '"kind": "tts"' in text or "'kind': 'tts'" in text:
            hints.append("tts_backend_service")
        else:
            hints.append("service_registry")
    return sorted(set(hints))

def _ui_shell_discover_addon_manifests():
    addons_dir = _app_root() / "addons"
    discovered = []
    if not addons_dir.exists():
        return discovered
    for addon_dir in sorted((path for path in addons_dir.iterdir() if path.is_dir()), key=lambda path: path.name.lower()):
        manifest_path = addon_dir / "addon.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            discovered.append({
                "id": addon_dir.name,
                "name": addon_dir.name,
                "category": "other",
                "enabled": False,
                "error": str(exc),
                "areas": [],
                "service_hints": [],
            })
            continue
        if not isinstance(manifest, dict):
            continue
        manifest = dict(manifest)
        manifest["root"] = str(addon_dir)
        manifest["areas"] = _ui_shell_static_tab_areas(addon_dir, manifest)
        manifest["service_hints"] = _ui_shell_static_service_hints(addon_dir, manifest)
        discovered.append(manifest)
    return discovered

def _ui_shell_mount_target_for_area(area):
    return ui_target_for_area(area)

def _ui_shell_target_is_deferred(target):
    return ui_target_is_deferred(target)

def _ui_shell_fallback_targets_for_manifest(manifest):
    service_targets = []
    for item in list(dict(manifest or {}).get("services", []) or []):
        if not isinstance(item, dict):
            continue
        service_targets.extend(ui_targets_for_service_id(item.get("id")))
    if service_targets:
        return sorted(set(service_targets))

    addon_id = str(manifest.get("id", "") or "").strip().lower()
    category = str(manifest.get("category", "") or "other").strip().lower()
    return list(ui_fallback_targets_for_manifest(addon_id, category))

def _ui_shell_addon_mount_report(window):
    session = _read_ui_shell_session_snapshot()
    registry_state = _ui_shell_addon_registry_state(session)
    manifests = _ui_shell_discover_addon_manifests()
    mount_points = {
        **{target: _ui_shell_find_object(window, target) is not None for target in ui_mount_targets()},
        "sensory_feedback_sources_widget": _ui_shell_find_object(window, "sensory_feedback_sources_widget") is not None,
        "chat_provider_combo": _ui_shell_find_object(window, "chat_provider_combo") is not None,
        "chat_provider_fields_widget": _ui_shell_find_object(window, "chat_provider_fields_widget") is not None,
        "chat_provider_generation_fields_widget": _ui_shell_find_object(window, "chat_provider_generation_fields_widget") is not None,
        "OperationalViewDock": _ui_shell_find_object(window, "OperationalViewDock") is not None,
    }
    rows = []
    for manifest in manifests:
        areas = list(manifest.get("areas", []) or [])
        service_hints = list(manifest.get("service_hints", []) or [])
        ui_targets = []
        for area in areas:
            target = _ui_shell_mount_target_for_area(area)
            if target:
                ui_targets.append(target)
        service_targets = _ui_shell_fallback_targets_for_manifest(manifest) if not ui_targets else []
        targets = [*ui_targets, *service_targets]
        rows.append({
            "id": str(manifest.get("id", "") or ""),
            "name": str(manifest.get("name", "") or manifest.get("id", "") or ""),
            "category": str(manifest.get("category", "") or "other"),
            "root": str(manifest.get("root", "") or ""),
            "enabled": _ui_shell_addon_effectively_enabled(manifest, registry_state),
            "areas": areas,
            "service_hints": service_hints,
            "ui_targets": sorted(set(ui_targets)),
            "service_targets": sorted(set(service_targets)),
            "targets": sorted(set(targets)),
            "missing_targets": sorted(
                set(
                    target
                    for target in targets
                    if not mount_points.get(target, False) and not _ui_shell_target_is_deferred(target)
                )
            ),
            "error": str(manifest.get("error", "") or ""),
        })
    enabled_count = sum(1 for row in rows if row["enabled"])
    return {
        "mount_points": mount_points,
        "addons": rows,
        "enabled_count": enabled_count,
        "total_count": len(rows),
    }

def _print_ui_shell_addon_mount_report(report, prefix="[UI Shell Smoke]"):
    print(f"{prefix} Addon manifests discovered: {report['total_count']} ({report['enabled_count']} effectively enabled)")
    print(f"{prefix} Addon mount points:")
    for name, present in sorted((report.get("mount_points") or {}).items()):
        print(f"  - {name}: {'present' if present else 'missing'}")
    print(f"{prefix} Would mount/register:")
    for row in report.get("addons", []):
        status = "enabled" if row.get("enabled") else "disabled"
        areas = ", ".join(row.get("areas") or [])
        hints = ", ".join(row.get("service_hints") or [])
        targets = ", ".join(row.get("targets") or [])
        missing = ", ".join(row.get("missing_targets") or [])
        detail_bits = []
        if areas:
            detail_bits.append(f"areas={areas}")
        if hints:
            detail_bits.append(f"services={hints}")
        if targets:
            detail_bits.append(f"targets={targets}")
        if missing:
            detail_bits.append(f"missing_targets={missing}")
        if row.get("error"):
            detail_bits.append(f"error={row['error']}")
        detail = "; ".join(detail_bits) if detail_bits else "manifest-only"
        print(f"  - {row.get('id') or row.get('name')} [{status}]: {detail}")

def _ui_shell_rows_for_target(report, target, exclude_addon_ids=None):
    target = str(target or "").strip()
    excluded = {str(item or "").strip() for item in (exclude_addon_ids or set()) if str(item or "").strip()}
    rows = []
    for row in report.get("addons", []):
        if str(row.get("id") or "").strip() in excluded:
            continue
        if target in set(row.get("targets") or []):
            rows.append(row)
    return rows

def _ui_shell_addon_rows_text(rows):
    if not rows:
        return "No addon manifests currently target this mount point."
    lines = []
    for row in rows:
        status = "enabled" if row.get("enabled") else "disabled"
        name = str(row.get("name") or row.get("id") or "Unnamed addon").strip()
        addon_id = str(row.get("id") or "").strip()
        areas = ", ".join(row.get("areas") or [])
        services = ", ".join(row.get("service_hints") or [])
        details = [f"{name} [{status}]"]
        if addon_id and addon_id != name:
            details.append(addon_id)
        if areas:
            details.append(f"area: {areas}")
        if services:
            details.append(f"services: {services}")
        lines.append(" - " + " | ".join(details))
    return "\n".join(lines)

def _ui_shell_norm_label(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

def _ui_shell_target_addon_rows(report, target):
    target = str(target or "").strip()
    return [
        row
        for row in report.get("addons", [])
        if row.get("enabled") and target in set(row.get("ui_targets") or [])
    ]

def _ui_shell_static_addon_comparison(ui_path, report, live_mount_report):
    static_tabs = _collect_ui_shell_static_tabs(ui_path)
    live_tabs = list((live_mount_report or {}).get("live_tabs") or [])
    live_by_target = {}
    for live_tab in live_tabs:
        target = str(live_tab.get("target") or "").strip()
        if not target:
            continue
        live_by_target.setdefault(target, []).append(live_tab)

    rows = []
    for target in UI_SHELL_TAB_MOUNT_WIDGETS:
        static_pages = list(static_tabs.get(target, []) or [])
        addon_rows = _ui_shell_target_addon_rows(report, target)
        live_target_tabs = list(live_by_target.get(target, []) or [])
        static_titles = [str(page.get("title") or "").strip() for page in static_pages if str(page.get("title") or "").strip()]
        static_norms = {_ui_shell_norm_label(title) for title in static_titles}
        live_titles = [str(tab.get("title") or "").strip() for tab in live_target_tabs if str(tab.get("title") or "").strip()]
        live_norms = {_ui_shell_norm_label(title) for title in live_titles}
        replaced_norms = {
            _ui_shell_norm_label(str(tab.get("title") or "").strip())
            for tab in live_target_tabs
            if tab.get("replaced_static_placeholder") and str(tab.get("title") or "").strip()
        }
        manifest_names = [str(row.get("name") or row.get("id") or "").strip() for row in addon_rows]
        manifest_norms = {_ui_shell_norm_label(name) for name in manifest_names}
        duplicate_candidates = [
            title for title in static_titles
            if _ui_shell_norm_label(title) not in replaced_norms
            and (_ui_shell_norm_label(title) in live_norms or _ui_shell_norm_label(title) in manifest_norms)
        ]
        placeholder_only = [
            str(row.get("name") or row.get("id") or "").strip()
            for row in addon_rows
            if str(row.get("id") or "").strip() not in set((live_mount_report or {}).get("mounted_ids") or [])
        ]
        if static_titles or addon_rows or live_target_tabs:
            rows.append({
                "target": target,
                "static_titles": static_titles,
                "live_titles": live_titles,
                "addon_names": manifest_names,
                "duplicate_candidates": duplicate_candidates,
                "placeholder_only": placeholder_only,
            })
    return rows

def _print_ui_shell_static_addon_comparison(ui_path, report, live_mount_report, prefix="[UI Shell Smoke]"):
    rows = _ui_shell_static_addon_comparison(ui_path, report, live_mount_report)
    print(f"{prefix} Static-vs-addon tab comparison:")
    if not rows:
        print("  none")
        return
    for row in rows:
        static_text = ", ".join(row.get("static_titles") or []) or "none"
        live_text = ", ".join(row.get("live_titles") or []) or "none"
        addon_text = ", ".join(row.get("addon_names") or []) or "none"
        duplicate_text = ", ".join(row.get("duplicate_candidates") or []) or "none"
        placeholder_text = ", ".join(row.get("placeholder_only") or []) or "none"
        print(f"  - {row.get('target')}: static=[{static_text}]")
        print(f"    addon targets=[{addon_text}]")
        print(f"    live-mounted=[{live_text}]")
        print(f"    static duplicate candidates=[{duplicate_text}]")
        print(f"    placeholder-only addon targets=[{placeholder_text}]")
