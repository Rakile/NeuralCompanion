from __future__ import annotations

import importlib

from core import expression_state


def _musetalk_state():
    return importlib.import_module("addons.musetalk_avatar.state")


def _visual_reply_state():
    return importlib.import_module("addons.visual_reply.state")


_MUSE_DYNAMIC_NAMES = {
    "MUSE_PREVIEW_STATE_PATH",
    "MUSE_PREVIEW_FRAME_PATH",
    "MUSE_PREVIEW_LOG_PATH",
    "MUSE_PREVIEW_FILE_LOG_ENABLED",
    "current_musetalk_frame_data",
    "current_musetalk_preview_chunk_id",
    "current_musetalk_pipeline_data",
}
_VISUAL_DYNAMIC_NAMES = {
    "VISUAL_REPLY_STATE_PATH",
    "current_visual_reply_data",
}
_EXPRESSION_DYNAMIC_NAMES = {
    "current_expression_data",
}


def __getattr__(name):
    if name in _MUSE_DYNAMIC_NAMES:
        return getattr(_musetalk_state(), name)
    if name in _VISUAL_DYNAMIC_NAMES:
        return getattr(_visual_reply_state(), name)
    if name in _EXPRESSION_DYNAMIC_NAMES:
        return getattr(expression_state, name)
    raise AttributeError(name)


def append_musetalk_preview_log(message):
    return _musetalk_state().append_musetalk_preview_log(message)


def write_musetalk_preview_snapshot(state=None):
    return _musetalk_state().write_musetalk_preview_snapshot(state)


def write_musetalk_preview_frame(payload):
    return _musetalk_state().write_musetalk_preview_frame(payload)


def consume_musetalk_preview_feed(after_seq=0):
    return _musetalk_state().consume_musetalk_preview_feed(after_seq)


def set_current_musetalk_frame_data(state):
    return _musetalk_state().set_current_musetalk_frame_data(state)


def update_current_musetalk_frame_data(**updates):
    return _musetalk_state().update_current_musetalk_frame_data(**updates)


def write_visual_reply_snapshot(state=None):
    return _visual_reply_state().write_visual_reply_snapshot(state)


def set_current_visual_reply_data(state):
    return _visual_reply_state().set_current_visual_reply_data(state)


def update_current_visual_reply_data(**updates):
    return _visual_reply_state().update_current_visual_reply_data(**updates)


def reset_musetalk_pipeline_data():
    return _musetalk_state().reset_musetalk_pipeline_data()


def begin_musetalk_pipeline_reply(stream_mode=False):
    return _musetalk_state().begin_musetalk_pipeline_reply(stream_mode=stream_mode)


def update_musetalk_pipeline_chunk(sequence_index, reply_id=None, **updates):
    return _musetalk_state().update_musetalk_pipeline_chunk(sequence_index, reply_id=reply_id, **updates)


def update_musetalk_pipeline_flags(reply_id=None, **updates):
    return _musetalk_state().update_musetalk_pipeline_flags(reply_id=reply_id, **updates)


def get_musetalk_pipeline_snapshot():
    return _musetalk_state().get_musetalk_pipeline_snapshot()


def set_current_expression_data(state):
    return expression_state.set_current_expression_data(state)


def reset_current_expression_data():
    return expression_state.reset_current_expression_data()
