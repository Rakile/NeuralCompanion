from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _assert_chat_is_wired_into_radial_menu() -> None:
    from addons.companion_orb_overlay.companion_orb.gaze_radial_menu import MAIN_GAZE_ACTIONS

    chat_actions = [action for action in MAIN_GAZE_ACTIONS if action.action_id == "chat"]
    if len(chat_actions) != 1 or not chat_actions[0].enabled:
        raise AssertionError("The radial cake menu must expose one enabled Chat action.")
    if chat_actions[0].label != "Chat":
        raise AssertionError(f"The radial chat action should be labeled Chat, got {chat_actions[0].label!r}.")

    controller_source = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "companion_orb_controller.py"
    ).read_text(encoding="utf-8")
    required_fragments = (
        'if normalized == "chat":',
        "self._dismiss_gaze_radial_menu()",
        "self._show_chat_input_popup(chat_anchor)",
    )
    missing = [fragment for fragment in required_fragments if fragment not in controller_source]
    if missing:
        raise AssertionError(f"Radial Chat dispatch is missing: {missing}")


def main() -> None:
    _assert_chat_is_wired_into_radial_menu()
    print("Companion Orb radial chat smoke passed.")


if __name__ == "__main__":
    main()
