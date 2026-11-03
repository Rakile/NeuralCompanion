"""Translate GUI controls into Ditto's existing inference options (no GPU work)."""

import json
import math
from pathlib import Path


EMOTIONS = ("Checkpoint default", "Angry", "Disgust", "Fear", "Happy", "Neutral",
            "Sad", "Surprise", "Contempt")
DEFAULTS = {
    "expression": 1.0, "motion": "Automatic", "pitch_strength": 1.0,
    "yaw_strength": 1.0, "roll_strength": 1.0, "translation_strength": 1.0,
    "emotion": "Checkpoint default", "relative": True, "eyes": "Automatic",
    "blink_style": "Checkpoint blink sequence", "blink_open": 0,
    "pitch_offset": 2.0, "yaw_offset": 0.0, "roll_offset": 0.0,
    "steps": 50, "smoothing": 3, "seed": "", "fade_in": 0, "fade_out": 0,
    "fade_target": "Initial generated pose", "fade_keys": "Expression only",
    "max_size": 1920, "crop_scale": 2.3, "crop_x": 0.0, "crop_y": -0.125,
    "crop_rotate": True, "source_smoothing": 13, "source_frames": -1,
    "eye_first_frame": False, "conditioning": "Checkpoint reference",
    "stitching": True, "advanced": "{}",
}


def _number(values, key, low, high, integer=False):
    try:
        value = float(values[key])
    except (TypeError, ValueError):
        raise ValueError(f"{key}: enter a number.") from None
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{key}: must be between {low} and {high}.")
    if integer and not value.is_integer():
        raise ValueError(f"{key}: enter a whole number.")
    return int(value) if integer else value


def _choice(values, key, choices):
    value = values[key]
    if value not in choices:
        raise ValueError(f"{key}: choose one of {', '.join(choices)}.")
    return value


def parse_seed(value):
    if str(value).strip() == "":
        return None
    try:
        seed = int(str(value).strip())
    except ValueError:
        raise ValueError("Seed must be a whole number, or blank for random.") from None
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("Seed must be between 0 and 4294967295.")
    return seed


