"""Opt-in, workflow-scoped ComfyUI controls. No Qt or network operations."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from collections.abc import Mapping
from typing import Any

from addons.visual_reply.providers import provider_settings_from_config

SAMPLER_CLASSES = {"KSampler": "seed", "KSamplerAdvanced": "noise_seed"}
SAMPLER_FIELDS = ("steps", "cfg", "sampler_name", "scheduler", "denoise")
NUMERIC_LIMITS = {"steps": (1, 10000), "cfg": (0, 100), "denoise": (0, 1),
                  "width": (64, 8192), "height": (64, 8192), "timeout_seconds": (5, 86400)}
MODES = {"dimension_mode": ("legacy", "workflow", "custom"),
         "seed_mode": ("legacy", "random", "workflow", "fixed"),
         "cleanup_mode": ("keep_cache", "free_memory", "unload_models")}


def _identity(base_url: str, path: str) -> str:
    return hashlib.sha256(json.dumps([base_url.strip().rstrip("/"), path.strip()]).encode()).hexdigest()


def profile_for(config: dict, base_url: str, path: str) -> dict:
    provider = provider_settings_from_config(config).get("comfyui", {})
    profiles = provider.get("generation_profiles", {})
    entry = profiles.get(_identity(base_url, path), {}) if isinstance(profiles, Mapping) else {}
    return copy.deepcopy(dict(entry)) if isinstance(entry, Mapping) else {}


def validate_field(field: str, value: Any) -> Any:
    """Validate at both persistence and generation boundaries; seeds remain text."""
    if field in MODES:
        if value not in MODES[field]:
            raise ValueError(f"Invalid {field}.")
        return value
    if field == "seed":
        text = str(value).strip()
        if not text.isascii() or not text.isdecimal() or not 0 <= int(text) <= 2**64 - 1:
            raise ValueError("Seed must be an unsigned 64-bit integer.")
        return str(int(text))
    if field in NUMERIC_LIMITS:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid {field}.") from exc
        low, high = NUMERIC_LIMITS[field]
        if isinstance(value, bool) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f"{field} must be between {low} and {high}.")
        if field in {"steps", "width", "height"}:
            if not number.is_integer() or (field != "steps" and int(number) % 8):
                raise ValueError(f"{field} must be an integer" + (" and a multiple of 8." if field != "steps" else "."))
            return int(number)
        return number
    if field == "sampler_enabled":
        if not isinstance(value, bool):
            raise ValueError("Sampler override must be true or false.")
        return value
    if field in {"sampler_id", "sampler_name", "scheduler", "negative_prompt"}:
        if not isinstance(value, str):
            raise ValueError(f"Invalid {field}.")
        return value.strip()
    raise ValueError(f"Unknown generation setting: {field}")


def update_profile(config: dict, base_url: str, path: str, field: str, value: Any) -> dict:
    settings = provider_settings_from_config(config)
    provider = dict(settings.get("comfyui", {}))
    raw = provider.get("generation_profiles", {})
    profiles = {str(key): dict(value) if isinstance(value, Mapping) else value
                for key, value in raw.items()} if isinstance(raw, Mapping) else {}
    key = _identity(base_url, path)
    profile = profile_for(config, base_url, path)
    if field == "reset_sampler":
        for name in (*SAMPLER_FIELDS, "sampler_enabled"):
            profile.pop(name, None)
    elif value is None or value == "":
        if field not in {*SAMPLER_FIELDS, *NUMERIC_LIMITS, *MODES, "seed", "sampler_id", "sampler_enabled", "negative_prompt"}:
            raise ValueError(f"Unknown generation setting: {field}")
        if ((field in {"width", "height"} and profile.get("dimension_mode") == "custom")
                or (field == "seed" and profile.get("seed_mode") == "fixed")):
            raise ValueError(f"{field} is required in the selected generation mode.")
        profile.pop(field, None)
    else:
        profile[field] = validate_field(field, value)
    profiles[key] = profile
    provider["generation_profiles"] = profiles
    settings["comfyui"] = provider
    return settings


def _inputs(workflow: dict, node_id: str) -> dict:
    node = workflow.get(node_id, {})
    inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
    return inputs if isinstance(inputs, dict) else {}


def _literal(inputs: dict, field: str) -> bool:
    return field in inputs and isinstance(inputs[field], (str, int, float)) and not isinstance(inputs[field], bool)


def _schema(info: dict, class_type: str) -> dict:
    node = info.get(class_type, {})
    sections = node.get("input", {}) if isinstance(node, dict) else {}
    if not isinstance(sections, dict):
        return {}
    result = {}
    for name in ("required", "optional"):
        if isinstance(sections.get(name), dict):
            result.update(sections[name])
    return result


def _choices(schema: dict, field: str) -> list[str]:
    spec = schema.get(field, [])
    return list(spec[0]) if isinstance(spec, (list, tuple)) and spec and isinstance(spec[0], (list, tuple)) else []


def _requires_target(workflow: dict) -> bool:
    return sum(1 for node in workflow.values() if isinstance(node, dict)
               and "ksampler" in str(node.get("class_type", "")).lower()) > 1


def describe_workflow(workflow: dict, object_info: dict, primary_id: str, latent_id: str) -> dict:
    samplers = []
    for node_id, node in workflow.items():
        class_type = node.get("class_type", "") if isinstance(node, dict) else ""
        if class_type not in SAMPLER_CLASSES:
            continue
        inputs, schema = _inputs(workflow, node_id), _schema(object_info, class_type)
        seed_key = SAMPLER_CLASSES[class_type]
        values = {field: inputs.get(field) if _literal(inputs, field) else None for field in SAMPLER_FIELDS}
        values["seed"] = str(inputs[seed_key]) if _literal(inputs, seed_key) else ""
        supported = {field: _literal(inputs, field) and field in schema for field in SAMPLER_FIELDS}
        supported["seed"] = _literal(inputs, seed_key)
        meta = node.get("_meta")
        title = str(meta.get("title") or class_type) if isinstance(meta, dict) else class_type
        samplers.append({"id": str(node_id), "label": f"{title} · #{node_id}", "values": values,
                         "supported": supported, "samplers": _choices(schema, "sampler_name"),
                         "schedulers": _choices(schema, "scheduler")})
    latent = _inputs(workflow, latent_id)
    width_key = "width" if "width" in latent else "width_override"
    height_key = "height" if "height" in latent else "height_override"
    dimensions_supported = all(_literal(latent, key) and isinstance(latent[key], int) for key in (width_key, height_key))
    metadata_available = any(any(sampler["supported"][field] for field in SAMPLER_FIELDS)
                             for sampler in samplers)
    status = ("Ready" if metadata_available else
              "Workflow loaded; waiting for ComfyUI node metadata to edit sampler settings.")
    if not samplers:
        status = "No supported sampler found; workflow controls generation."
    return {"samplers": samplers, "requires_target": _requires_target(workflow), "primary_id": primary_id, "latent_id": latent_id,
            "width": latent.get(width_key) if dimensions_supported else None,
            "height": latent.get(height_key) if dimensions_supported else None,
            "dimensions_supported": dimensions_supported, "metadata_available": metadata_available,
            "status": status}


def apply_settings(current: dict, original: dict, profile: dict, object_info: dict,
                   primary_id: str, latent_id: str) -> None:
    """Apply explicit controls after the existing NC injection, before queueing."""
    if not profile:
        return
    mode = validate_field("dimension_mode", profile.get("dimension_mode", "legacy"))
    latent = _inputs(original, latent_id)
    if mode == "workflow":
        # Restoring links is safe: no new connections or values are invented.
        for field in ("width", "height", "width_override", "height_override"):
            target = _inputs(current, latent_id)
            if field in latent:
                target[field] = copy.deepcopy(latent[field])
    elif mode == "custom":
        width_key = "width" if "width" in latent else "width_override"
        height_key = "height" if "height" in latent else "height_override"
        for field, key in (("width", width_key), ("height", height_key)):
            if not _literal(latent, key):
                raise ValueError(f"Custom dimensions unavailable: {key} is missing or linked.")
            _inputs(current, latent_id)[key] = validate_field(field, profile.get(field))

    seed_mode = validate_field("seed_mode", profile.get("seed_mode", "legacy"))
    enabled = validate_field("sampler_enabled", profile.get("sampler_enabled", False))
    if not enabled and seed_mode == "legacy":
        return
    candidates = [str(key) for key, node in original.items()
                  if isinstance(node, dict) and node.get("class_type") in SAMPLER_CLASSES]
    sampler_id = str(profile.get("sampler_id") or (candidates[0] if len(candidates) == 1 and not _requires_target(original) else ""))
    if sampler_id not in candidates:
        raise ValueError("Choose a supported sampler target before enabling generation overrides.")
    class_type = original[sampler_id]["class_type"]
    source, target = _inputs(original, sampler_id), _inputs(current, sampler_id)
    seed_key = SAMPLER_CLASSES[class_type]
    if seed_mode != "legacy":
        if not _literal(source, seed_key):
            raise ValueError("The sampler seed is missing or linked; leave it workflow controlled.")
        target[seed_key] = (random.randint(0, 2**63 - 1) if seed_mode == "random" else
                            int(validate_field("seed", profile.get("seed") if seed_mode == "fixed" else source[seed_key])))
    if enabled:
        schema = _schema(object_info, class_type)
        for field in SAMPLER_FIELDS:
            if field not in profile:
                continue
            if not _literal(source, field):
                raise ValueError(f"{field} is missing or linked on sampler {sampler_id}.")
            if field not in schema:
                raise ValueError(f"Server metadata unavailable for {field}; refresh the workflow.")
            value = validate_field(field, profile[field])
            if field in {"sampler_name", "scheduler"}:
                if value not in _choices(schema, field):
                    raise ValueError(f"Server does not support {field}: {value}")
            else:
                spec = schema[field]
                limits = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                if not limits.get("min", -math.inf) <= value <= limits.get("max", math.inf):
                    raise ValueError(f"{field} is outside the connected server's limits.")
            target[field] = value
