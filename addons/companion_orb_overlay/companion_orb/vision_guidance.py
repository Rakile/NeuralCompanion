from __future__ import annotations

import json
import urllib.request
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit


VALID_RUNTIME_LOCATIONS = frozenset({"primary", "separate_local", "lan"})
PRIMARY_PARALLEL_MODEL_HANDLING = "parallel_pinned"
DEFAULT_VISION_CAPABILITY_MODE = "auto"
VALID_VISION_CAPABILITY_MODES = frozenset(
    {"auto", "structured_regions", "description", "ocr"}
)
VALID_MODEL_HANDLING = frozenset(
    {
        "auto_load",
        "already_loaded",
        "auto_with_fallback",
        PRIMARY_PARALLEL_MODEL_HANDLING,
    }
)


def auxiliary_vision_enabled(settings: Mapping[str, object]) -> bool:
    """Return whether the active Companion Orb may use its auxiliary vision model."""

    return bool(
        settings.get("companion_orb_enabled", False)
        and settings.get("companion_orb_vision_enabled", False)
    )


def lfm_features_enabled(settings: Mapping[str, object]) -> bool:
    """Backward-compatible alias for the original LFM-specific helper."""

    return auxiliary_vision_enabled(settings)


def normalize_vision_capability_mode(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return (
        normalized
        if normalized in VALID_VISION_CAPABILITY_MODES
        else DEFAULT_VISION_CAPABILITY_MODE
    )


def capability_supports_regions(value: object) -> bool:
    return normalize_vision_capability_mode(value) in {
        "auto",
        "structured_regions",
    }


def primary_parallel_enabled(settings: Mapping[str, object]) -> bool:
    return bool(
        normalize_runtime_location(
            settings.get("companion_orb_vision_runtime_location")
        )
        == "primary"
        and str(
            settings.get("companion_orb_vision_provider_id") or ""
        ).strip().lower()
        == "lmstudio"
        and str(settings.get("companion_orb_vision_model_id") or "").strip()
        and bool(
            settings.get("companion_orb_vision_primary_parallel_models", True)
        )
        and lfm_features_enabled(settings)
    )


def normalize_runtime_location(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in VALID_RUNTIME_LOCATIONS else "primary"


def normalize_model_handling(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in VALID_MODEL_HANDLING else "auto_load"


def normalize_lmstudio_base_url(value: object, *, required: bool) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        if required:
            raise ValueError("An LM Studio server URL is required.")
        return ""

    parsed = urlsplit(raw_value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("The LM Studio server URL must use http or https.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("The LM Studio server URL must not include credentials.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The LM Studio server URL has an invalid port.") from exc
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if scheme == "http" else 443
    netloc = host if port in {None, default_port} else f"{host}:{port}"
    return urlunsplit((scheme, netloc, "/v1", "", ""))


def probe_lmstudio_models(
    base_url: str,
    *,
    timeout_seconds: float,
) -> tuple[str, ...]:
    normalized_url = normalize_lmstudio_base_url(base_url, required=True)
    request = urllib.request.Request(
        f"{normalized_url}/models",
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer lm-studio",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=float(timeout_seconds)) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, Mapping):
        raise ValueError("LM Studio returned an invalid model-list response.")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("LM Studio returned an invalid model-list response.")

    model_ids: list[str] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        model_id = str(item.get("id") or "").strip()
        if model_id:
            model_ids.append(model_id)
    return tuple(model_ids)
