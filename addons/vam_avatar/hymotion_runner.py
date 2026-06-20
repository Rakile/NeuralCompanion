"""Subprocess bridge for Tencent HY-Motion text-to-motion generation."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from addons.vam_avatar.hymotion_config import HYMotionSettings, resolve_settings, validate_model_path


MOTION_OUTPUT_SUFFIXES = {
    ".fbx",
    ".bvh",
    ".npz",
    ".npy",
    ".pkl",
    ".html",
    ".json",
}

SMPLH_PROXY_JOINTS = {
    "pelvis": 0,
    "spine1": 9,
    "spine2": 10,
    "spine3": 11,
    "neck": 12,
    "head": 13,
    "left_shoulder": 15,
    "left_elbow": 16,
    "left_wrist": 17,
    "right_shoulder": 34,
    "right_elbow": 35,
    "right_wrist": 36,
}

TIMELINE_SMPL_CONTROLLERS = [
    ("hipControl", 0, True, True),
    ("abdomenControl", 3, False, True),
    ("chestControl", 9, False, True),
    ("neckControl", 12, False, True),
    ("headControl", 15, False, True),
    ("lShoulderControl", 13, False, True),
    ("rShoulderControl", 14, False, True),
    ("lArmControl", 16, False, True),
    ("rArmControl", 17, False, True),
    ("lElbowControl", 18, False, True),
    ("rElbowControl", 19, False, True),
    ("lHandControl", 20, False, True),
    ("rHandControl", 21, False, True),
    ("lThighControl", 1, False, True),
    ("rThighControl", 2, False, True),
    ("lKneeControl", 4, False, True),
    ("rKneeControl", 5, False, True),
    ("lFootControl", 7, False, True),
    ("rFootControl", 8, False, True),
]

VOXTA_ANIMATION_DIR = Path("Saves") / "PluginData" / "Voxta" / "Animation"


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _safe_motion_id(value: str | None = None) -> str:
    base = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return base[:60] or f"motion_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def _duration_to_frames(duration_seconds: float) -> int:
    return max(1, int(round(max(0.25, float(duration_seconds)) * 30.0)))


def _json_safe_path(value: Path) -> str:
    return str(value.resolve()) if value.exists() else str(value)


def build_command(settings: HYMotionSettings, *, input_text_dir: Path, output_dir: Path) -> list[str]:
    python_exe = _venv_python(settings.venv_dir)
    if not python_exe.exists():
        python_exe = Path(sys.executable)
    command = [
        str(python_exe),
        str(settings.repo_dir / "local_infer.py"),
        "--model_path",
        str(settings.model_path),
        "--input_text_dir",
        str(input_text_dir),
        "--output_dir",
        str(output_dir),
        "--cfg_scale",
        str(float(settings.cfg_scale)),
        "--num_seeds",
        str(int(settings.num_seeds)),
    ]
    if settings.device_ids:
        command.extend(["--device_ids", settings.device_ids])
    if settings.disable_rewrite:
        command.append("--disable_rewrite")
    if settings.disable_duration_est:
        command.append("--disable_duration_est")
    if settings.prompt_engineering_host:
        command.extend(["--prompt_engineering_host", settings.prompt_engineering_host])
    if settings.prompt_engineering_model_path:
        command.extend(["--prompt_engineering_model_path", settings.prompt_engineering_model_path])
    if settings.validation_steps:
        command.extend(["--validation_steps", str(int(settings.validation_steps))])
    return command


def prepare_prompt_file(
    settings: HYMotionSettings,
    prompt: str,
    *,
    motion_id: str | None = None,
    write_input: bool = True,
) -> dict[str, Any]:
    run_id = _safe_motion_id(motion_id)
    frame_count = _duration_to_frames(settings.duration_seconds)
    run_root = settings.output_dir / run_id
    input_dir = run_root / "input"
    output_dir = run_root / "output"
    if write_input:
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = input_dir / "prompt.txt"
    if write_input:
        prompt_file.write_text(f"{str(prompt).strip()}#{frame_count}#1\n", encoding="utf-8")
    return {
        "run_id": run_id,
        "run_root": run_root,
        "input_dir": input_dir,
        "output_dir": output_dir,
        "prompt_file": prompt_file,
        "frame_count": frame_count,
    }


def discover_motion_outputs(output_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(output_dir)
    if not root.exists():
        return []
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in MOTION_OUTPUT_SUFFIXES:
            continue
        if path.name.startswith("batch_"):
            continue
        files.append(
            {
                "path": str(path),
                "name": path.name,
                "suffix": path.suffix.lower(),
                "bytes": path.stat().st_size,
            }
        )
    return files


def _copy_motion_asset(item: dict[str, Any], target_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    source = Path(str(item.get("path") or ""))
    copied = dict(item)
    copied["original_path"] = str(source)
    copied["staged"] = False
    if not source.exists() or not source.is_file():
        copied["missing"] = True
        return copied
    target_dir.mkdir(parents=True, exist_ok=True) if not dry_run else None
    target = target_dir / source.name
    if not dry_run:
        shutil.copy2(source, target)
    copied["path"] = str(target)
    copied["bytes"] = source.stat().st_size
    copied["staged"] = True
    copied["missing"] = False
    return copied


def _axis_angle_frame(poses: Any, frame_index: int, joint_name: str) -> list[float]:
    joint_index = SMPLH_PROXY_JOINTS[joint_name] * 3
    return [float(value) for value in poses[frame_index, joint_index : joint_index + 3]]


def _vec3(values: Any) -> list[float]:
    return [float(values[0]), float(values[1]), float(values[2])]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def build_vam_motion_proxy(
    npz_path: str | Path,
    target_path: str | Path,
    *,
    prompt: str = "",
    duration_seconds: float = 0.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create a small VaM-controller proxy track from HY-Motion SMPL axis-angle output.

    VaM cannot reliably import arbitrary FBX animation at runtime from an MVRScript.
    This proxy gives the bridge a native fallback: hip/chest/head/hand offsets derived
    from the generated motion. It is intentionally conservative and reversible.
    """

    source = Path(npz_path)
    target = Path(target_path)
    if not source.exists():
        return {"ok": False, "error": f"NPZ file not found: {source}", "path": str(target)}
    try:
        import numpy as np  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on local runtime
        return {"ok": False, "error": f"NumPy is required to build a VaM motion proxy: {exc}", "path": str(target)}

    data = np.load(source, allow_pickle=True)
    poses = data["poses"]
    trans = data["trans"]
    frame_count = int(min(len(poses), len(trans)))
    if frame_count <= 0:
        return {"ok": False, "error": "HY-Motion NPZ contains no frames.", "path": str(target)}

    duration = float(duration_seconds or max(0.25, frame_count / 30.0))
    fps = float(frame_count / duration)
    trans0 = trans[0].copy()
    frames = []
    previous_left = None
    previous_right = None

    for frame_index in range(frame_count):
        t = frame_index / max(1.0, fps)
        root = trans[frame_index] - trans0
        pelvis = _axis_angle_frame(poses, frame_index, "pelvis")
        spine = [
            _axis_angle_frame(poses, frame_index, "spine1"),
            _axis_angle_frame(poses, frame_index, "spine2"),
            _axis_angle_frame(poses, frame_index, "spine3"),
        ]
        neck = _axis_angle_frame(poses, frame_index, "neck")
        head = _axis_angle_frame(poses, frame_index, "head")
        left_shoulder = _axis_angle_frame(poses, frame_index, "left_shoulder")
        left_elbow = _axis_angle_frame(poses, frame_index, "left_elbow")
        left_wrist = _axis_angle_frame(poses, frame_index, "left_wrist")
        right_shoulder = _axis_angle_frame(poses, frame_index, "right_shoulder")
        right_elbow = _axis_angle_frame(poses, frame_index, "right_elbow")
        right_wrist = _axis_angle_frame(poses, frame_index, "right_wrist")

        spine_mix = [
            sum(values[axis] for values in spine) / len(spine)
            for axis in range(3)
        ]
        left = [
            _clamp((left_shoulder[2] + left_elbow[2] * 0.35 + left_wrist[2] * 0.15) * 0.12, -0.22, 0.22),
            _clamp((left_shoulder[0] + left_elbow[0] * 0.35) * 0.10, -0.18, 0.18),
            _clamp((left_shoulder[1] + left_elbow[1] * 0.25 + left_wrist[1] * 0.15) * 0.12, -0.22, 0.22),
        ]
        right = [
            _clamp((right_shoulder[2] + right_elbow[2] * 0.35 + right_wrist[2] * 0.15) * -0.12, -0.22, 0.22),
            _clamp((right_shoulder[0] + right_elbow[0] * 0.35) * 0.10, -0.18, 0.18),
            _clamp((right_shoulder[1] + right_elbow[1] * 0.25 + right_wrist[1] * 0.15) * 0.12, -0.22, 0.22),
        ]
        if previous_left is not None:
            left = [previous_left[i] * 0.55 + left[i] * 0.45 for i in range(3)]
            right = [previous_right[i] * 0.55 + right[i] * 0.45 for i in range(3)]
        previous_left = left
        previous_right = right

        frames.append(
            {
                "t": round(t, 4),
                "hip": [
                    round(_clamp(float(root[0]) * 0.18, -0.18, 0.18), 5),
                    round(_clamp(float(root[1]) * 0.08, -0.10, 0.10), 5),
                    round(_clamp(float(root[2]) * 0.18, -0.18, 0.18), 5),
                ],
                "chest": [
                    round(_clamp(spine_mix[2] * 0.08, -0.12, 0.12), 5),
                    round(_clamp(spine_mix[0] * 0.07, -0.10, 0.10), 5),
                    round(_clamp(spine_mix[1] * 0.08, -0.12, 0.12), 5),
                ],
                "head": [
                    round(_clamp((head[2] + neck[2] * 0.5) * 0.05, -0.06, 0.06), 5),
                    round(_clamp((head[0] + neck[0] * 0.5) * 0.04, -0.05, 0.05), 5),
                    round(_clamp((head[1] + neck[1] * 0.5) * 0.05, -0.06, 0.06), 5),
                ],
                "leftHand": [round(value, 5) for value in left],
                "rightHand": [round(value, 5) for value in right],
                "rootEuler": [round(_clamp(value * 12.0, -18.0, 18.0), 4) for value in pelvis],
            }
        )

    payload = {
        "schema_version": 1,
        "source": "nc.vam_avatar.hy_motion_proxy",
        "prompt": str(prompt or ""),
        "npz_path": str(source),
        "duration_seconds": round(duration, 4),
        "fps": round(fps, 4),
        "frame_count": frame_count,
        "controls": ["hip", "chest", "head", "leftHand", "rightHand"],
        "frames": frames,
    }
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(target), "bytes": len(json.dumps(payload)), "frame_count": frame_count, "fps": fps}


