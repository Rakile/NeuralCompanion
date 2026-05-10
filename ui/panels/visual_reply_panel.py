"""Compatibility access for the addon-owned Visual Reply panel."""

from core.addons import bootstrap_runtime


QtVisualReplyPanel = bootstrap_runtime.invoke_addon_capability(
    "nc.visual_reply",
    "ui.panel_class",
)
if QtVisualReplyPanel is None:
    raise ImportError("Visual Reply addon did not provide ui.panel_class.")

__all__ = ["QtVisualReplyPanel"]
