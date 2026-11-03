from __future__ import annotations

current_expression_data = {}


def set_current_expression_data(state):
    global current_expression_data
    current_expression_data = dict(state or {})


def reset_current_expression_data():
    set_current_expression_data({"names": [], "frames": []})