def build_vam_smpl_motion_json(
    npz_path: str | Path,
    target_path: str | Path,
    *,
    prompt: str = "",
    duration_seconds: float = 0.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Export HY-Motion NPZ into the compact SMPL JSON shape used by VaM retargeters.

    The file intentionally stores flat arrays: frameCount/fps/poses/trans/Rh. This is
    compatible with Voxta's Animate debug loader and our bridge-side SMPL playback.
    """

    source = Path(npz_path)
    target = Path(target_path)
    if not source.exists():
        return {"ok": False, "error": f"NPZ file not found: {source}", "path": str(target)}
    try:
        import numpy as np  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on local runtime
        return {"ok": False, "error": f"NumPy is required to build SMPL motion JSON: {exc}", "path": str(target)}

    data = np.load(source, allow_pickle=True)
    poses = data["poses"].astype("float32")
    trans = data["trans"].astype("float32")
    rh = data["Rh"].astype("float32") if "Rh" in data.files else poses[:, :3]
    frame_count = int(min(len(poses), len(trans), len(rh)))
    if frame_count <= 0:
        return {"ok": False, "error": "HY-Motion NPZ contains no SMPL frames.", "path": str(target)}

    duration = float(duration_seconds or max(0.25, frame_count / 30.0))
    fps = max(1, int(round(frame_count / duration)))
    payload = {
        "schema_version": 1,
        "source": "nc.vam_avatar.hy_motion_smpl",
        "label": str(prompt or "HY-Motion"),
        "prompt": str(prompt or ""),
        "npz_path": str(source),
        "frameCount": frame_count,
        "fps": fps,
        "poses": poses[:frame_count].reshape(-1).round(6).tolist(),
        "trans": trans[:frame_count].reshape(-1).round(6).tolist(),
        "Rh": rh[:frame_count].reshape(-1).round(6).tolist(),
    }
    encoded = json.dumps(payload, separators=(",", ":"))
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(target), "bytes": len(encoded), "frame_count": frame_count, "fps": fps}


def _timeline_curve(values: list[float], times: list[float], *, curve_type: int = 3) -> list[dict[str, str]]:
    return [
        {
            "t": f"{float(t):.4f}".rstrip("0").rstrip(".") or "0",
            "v": f"{float(v):.6f}".rstrip("0").rstrip(".") or "0",
            "c": str(int(curve_type)),
        }
        for t, v in zip(times, values)
    ]


def _axis_angle_quaternion(values: list[float], offset: int) -> tuple[float, float, float, float]:
    if len(values) <= offset + 2:
        return (0.0, 0.0, 0.0, 1.0)
    x = float(values[offset])
    y = float(values[offset + 1])
    z = float(values[offset + 2])
    axis = (-x, y, z)
    magnitude = math.sqrt(axis[0] * axis[0] + axis[1] * axis[1] + axis[2] * axis[2])
    if magnitude < 0.000001:
        return (0.0, 0.0, 0.0, 1.0)
    angle = -magnitude
    half = angle * 0.5
    scale = math.sin(half) / magnitude
    return (
        axis[0] * scale,
        axis[1] * scale,
        axis[2] * scale,
        math.cos(half),
    )


def _timeline_controller_curves(
    *,
    controller: str,
    joint_index: int,
    target_position: bool,
    target_rotation: bool,
    frame_indices: list[int],
    times: list[float],
    poses: list[float],
    trans: list[float],
    rh: list[float],
) -> dict[str, Any]:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    qx: list[float] = []
    qy: list[float] = []
    qz: list[float] = []
    qw: list[float] = []
    first_root = (0.0, 0.0, 0.0)
    if len(trans) >= 3:
        first_root = (-float(trans[0]), float(trans[1]), float(trans[2]))

    for frame in frame_indices:
        if target_position and joint_index == 0 and len(trans) > frame * 3 + 2:
            root = (-float(trans[frame * 3]), float(trans[frame * 3 + 1]), float(trans[frame * 3 + 2]))
            xs.append(round((root[0] - first_root[0]) * 0.18, 6))
            ys.append(0.0)
            zs.append(round((root[2] - first_root[2]) * 0.18, 6))
        else:
            xs.append(0.0)
            ys.append(0.0)
            zs.append(0.0)

        if joint_index == 0 and len(rh) > frame * 3 + 2:
            quat = _axis_angle_quaternion(rh, frame * 3)
        else:
            quat = _axis_angle_quaternion(poses, frame * 156 + joint_index * 3)
        qx.append(round(quat[0], 6))
        qy.append(round(quat[1], 6))
        qz.append(round(quat[2], 6))
        qw.append(round(quat[3], 6))

    return {
        "Controller": controller,
        "TargetsPosition": "1" if target_position else "0",
        "TargetsRotation": "1" if target_rotation else "0",
        "ControlPosition": "1" if target_position else "0",
        "ControlRotation": "1" if target_rotation else "0",
        "X": _timeline_curve(xs, times),
        "Y": _timeline_curve(ys, times),
        "Z": _timeline_curve(zs, times),
        "RotX": _timeline_curve(qx, times),
        "RotY": _timeline_curve(qy, times),
        "RotZ": _timeline_curve(qz, times),
        "RotW": _timeline_curve(qw, times),
    }


def build_vam_timeline_export(
    smpl_json_path: str | Path,
    clip_path: str | Path,
    storable_path: str | Path,
    *,
    clip_name: str = "NC_HY_Motion",
    prompt: str = "",
    max_keyframes: int = 180,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build a readable AcidBubbles Timeline clip/storable export from SMPL JSON.

    Timeline accepts uncompressed keyframe objects, so this avoids depending on
    Timeline's optimized string encoder. The export is intentionally a separate
    artifact; the bridge runtime playback remains the safe immediate path.
    """

    source = Path(smpl_json_path)
    target_clip = Path(clip_path)
    target_storable = Path(storable_path)
    if not source.exists():
        return {"ok": False, "error": f"SMPL JSON not found: {source}", "path": str(target_clip)}

    root = json.loads(source.read_text(encoding="utf-8"))
    frame_count = int(root.get("frameCount") or root.get("frame_count") or 0)
    fps = int(root.get("fps") or 30)
    if frame_count <= 0:
        return {"ok": False, "error": "SMPL JSON contains no frames.", "path": str(target_clip)}
    fps = max(1, fps)
    duration = max(0.1, frame_count / float(fps))
    stride = max(1, int(math.ceil(frame_count / max(2, int(max_keyframes)))))
    frame_indices = list(range(0, frame_count, stride))
    if frame_indices[-1] != frame_count - 1:
        frame_indices.append(frame_count - 1)
    times = [min(duration, frame / float(fps)) for frame in frame_indices]

    poses = [float(value) for value in root.get("poses") or []]
    trans = [float(value) for value in root.get("trans") or []]
    rh = [float(value) for value in root.get("Rh") or []]
    controllers = [
        _timeline_controller_curves(
            controller=name,
            joint_index=joint,
            target_position=target_position,
            target_rotation=target_rotation,
            frame_indices=frame_indices,
            times=times,
            poses=poses,
            trans=trans,
            rh=rh,
        )
        for name, joint, target_position, target_rotation in TIMELINE_SMPL_CONTROLLERS
    ]

    clip = {
        "AnimationName": str(clip_name or "NC_HY_Motion"),
        "AnimationLength": f"{duration:.4f}".rstrip("0").rstrip(".") or "0.1",
        "BlendDuration": "0.35",
        "Loop": "0",
        "PreserveLastFrame": "0",
        "LoopSelfBlendDuration": "0",
        "NextAnimationRandomizeWeight": "1",
        "AutoTransitionPrevious": "0",
        "AutoTransitionNext": "0",
        "SyncTransitionTime": "0",
        "SyncTransitionTimeNL": "0",
        "EnsureQuaternionContinuity": "1",
        "AnimationLayer": "NC HY-Motion",
        "Speed": "1",
        "Weight": "1",
        "Uninterruptible": "0",
        "AnimationSegment": "Generated",
        "Controllers": controllers,
        "NCMetadata": {
            "source": "nc.vam_avatar.hy_motion_timeline",
            "prompt": str(prompt or root.get("prompt") or root.get("label") or ""),
            "smpl_json_path": str(source),
            "frame_count": frame_count,
            "sampled_keyframes": len(frame_indices),
            "fps": fps,
        },
    }
    storable = {
        "id": "plugin#0_VamTimeline.AtomPlugin",
        "pluginLabel": "NC HY-Motion Timeline Export",
        "Animation": {
            "SerializeVersion": "283",
            "SerializeMode": "1",
            "Speed": "1",
            "Weight": "1",
            "Master": "0",
            "SyncWithPeers": "0",
            "SyncSubsceneOnly": "0",
            "TimeMode": "0",
            "LiveParenting": "0",
            "ForceBlendTime": "0",
            "PauseSequencing": "0",
            "GlobalTriggers": {
                "OnClipsChanged": {"startActions": [], "transitionActions": [], "endActions": []},
                "IsPlayingChanged": {"startActions": [], "transitionActions": [], "endActions": []},
            },
            "Clips": [clip],
        },
        "Options": {
            "AutoKeyframeAllControllers": "0",
            "Snap": "0.1",
            "Locked": "0",
            "ShowPaths": "0",
        },
    }
    if not dry_run:
        target_clip.parent.mkdir(parents=True, exist_ok=True)
        target_clip.write_text(json.dumps(clip, indent=2), encoding="utf-8")
        target_storable.write_text(json.dumps(storable, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "path": str(target_clip),
        "storable_path": str(target_storable),
        "bytes": len(json.dumps(clip)),
        "storable_bytes": len(json.dumps(storable)),
        "frame_count": frame_count,
        "sampled_keyframes": len(frame_indices),
        "duration_seconds": duration,
    }


def stage_motion_assets_for_vam(
    motion_result: dict[str, Any],
    *,
    runtime_config: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    settings = resolve_settings(runtime_config, overrides)
    manifest = dict((motion_result or {}).get("manifest") or {})
    outputs = list(manifest.get("outputs") or [])
    run_id = _safe_motion_id(str(manifest.get("run_id") or "hy_motion"))
    stage_dir = Path(settings.bridge_root) / "motion" / run_id
    staged_outputs = [_copy_motion_asset(dict(item or {}), stage_dir, dry_run=dry_run) for item in outputs]
    warnings: list[str] = [f"Missing motion asset: {item.get('original_path')}" for item in staged_outputs if item.get("missing")]

    manifest_path = Path(str((motion_result or {}).get("manifest_path") or ""))
    if not manifest_path.exists() and manifest.get("output_dir"):
        candidate = Path(str(manifest.get("output_dir"))).parent / "motion_manifest.json"
        if candidate.exists():
            manifest_path = candidate
    staged_manifest_path = ""
    if manifest_path.exists():
        target = stage_dir / "motion_manifest.json"
        if not dry_run:
            stage_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manifest_path, target)
        staged_manifest_path = str(target)

    proxy_path = ""
    smpl_path = ""
    timeline_clip_path = ""
    timeline_storable_path = ""
    voxta_debug_path = ""
    npz_output = next((item for item in staged_outputs if str(item.get("suffix") or "").lower() == ".npz" and not item.get("missing")), None)
    if npz_output:
        npz_source = npz_output.get("original_path") if dry_run else npz_output.get("path")
        smpl_result = build_vam_smpl_motion_json(
            npz_source or npz_output.get("path") or npz_output.get("original_path"),
            stage_dir / "motion_smpl.json",
            prompt=str(manifest.get("prompt") or ""),
            duration_seconds=float(manifest.get("duration_seconds") or 0.0),
            dry_run=dry_run,
        )
        if smpl_result.get("ok"):
            smpl_path = str(smpl_result.get("path") or "")
            staged_outputs.append(
                {
                    "path": smpl_path,
                    "name": "motion_smpl.json",
                    "suffix": ".json",
                    "bytes": int(smpl_result.get("bytes") or 0),
                    "staged": not dry_run,
                    "missing": False,
                    "asset_role": "vam_smpl_motion",
                }
            )
            timeline_result = build_vam_timeline_export(
                smpl_path,
                stage_dir / "motion_timeline_clip.json",
                stage_dir / "motion_timeline_storable.json",
                clip_name=run_id,
                prompt=str(manifest.get("prompt") or ""),
                dry_run=dry_run,
            )
            if timeline_result.get("ok"):
                timeline_clip_path = str(timeline_result.get("path") or "")
                timeline_storable_path = str(timeline_result.get("storable_path") or "")
                staged_outputs.append(
                    {
                        "path": timeline_clip_path,
                        "name": "motion_timeline_clip.json",
                        "suffix": ".json",
                        "bytes": int(timeline_result.get("bytes") or 0),
                        "staged": not dry_run,
                        "missing": False,
                        "asset_role": "vam_timeline_clip",
                    }
                )
                staged_outputs.append(
                    {
                        "path": timeline_storable_path,
                        "name": "motion_timeline_storable.json",
                        "suffix": ".json",
                        "bytes": int(timeline_result.get("storable_bytes") or 0),
                        "staged": not dry_run,
                        "missing": False,
                        "asset_role": "vam_timeline_storable",
                    }
                )
            else:
                warnings.append(str(timeline_result.get("error") or "Failed to build Timeline export."))
            if settings.vam_root:
                voxta_dir = Path(settings.vam_root) / VOXTA_ANIMATION_DIR
                voxta_name = f"{run_id}.json"
                voxta_target = voxta_dir / voxta_name
                voxta_debug_path = str(voxta_target)
                if not dry_run:
                    voxta_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(Path(smpl_path), voxta_target)
        else:
            warnings.append(str(smpl_result.get("error") or "Failed to build SMPL motion JSON."))

        proxy_result = build_vam_motion_proxy(
            npz_source or npz_output.get("path") or npz_output.get("original_path"),
            stage_dir / "motion_proxy.json",
            prompt=str(manifest.get("prompt") or ""),
            duration_seconds=float(manifest.get("duration_seconds") or 0.0),
            dry_run=dry_run,
        )
        if proxy_result.get("ok"):
            proxy_path = str(proxy_result.get("path") or "")
            staged_outputs.append(
                {
                    "path": proxy_path,
                    "name": "motion_proxy.json",
                    "suffix": ".json",
                    "bytes": int(proxy_result.get("bytes") or 0),
                    "staged": not dry_run,
                    "missing": False,
                    "asset_role": "vam_motion_proxy",
                }
            )
        else:
            warnings.append(str(proxy_result.get("error") or "Failed to build VaM motion proxy."))

    primary = next((item for item in staged_outputs if item.get("suffix") == ".fbx" and not item.get("missing")), None)
    if primary is None:
        primary = next((item for item in staged_outputs if not item.get("missing")), None)

    return {
        "ok": any(not item.get("missing") for item in staged_outputs),
        "dry_run": bool(dry_run),
        "stage_dir": str(stage_dir),
        "manifest_path": staged_manifest_path,
        "proxy_path": proxy_path,
        "smpl_path": smpl_path,
        "timeline_clip_path": timeline_clip_path,
        "timeline_storable_path": timeline_storable_path,
        "voxta_debug_path": voxta_debug_path,
        "outputs": staged_outputs,
        "primary_output": primary or {},
        "warnings": warnings,
    }


def build_manifest(
    *,
    settings: HYMotionSettings,
    prompt: str,
    prepared: dict[str, Any],
    command: list[str],
    dry_run: bool,
    process_result: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    outputs = discover_motion_outputs(prepared["output_dir"])
    primary = next((item for item in outputs if item["suffix"] == ".fbx"), None) or (outputs[0] if outputs else None)
    return {
        "schema_version": 1,
        "source": "nc.vam_avatar.hy_motion",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dry_run": bool(dry_run),
        "prompt": str(prompt),
        "run_id": prepared["run_id"],
        "duration_seconds": settings.duration_seconds,
        "frame_count": prepared["frame_count"],
        "cfg_scale": settings.cfg_scale,
        "num_seeds": settings.num_seeds,
        "disable_rewrite": settings.disable_rewrite,
        "disable_duration_est": settings.disable_duration_est,
        "model_path": _json_safe_path(settings.model_path),
        "repo_dir": _json_safe_path(settings.repo_dir),
        "input_file": str(prepared["prompt_file"]),
        "output_dir": str(prepared["output_dir"]),
        "outputs": outputs,
        "primary_output": primary,
        "process": process_result or {},
        "warnings": list(warnings or []),
    }


def run_prompt_to_motion(
    prompt: str,
    *,
    runtime_config: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return {"ok": False, "error": "Prompt is required."}

    settings = resolve_settings(runtime_config, overrides)
    model_check = validate_model_path(settings.model_path)
    local_infer = settings.repo_dir / "local_infer.py"
    warnings = []
    if not model_check["ok"]:
        warnings.append("HY-Motion model folder is missing config.yml or latest.ckpt.")
    if not local_infer.exists():
        warnings.append("HY-Motion source checkout is missing local_infer.py.")
    if settings.disable_rewrite is False or settings.disable_duration_est is False:
        if not settings.prompt_engineering_host and not settings.prompt_engineering_model_path:
            warnings.append("Prompt rewrite/duration estimation needs a prompt engineering host or model path.")

    motion_id = str((overrides or {}).get("motion_id") or "")
    prepared = prepare_prompt_file(settings, prompt_text, motion_id=motion_id, write_input=not dry_run)
    command = build_command(settings, input_text_dir=prepared["input_dir"], output_dir=prepared["output_dir"])

    if dry_run:
        manifest = build_manifest(
            settings=settings,
            prompt=prompt_text,
            prepared=prepared,
            command=command,
            dry_run=True,
            warnings=warnings,
        )
        return {
            "ok": True,
            "dry_run": True,
            "command": command,
            "settings": settings.as_payload(),
            "model_check": model_check,
            "manifest": manifest,
            "warnings": warnings,
        }

    if warnings:
        return {
            "ok": False,
            "error": "HY-Motion is not ready.",
            "command": command,
            "settings": settings.as_payload(),
            "model_check": model_check,
            "warnings": warnings,
        }

    env = os.environ.copy()
    env.setdefault("HF_HOME", str(settings.cache_dir / "huggingface"))
    env.setdefault("HUGGINGFACE_HUB_CACHE", str(settings.cache_dir / "huggingface" / "hub"))
    env.setdefault("TRANSFORMERS_CACHE", str(settings.cache_dir / "transformers"))
    env.setdefault("USE_HF_MODELS", "1")
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(settings.repo_dir) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")

    started_at = time.time()
    timeout = None
    if timeout_seconds is not None:
        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError):
            timeout = None

    proc = subprocess.run(
        command,
        cwd=str(settings.repo_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    process_result = {
        "returncode": proc.returncode,
        "elapsed_seconds": round(time.time() - started_at, 3),
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }
    manifest = build_manifest(
        settings=settings,
        prompt=prompt_text,
        prepared=prepared,
        command=command,
        dry_run=False,
        process_result=process_result,
        warnings=warnings,
    )
    manifest_path = prepared["run_root"] / "motion_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "ok": proc.returncode == 0,
        "dry_run": False,
        "command": command,
        "settings": settings.as_payload(),
        "model_check": model_check,
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "warnings": warnings,
        "error": "" if proc.returncode == 0 else "HY-Motion local_infer.py returned a non-zero exit code.",
    }


def build_vam_bridge_payload(
    motion_result: dict[str, Any],
    *,
    runtime_config: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = resolve_settings(runtime_config, overrides)
    manifest = dict((motion_result or {}).get("manifest") or {})
    outputs = list(manifest.get("outputs") or [])
    primary = manifest.get("primary_output") or (outputs[0] if outputs else {})
    runtime = dict(runtime_config or {})
    runtime.update(dict(overrides or {}))
    stage_assets = bool(runtime.get("stage_assets", runtime.get("vam_hymotion_stage_assets", True)))
    dry_run = bool(runtime.get("dry_run", False))
    staged = {}
    if stage_assets and outputs:
        staged = stage_motion_assets_for_vam(motion_result, runtime_config=runtime_config, overrides=runtime, dry_run=dry_run)
        outputs = list(staged.get("outputs") or outputs)
        primary = staged.get("primary_output") or primary

    def first_path(suffix: str) -> str:
        for item in outputs:
            if str(item.get("suffix") or "").lower() == suffix:
                return str(item.get("path") or "")
        return ""

    primary_path = str((primary or {}).get("path") or "")
    return {
        "target_atom_uid": str(runtime.get("vam_target_atom_uid", "Person") or "Person"),
        "target_storable_id": str(runtime.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge"),
        "motion_source": "hy_motion",
        "prompt": manifest.get("prompt", ""),
        "duration_seconds": manifest.get("duration_seconds", settings.duration_seconds),
        "frame_count": manifest.get("frame_count", _duration_to_frames(settings.duration_seconds)),
        "output_dir": manifest.get("output_dir", ""),
        "motion_stage_dir": str(staged.get("stage_dir") or ""),
        "motion_manifest_path": str(staged.get("manifest_path") or (motion_result or {}).get("manifest_path") or ""),
        "motion_file": primary_path,
        "motion_fbx_path": first_path(".fbx") or (primary_path if primary_path.lower().endswith(".fbx") else ""),
        "motion_npz_path": first_path(".npz"),
        "motion_smpl_path": str(staged.get("smpl_path") or ""),
        "motion_voxta_debug_path": str(staged.get("voxta_debug_path") or ""),
        "motion_proxy_path": str(staged.get("proxy_path") or ""),
        "motion_timeline_clip_path": str(staged.get("timeline_clip_path") or ""),
        "motion_timeline_storable_path": str(staged.get("timeline_storable_path") or ""),
        "motion_meta_path": first_path(".json"),
        "motion_asset_status": "staged" if staged.get("ok") else ("not_staged" if not stage_assets else "missing"),
        "motion_files": outputs,
        "primary_motion_file": primary,
        "timeline_clip": str(runtime.get("timeline_clip", "") or ""),
        "timeline_auto_resume": bool(runtime.get("vam_timeline_auto_resume", True)),
        "asset_warnings": list(staged.get("warnings") or []),
        "notes": "HY-Motion output staged with SMPL JSON first, controller proxy fallback, Timeline export, and FBX reference asset.",
    }


def write_vam_bridge_command(
    bridge_root: str | Path,
    action: str,
    payload: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not str(bridge_root or "").strip():
        return {"ok": False, "error": "Bridge root is required.", "dry_run": bool(dry_run)}
    bridge = Path(bridge_root)
    inbox = bridge / "inbox"
    command_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    final_path = inbox / f"{command_id}_{str(action or 'hy_motion_generated')}.json"
    body = {
        "session_id": "hy_motion",
        "command_id": command_id,
        "sent_at": time.time(),
        "action": str(action or "hy_motion_generated"),
        "payload": dict(payload or {}),
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "path": str(final_path), "body": body}
    inbox.mkdir(parents=True, exist_ok=True)
    tmp_path = final_path.with_suffix(final_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    os.replace(tmp_path, final_path)
    return {"ok": True, "dry_run": False, "path": str(final_path), "body": body}
