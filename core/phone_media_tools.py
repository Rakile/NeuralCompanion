"""Shared FFmpeg discovery and inspection for phone media delivery."""
import json
import os
import shutil
import subprocess


def tools():
    found = tuple(shutil.which(name) for name in ('ffmpeg', 'ffprobe'))
    if not all(found):
        raise RuntimeError('Encoding measurement blocked: ffmpeg and ffprobe must already be installed')
    return found


def hidden():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def inspect_video(ffprobe, path):
    result = subprocess.run([ffprobe, '-v', 'error', '-show_entries',
                             'stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames:format=duration',
                             '-of', 'json', str(path)], capture_output=True, check=True, timeout=20, **hidden())
    return json.loads(result.stdout)
