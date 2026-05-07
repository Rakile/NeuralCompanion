def show_dock(bridge):
    dock = bridge._ui_object("VisualReplyDock")
    if dock is None:
        return
    try:
        dock.show()
        dock.raise_()
    except Exception:
        pass


def bind_show_button(bridge):
    show_button = bridge._ui_object("btn_visual_reply")
    if show_button is not None and hasattr(show_button, "clicked"):
        show_button.clicked.connect(lambda: show_dock(bridge))