def make_kwargs(values, is_video):
    values = {**DEFAULTS, **values}
    for key in ("relative", "crop_rotate", "eye_first_frame", "stitching"):
        if not isinstance(values[key], bool):
            raise ValueError(f"{key}: must be true or false.")
    mode = _choice(values, "motion", ("Automatic", "Expression only", "Animate head and expression"))
    weights = {"exp": _number(values, "expression", 0, 2)}
    if mode == "Animate head and expression" or (mode == "Automatic" and not is_video):
        weights.update({key: _number(values, field, 0, 2) for key, field in (
            ("pitch", "pitch_strength"), ("yaw", "yaw_strength"),
            ("roll", "roll_strength"), ("t", "translation_strength"))})
    emotion = _choice(values, "emotion", EMOTIONS)
    eyes = _choice(values, "eyes", ("Automatic", "Enabled", "Disabled"))
    blink = _choice(values, "blink_style", ("Checkpoint blink sequence", "Generated eye motion"))
    fade_target = _choice(values, "fade_target", ("Initial generated pose", "Source pose"))
    fade_keys = _choice(values, "fade_keys", ("Expression only", "Expression and head motion"))
    conditioning = _choice(values, "conditioning", ("Checkpoint reference", "Source face"))
    setup = {
        "use_d_keys": weights, "relative_d": bool(values["relative"]),
        "drive_eye": {"Automatic": None, "Enabled": True, "Disabled": False}[eyes],
        "delta_eye_open_n": _number(values, "blink_open", -1, 10000, integer=True),
        "overall_ctrl_info": {"delta_" + key: _number(values, field, -90, 90)
                              for key, field in (("pitch", "pitch_offset"),
                                                 ("yaw", "yaw_offset"), ("roll", "roll_offset"))},
        "sampling_timesteps": _number(values, "steps", 1, 1000, integer=True),
        "smo_k_d": _number(values, "smoothing", 1, 101, integer=True),
        "fade_type": "d0" if fade_target == "Initial generated pose" else "s",
        "fade_out_keys": ["exp"] if fade_keys == "Expression only" else ["exp", "pitch", "yaw", "roll", "t"],
        "max_size": _number(values, "max_size", 256, 8192, integer=True),
        "crop_scale": _number(values, "crop_scale", 0.1, 10),
        "crop_vx_ratio": _number(values, "crop_x", -2, 2),
        "crop_vy_ratio": _number(values, "crop_y", -2, 2),
        "crop_flag_do_rot": bool(values["crop_rotate"]),
        "smo_k_s": _number(values, "source_smoothing", 1, 101, integer=True),
        "template_n_frames": _number(values, "source_frames", -1, 1000000, integer=True),
        "eye_f0_mode": bool(values["eye_first_frame"]),
        "flag_stitching": bool(values["stitching"]),
    }
    if emotion != "Checkpoint default":
        setup["emo"] = EMOTIONS.index(emotion) - 1
    if blink == "Generated eye motion":
        setup["delta_eye_arr"] = None
    if conditioning == "Source face":
        setup["ch_info"] = None
    run = {"fade_in": _number(values, "fade_in", 0, 1000000, integer=True),
           "fade_out": _number(values, "fade_out", 0, 1000000, integer=True)}
    try:
        advanced = json.loads(values["advanced"] or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Advanced settings must be valid JSON: {exc}") from None
    if not isinstance(advanced, dict) or set(advanced) - {"setup_kwargs", "run_kwargs"}:
        raise ValueError("Advanced JSON must contain only setup_kwargs and/or run_kwargs objects.")
    for key, target in (("setup_kwargs", setup), ("run_kwargs", run)):
        section = advanced.get(key, {})
        if not isinstance(section, dict):
            raise ValueError(f"{key} must be a JSON object.")
        target.update(section)
    if setup.get("online_mode", False):
        raise ValueError("This GUI uses offline inference; online_mode must be false.")
    # Validate settings that can otherwise fail late in the motion worker.
    for key, low, high in (("sampling_timesteps", 1, 1000), ("smo_k_d", 1, 101),
                           ("overlap_v2", 1, 79)):
        if key in setup:
            setup[key] = _number(setup, key, low, high, integer=True)
    if "ctrl_info" in run:
        controls = run["ctrl_info"]
        if not isinstance(controls, dict):
            raise ValueError("ctrl_info must map nonnegative frame numbers to control objects.")
        parsed = {}
        for frame, control in controls.items():
            try:
                index = int(frame)
            except (TypeError, ValueError):
                raise ValueError("ctrl_info frame numbers must be nonnegative integers.") from None
            if index < 0 or str(index) != str(frame) or not isinstance(control, dict):
                raise ValueError("ctrl_info must map nonnegative frame numbers to control objects.")
            parsed[index] = control
        run["ctrl_info"] = parsed
    return {"setup_kwargs": setup, "run_kwargs": run}


def build_job(values, source_path, audio_path, output_path, is_video):
    source, audio, output = (Path(p).expanduser().resolve() for p in
                             (source_path, audio_path, output_path))
    for label, path in (("Source", source), ("Audio", audio)):
        if not path.is_file():
            raise ValueError(f"{label} file does not exist: {path}")
    if output.suffix.lower() != ".mp4":
        raise ValueError("Output must be an MP4 file.")
    if output.exists():
        raise ValueError(f"Output already exists; choose a new name: {output}")
    return {"schema_version": 1, "source_path": str(source), "audio_path": str(audio),
            "output_path": str(output), "is_video": bool(is_video),
            "seed": parse_seed(values.get("seed", "")),
            "controls": {**DEFAULTS, **values}, "kwargs": make_kwargs(values, is_video)}
