from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VisualReplyProviderSpec:
    provider_id: str
    label: str
    default_model: str
    legacy_api_key_config_key: str
    legacy_model_config_key: str
    legacy_size_config_key: str
    api_key_env_names: tuple[str, ...] = field(default_factory=tuple)
    model_env_names: tuple[str, ...] = field(default_factory=tuple)
    size_env_names: tuple[str, ...] = field(default_factory=tuple)
    base_url_env_names: tuple[str, ...] = field(default_factory=tuple)
    default_base_url: str = ""
    deprecated_models: frozenset[str] = field(default_factory=frozenset)
    legacy_default_models: frozenset[str] = field(default_factory=frozenset)
    requires_api_key: bool = True
    api_key_setting_key: str = "api_key"
    model_setting_key: str = "model"
    size_setting_key: str = "size"
    base_url_setting_key: str = "base_url"


PROVIDER_SPECS: tuple[VisualReplyProviderSpec, ...] = (
    VisualReplyProviderSpec(
        provider_id="openai",
        label="OpenAI",
        default_model="gpt-image-1",
        legacy_api_key_config_key="visual_reply_openai_api_key",
        legacy_model_config_key="visual_reply_openai_model",
        legacy_size_config_key="visual_reply_openai_size",
        api_key_env_names=("NC_VISUAL_REPLY_API_KEY", "OPENAI_API_KEY"),
        model_env_names=("NC_VISUAL_REPLY_MODEL",),
        size_env_names=("NC_VISUAL_REPLY_SIZE",),
        base_url_env_names=("NC_VISUAL_REPLY_BASE_URL",),
        requires_api_key=False,
    ),
    VisualReplyProviderSpec(
        provider_id="xai",
        label="xAI / Grok",
        default_model="grok-imagine-image-quality",
        legacy_api_key_config_key="visual_reply_xai_api_key",
        legacy_model_config_key="visual_reply_xai_model",
        legacy_size_config_key="visual_reply_xai_size",
        api_key_env_names=("NC_VISUAL_REPLY_XAI_API_KEY", "XAI_API_KEY", "NC_VISUAL_REPLY_API_KEY"),
        model_env_names=("NC_VISUAL_REPLY_XAI_MODEL", "NC_VISUAL_REPLY_MODEL"),
        size_env_names=("NC_VISUAL_REPLY_XAI_SIZE", "NC_VISUAL_REPLY_SIZE"),
        base_url_env_names=("NC_VISUAL_REPLY_BASE_URL", "NC_VISUAL_REPLY_XAI_BASE_URL"),
        default_base_url="https://api.x.ai/v1",
        deprecated_models=frozenset({"grok-imagine-image", "grok-imagine-image-pro"}),
    ),
    VisualReplyProviderSpec(
        provider_id="runware",
        label="Runware",
        default_model="runware:z-image@turbo",
        legacy_api_key_config_key="visual_reply_runware_api_key",
        legacy_model_config_key="visual_reply_runware_model",
        legacy_size_config_key="visual_reply_runware_size",
        api_key_env_names=("NC_VISUAL_REPLY_RUNWARE_API_KEY", "RUNWARE_API_KEY", "NC_VISUAL_REPLY_API_KEY"),
        model_env_names=("NC_VISUAL_REPLY_RUNWARE_MODEL", "NC_VISUAL_REPLY_MODEL"),
        size_env_names=("NC_VISUAL_REPLY_RUNWARE_SIZE", "NC_VISUAL_REPLY_SIZE"),
        legacy_default_models=frozenset({"runware:101@1"}),
    ),
    VisualReplyProviderSpec(
        provider_id="comfyui",
        label="ComfyUI",
        default_model="user/default/workflows/NeuralCompanionFlow.json",
        legacy_api_key_config_key="visual_reply_comfyui_base_url",
        legacy_model_config_key="visual_reply_comfyui_workflow_path",
        legacy_size_config_key="visual_reply_comfyui_size",
        api_key_env_names=(),
        model_env_names=("NC_VISUAL_REPLY_COMFYUI_WORKFLOW", "COMFYUI_WORKFLOW_PATH"),
        size_env_names=("NC_VISUAL_REPLY_COMFYUI_SIZE", "NC_VISUAL_REPLY_SIZE"),
        base_url_env_names=("NC_VISUAL_REPLY_COMFYUI_BASE_URL", "COMFYUI_BASE_URL", "NC_VISUAL_REPLY_BASE_URL"),
        default_base_url="http://127.0.0.1:8188",
        requires_api_key=False,
        api_key_setting_key="base_url",
        model_setting_key="workflow_path",
    ),
)

