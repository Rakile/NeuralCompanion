from __future__ import annotations


SCENE_ONLY = "scene_only"
STORY_BIBLE = "story_bible"
VALID_ANALYSIS_MODES = {SCENE_ONLY, STORY_BIBLE}


def normalize_analysis_mode(value) -> str:
    mode = str(value or SCENE_ONLY).strip().lower()
    return mode if mode in VALID_ANALYSIS_MODES else SCENE_ONLY
