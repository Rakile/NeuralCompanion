from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from addons.vam_avatar.hymotion_config import resolve_settings


KEEP_ATOM_TYPES = {
    "WindowCamera",
    "PlayerNavigationPanel",
    "CoreControl",
    "VRController",
    "Person",
    "InvisibleLight",
    "Empty",
}


def _vec(x: float, y: float, z: float) -> dict[str, str]:
    return {"x": f"{x:.4f}", "y": f"{y:.4f}", "z": f"{z:.4f}"}


def _button_atom(atom_id: str, label: str, y: float, receiver_target: str, *, bool_value: bool | None = None) -> dict[str, Any]:
    action: dict[str, Any] = {
        "name": f"A_{receiver_target}",
        "receiverAtom": "Person",
        "receiver": "plugin#0_NeuralCompanionBridge",
        "receiverTargetName": receiver_target,
    }
    if bool_value is not None:
        action["boolValue"] = "true" if bool_value else "false"

    return {
        "id": atom_id,
        "on": "true",
        "collisionEnabled": "false",
        "type": "UIButtonImage",
        "position": _vec(0.0, 0.0, 0.0),
        "rotation": _vec(0.0, 0.0, 0.0),
        "containerPosition": _vec(-0.95, y, -1.15),
        "containerRotation": _vec(0.0, 0.0, 0.0),
        "storables": [
            {"id": "AtomControl", "hidden": "true"},
            {"id": "scale", "scale": "1.0"},
            {"id": "Canvas", "xSize": "260", "ySize": "58"},
            {"id": "VisibilityControl", "onlyVisibleWhenMainUIOpen": "false"},
            {
                "id": "BackgroundColor",
                "alpha": "0.75",
                "color": {"h": "0.58", "s": "0.74", "v": "0.28"},
            },
            {
                "id": "Trigger",
                "trigger": {
                    "displayName": f"A_{label}",
                    "startActions": [action],
                    "transitionActions": [],
                    "endActions": [],
                },
            },
            {
                "id": "control",
                "canGrabPosition": "false",
                "canGrabRotation": "false",
                "position": _vec(-0.95, y, -1.15),
                "rotation": _vec(0.0, 0.0, 0.0),
            },
        ],
    }


def _label_atom(atom_id: str, label: str, y: float) -> dict[str, Any]:
    return {
        "id": atom_id,
        "on": "true",
        "collisionEnabled": "false",
        "type": "UIText",
        "position": _vec(0.0, 0.0, 0.0),
        "rotation": _vec(0.0, 0.0, 0.0),
        "containerPosition": _vec(-0.95, y, -1.18),
        "containerRotation": _vec(0.0, 0.0, 0.0),
        "storables": [
            {"id": "AtomControl", "hidden": "true"},
            {"id": "scale", "scale": "0.9"},
            {"id": "Text", "fontSize": "28", "text": label},
            {"id": "Panel", "alpha": "0"},
            {"id": "TextColor", "color": {"h": "0.53", "s": "0.35", "v": "1.0"}},
            {
                "id": "control",
                "canGrabPosition": "false",
                "canGrabRotation": "false",
                "position": _vec(-0.95, y, -1.18),
                "rotation": _vec(0.0, 0.0, 0.0),
            },
        ],
    }


def _section_atom(atom_id: str, label: str, y: float) -> dict[str, Any]:
    atom = _label_atom(atom_id, label, y)
    for storable in atom["storables"]:
        if storable.get("id") == "Text":
            storable["fontSize"] = "34"
            storable["text"] = label
        elif storable.get("id") == "TextColor":
            storable["color"] = {"h": "0.12", "s": "0.85", "v": "1.0"}
    return atom


