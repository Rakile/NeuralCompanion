"""Addon manifest reporting helpers for the lightweight Designer UI shell."""

import json
import re
from pathlib import Path

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
            return payload if isinstance(payload, dict) else {}
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

def _ui_shell_static_tab_areas(addon_dir):
    main_path = Path(addon_dir) / "main.py"
    try:
        text = main_path.read_text(encoding="utf-8")
    except Exception:
        return []
    areas = []
    for match in re.finditer(r"register_(?:designer_)?tab\s*\(", text):
        body = text[match.start(): match.start() + 2000]
        area_match = re.search(r"area\s*=\s*[\"']([^\"']+)[\"']", body)
        if area_match:
            areas.append(area_match.group(1).strip())
    return sorted(set(item for item in areas if item))

def _ui_shell_static_service_hints(addon_dir, manifest):
    addon_id = str(manifest.get("id", "") or "").strip().lower()
    name = str(manifest.get("name", "") or "").strip().lower()
    hints = []
    if addon_id.startswith("nc.chat_provider_") or "chat provider" in name or addon_id == "nc.claude_provider":
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
        manifest["areas"] = _ui_shell_static_tab_areas(addon_dir)
        manifest["service_hints"] = _ui_shell_static_service_hints(addon_dir, manifest)
        discovered.append(manifest)
    return discovered

def _ui_shell_mount_target_for_area(area):
    mapping = {
        "top_level": "left_tabs",
        "host_settings": "host_settings_tabs",
        "musetalk": "musetalk_tabs",
        "tts_runtime": "tts_runtime_addon_tabs",
        "vision_source": "sensory_feedback_tabs",
        "operational_view": "right_tabs",
    }
    return mapping.get(str(area or "").strip(), "")

def _ui_shell_target_is_deferred(target):
    # Nested addon-owned mount points can be introduced by an earlier live addon
    # contribution rather than being present statically in main.ui.
    return str(target or "").strip() in {"musetalk_tabs"}

def _ui_shell_fallback_targets_for_manifest(manifest):
    addon_id = str(manifest.get("id", "") or "").strip().lower()
    category = str(manifest.get("category", "") or "other").strip().lower()
    if addon_id.startswith("nc.chat_provider_") or addon_id == "nc.claude_provider":
        return ["chat_provider_combo"]
    if category == "vision":
        return ["sensory_feedback_tabs"]
    if category == "musetalk":
        return ["musetalk_tabs"]
    if category == "visuals":
        return ["host_settings_tabs"]
    if category == "chat":
        return ["left_tabs"]
    if category == "global":
        return ["left_tabs"]
    return []

def _ui_shell_addon_mount_report(window):
    session = _read_ui_shell_session_snapshot()
    registry_state = _ui_shell_addon_registry_state(session)
    manifests = _ui_shell_discover_addon_manifests()
    mount_points = {
        "left_tabs": _ui_shell_find_object(window, "left_tabs") is not None,
        "host_settings_tabs": _ui_shell_find_object(window, "host_settings_tabs") is not None,
        "right_tabs": _ui_shell_find_object(window, "right_tabs") is not None,
        "tts_runtime_addon_tabs": _ui_shell_find_object(window, "tts_runtime_addon_tabs") is not None,
        "musetalk_tabs": _ui_shell_find_object(window, "musetalk_tabs") is not None,
        "sensory_feedback_tabs": _ui_shell_find_object(window, "sensory_feedback_tabs") is not None,
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
        targets = []
        for area in areas:
            target = _ui_shell_mount_target_for_area(area)
            if target:
                targets.append(target)
        if not targets:
            targets = _ui_shell_fallback_targets_for_manifest(manifest)
        rows.append({
            "id": str(manifest.get("id", "") or ""),
            "name": str(manifest.get("name", "") or manifest.get("id", "") or ""),
            "category": str(manifest.get("category", "") or "other"),
            "root": str(manifest.get("root", "") or ""),
            "enabled": _ui_shell_addon_effectively_enabled(manifest, registry_state),
            "areas": areas,
            "service_hints": service_hints,
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
        if row.get("enabled") and target in set(row.get("targets") or [])
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