PROVIDERS_BY_ID = {spec.provider_id: spec for spec in PROVIDER_SPECS}


def provider_spec(provider: str | None) -> VisualReplyProviderSpec:
    provider_id = str(provider or "openai").strip().lower()
    return PROVIDERS_BY_ID.get(provider_id, PROVIDERS_BY_ID["openai"])


def provider_ids() -> tuple[str, ...]:
    return tuple(spec.provider_id for spec in PROVIDER_SPECS)


def provider_labels() -> list[str]:
    return [spec.label for spec in PROVIDER_SPECS]


def provider_label_from_value(value: str | None) -> str:
    return provider_spec(value).label


def provider_value_from_label(label: str | None) -> str:
    text = str(label or "").strip().lower()
    for spec in PROVIDER_SPECS:
        if spec.provider_id in text or spec.label.lower() in text:
            return spec.provider_id
    if "grok" in text:
        return "xai"
    return "openai"


def provider_setting_key(provider: str | None, role: str) -> str:
    spec = provider_spec(provider)
    role = str(role or "").strip().lower()
    if role == "api_key":
        return spec.api_key_setting_key
    if role == "model":
        return spec.model_setting_key
    if role == "size":
        return spec.size_setting_key
    if role == "base_url":
        return spec.base_url_setting_key
    if role == "workflow_path":
        return spec.model_setting_key
    return role


def provider_settings_from_config(config: dict | None) -> dict[str, dict]:
    source = dict(config or {})
    raw_settings = source.get("visual_reply_provider_settings", {})
    settings = {}
    if isinstance(raw_settings, dict):
        for provider_id, payload in raw_settings.items():
            provider_id = str(provider_id or "").strip().lower()
            if not provider_id:
                continue
            settings[provider_id] = dict(payload or {}) if isinstance(payload, dict) else {}

    for spec in PROVIDER_SPECS:
        provider_payload = settings.setdefault(spec.provider_id, {})
        for role, legacy_key in (
            ("api_key", spec.legacy_api_key_config_key),
            ("model", spec.legacy_model_config_key),
            ("size", spec.legacy_size_config_key),
        ):
            setting_key = provider_setting_key(spec.provider_id, role)
            if setting_key not in provider_payload and legacy_key in source:
                provider_payload[setting_key] = source.get(legacy_key, "")
    return settings


def provider_setting_from_config(config: dict | None, provider: str | None, role: str, default=""):
    provider_id = provider_spec(provider).provider_id
    payload = provider_settings_from_config(config).get(provider_id, {})
    return payload.get(provider_setting_key(provider_id, role), default)


def updated_provider_settings(config: dict | None, provider: str | None, role: str, value) -> dict[str, dict]:
    settings = provider_settings_from_config(config)
    provider_id = provider_spec(provider).provider_id
    payload = dict(settings.get(provider_id, {}) or {})
    payload[provider_setting_key(provider_id, role)] = value
    settings[provider_id] = payload
    return settings


def default_model_for_provider(provider: str | None) -> str:
    return provider_spec(provider).default_model


def known_default_models() -> set[str]:
    values = set()
    for spec in PROVIDER_SPECS:
        values.add(spec.default_model)
        values.update(spec.deprecated_models)
        values.update(spec.legacy_default_models)
    return values


def normalize_model_for_provider(provider: str | None, model: str | None) -> str:
    spec = provider_spec(provider)
    model_name = str(model or spec.default_model).strip() or spec.default_model
    if model_name in spec.deprecated_models or model_name in spec.legacy_default_models:
        return spec.default_model
    return model_name


def model_override_for_provider(provider: str | None, model: str | None) -> str:
    model_name = str(model or "").strip()
    if not model_name:
        return ""
    model_name = normalize_model_for_provider(provider, model_name)
    return "" if model_name == default_model_for_provider(provider) else model_name


def env_value(names: tuple[str, ...], environ) -> str:
    for name in names:
        value = str((environ or {}).get(name, "") or "").strip()
        if value:
            return value
    return ""
