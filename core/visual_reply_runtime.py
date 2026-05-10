from __future__ import annotations

"""Compatibility access to Visual Reply runtime helpers.

The Visual Reply addon owns the implementation. Core/engine callers import this
module during the migration away from direct addon imports.
"""

from addons.visual_reply.runtime_config import *  # noqa: F401,F403
