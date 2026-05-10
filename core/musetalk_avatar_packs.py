"""Compatibility access to MuseTalk avatar pack helpers.

The MuseTalk addon owns the avatar-pack implementation. Core/engine callers use
this module while direct imports from addon internals are phased out.
"""

from __future__ import annotations

from addons.musetalk_avatar.avatar_packs import *  # noqa: F401,F403
