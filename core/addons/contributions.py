from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


WidgetFactory = Callable[[Any], Any]


@dataclass(frozen=True)
class AddonUIMount:
    """Stable host mount point exposed to addon UI contributions.

    Addons register semantic areas such as ``top_level`` or ``tts_runtime``;
    the host decides which concrete Designer widget receives that area. Keeping
    this contract in core/addons avoids each UI surface inventing its own map.
    """

    area: str
    target: str
    label: str
    deferred: bool = False


ADDON_UI_MOUNTS: tuple[AddonUIMount, ...] = (
    AddonUIMount("top_level", "left_tabs", "Workspace Tabs"),
    AddonUIMount("host_settings", "host_settings_tabs", "System Shaping"),
    AddonUIMount("operational_view", "right_tabs", "Operational View"),
    AddonUIMount("musetalk", "musetalk_tabs", "MuseTalk", deferred=True),
    AddonUIMount("tts_runtime", "tts_runtime_addon_tabs", "TTS Runtime"),
    AddonUIMount("vision_source", "sensory_feedback_tabs", "Vision Sources"),
)


ADDON_UI_MOUNT_BY_AREA = {mount.area: mount for mount in ADDON_UI_MOUNTS}
ADDON_UI_MOUNT_BY_TARGET = {mount.target: mount for mount in ADDON_UI_MOUNTS}


def normalize_ui_area(area: str | None) -> str:
    value = str(area or "").strip()
    return value if value else "top_level"


def ui_mount_for_area(area: str | None) -> AddonUIMount | None:
    return ADDON_UI_MOUNT_BY_AREA.get(normalize_ui_area(area))


def ui_target_for_area(area: str | None) -> str:
    mount = ui_mount_for_area(area)
    return mount.target if mount is not None else ""


def ui_area_for_target(target: str | None) -> str:
    mount = ADDON_UI_MOUNT_BY_TARGET.get(str(target or "").strip())
    return mount.area if mount is not None else ""


def ui_target_is_deferred(target: str | None) -> bool:
    mount = ADDON_UI_MOUNT_BY_TARGET.get(str(target or "").strip())
    return bool(mount.deferred) if mount is not None else False


def ui_mount_targets() -> tuple[str, ...]:
    return tuple(mount.target for mount in ADDON_UI_MOUNTS)


def ui_required_static_mount_targets() -> tuple[str, ...]:
    return tuple(mount.target for mount in ADDON_UI_MOUNTS if not mount.deferred)


def ui_fallback_targets_for_manifest(addon_id: str | None, category: str | None) -> tuple[str, ...]:
    addon_id = str(addon_id or "").strip().lower()
    category = str(category or "other").strip().lower() or "other"
    if addon_id.startswith("nc.chat_provider_") or addon_id == "nc.claude_provider":
        return ("chat_provider_combo",)
    category_targets = {
        "vision": ("sensory_feedback_tabs",),
        "musetalk": ("musetalk_tabs",),
        "visuals": ("host_settings_tabs",),
        "chat": ("left_tabs",),
        "global": ("left_tabs",),
    }
    return category_targets.get(category, ())


def ui_mount_adoption_specs() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "area": mount.area,
            "source_name": "tabs" if mount.area == "top_level" else mount.target,
            "target_name": mount.target,
            "mode": "titles",
        }
        for mount in ADDON_UI_MOUNTS
        if mount.area != "vision_source"
    )


@dataclass
class TabContribution:
    id: str
    title: str
    factory: WidgetFactory
    addon_id: str = ""
    area: str = "top_level"
    order: int = 1000
    tooltip: str = ""
    parent_tab_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def mount_area(self) -> str:
        return normalize_ui_area(self.area)

    @property
    def mount_target(self) -> str:
        return ui_target_for_area(self.area)

    @property
    def ui_kind(self) -> str:
        return str((self.metadata or {}).get("ui_kind") or "factory").strip() or "factory"

    @property
    def ui_path(self) -> str:
        return str((self.metadata or {}).get("ui_path") or "").strip()

    @property
    def icon_path(self) -> str:
        return str((self.metadata or {}).get("icon_path") or "").strip()
