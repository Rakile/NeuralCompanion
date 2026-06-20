from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from addons.vam_avatar.hymotion_config import resolve_settings, validate_model_path
from addons.vam_avatar.hymotion_runner import (
    build_command,
    build_vam_timeline_export,
    build_vam_bridge_payload,
    run_prompt_to_motion,
    write_vam_bridge_command,
)
from addons.vam_avatar.scripts.hymotion_test_app import send_bridge_action


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def main() -> int:
    settings = resolve_settings()
    assert_true(settings.model_name == "HY-Motion-1.0-Lite", "Lite model should be the default.")
    assert_true(str(settings.vam_root).lower().endswith("vam 1.20.0.6") or settings.vam_root == "", "VaM root default should be configurable.")

    check = validate_model_path(settings.model_path)
    assert_true({"ok", "config_path", "checkpoint_path", "missing"}.issubset(check), "Model check shape changed.")

    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir) / "outputs"
        input_dir = Path(temp_dir) / "inputs"
        dry = run_prompt_to_motion(
            "A person waves hello with a relaxed idle stance.",
            overrides={"output_dir": str(output_dir), "input_dir": str(input_dir), "duration_seconds": 2.0, "num_seeds": 1},
            dry_run=True,
        )
        assert_true(dry["ok"], "Dry-run prompt-to-motion should succeed without GPU or weights.")
        assert_true("--model_path" in dry["command"], "Command must include HY-Motion model path.")
        assert_true("--disable_rewrite" in dry["command"], "Default should disable prompt rewrite.")
        assert_true("--disable_duration_est" in dry["command"], "Default should disable duration estimation.")

        command = build_command(settings, input_text_dir=input_dir, output_dir=output_dir)
        assert_true(str(settings.repo_dir / "local_infer.py") in command, "Command should call local_infer.py.")

        payload = build_vam_bridge_payload(dry, runtime_config={"vam_target_atom_uid": "Person"})
        assert_true(payload["motion_source"] == "hy_motion", "Bridge payload should identify HY-Motion.")
        planned = write_vam_bridge_command(Path(temp_dir) / "bridge", "hy_motion_generated", payload, dry_run=True)
        assert_true(planned["dry_run"], "Bridge command dry-run must not write files.")
        assert_true(planned["path"].endswith("_hy_motion_generated.json"), "Bridge command should target inbox json.")

        stop = send_bridge_action("hy_motion_stop", vam_root=str(Path(temp_dir) / "vam"), dry_run=True)
        assert_true(stop["ok"], "HY-Motion stop action dry-run should build a bridge command.")
        assert_true(stop["command"]["path"].endswith("_hy_motion_stop.json"), "Stop command should use the HY-Motion action name.")

        smpl = Path(temp_dir) / "motion_smpl.json"
        smpl.write_text(
            json.dumps(
                {
                    "frameCount": 2,
                    "fps": 30,
                    "poses": [0.0] * (156 * 2),
                    "trans": [0.0, 0.0, 0.0, 0.1, 0.0, 0.0],
                    "Rh": [0.0, 0.0, 0.0, 0.02, 0.0, 0.0],
                }
            ),
            encoding="utf-8",
        )
        timeline = build_vam_timeline_export(
            smpl,
            Path(temp_dir) / "motion_timeline_clip.json",
            Path(temp_dir) / "motion_timeline_storable.json",
            clip_name="smoke_timeline",
        )
        assert_true(timeline["ok"], timeline.get("error") or "Timeline export should build from SMPL JSON.")
        clip_text = Path(timeline["path"]).read_text(encoding="utf-8")
        assert_true("Controllers" in clip_text and "hipControl" in clip_text, "Timeline export should include VaM controller curves.")

    bridge_source = (REPO_ROOT / "nuralcompanionbridge" / "NeuralCompanionBridge.cs").read_text(encoding="utf-8")
    for required in (
        "Play Latest HY-Motion",
        "Stop HY-Motion",
        "Reset HY-Motion Pose",
        "Set HY-Motion Strength",
        "Loop HY-Motion",
        "Load HY-Motion By Name",
        "HY-Motion Conflict Guard",
        "On HY-Motion Started",
        "On HY-Motion Finished",
        "On HY-Motion Missing/Failed",
    ):
        assert_true(required in bridge_source, f"Bridge is missing VaM trigger surface: {required}")

    if os.environ.get("NC_VAM_HYMOTION_REAL_INFERENCE") == "1":
        real = run_prompt_to_motion(
            "A person stands calmly and breathes.",
            overrides={"duration_seconds": 2.0, "num_seeds": 1},
            dry_run=False,
            timeout_seconds=900,
        )
        assert_true(real["ok"], real.get("error") or "Real HY-Motion inference failed.")

    print("[vam_avatar] HY-Motion smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
