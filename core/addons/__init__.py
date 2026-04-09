"""Addon framework primitives for Neural Interface."""

from .base import BaseAddon
from .contributions import TabContribution
from .context import AddonContext, AddonPermissionError
from .manager import AddonManager
from .manifest import AddonManifest

__all__ = [
    "AddonContext",
    "AddonManager",
    "AddonManifest",
    "AddonPermissionError",
    "BaseAddon",
    "TabContribution",
]

