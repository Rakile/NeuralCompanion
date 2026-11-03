"""Small portable authoring example; loading it has no runtime side effects."""

from pathlib import Path
from .scenario_models import decode_scenario_json, parse_scenario


def lighthouse_example() -> dict:
    raw = decode_scenario_json(
        (Path(__file__).parent / "defaults" / "lighthouse_scenario.json").read_text(
            encoding="utf-8"
        )
    )
    return parse_scenario(raw).payload()


def generation_guidance() -> str:
    return (
        "Include scenario_extension matching this exact version-1 structure. Replace the example with the requested story. "
        "Use stable unique ASCII IDs; keep every field and strict value types. Roles must refer to IDs in the story personas. "
        "Allowed triggers: session_started, user_turn_completed, choice_clicked, action_completed. "
        "Conditions are null or {op: eq/ne/lt/le/gt/ge, variable_id, value}, or {op: all/any, children: [conditions]}. "
        "Actions are only mprc.story.narrate {text}, mprc.scenario.change_scene {scene_id}, "
        "mprc.scenario.set_state {variable_id,value}. Events have id,title,trigger,condition,effects,once. "
        "Roles have id,persona_id,instructions. Effects have id,action_id,arguments. "
        "Do not include pending actions, execution history, model tools, scripts, paths or credentials."
    )
