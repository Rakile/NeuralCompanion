"""Shell-preview addon service bootstrap helpers.

The read-only shell is intentionally lighter than the live addon manager, but
it still should not import addon implementation classes directly. These helpers
ask addon entrypoints for shell services through capability names.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


_ADDON_DIR_BY_ID = {
    "nc.audio_story_mode": "audio_story_mode",
    "nc.chat_session_player": "chat_session_player",
    "nc.hotkeys": "hotkeys",
    "nc.visual_reply": "visual_reply",
}


def create_shell_addon_service(addon_id, capability, payload=None, default=None):
    addon_dir_name = _ADDON_DIR_BY_ID.get(str(addon_id or "").strip())
    if not addon_dir_name:
        return default
    entry_path = Path(__file__).resolve().parents[2] / "addons" / addon_dir_name / "main.py"
    if not entry_path.exists():
        return default
    try:
        module_name = f"nc_shell_service_{addon_dir_name}"
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            return default
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        addon_cls = getattr(module, "Addon", None)
        addon = addon_cls() if callable(addon_cls) else None
        invoker = getattr(addon, "invoke_capability", None)
        if not callable(invoker):
            return default
        result = invoker(str(capability), dict(payload or {}))
        return default if result is None else result
    except Exception:
        return default
