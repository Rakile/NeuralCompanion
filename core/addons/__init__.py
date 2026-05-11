"""Addon framework primitives for Neural Companion."""

from .base import BaseAddon
from .contributions import (
    ADDON_SERVICE_TARGETS,
    ADDON_UI_MOUNTS,
    AddonUIMount,
    TabContribution,
    known_addon_service_ids,
    normalize_ui_area,
    ui_area_for_target,
    ui_mount_adoption_specs,
    ui_mount_for_area,
    ui_mount_targets,
    ui_fallback_targets_for_manifest,
    ui_required_static_mount_targets,
    ui_target_for_area,
    ui_target_is_deferred,
    ui_targets_for_service_id,
)
from .context import AddonContext, AddonPermissionError
from .manager import AddonManager
from .manifest import AddonManifest

__all__ = [
    "AddonContext",
    "AddonManager",
    "AddonManifest",
    "AddonPermissionError",
    "ADDON_UI_MOUNTS",
    "ADDON_SERVICE_TARGETS",
    "AddonUIMount",
    "BaseAddon",
    "TabContribution",
    "normalize_ui_area",
    "known_addon_service_ids",
    "ui_area_for_target",
    "ui_mount_adoption_specs",
    "ui_mount_for_area",
    "ui_mount_targets",
    "ui_fallback_targets_for_manifest",
    "ui_required_static_mount_targets",
    "ui_target_for_area",
    "ui_target_is_deferred",
    "ui_targets_for_service_id",
]
