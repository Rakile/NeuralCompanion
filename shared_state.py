from __future__ import annotations

from addons.musetalk_avatar import state as musetalk_state
from addons.visual_reply import state as visual_reply_state


current_expression_data = {}

MUSE_PREVIEW_STATE_PATH = musetalk_state.MUSE_PREVIEW_STATE_PATH
MUSE_PREVIEW_FRAME_PATH = musetalk_state.MUSE_PREVIEW_FRAME_PATH
MUSE_PREVIEW_LOG_PATH = musetalk_state.MUSE_PREVIEW_LOG_PATH
VISUAL_REPLY_STATE_PATH = visual_reply_state.VISUAL_REPLY_STATE_PATH
MUSE_PREVIEW_FILE_LOG_ENABLED = musetalk_state.MUSE_PREVIEW_FILE_LOG_ENABLED


_MUSE_DYNAMIC_NAMES = {
    "current_musetalk_frame_data",
    "current_musetalk_preview_chunk_id",
    "current_musetalk_pipeline_data",
}
_VISUAL_DYNAMIC_NAMES = {
    "current_visual_reply_data",
}


def __getattr__(name):
    if name in _MUSE_DYNAMIC_NAMES:
        return getattr(musetalk_state, name)
    if name in _VISUAL_DYNAMIC_NAMES:
        return getattr(visual_reply_state, name)
    raise AttributeError(name)


def append_musetalk_preview_log(message):
    return musetalk_state.append_musetalk_preview_log(message)


def write_musetalk_preview_snapshot(state=None):
    return musetalk_state.write_musetalk_preview_snapshot(state)


def write_musetalk_preview_frame(payload):
    return musetalk_state.write_musetalk_preview_frame(payload)


def consume_musetalk_preview_feed(after_seq=0):
    return musetalk_state.consume_musetalk_preview_feed(after_seq)


def set_current_musetalk_frame_data(state):
    return musetalk_state.set_current_musetalk_frame_data(state)


def update_current_musetalk_frame_data(**updates):
    return musetalk_state.update_current_musetalk_frame_data(**updates)


def write_visual_reply_snapshot(state=None):
    return visual_reply_state.write_visual_reply_snapshot(state)


def set_current_visual_reply_data(state):
    return visual_reply_state.set_current_visual_reply_data(state)


def update_current_visual_reply_data(**updates):
    return visual_reply_state.update_current_visual_reply_data(**updates)


def reset_musetalk_pipeline_data():
    return musetalk_state.reset_musetalk_pipeline_data()


def begin_musetalk_pipeline_reply(stream_mode=False):
    return musetalk_state.begin_musetalk_pipeline_reply(stream_mode=stream_mode)


def update_musetalk_pipeline_chunk(sequence_index, reply_id=None, **updates):
    return musetalk_state.update_musetalk_pipeline_chunk(sequence_index, reply_id=reply_id, **updates)


def update_musetalk_pipeline_flags(reply_id=None, **updates):
    return musetalk_state.update_musetalk_pipeline_flags(reply_id=reply_id, **updates)


def get_musetalk_pipeline_snapshot():
    return musetalk_state.get_musetalk_pipeline_snapshot()
