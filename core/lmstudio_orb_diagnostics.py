from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from core import chat_providers, companion_orb_reply_styles
from core.runtime.config import RuntimeConfigService
from core.runtime.providers import ProviderSelection, ProviderService
from core.runtime_chat import ChatProviderRuntime


ModelInspect = Callable[[str], Sequence[object]]
ModelLoad = Callable[[str, str], object]
ModelUnload = Callable[[str, str], object]
ModelUnloadOne = Callable[[str, str], object]
ModelIdentifierResolver = Callable[[str, str], str]


def diagnose_session_payload(payload: Mapping[str, object]) -> dict[str, object]:
    chat_runtime = _mapping(payload.get("chat_runtime"))
    chat_core = _mapping(chat_runtime.get("core"))
    provider_id = str(chat_core.get("provider") or "lmstudio").strip().lower()
    provider_settings = _mapping(chat_runtime.get("provider_settings"))
    selected_provider = _mapping(provider_settings.get(provider_id))
    companion_orb = _mapping(payload.get("companion_orb"))

    lfm_master_enabled = bool(
        companion_orb.get("companion_orb_vision_enabled", False)
    )
    smart_drop_enabled = bool(
        companion_orb.get("companion_orb_smart_drop_guidance_enabled", False)
    )
    smart_drop_mode = str(
        companion_orb.get("companion_orb_smart_drop_guidance_mode") or "off"
    ).strip().lower()
    lfm_drop_guidance_enabled = bool(
        lfm_master_enabled
        and companion_orb.get("companion_orb_visual_guidance_enabled", False)
        and companion_orb.get("companion_orb_visual_guidance_drop_enabled", True)
    )
    main_base_url = str(selected_provider.get("base_url") or "").strip()
    lfm_runtime_location = str(
        companion_orb.get("companion_orb_vision_runtime_location") or "primary"
    ).strip().lower()
    configured_lfm_base_url = str(
        companion_orb.get("companion_orb_vision_base_url") or ""
    ).strip()
    lfm_base_url = (
        main_base_url
        if lfm_runtime_location == "primary"
        else configured_lfm_base_url
    )
    return {
        "provider_id": provider_id,
        "main_model_id": str(selected_provider.get("model_name") or "").strip(),
        "main_base_url": main_base_url,
        "main_supports_images": bool(
            selected_provider.get("model_supports_images", False)
        ),
        "lfm_master_enabled": lfm_master_enabled,
        "lfm_model_id": str(
            companion_orb.get("companion_orb_vision_model_id") or ""
        ).strip(),
        "lfm_runtime_location": lfm_runtime_location,
        "lfm_base_url": lfm_base_url,
        "lfm_effective": lfm_master_enabled,
        "visual_guidance_subordinate_enabled": bool(
            companion_orb.get("companion_orb_visual_guidance_enabled", False)
        ),
        "lfm_drop_guidance_enabled": lfm_drop_guidance_enabled,
        "smart_drop_enabled": smart_drop_enabled,
        "smart_drop_mode": smart_drop_mode,
        "smart_drop_extra_main_request": bool(
            smart_drop_enabled
            and smart_drop_mode == "smart"
            and not lfm_drop_guidance_enabled
        ),
        "orb_response_max_output_tokens": (
            companion_orb_reply_styles.ORB_RESPONSE_MAX_OUTPUT_TOKENS
        ),
    }


def run_model_residency_probe(
    diagnosis: Mapping[str, object],
    *,
    inspect_models: ModelInspect,
    load_model: ModelLoad,
    unload_models: ModelUnload,
    unload_model: ModelUnloadOne | None = None,
    pinned_load_model: ModelLoad | None = None,
    prepare_attempts: int = 3,
) -> dict[str, object]:
    provider_id = str(diagnosis.get("provider_id") or "").strip().lower()
    model_id = str(diagnosis.get("main_model_id") or "").strip()
    endpoint = str(diagnosis.get("main_base_url") or "").strip()
    attempts = max(1, min(10, int(prepare_attempts or 1)))
    if provider_id != "lmstudio" or not model_id or not endpoint:
        raise ValueError("The diagnostic requires a configured LM Studio main model.")

    load_calls: list[dict[str, str]] = []
    unload_calls: list[dict[str, str]] = []

    def traced_load(requested_model: str, requested_endpoint: str) -> object:
        load_calls.append(
            {"model_id": requested_model, "endpoint": requested_endpoint}
        )
        return load_model(requested_model, requested_endpoint)

    def traced_unload(reason: str, requested_endpoint: str) -> object:
        unload_calls.append(
            {"reason": str(reason or ""), "endpoint": requested_endpoint}
        )
        return unload_models(reason, requested_endpoint)

    loaded_before = tuple(inspect_models(endpoint))
    config = RuntimeConfigService(
        {
            "chat_provider": provider_id,
            "model_name": model_id,
            "lmstudio_base_url": endpoint,
        }
    )
    service = ProviderService(
        ChatProviderRuntime(config.snapshot),
        model_unload=traced_unload,
        model_load=traced_load,
        preserved_model_load=(pinned_load_model or traced_load),
        model_inspect=inspect_models,
        model_unload_one=unload_model,
    )
    selection = ProviderSelection(
        provider_id=provider_id,
        model_id=model_id,
        config=config.snapshot(),
        context=chat_providers.FrozenChatProviderContext(
            provider_name=provider_id,
            model_name=model_id,
            provider_config={"base_url": endpoint},
        ),
    )
    prepare_results = [
        bool(service.prepare_model(selection, reason="Companion Orb diagnostic"))
        for _index in range(attempts)
    ]
    loaded_after = tuple(inspect_models(endpoint))
    main_was_loaded = _contains_model(loaded_before, model_id)
    main_is_loaded = _contains_model(loaded_after, model_id)
    passed = bool(
        all(prepare_results)
        and main_is_loaded
        and (not main_was_loaded or (not load_calls and not unload_calls))
        and (main_was_loaded or len(load_calls) <= 1)
    )
    return {
        "prepare_attempts": attempts,
        "prepare_results": prepare_results,
        "loaded_before": _serialize_instances(loaded_before),
        "loaded_after": _serialize_instances(loaded_after),
        "load_calls": load_calls,
        "unload_calls": unload_calls,
        "main_was_loaded": main_was_loaded,
        "main_is_loaded": main_is_loaded,
        "passed": passed,
    }


