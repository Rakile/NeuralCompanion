"""Addon-local HY-Motion configuration for the VaM avatar provider."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from addons.vam_avatar import config as vam_config


ENV_MAP = {
    "repo_url": "NC_VAM_HYMOTION_REPO_URL",
    "repo_dir": "NC_VAM_HYMOTION_REPO_DIR",
    "venv_dir": "NC_VAM_HYMOTION_VENV_DIR",
    "model_path": "NC_VAM_HYMOTION_MODEL_PATH",
    "cache_dir": "NC_VAM_HYMOTION_CACHE_DIR",
    "output_dir": "NC_VAM_HYMOTION_OUTPUT_DIR",
    "input_dir": "NC_VAM_HYMOTION_INPUT_DIR",
    "device_ids": "NC_VAM_HYMOTION_DEVICE_IDS",
    "duration_seconds": "NC_VAM_HYMOTION_DURATION_SECONDS",
    "num_seeds": "NC_VAM_HYMOTION_NUM_SEEDS",
    "cfg_scale": "NC_VAM_HYMOTION_CFG_SCALE",
    "disable_rewrite": "NC_VAM_HYMOTION_DISABLE_REWRITE",
    "disable_duration_est": "NC_VAM_HYMOTION_DISABLE_DURATION_EST",
    "prompt_engineering_host": "NC_VAM_HYMOTION_PROMPT_ENGINEERING_HOST",
    "prompt_engineering_model_path": "NC_VAM_HYMOTION_PROMPT_ENGINEERING_MODEL_PATH",
    "validation_steps": "NC_VAM_HYMOTION_VALIDATION_STEPS",
    "vam_root": "NC_VAM_ROOT",
}


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return bool(default)


def _float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _path_value(value: Any, default: Path) -> Path:
    text = str(value or "").strip()
    if not text:
        return Path(default)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path(vam_config.APP_ROOT) / path
    return path


def _first_existing_model_dir() -> Path:
    candidates = (
        Path(vam_config.DEFAULT_HYMOTION_MODEL_DIR),
        Path(vam_config.DEFAULT_HYMOTION_USER_MODEL_DIR),
    )
    for candidate in candidates:
        if (candidate / "config.yml").exists() and (candidate / "latest.ckpt").exists():
            return candidate
    return Path(vam_config.DEFAULT_HYMOTION_MODEL_DIR)


@dataclass(frozen=True)
class HYMotionSettings:
    repo_url: str
    repo_dir: Path
    venv_dir: Path
    model_path: Path
    model_name: str
    cache_dir: Path
    output_dir: Path
    input_dir: Path
    device_ids: str
    duration_seconds: float
    num_seeds: int
    cfg_scale: float
    disable_rewrite: bool
    disable_duration_est: bool
    prompt_engineering_host: str
    prompt_engineering_model_path: str
    validation_steps: int | None
    vam_root: str
    bridge_root: str

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


def _runtime_value(runtime_config: dict[str, Any], key: str, default: Any, environ: dict[str, str]) -> Any:
    env_name = ENV_MAP.get(key)
    if env_name and str(environ.get(env_name, "") or "").strip():
        return environ[env_name]
    return runtime_config.get(f"vam_hymotion_{key}", default)


def resolve_settings(
    runtime_config: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    environ: dict[str, str] | None = None,
) -> HYMotionSettings:
    runtime = dict(runtime_config or {})
    runtime.update(dict(overrides or {}))
    env = environ if environ is not None else os.environ

    model_default = _first_existing_model_dir()
    repo_url = str(_runtime_value(runtime, "repo_url", vam_config.DEFAULT_HYMOTION_REPO_URL, env) or "").strip()
    repo_dir = _path_value(_runtime_value(runtime, "repo_dir", "", env), vam_config.DEFAULT_HYMOTION_REPO_DIR)
    venv_dir = _path_value(_runtime_value(runtime, "venv_dir", "", env), vam_config.DEFAULT_HYMOTION_VENV_DIR)
    model_path = _path_value(_runtime_value(runtime, "model_path", "", env), model_default)
    cache_dir = _path_value(_runtime_value(runtime, "cache_dir", "", env), vam_config.DEFAULT_HYMOTION_CACHE_DIR)
    output_dir = _path_value(_runtime_value(runtime, "output_dir", "", env), vam_config.DEFAULT_HYMOTION_OUTPUT_DIR)
    input_dir = _path_value(_runtime_value(runtime, "input_dir", "", env), vam_config.DEFAULT_HYMOTION_INPUT_DIR)
    device_ids = str(_runtime_value(runtime, "device_ids", vam_config.DEFAULT_HYMOTION_DEVICE_IDS, env) or "").strip()
    duration_seconds = max(
        0.25,
        _float_value(_runtime_value(runtime, "duration_seconds", vam_config.DEFAULT_HYMOTION_DURATION_SECONDS, env), vam_config.DEFAULT_HYMOTION_DURATION_SECONDS),
    )
    num_seeds = max(1, _int_value(_runtime_value(runtime, "num_seeds", vam_config.DEFAULT_HYMOTION_NUM_SEEDS, env), vam_config.DEFAULT_HYMOTION_NUM_SEEDS))
    cfg_scale = _float_value(_runtime_value(runtime, "cfg_scale", vam_config.DEFAULT_HYMOTION_CFG_SCALE, env), vam_config.DEFAULT_HYMOTION_CFG_SCALE)
    disable_rewrite = _truthy(_runtime_value(runtime, "disable_rewrite", vam_config.DEFAULT_HYMOTION_DISABLE_REWRITE, env), vam_config.DEFAULT_HYMOTION_DISABLE_REWRITE)
    disable_duration_est = _truthy(
        _runtime_value(runtime, "disable_duration_est", vam_config.DEFAULT_HYMOTION_DISABLE_DURATION_EST, env),
        vam_config.DEFAULT_HYMOTION_DISABLE_DURATION_EST,
    )
    prompt_engineering_host = str(_runtime_value(runtime, "prompt_engineering_host", "", env) or "").strip()
    prompt_engineering_model_path = str(_runtime_value(runtime, "prompt_engineering_model_path", "", env) or "").strip()
    raw_validation_steps = _runtime_value(runtime, "validation_steps", "", env)
    validation_steps = None if str(raw_validation_steps or "").strip() == "" else max(1, _int_value(raw_validation_steps, 50))
    vam_root = str(runtime.get("vam_root") or env.get("NC_VAM_ROOT") or vam_config.DEFAULT_EXTERNAL_VAM_ROOT or vam_config.DEFAULT_ROOT or "").strip()
    normalized_vam_root = vam_config.normalize_root(vam_root)
    bridge_root = vam_config.derive_bridge_root(normalized_vam_root)

    return HYMotionSettings(
        repo_url=repo_url,
        repo_dir=repo_dir,
        venv_dir=venv_dir,
        model_path=model_path,
        model_name=vam_config.DEFAULT_HYMOTION_MODEL_NAME,
        cache_dir=cache_dir,
        output_dir=output_dir,
        input_dir=input_dir,
        device_ids=device_ids,
        duration_seconds=duration_seconds,
        num_seeds=num_seeds,
        cfg_scale=cfg_scale,
        disable_rewrite=disable_rewrite,
        disable_duration_est=disable_duration_est,
        prompt_engineering_host=prompt_engineering_host,
        prompt_engineering_model_path=prompt_engineering_model_path,
        validation_steps=validation_steps,
        vam_root=normalized_vam_root,
        bridge_root=bridge_root,
    )


def validate_model_path(model_path: str | Path) -> dict[str, Any]:
    root = Path(model_path)
    config_path = root / "config.yml"
    checkpoint_path = root / "latest.ckpt"
    missing = []
    if not config_path.exists():
        missing.append(str(config_path))
    if not checkpoint_path.exists():
        missing.append(str(checkpoint_path))
    return {
        "ok": not missing,
        "model_path": str(root),
        "config_path": str(config_path),
        "checkpoint_path": str(checkpoint_path),
        "missing": missing,
    }


def default_runtime_payload() -> dict[str, Any]:
    settings = resolve_settings()
    payload = settings.as_payload()
    payload["model_check"] = validate_model_path(settings.model_path)
    payload["repo_local_infer"] = str(settings.repo_dir / "local_infer.py")
    return payload
