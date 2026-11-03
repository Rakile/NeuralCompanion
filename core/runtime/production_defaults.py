from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.addons import bootstrap_runtime
from core.runtime.config_defaults import build_runtime_config_defaults
from core.sensory import DEFAULT_SENSORY_PINGPONG_PROMPT

@dataclass(frozen=True, slots=True)
class ProductionRuntimeDefaults:
    config: dict[str, Any]
    visual_reply_capabilities: Any | None
    visual_reply_story_theme_presets: tuple[Any, ...]


def build_production_runtime_defaults(
    app_root: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    before_visual_reply_publish: Callable[[dict[str, Any]], bool],
) -> ProductionRuntimeDefaults:
    root = Path(app_root).resolve()
    environment = os.environ if environ is None else environ
    config_ref: dict[str, Any] = {}
    visual_capabilities = bootstrap_runtime.invoke_addon_capability(
        "nc.visual_reply",
        "runtime.host_capabilities",
        {
            "config_getter": lambda: config_ref,
            "environ": environment,
            "output_dir": root / "runtime" / "visual_replies",
            "before_publish": before_visual_reply_publish,
        },
        app_root=root,
        default=None,
    )
    story_prompts = (
        dict(visual_capabilities.default_story_theme_prompts() or {})
        if visual_capabilities is not None
        else {}
    )
    config_ref.update(
        build_runtime_config_defaults(
            root,
            environ=environment,
            sensory_pingpong_prompt=DEFAULT_SENSORY_PINGPONG_PROMPT,
            visual_reply_story_theme_prompts=story_prompts,
        )
    )
    return ProductionRuntimeDefaults(
        config=config_ref,
        visual_reply_capabilities=visual_capabilities,
        visual_reply_story_theme_presets=tuple(
            getattr(visual_capabilities, "VISUAL_REPLY_STORY_THEME_PRESETS", ()) or ()
        ),
    )


__all__ = ["ProductionRuntimeDefaults", "build_production_runtime_defaults"]
