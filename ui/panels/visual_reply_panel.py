"""Compatibility import for the addon-owned Visual Reply panel.

The Visual Reply panel implementation lives in ``addons.visual_reply`` so the
addon owns its dock surface. This module remains only for older host imports
while the runtime bridge continues moving toward fully addon-owned UI.
"""

from addons.visual_reply.controller import AddonVisualReplyPanel as QtVisualReplyPanel

__all__ = ["QtVisualReplyPanel"]
