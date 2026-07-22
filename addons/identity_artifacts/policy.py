from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

from addons.identity_artifacts.normalized_model import IdentityRecord, RuntimeLayer
from core.lmstudio_runtime import is_local_base_url


@dataclass(frozen=True)
class RuntimeUse:
    surface: str
    provider_is_remote: bool
    requested_use: str = ""
    transient: bool = False
    owner_override: bool = False


@dataclass(frozen=True)
class UserApproval:
    connected: bool
    transient_active: bool = False
    review_approved: bool = False
    approved_operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectiveUseDecision:
    allowed: bool
    effective_uses: tuple[str, ...]
    reason_code: str
    explanation: str


_OPERATION_ALIASES = {
    "always_inject": frozenset(("always_inject", "hot_identity")),
    "private_retrieval": frozenset(
        (
            "private_retrieval",
            "contextual_retrieval",
            "retrieve_when_relevant",
            "ltm_retrieval",
        )
    ),
    "persistence_export": frozenset(("persistence_export", "external_export")),
    "debug_trace": frozenset(("debug_trace", "debug_logging")),
    "provider_transmission": frozenset(("provider_transmission",)),
    "embedding_transmission": frozenset(
        ("embedding_transmission", "semantic_embedding")
    ),
}

_EXPOSURE_OPERATIONS = {
    "persistence_export": "external_export",
    "debug_trace": "debug_logs",
}

_ENDPOINT_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def classify_endpoint_is_remote(value: Any) -> bool | None:
    endpoint = str(value or "").strip()
    if not endpoint:
        return None
    parse_value = (
        endpoint if _ENDPOINT_SCHEME_RE.match(endpoint) else f"http://{endpoint}"
    )
    try:
        parsed = urlparse(parse_value)
        if parsed.scheme.casefold() not in {"http", "https"}:
            return None
        host = str(parsed.hostname or "").strip()
        parsed.port
    except (TypeError, ValueError):
        return None
    if not host or any(character.isspace() for character in host):
        return None
    return not is_local_base_url(endpoint)


