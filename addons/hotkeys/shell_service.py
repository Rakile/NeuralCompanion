class _UiShellHotkeyService:
    """Read-only shell hotkey service exposed by the Hotkeys addon."""

    def _session_snapshot(self):
        from ui.runtime.shell_addon_reports import _read_ui_shell_session_snapshot

        return _read_ui_shell_session_snapshot()

    def list_bindings(self):
        try:
            from core import runtime_hotkeys as _hotkeys
            from addons.hotkeys import actions

            session = self._session_snapshot()
            ui_defaults = dict(_hotkeys.DEFAULT_UI_ACTION_HOTKEYS)
            ui_defaults.update(actions.UI_ACTION_HOTKEYS)
            labels = dict(_hotkeys.HOTKEY_ACTION_LABELS)
            labels.update(actions.UI_ACTION_LABELS)
            push_to_talk = _hotkeys.normalize_hotkey_text(
                session.get("push_to_talk_hotkey", _hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY)
            ) or _hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY
            manual_bindings = _hotkeys.normalize_manual_action_hotkeys(
                session.get("manual_action_hotkeys", _hotkeys.DEFAULT_MANUAL_ACTION_HOTKEYS)
            )
            ui_bindings = _hotkeys.normalize_ui_action_hotkeys(
                session.get("ui_action_hotkeys", ui_defaults)
            )
            entries = [
                {
                    "action": "push_to_talk",
                    "label": str(labels.get("push_to_talk", "Push-to-Talk")),
                    "binding": str(push_to_talk or ""),
                    "default_binding": str(_hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY),
                    "category": "input",
                    "scope": "global",
                    "description": "Read-only shell preview of the Push-to-Talk binding.",
                }
            ]
            for action, default_binding in _hotkeys.DEFAULT_MANUAL_ACTION_HOTKEYS.items():
                entries.append(
                    {
                        "action": action,
                        "label": str(labels.get(action, action)),
                        "binding": str(manual_bindings.get(action, "") or ""),
                        "default_binding": str(default_binding or ""),
                        "category": "manual_controls",
                        "scope": "global_and_window",
                        "description": "Read-only shell preview of a manual control binding.",
                    }
                )
            for action, default_binding in ui_defaults.items():
                entries.append(
                    {
                        "action": action,
                        "label": str(labels.get(action, action)),
                        "binding": str(ui_bindings.get(action, "") or ""),
                        "default_binding": str(default_binding or ""),
                        "category": "ui_actions",
                        "scope": "window",
                        "description": "Read-only shell preview of a focused-window shortcut.",
                    }
                )
            return entries
        except Exception:
            return []

    def set_binding(self, action, binding):
        action_key = str(action or "").strip()
        for entry in self.list_bindings():
            if str(entry.get("action", "") or "") == action_key:
                return str(entry.get("binding", "") or "")
        return ""

    def reset_defaults(self):
        return self.list_bindings()
