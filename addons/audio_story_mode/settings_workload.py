from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


class SettingsApplyCancelled(RuntimeError):
    """Stop a staged settings workload without hiding cancellation as fallback."""


def _clean(value: object) -> str:
    return str(value or "").strip()


def _unique(values: object) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in list(values or []):
        normalized = _clean(value).lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


def _clamped_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = int(default)
    return max(int(minimum), min(int(maximum), normalized))


def _clamped_float(
    value: object, *, default: float, minimum: float, maximum: float
) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        normalized = float(default)
    return max(float(minimum), min(float(maximum), normalized))


@dataclass(frozen=True)
class PlannerSettingsSnapshot:
    analysis_mode: str = "scene_only"
    use_llm_story_analysis: bool = False
    instructor_beats_enabled: bool = False
    provider_mode: str = "current"
    provider_id: str = ""
    provider_label: str = "Current Chat Provider"
    model_override: str = ""
    continuity_strength: float = 0.8

    @classmethod
    def from_mapping(cls, source: Mapping | None) -> "PlannerSettingsSnapshot":
        value = dict(source or {})
        analysis_mode = _clean(value.get("analysis_mode") or "scene_only").lower()
        provider_mode = _clean(value.get("provider_mode") or "current").lower()
        return cls(
            analysis_mode=analysis_mode if analysis_mode in {"scene_only", "story_bible"} else "scene_only",
            use_llm_story_analysis=bool(value.get("use_llm_story_analysis", False)),
            instructor_beats_enabled=bool(value.get("instructor_beats_enabled", False)),
            provider_mode=provider_mode if provider_mode in {"current", "deepseek", "lmstudio"} else "current",
            provider_id=_clean(value.get("provider_id")).lower(),
            provider_label=_clean(value.get("provider_label") or "Current Chat Provider"),
            model_override=_clean(value.get("model_override")),
            continuity_strength=_clamped_float(
                value.get("continuity_strength", 0.8),
                default=0.8,
                minimum=0.0,
                maximum=1.0,
            ),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "analysis_mode": self.analysis_mode,
            "use_llm_story_analysis": self.use_llm_story_analysis,
            "instructor_beats_enabled": self.instructor_beats_enabled,
            "provider_mode": self.provider_mode,
            "provider_id": self.provider_id,
            "provider_label": self.provider_label,
            "model_override": self.model_override,
            "continuity_strength": self.continuity_strength,
        }


@dataclass(frozen=True)
class StyleSettingsSnapshot:
    style_enabled: tuple[str, ...] = ()
    style_prompts: tuple[tuple[str, str], ...] = ()
    style_change_live: bool = False
    master_prompt_enabled: bool = False
    master_prompt_mode: str = "medium"
    prompt_block_limits: tuple[tuple[str, int], ...] = ()
    prompt_safety_cap: int = 1800

    @classmethod
    def from_mapping(cls, source: Mapping | None) -> "StyleSettingsSnapshot":
        value = dict(source or {})
        prompts = tuple(
            sorted(
                (
                    _clean(key).lower(),
                    _clean(prompt),
                )
                for key, prompt in dict(value.get("style_prompts") or {}).items()
                if _clean(key)
            )
        )
        mode = _clean(value.get("master_prompt_mode") or "medium").lower()
        block_limits = tuple(
            sorted(
                (
                    _clean(key).lower(),
                    _clamped_int(limit, default=40, minimum=40, maximum=1600),
                )
                for key, limit in dict(value.get("prompt_block_limits") or {}).items()
                if _clean(key)
            )
        )
        safety_cap = _clamped_int(
            value.get("prompt_safety_cap", 1800),
            default=1800,
            minimum=400,
            maximum=6000,
        )
        return cls(
            style_enabled=_unique(value.get("style_enabled") or ()),
            style_prompts=prompts,
            style_change_live=bool(value.get("style_change_live", False)),
            master_prompt_enabled=bool(value.get("master_prompt_enabled", False)),
            master_prompt_mode=mode if mode in {"simple", "medium", "strong", "strongest"} else "medium",
            prompt_block_limits=block_limits,
            prompt_safety_cap=safety_cap,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "style_enabled": list(self.style_enabled),
            "style_prompts": dict(self.style_prompts),
            "style_change_live": self.style_change_live,
            "master_prompt_enabled": self.master_prompt_enabled,
            "master_prompt_mode": self.master_prompt_mode,
            "prompt_block_limits": dict(self.prompt_block_limits),
            "prompt_safety_cap": self.prompt_safety_cap,
        }


@dataclass(frozen=True)
class SettingsApplyRequest:
    generation_id: int
    operation: Literal["planner", "style"]
    project_id: str
    project_generation: int
    manifest_revision: int
    input_fingerprint: str
    planner: PlannerSettingsSnapshot
    style: StyleSettingsSnapshot

    def ownership_payload(self) -> dict[str, object]:
        return {
            "generation_id": self.generation_id,
            "operation": self.operation,
            "project_id": self.project_id,
            "project_generation": self.project_generation,
            "manifest_revision": self.manifest_revision,
            "input_fingerprint": self.input_fingerprint,
        }