def evaluate_effective_use(
    record: IdentityRecord,
    runtime_use: RuntimeUse,
    approval: UserApproval,
) -> EffectiveUseDecision:
    if not approval.connected:
        return _denied("user_approval_required", "The identity artifact is not connected by the user.")
    if record.runtime_layer == RuntimeLayer.UNCLASSIFIED:
        return _denied(
            "semantic_review_required",
            "The record has no approved runtime-layer classification.",
        )
    if record.review_state == "required" and not approval.review_approved:
        return _denied("record_review_required", "The record requires an explicit review decision.")
    if runtime_use.transient and not approval.transient_active:
        return _denied("transient_inactive", "Transient continuity is not active for this chat.")
    if not record.runtime_suitability:
        return _denied(
            "no_runtime_suitable_use",
            "The record declares no runtime-suitable uses, so use fails closed.",
        )

    policy = record.declared_policy
    allowed_surfaces = policy.get("allowed_surfaces")
    if allowed_surfaces is not None:
        if not _string_sequence(allowed_surfaces):
            return _denied(
                "policy_review_required",
                "The declared surface policy is malformed or empty.",
            )
        if runtime_use.surface not in allowed_surfaces:
            return _denied(
                "surface_not_permitted",
                f"Declared policy does not permit the {runtime_use.surface!r} surface.",
            )

    malformed_eligibility = tuple(
        sorted(
            str(key)
            for key, value in policy.items()
            if str(key).startswith("eligible_for_") and not isinstance(value, bool)
        )
    )
    requested_operation = _canonical_operation(runtime_use.requested_use)
    if not requested_operation:
        if malformed_eligibility:
            names = ", ".join(malformed_eligibility)
            return _denied(
                "policy_review_required",
                f"Malformed eligibility policy requires Boolean values: {names}.",
            )
        return _denied(
            "runtime_operation_required",
            "Identity Relay authorization requires one explicit runtime operation.",
        )
    aliases = _OPERATION_ALIASES.get(requested_operation)
    if aliases is None:
        return _denied(
            "runtime_operation_unsupported",
            f"Identity Relay does not recognize runtime operation {runtime_use.requested_use!r}.",
        )

    if malformed_eligibility:
        names = ", ".join(malformed_eligibility)
        malformed_uses = {
            _use_name(name) for name in malformed_eligibility
        }
        if aliases.intersection(malformed_uses):
            return _denied(
                "runtime_use_not_permitted",
                f"Declared eligibility for {requested_operation!r} is malformed: {names}.",
            )
        return _denied(
            "policy_review_required",
            f"Malformed eligibility policy requires Boolean values: {names}.",
        )

    prohibited = policy.get("prohibited_runtime_use", ())
    if prohibited is None:
        prohibited = ()
    if not _string_sequence(prohibited, allow_empty=True):
        return _denied("policy_review_required", "The prohibited-use policy is malformed.")
    prohibited_operations = {
        _canonical_operation(value) or _use_name(value) for value in prohibited
    }
    if requested_operation in prohibited_operations:
        return _denied(
            "runtime_use_prohibited",
            f"Declared policy prohibits {requested_operation!r}.",
        )

    eligibility = {
        _use_name(str(key)): value
        for key, value in policy.items()
        if str(key).startswith("eligible_for_")
    }
    exact_eligibility = eligibility.get(requested_operation)
    explicitly_denied = (
        ()
        if exact_eligibility is True
        else tuple(
            sorted(alias for alias in aliases if eligibility.get(alias) is False)
        )
    )
    if explicitly_denied:
        other_allowed = any(value is True for value in eligibility.values())
        if not other_allowed and not str(policy.get("preferred_runtime_use") or ""):
            return _denied(
                "no_effective_use",
                f"No effective {requested_operation!r} use remains because declared eligibility explicitly denies it.",
            )
        return _denied(
            "runtime_use_not_permitted",
            f"Declared policy does not permit {requested_operation!r}.",
        )

    if requested_operation not in {
        "provider_transmission",
        "embedding_transmission",
    }:
        preferred = _use_name(str(policy.get("preferred_runtime_use") or ""))
        declared = preferred in aliases or any(
            eligibility.get(alias) is True for alias in aliases
        )
        if not declared:
            return _denied(
                "runtime_use_not_permitted",
                f"Declared policy does not explicitly permit {requested_operation!r}.",
            )
        suitable_uses = {
            _use_name(str(value)) for value in record.runtime_suitability
        }
        if not aliases.intersection(suitable_uses):
            return _denied(
                "no_effective_use",
                f"No effective {requested_operation!r} use remains because runtime suitability does not include it.",
            )

        removed: list[tuple[str, str]] = []
        for use, value in eligibility.items():
            if value is False and use not in aliases:
                removed.append((use, "declared eligibility explicitly denies it"))
        preferred_operation = _canonical_operation(preferred)
        if (
            preferred_operation
            and preferred_operation != requested_operation
            and not _OPERATION_ALIASES[preferred_operation].intersection(suitable_uses)
        ):
            removed.append(
                (preferred_operation, "record runtime suitability does not include it")
            )
    else:
        removed = []

    exposure = _evaluate_exposure(record, runtime_use, approval, requested_operation)
    if exposure is not None and not exposure.allowed:
        return exposure
    if exposure is not None and exposure.reason_code == "owner_override":
        return exposure
    if exposure is not None and exposure.reason_code == "allowed_narrowed":
        return EffectiveUseDecision(
            allowed=True,
            effective_uses=(requested_operation,),
            reason_code="allowed_narrowed",
            explanation=exposure.explanation,
        )
    if removed:
        return EffectiveUseDecision(
            True,
            (requested_operation,),
            "allowed_narrowed",
            " ".join(
                (
                    "Use is allowed only after visible narrowing.",
                    *_removal_explanations(tuple(removed)),
                )
            ),
        )
    return EffectiveUseDecision(
        allowed=True,
        effective_uses=(requested_operation,),
        reason_code="allowed",
        explanation="Declared policy, semantic suitability, runtime capability, and user approval intersect.",
    )


