"""Smoke checks for performance profile chunking settings."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_PATH = ROOT_DIR / "ui" / "runtime" / "backend_dry_run_runtime.py"

MUSETALK_TIMING_KEYS = {
    "musetalk_chunk_target_chars",
    "musetalk_chunk_max_chars",
    "musetalk_quickstart_1_target_chars",
    "musetalk_quickstart_1_max_chars",
    "musetalk_quickstart_2_target_chars",
    "musetalk_quickstart_2_max_chars",
}


def _backend_tree() -> ast.Module:
    return ast.parse(BACKEND_PATH.read_text(encoding="utf-8"), filename=str(BACKEND_PATH))


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} was not found")


def _base_apply_keys(tree: ast.Module) -> set[str]:
    namespace: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "BASE_PERFORMANCE_PROFILE_APPLY_KEYS" in names:
                module = ast.Module(body=[node], type_ignores=[])
                ast.fix_missing_locations(module)
                exec(compile(module, str(BACKEND_PATH), "exec"), namespace)
                break
    return set(namespace.get("BASE_PERFORMANCE_PROFILE_APPLY_KEYS") or set())


def test_performance_profiles_apply_musetalk_timing_keys_without_active_musetalk() -> None:
    missing = MUSETALK_TIMING_KEYS - _base_apply_keys(_backend_tree())
    assert not missing, f"MuseTalk timing keys missing from profile apply keys: {sorted(missing)}"


def test_save_latest_performance_profile_captures_chunking_sliders() -> None:
    tree = _backend_tree()
    function = _find_function(tree, "save_latest_performance_profile")
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_build_current_performance_override"
    ]
    assert calls, "save_latest_performance_profile must build a current override"
    assert any(
        keyword.arg == "include_chunking"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for call in calls
        for keyword in call.keywords
    ), "Saving a performance profile must capture current chunking sliders"


if __name__ == "__main__":
    test_performance_profiles_apply_musetalk_timing_keys_without_active_musetalk()
    test_save_latest_performance_profile_captures_chunking_sliders()
    print("performance profile chunking smoke checks passed.")
