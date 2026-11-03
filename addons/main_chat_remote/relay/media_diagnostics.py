"""Bounded, content-free LAN/Internet media diagnostics; private stdout is untouched."""
import logging
import json
import math
from logging.handlers import RotatingFileHandler
import re


_SAFE = re.compile(
    r'(?:audio_deadline_missed phase=(?:pacing|encoding) late_ms=\d+\.\d sample=\d+'
    r'|audio_delivery_gap gap_ms=\d+\.\d sample=\d+'
    r'|audio_reservation key=\d+ first=\d+ samples=\d+'
    r'|audio_(?:commit|cancel) key=\d+'
    r'|audio_track_stopped sample=\d+)')

# Exact, content-free schema. No exception text, paths, asset IDs, SDP or tokens.
_NUMERIC = set('peer key frame stamp elapsed_ms media_ms offered encoded late overwritten thinned '
               'sequence segment status cache_frames idle_start gap_ms pending width height remaining_ms'.split())
_BOOL = {'same_motion', 'ready'}
_ENUM = {
    'event': {'handoff','source_wait','source_error','source_ready','video_sample','video_drop',
              'video_end','pump_sample','pump_error','idle_phase','segment_pending','frame_work','handoff_prepare'},
    'outcome': {'ready','unmapped','hidden','alignment_timeout','cancelled'},
    'phase': {'idle_decode','speech_decode','fade'},
    'operation': {'trial','prepare','segment','prefetch'},
    'error': {'ValueError','TimeoutError','OSError','RuntimeError','other'},
    'mode': {'idle','speech','hidden'},
    'route': {'arm','recover','prepare','prefetch','status','media'},
    'reason': {'spacing','late_before','late_after','missing_segment','worker_error',
               'ownership_changed','invalid_source','cancelled','source_changed'},
}

def _avatar_safe(value):
    if not isinstance(value, dict) or value.get('event') not in _ENUM['event'] or len(value)>24:
        return False
    for key, item in value.items():
        if key in _ENUM:
            if not isinstance(item,str) or item not in _ENUM[key]: return False
        elif key in _BOOL:
            if type(item) is not bool: return False
        elif key in _NUMERIC:
            if type(item) not in (int,float) or not math.isfinite(item) or not 0<=item<=2**53-1: return False
        else: return False
    return True

def avatar_event(logger, event, **fields):
    value={'event':event,**fields}
    if _avatar_safe(value):
        logger.info('avatar_event %s',json.dumps(value,separators=(',',':')))


class _ContentFree(logging.Filter):
    def filter(self, record):
        try:
            message=record.getMessage()
            return (_avatar_safe(json.loads(message[len('avatar_event '):])) if message.startswith('avatar_event ')
                    else _SAFE.fullmatch(message) is not None)
        except (TypeError, ValueError):
            return False


class _MediaLog(RotatingFileHandler):
    def __init__(self, path, loggers):
        super().__init__(path, maxBytes=256 * 1024, backupCount=2, encoding='utf-8', delay=True)
        self.owners = [(logger,logger.level) for logger in loggers]

    def close(self):
        for owner,level in self.owners:
            owner.removeHandler(self)
            owner.setLevel(level)
        super().close()


def install_media_diagnostics(directory, *, internet=False):
    directory.mkdir(parents=True, exist_ok=True)
    loggers=[logging.getLogger('addons.main_chat_remote.relay.'+name)
             for name in ('media_clock','avatar_pump','avatar_source','av_control')]
    handler = _MediaLog(directory / ('av-media-internet.log' if internet else 'av-media.log'), loggers)
    handler.addFilter(_ContentFree())
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return handler
