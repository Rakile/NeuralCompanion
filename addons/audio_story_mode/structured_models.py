from __future__ import annotations

from collections.abc import Mapping
from typing import Any


try:
    from pydantic import BaseModel, ConfigDict, Field, model_validator

    PYDANTIC_AVAILABLE = True
except Exception:
    BaseModel = object  # type: ignore[assignment]
    ConfigDict = None  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]
    model_validator = None  # type: ignore[assignment]
    PYDANTIC_AVAILABLE = False


if PYDANTIC_AVAILABLE:

    class StoryEntity(BaseModel):
        model_config = ConfigDict(extra="ignore")

        id: str
        label: str
        aliases: list[str] = Field(default_factory=list)
        summary: str = ""
        appearance_anchor: str = ""
        anchor_text: str = ""


    class StoryBeat(BaseModel):
        model_config = ConfigDict(extra="ignore")

        beat_id: str
        chunk_index: int = Field(default=0, ge=0)
        start_seconds: float = Field(default=0.0, ge=0.0)
        end_seconds: float = Field(default=0.0, ge=0.0)
        story_event: str
        narrative_function: str = ""
        character_ids: list[str] = Field(default_factory=list)
        location_id: str = ""
        visible_action: str
        mood: str = ""
        lighting: str = ""
        camera: str = ""
        continuity_anchors: list[str] = Field(default_factory=list)
        visual_change_score: float = Field(default=0.5, ge=0.0, le=1.0)
        image_worthy: bool = True
        source_evidence: str = ""
        confidence: float = Field(default=0.5, ge=0.0, le=1.0)
        avoid: list[str] = Field(default_factory=list)

        @model_validator(mode="after")
        def _ordered_times(self):
            if self.end_seconds < self.start_seconds:
                self.end_seconds = self.start_seconds
            return self


    class StoryBeatAnalysis(BaseModel):
        model_config = ConfigDict(extra="ignore")

        story_summary: str = ""
        global_visual_style: str = ""
        world_anchor: str = ""
        tone: list[str] = Field(default_factory=list)
        palette: list[str] = Field(default_factory=list)
        time_period: str = ""
        characters: list[StoryEntity] = Field(default_factory=list)
        locations: list[StoryEntity] = Field(default_factory=list)
        beats: list[StoryBeat] = Field(min_length=1)

else:
    StoryEntity = None
    StoryBeat = None
    StoryBeatAnalysis = None


def model_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        result = dumper(mode="python")
        return dict(result) if isinstance(result, Mapping) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _clean_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def story_beat_payload_to_existing_analysis(payload: Any) -> dict[str, Any]:
    source = model_to_dict(payload)
    if PYDANTIC_AVAILABLE and StoryBeatAnalysis is not None:
        source = StoryBeatAnalysis.model_validate(source).model_dump(mode="python")
    characters = [dict(item) for item in list(source.get("characters") or []) if isinstance(item, Mapping)]
    locations = [dict(item) for item in list(source.get("locations") or []) if isinstance(item, Mapping)]
    story_bible = {
        "summary": _clean_text(source.get("story_summary"), 900),
        "global_visual_style": _clean_text(source.get("global_visual_style"), 600),
        "world_anchor": _clean_text(source.get("world_anchor"), 600),
        "tone": [str(item).strip() for item in list(source.get("tone") or []) if str(item).strip()],
        "palette": [str(item).strip() for item in list(source.get("palette") or []) if str(item).strip()],
        "time_period": _clean_text(source.get("time_period"), 120),
        "characters": characters,
        "locations": locations,
        "props": [],
    }
    scenes = []
    for index, raw_beat in enumerate(list(source.get("beats") or [])):
        if not isinstance(raw_beat, Mapping):
            continue
        beat = dict(raw_beat)
        visible_action = _clean_text(beat.get("visible_action"), 320)
        image_parts = [
            visible_action,
            _clean_text(beat.get("lighting"), 160),
            _clean_text(beat.get("mood"), 120),
            _clean_text(beat.get("camera"), 120),
        ]
        scene_id = _clean_text(beat.get("beat_id"), 100) or f"beat_{index + 1}"
        continuity = "; ".join(
            str(item).strip()
            for item in list(beat.get("continuity_anchors") or [])
            if str(item).strip()
        )
        avoid = "; ".join(
            str(item).strip()
            for item in list(beat.get("avoid") or [])
            if str(item).strip()
        )
        scenes.append(
            {
                "chunk_index": max(0, int(beat.get("chunk_index", index) or 0)),
                "scene_id": scene_id,
                "is_new_scene": bool(beat.get("image_worthy", True)),
                "continuation_of_scene_id": "",
                "location_id": _clean_text(beat.get("location_id"), 100),
                "active_character_ids": [
                    str(item).strip()
                    for item in list(beat.get("character_ids") or [])
                    if str(item).strip()
                ],
                "prop_ids": [],
                "scene_focus": _clean_text(beat.get("story_event"), 320),
                "image_prompt": _clean_text(
                    ", ".join(part for part in image_parts if part),
                    600,
                ),
                "key_action": visible_action,
                "environment": _clean_text(beat.get("location_id"), 180),
                "mood": _clean_text(beat.get("mood"), 120),
                "time_of_day": "",
                "camera": _clean_text(beat.get("camera"), 120),
                "continuity_priority": ["characters", "location", "mood"],
                "continuity": _clean_text(continuity, 320),
                "preserve": _clean_text(continuity, 320),
                "avoid": _clean_text(avoid, 240),
                "start_seconds": max(0.0, float(beat.get("start_seconds", 0.0) or 0.0)),
                "end_seconds": max(0.0, float(beat.get("end_seconds", 0.0) or 0.0)),
                "visual_change_score": float(beat.get("visual_change_score", 0.5) or 0.5),
                "source_evidence": _clean_text(beat.get("source_evidence"), 320),
                "confidence": float(beat.get("confidence", 0.5) or 0.5),
            }
        )
    return {"story_bible": story_bible, "scenes": scenes}


__all__ = [
    "PYDANTIC_AVAILABLE",
    "StoryBeat",
    "StoryBeatAnalysis",
    "StoryEntity",
    "model_to_dict",
    "story_beat_payload_to_existing_analysis",
]