def add_lab_buttons(scene: dict[str, Any]) -> None:
    atoms = scene.setdefault("atoms", [])
    atoms[:] = [atom for atom in atoms if not str(atom.get("id", "")).startswith("NC HY-Motion ")]
    atoms.append(_section_atom("NC HY-Motion Router Header", "NC HY-Motion Action Router", 1.94))
    buttons = [
        ("NC HY-Motion Self Test Button", "NC HY-Motion Self Test Label", "Self Test", 1.72, "NC Bridge Self Test", None),
        ("NC HY-Motion Play Button", "NC HY-Motion Play Label", "Play Latest", 1.54, "Play Latest HY-Motion", None),
        ("NC HY-Motion Stop Button", "NC HY-Motion Stop Label", "Stop", 1.36, "Stop HY-Motion", None),
        ("NC HY-Motion Reset Button", "NC HY-Motion Reset Label", "Reset Pose", 1.18, "Reset HY-Motion Pose", None),
        ("NC HY-Motion Loop On Button", "NC HY-Motion Loop On Label", "Loop On", 1.00, "Loop HY-Motion", True),
        ("NC HY-Motion Loop Off Button", "NC HY-Motion Loop Off Label", "Loop Off", 0.82, "Loop HY-Motion", False),
        ("NC HY-Motion Started Trigger Button", "NC HY-Motion Started Trigger Label", "Started Event", 0.52, "Open HY-Motion Started Trigger", None),
        ("NC HY-Motion Finished Trigger Button", "NC HY-Motion Finished Trigger Label", "Finished Event", 0.34, "Open HY-Motion Finished Trigger", None),
        ("NC HY-Motion Failed Trigger Button", "NC HY-Motion Failed Trigger Label", "Missing/Failed Event", 0.16, "Open HY-Motion Missing/Failed Trigger", None),
    ]
    for button_id, label_id, label, y, target, bool_value in buttons:
        if label == "Started Event":
            atoms.append(_section_atom("NC HY-Motion Events Header", "Event Triggers", 0.68))
        atoms.append(_button_atom(button_id, label, y, target, bool_value=bool_value))
        atoms.append(_label_atom(label_id, label, y))
    atoms.append(_label_atom("NC HY-Motion Events Help", "Use event trigger panels to wire lights, UI, audio, expressions, or Timeline reactions.", -0.04))


def _scene_files(vam_root: Path) -> list[Path]:
    scene_root = vam_root / "Saves" / "scene"
    if not scene_root.exists():
        return []
    return sorted(scene_root.rglob("*.json"), key=lambda p: p.stat().st_size)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _has_bridge(scene: dict[str, Any]) -> bool:
    return "NeuralCompanionBridge" in json.dumps(scene)


def _person_count(scene: dict[str, Any]) -> int:
    return sum(1 for atom in scene.get("atoms") or [] if atom.get("type") == "Person")


def find_bridge_scene(vam_root: Path, source: str = "") -> Path | None:
    if source.strip():
        path = Path(source).expanduser()
        return path if path.exists() else None
    for path in _scene_files(vam_root):
        scene = _read_json(path)
        if not scene:
            continue
        if _person_count(scene) == 1 and _has_bridge(scene):
            return path
    return None


def trim_scene(scene: dict[str, Any]) -> dict[str, Any]:
    trimmed = {
        key: value
        for key, value in scene.items()
        if key != "atoms"
    }
    atoms = []
    for atom in scene.get("atoms") or []:
        atom_type = str(atom.get("type") or "")
        atom_id = str(atom.get("id") or "")
        if atom_type in KEEP_ATOM_TYPES or atom_id in {"AutoFocusPoint"}:
            atoms.append(atom)
    trimmed["atoms"] = atoms
    add_lab_buttons(trimmed)
    return trimmed


def install_lab_scene(vam_root: Path, *, source: str = "", dry_run: bool = False) -> dict[str, Any]:
    source_path = find_bridge_scene(vam_root, source)
    if source_path is None:
        return {
            "ok": False,
            "error": f"No one-Person scene containing NeuralCompanionBridge was found under {vam_root / 'Saves' / 'scene'}.",
        }

    scene = _read_json(source_path)
    if not scene:
        return {"ok": False, "error": f"Could not read source scene: {source_path}"}

    trimmed = trim_scene(scene)
    target = vam_root / "Saves" / "scene" / "NeuralCompanion" / "HY_Motion_Lab.json"
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(trimmed, indent=3), encoding="utf-8")

    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "source": str(source_path),
        "target": str(target),
        "source_atoms": len(scene.get("atoms") or []),
        "lab_atoms": len(trimmed.get("atoms") or []),
        "has_bridge": _has_bridge(trimmed),
        "person_count": _person_count(trimmed),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Install a small VaM HY-Motion lab scene from an existing bridge scene.")
    parser.add_argument("--vam-root", default="", help="VaM root path. Defaults to the configured VaM root.")
    parser.add_argument("--source", default="", help="Optional source scene JSON to trim/copy.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = resolve_settings(overrides={"vam_root": args.vam_root} if args.vam_root.strip() else {})
    result = install_lab_scene(Path(settings.vam_root), source=args.source, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