def _evaluate_exposure(
    record: IdentityRecord,
    runtime_use: RuntimeUse,
    approval: UserApproval,
    operation: str,
) -> EffectiveUseDecision | None:
    exposure_key = _EXPOSURE_OPERATIONS.get(operation)
    if operation in {"provider_transmission", "embedding_transmission"}:
        exposure_key = (
            "private_remote_1on1"
            if runtime_use.provider_is_remote
            else "private_local_1on1"
        )
    if exposure_key is None:
        return None
    if runtime_use.owner_override:
        return EffectiveUseDecision(
            True,
            (operation,),
            "owner_override",
            "The owner explicitly authorized unrestricted Identity Relay exposure.",
        )
    exposure = record.exposure_policy
    remote_authority = record.declared_policy.get("allow_remote_provider")
    if (
        operation in {"provider_transmission", "embedding_transmission"}
        and runtime_use.provider_is_remote
        and "allow_remote_provider" in record.declared_policy
        and type(remote_authority) is not bool
    ):
        return _denied(
            "policy_review_required",
            "Remote provider authority must be an explicit Boolean value.",
        )
    if (
        operation in {"provider_transmission", "embedding_transmission"}
        and runtime_use.provider_is_remote
        and remote_authority is False
    ):
        exposure_value = exposure.get(exposure_key)
        exposure_mode = (
            exposure_value.strip().casefold()
            if isinstance(exposure_value, str)
            else ""
        )
        if exposure_key in exposure and exposure_mode != "deny":
            return _denied(
                "remote_provider_not_permitted",
                "Explicit allow_remote_provider=False conflicts with the remote "
                f"exposure mode {exposure_mode or 'malformed'!r}; policy is narrowed "
                "to deny remote transmission.",
            )
        return _denied(
            "remote_provider_not_permitted",
            "Explicit allow_remote_provider=False is a hard ceiling that denies "
            "remote transmission.",
        )
    if exposure_key not in exposure:
        return _denied(
            "exposure_authorization_required",
            f"Exposure policy does not explicitly authorize {exposure_key!r}.",
        )
    value = exposure.get(exposure_key)
    if not isinstance(value, str) or not value.strip():
        return _denied(
            "policy_review_required",
            f"Exposure policy for {exposure_key!r} is malformed.",
        )
    mode = value.strip().casefold()
    if mode == "allow":
        return EffectiveUseDecision(True, (operation,), "allowed", "Exposure policy explicitly allows this operation.")
    approved_operations = {
        _canonical_operation(item) or str(item) for item in approval.approved_operations
    }
    if mode == "ask_user":
        if operation in approved_operations:
            return EffectiveUseDecision(
                True,
                (operation,),
                "allowed",
                "The exposure policy required and received explicit user approval.",
            )
        return _denied(
            "operation_user_approval_required",
            f"Exposure policy requires explicit user approval for {operation!r}.",
        )
    if operation == "debug_trace" and mode == "redact":
        return EffectiveUseDecision(
            True,
            (operation,),
            "allowed_narrowed",
            "Debug trace exposure is allowed only in redacted form by declared policy.",
        )
    return _denied(
        "exposure_not_permitted",
        f"Exposure policy mode {mode!r} does not permit exact {operation!r} use.",
    )


def _canonical_operation(value: str) -> str:
    use = _use_name(str(value or ""))
    for operation, aliases in _OPERATION_ALIASES.items():
        if use == operation or use in aliases:
            return operation
    return ""


def _effective_uses(
    record: IdentityRecord, policy: Mapping[str, Any], requested_use: str
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    suitable_uses = tuple(dict.fromkeys(_use_name(value) for value in record.runtime_suitability))
    declared_uses: list[str] = []
    preferred = policy.get("preferred_runtime_use")
    if isinstance(preferred, str) and preferred:
        declared_uses.append(preferred)
    declared_uses.extend(
        _use_name(str(key))
        for key, value in policy.items()
        if str(key).startswith("eligible_for_") and value is True
    )
    candidates = [requested_use] if requested_use else declared_uses or list(suitable_uses)
    explicitly_ineligible = {
        _use_name(str(key))
        for key, value in policy.items()
        if str(key).startswith("eligible_for_") and value is False
    }
    prohibited = policy.get("prohibited_runtime_use", ())
    prohibited_values = (
        {_use_name(value) for value in prohibited}
        if _string_sequence(prohibited, allow_empty=True)
        else set()
    )
    effective: list[str] = []
    removed: list[tuple[str, str]] = []
    for value in dict.fromkeys(candidates):
        if value in explicitly_ineligible:
            removed.append((value, "declared eligibility explicitly denies it"))
        elif value in prohibited_values:
            removed.append((value, "declared policy prohibits it"))
        elif value not in suitable_uses:
            removed.append((value, "record runtime suitability does not include it"))
        else:
            effective.append(value)
    removed_values = {value for value, _reason in removed}
    removed.extend(
        (value, "declared eligibility explicitly denies it")
        for value in suitable_uses
        if value in explicitly_ineligible and value not in removed_values
    )
    return tuple(effective), tuple(removed)


def _use_name(value: str) -> str:
    prefix = "eligible_for_"
    return value[len(prefix) :] if value.startswith(prefix) else value


def _removal_explanations(removed: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    return tuple(f"Removed {value!r} because {reason}." for value, reason in removed)


def _string_sequence(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, (list, tuple))
        and (allow_empty or bool(value))
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def _denied(reason_code: str, explanation: str) -> EffectiveUseDecision:
    return EffectiveUseDecision(False, (), reason_code, explanation)
