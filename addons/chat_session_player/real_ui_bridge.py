from PySide6 import QtCore


def add_replay_context_menu_action_for_backend(backend, menu, chat_edit, point):
    """Add Chat Player replay action to the main Chat context menu when applicable."""
    if menu is None or chat_edit is None or bool(getattr(backend, "chat_edit_mode", False)):
        return
    replay_index = None
    try:
        cursor = chat_edit.cursorForPosition(point)
        position = cursor.position()
        resolver = getattr(backend, "_replay_index_for_chat_position", None)
        if not callable(resolver):
            resolver = getattr(backend, "_assistant_replay_index_for_chat_position", None)
        replay_index = resolver(position) if callable(resolver) else None
    except Exception:
        replay_index = None
    if replay_index is None:
        return
    try:
        menu.addSeparator()
        replay_action = menu.addAction(f"Start Playing From This Message (#{replay_index})")
        replay_action.triggered.connect(
            lambda _checked=False, idx=replay_index: QtCore.QTimer.singleShot(
                250,
                lambda: backend.trigger_replay_from_chat_index(idx),
            )
        )
    except Exception:
        pass


def add_replay_context_menu_action(bridge, menu, chat_edit, point):
    add_replay_context_menu_action_for_backend(bridge.backend, menu, chat_edit, point)
