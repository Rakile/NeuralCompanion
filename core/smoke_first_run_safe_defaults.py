from __future__ import annotations

import ast
import json
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _engine_default_nodes() -> dict[str, ast.AST]:
    module = ast.parse((ROOT / "engine.py").read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "RUNTIME_CONFIG" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            break
        defaults: dict[str, ast.AST] = {}
        for key_node, value_node in zip(node.value.keys, node.value.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            defaults[key_node.value] = value_node
        return defaults
    raise AssertionError("engine.py RUNTIME_CONFIG dictionary was not found")


def _engine_constant_defaults() -> dict[str, object]:
    return {
        key: value.value
        for key, value in _engine_default_nodes().items()
        if isinstance(value, ast.Constant)
    }


def _environment_fallback(node: ast.AST) -> object:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or len(child.args) < 2:
            continue
        function = child.func
        if not isinstance(function, ast.Attribute) or function.attr != "get":
            continue
        owner = function.value
        if not (
            isinstance(owner, ast.Attribute)
            and owner.attr == "environ"
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "os"
        ):
            continue
        return ast.literal_eval(child.args[1])
    raise AssertionError("environment-backed default has no os.environ.get fallback")


def _widget(root: ET.Element, name: str) -> ET.Element:
    widget = root.find(f".//widget[@name='{name}']")
    if widget is None:
        raise AssertionError(f"main.ui widget not found: {name}")
    return widget


def _property_value(widget: ET.Element, name: str, default: object) -> object:
    property_node = widget.find(f"./property[@name='{name}']")
    if property_node is None or len(property_node) != 1:
        return default
    value_node = property_node[0]
    if value_node.tag == "number":
        return int(value_node.text or 0)
    if value_node.tag == "bool":
        return str(value_node.text or "false").strip().lower() == "true"
    return value_node.text


def test_first_run_runtime_defaults_are_safe() -> None:
    default_nodes = _engine_default_nodes()
    defaults = _engine_constant_defaults()

    assert defaults["avatar_mode"] == "none"
    assert defaults["allow_proactive_replies"] is False
    assert defaults["spellcheck_enabled"] is True
    assert _environment_fallback(default_nodes["sensory_feedback_source"]) == "off"
    assert _environment_fallback(default_nodes["sensory_pingpong_enabled"]) == "0"
    assert _environment_fallback(default_nodes["sensory_allow_hidden_proactive_speech"]) == "0"
    assert _environment_fallback(default_nodes["sensory_allow_hidden_visual_generation"]) == "0"
    assert defaults["companion_orb_sensory_target_enabled"] is False

    for key in (
        "require_first_user_before_proactive",
        "continuity_memory_enabled",
        "continuity_memory_auto_summarize",
        "continuity_memory_inject",
        "long_term_memory_retrieval_enabled",
        "long_term_memory_image_review_enabled",
        "long_term_memory_auto_archive_enabled",
    ):
        assert defaults[key] is False, key


def test_first_run_musetalk_and_ui_defaults_agree() -> None:
    addon = json.loads((ROOT / "addons" / "musetalk_avatar" / "addon.json").read_text(encoding="utf-8"))
    assert addon["runtime_defaults"]["musetalk_vram_mode"] == "balanced"

    ui_root = ET.parse(ROOT / "main.ui").getroot()
    assert _property_value(_widget(ui_root, "engine_combo"), "currentIndex", 0) == 3
    assert _property_value(_widget(ui_root, "musetalk_vram_combo"), "currentIndex", 0) == 1
    assert _property_value(_widget(ui_root, "allow_proactive_checkbox"), "checked", False) is False


def test_tutorial_persona_does_not_enable_background_awareness() -> None:
    tutorial = json.loads((ROOT / "presets" / "Tutorial_Persona.json").read_text(encoding="utf-8"))

    assert tutorial["sensory_feedback_source"] == "off"
    assert tutorial["sensory_pingpong_enabled"] is False
    assert tutorial["sensory_allow_hidden_proactive_speech"] is False
    assert tutorial["sensory_allow_hidden_visual_generation"] is False
    assert tutorial["clipboard_supervisor_enabled"] is False
    assert tutorial["screen_supervisor_enabled"] is False
    assert tutorial["webcam_supervisor_enabled"] is False
    assert tutorial["heart_rate_behavior_enabled"] is False
    assert tutorial["allow_proactive_replies"] is False

    assert "companion_orb_target" in tutorial["sensory_pingpong_source_prompts"]
    assert "companion_orb_target" in tutorial["sensory_provider_metadata_overrides"]


if __name__ == "__main__":
    test_first_run_runtime_defaults_are_safe()
    test_first_run_musetalk_and_ui_defaults_agree()
    test_tutorial_persona_does_not_enable_background_awareness()
    print("smoke_first_run_safe_defaults: ok")