def run_image_response_probe(
    diagnosis: Mapping[str, object],
    *,
    image_path: Path,
    urlopen=urllib.request.urlopen,
    timeout_seconds: float = 30.0,
    resolve_model_identifier: ModelIdentifierResolver | None = None,
) -> dict[str, object]:
    model_id = str(diagnosis.get("main_model_id") or "").strip()
    endpoint = str(diagnosis.get("main_base_url") or "").strip().rstrip("/")
    path = Path(image_path)
    if not model_id or not endpoint:
        raise ValueError("The image probe requires a configured main model endpoint.")
    if not path.is_file():
        raise FileNotFoundError(path)
    request_model_id = model_id
    if callable(resolve_model_identifier):
        resolved_model_id = str(
            resolve_model_identifier(model_id, endpoint) or ""
        ).strip()
        if resolved_model_id:
            request_model_id = resolved_model_id

    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    image_data_url = (
        f"data:{mime_type};base64,"
        + base64.b64encode(path.read_bytes()).decode("ascii")
    )
    payload = {
        "model": request_model_id,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Companion Orb diagnostic. Describe the main visible "
                            "subject in one short sentence."
                        ),
                    },
                    {"type": "input_image", "image_url": image_data_url},
                ],
            }
        ],
        "max_output_tokens": companion_orb_reply_styles.ORB_RESPONSE_MAX_OUTPUT_TOKENS,
        "store": False,
        "stream": False,
        "reasoning": {"effort": "none"},
    }
    request = urllib.request.Request(
        endpoint + "/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer lm-studio",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(1.0, float(timeout_seconds))) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            error_body = ""
        detail = error_body[:2000] or str(exc.reason or exc)
        raise RuntimeError(
            f"LM Studio image probe failed with HTTP {exc.code}: {detail}"
        ) from exc
    if not isinstance(response_payload, Mapping):
        raise RuntimeError("LM Studio returned a non-object image probe response.")

    returned_model = str(response_payload.get("model") or "").strip()
    text = _responses_output_text(response_payload)
    degenerate = _is_degenerate_output(text)
    usage = _mapping(response_payload.get("usage"))
    output_tokens = int(usage.get("output_tokens") or 0)
    model_matches = returned_model == request_model_id
    output_within_cap = (
        output_tokens <= companion_orb_reply_styles.ORB_RESPONSE_MAX_OUTPUT_TOKENS
    )
    return {
        "requested_model_id": model_id,
        "returned_model_id": returned_model,
        "requested_model_id": request_model_id,
        "configured_model_id": model_id,
        "model_matches": model_matches,
        "text": text,
        "degenerate_output": degenerate,
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": output_tokens,
        "output_token_cap": companion_orb_reply_styles.ORB_RESPONSE_MAX_OUTPUT_TOKENS,
        "output_within_cap": output_within_cap,
        "passed": bool(model_matches and text and not degenerate and output_within_cap),
    }


def resolve_loaded_model_identifier(
    instances: Sequence[object],
    model_id: object,
) -> str:
    requested = str(model_id or "").strip()
    if not requested:
        return ""
    requested_folded = requested.casefold()
    exact_identifier = next(
        (
            str(getattr(instance, "identifier", "") or "").strip()
            for instance in instances
            if str(getattr(instance, "identifier", "") or "").strip().casefold()
            == requested_folded
        ),
        "",
    )
    if exact_identifier:
        return exact_identifier
    matches = [
        str(getattr(instance, "identifier", "") or "").strip()
        for instance in instances
        if str(getattr(instance, "identifier", "") or "").strip()
        and (
            str(getattr(instance, "model_key", "") or "").strip().casefold()
            == requested_folded
            or str(getattr(instance, "model_key", "") or "")
            .strip()
            .casefold()
            .startswith(f"{requested_folded}@")
        )
    ]
    return matches[0] if len(matches) == 1 else requested


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _contains_model(instances: Sequence[object], model_id: str) -> bool:
    return any(
        str(getattr(instance, "model_key", "") or "").strip() == model_id
        for instance in instances
    )


def _serialize_instances(instances: Sequence[object]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for instance in instances:
        identifier = str(getattr(instance, "identifier", "") or "").strip()
        model_key = str(getattr(instance, "model_key", "") or "").strip()
        if identifier or model_key:
            result.append({"identifier": identifier, "model_key": model_key})
    return result


def _responses_output_text(payload: Mapping[str, object]) -> str:
    chunks: list[str] = []
    output = payload.get("output")
    if not isinstance(output, Sequence) or isinstance(output, (str, bytes, bytearray)):
        return ""
    for item in output:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content")
        if not isinstance(content, Sequence) or isinstance(
            content,
            (str, bytes, bytearray),
        ):
            continue
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                text = str(part.get("text") or "").strip()
                if text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


def _is_degenerate_output(value: object) -> bool:
    text = re.sub(r"\s+", "", str(value or ""))
    if len(text) < 32:
        return False
    if len(set(text)) <= 2:
        return True
    return bool(re.fullmatch(r"(.{1,8})\1{7,}", text, flags=re.DOTALL))
