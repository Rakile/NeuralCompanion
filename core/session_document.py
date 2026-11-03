from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from addons.ditto_avatar.session_schema import flatten_ditto_settings, with_grouped_ditto_settings
from core.session_persistence_contract import (
    ACTIVE_CHAT_PROVIDER,
    ACTIVE_VISUAL_REPLY_PROVIDER,
    RestorePhase,
    SettingLifetime,
    SettingPolicy,
    policies_for_keys,
    policy_for_key,
    sanitize_session_value,
)

_MISSING = object()
_EXCLUDED_LIFETIMES = {
    SettingLifetime.TRANSIENT,
    SettingLifetime.DERIVED,
    SettingLifetime.PERSONA,
    SettingLifetime.CREDENTIAL,
    SettingLifetime.PRESET_ONLY,
    SettingLifetime.ADDON_GLOBAL,
    SettingLifetime.ADDON_PERSONA,
}


@dataclass(frozen=True)
class AddonSessionContribution:
    addon_id: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class SessionCollision:
    path: tuple[str, ...]
    accepted_owner: str | None
    rejected_owner: str
    reason: str


@dataclass(frozen=True)
class SessionMergeResult:
    payload: dict[str, Any]
    migrated_aliases: tuple[tuple[str, ...], ...]
    collisions: tuple[SessionCollision, ...]


@dataclass
class _ClaimNode:
    scalar_claims: dict[str, Any]
    children: dict[str, "_ClaimNode"]


def _nested_get(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current.get(part)
    return current


def _nested_set(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = payload
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = copy.deepcopy(value)


def _provider_token_value(
    token: str,
    payload: Mapping[str, Any],
    config_values: Mapping[str, Any],
) -> str:
    if token == ACTIVE_CHAT_PROVIDER:
        current = _nested_get(payload, ("chat_runtime", "core", "provider"))
        if current is _MISSING:
            current = payload.get("chat_provider")
        configured = config_values.get("chat_provider")
    elif token == ACTIVE_VISUAL_REPLY_PROVIDER:
        current = _nested_get(payload, ("visual_reply", "core", "provider"))
        if current is _MISSING:
            current = payload.get("visual_reply_provider")
        configured = config_values.get("visual_reply_provider")
    else:
        return ""
    return str(configured or ("" if current is _MISSING else current) or "").strip().lower()


def _resolve_path_tokens(
    path: tuple[str, ...] | None,
    payload: Mapping[str, Any],
    config_values: Mapping[str, Any],
) -> tuple[str, ...] | None:
    if path is None:
        return None
    resolved: list[str] = []
    for part in path:
        if part in {ACTIVE_CHAT_PROVIDER, ACTIVE_VISUAL_REPLY_PROVIDER}:
            provider = _provider_token_value(part, payload, config_values)
            if not provider:
                return None
            resolved.append(provider)
            continue
        resolved.append(str(part))
    return tuple(resolved)


def _resolve_canonical_path(
    policy: SettingPolicy,
    existing: Mapping[str, Any],
    config_values: Mapping[str, Any],
) -> tuple[str, ...] | None:
    return _resolve_path_tokens(getattr(policy, "canonical_path", None), existing, config_values)


def _nested_delete(payload: dict[str, Any], path: tuple[str, ...]) -> bool:
    if not path:
        return False
    current = payload
    parents: list[tuple[dict[str, Any], str]] = []
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            return False
        parents.append((current, part))
        current = next_value
    if path[-1] not in current:
        return False
    del current[path[-1]]
    for parent, part in reversed(parents):
        child = parent.get(part)
        if isinstance(child, dict) and not child:
            del parent[part]
        else:
            break
    return True


def _source_value(payload: Mapping[str, Any], source_path: tuple[str, ...]) -> Any:
    resolved_path = _resolve_path_tokens(source_path, payload, {})
    if resolved_path is None:
        return _MISSING
    value = _nested_get(payload, resolved_path)
    if value is _MISSING:
        return _MISSING
    return copy.deepcopy(value)


def _related_policies(
    policy: SettingPolicy,
    payload: Mapping[str, Any],
    policies: Mapping[str, SettingPolicy],
) -> tuple[SettingPolicy, ...]:
    if policy.canonical_path is None:
        return (policy,)
    related: list[SettingPolicy] = [policy]
    seen = {policy.key}
    for key in payload:
        extra = policy_for_key(str(key))
        if extra is None or extra.key in seen:
            continue
        if extra.canonical_path == policy.canonical_path:
            related.append(extra)
            seen.add(extra.key)
    for extra in policies.values():
        if extra.key in seen:
            continue
        if extra.canonical_path == policy.canonical_path:
            related.append(extra)
            seen.add(extra.key)
    leaf_key = policy.canonical_path[-1]
    leaf_policy = policy_for_key(leaf_key)
    if (
        leaf_policy is not None
        and leaf_policy.key not in seen
        and leaf_policy.canonical_path == policy.canonical_path
    ):
        related.append(leaf_policy)
    return tuple(related)


def _claim_node() -> _ClaimNode:
    return _ClaimNode(scalar_claims={}, children={})


def _collect_claims(
    node: _ClaimNode,
    payload: Mapping[str, Any],
    owner: str,
    prefix: tuple[str, ...] = (),
) -> None:
    for key, value in payload.items():
        child = node.children.setdefault(str(key), _claim_node())
        if isinstance(value, Mapping):
            path = (*prefix, str(key))
            policy = policy_for_key(str(key)) if not value else None
            if policy is not None and policy.owner == owner and policy.canonical_path == path:
                # An owned empty map clears that leaf. Empty namespace exports
                # still preserve existing data and other addons' contributions.
                child.scalar_claims[owner] = {}
            else:
                _collect_claims(child, value, owner, path)
            continue
        child.scalar_claims[owner] = copy.deepcopy(value)


def _sorted_scalar_claims(node: _ClaimNode) -> list[tuple[str, Any]]:
    return sorted(node.scalar_claims.items(), key=lambda item: item[0])


def _descendant_claim_paths(
    node: _ClaimNode,
    prefix: tuple[str, ...],
) -> list[tuple[tuple[str, ...], str]]:
    paths: list[tuple[tuple[str, ...], str]] = []
    for owner, _value in _sorted_scalar_claims(node):
        paths.append((prefix, owner))
    for key, child in sorted(node.children.items()):
        paths.extend(_descendant_claim_paths(child, (*prefix, key)))
    return paths


def _add_collision(
    collisions: list[SessionCollision],
    path: tuple[str, ...],
    accepted_owner: str | None,
    rejected_owner: str,
    reason: str,
) -> None:
    collision = SessionCollision(
        path=path,
        accepted_owner=accepted_owner,
        rejected_owner=rejected_owner,
        reason=reason,
    )
    if collision not in collisions:
        collisions.append(collision)


def _policy_owner_by_path(
    policies: Mapping[str, SettingPolicy],
) -> list[tuple[tuple[str, ...], str]]:
    owners: list[tuple[tuple[str, ...], str]] = []
    for policy in policies.values():
        if (
            policy.canonical_path is None
            or policy.lifetime not in {SettingLifetime.ADDON_GLOBAL, SettingLifetime.ADDON_PERSONA}
        ):
            continue
        owners.append((policy.canonical_path, policy.owner))
    return owners


def _path_matches(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    if len(pattern) != len(path):
        return False
    for pattern_part, path_part in zip(pattern, path):
        if pattern_part.startswith("{") and pattern_part.endswith("}"):
            continue
        if pattern_part != path_part:
            return False
    return True


def _explicit_owner_for_path(
    policy_owners: list[tuple[tuple[str, ...], str]],
    path: tuple[str, ...],
) -> str | None:
    matches = [owner for pattern, owner in policy_owners if _path_matches(pattern, path)]
    unique = sorted(set(matches))
    if len(unique) == 1:
        return unique[0]
    return None


def _resolve_claim_node(
    path: tuple[str, ...],
    existing_value: Any,
    node: _ClaimNode,
    policy_owners: list[tuple[tuple[str, ...], str]],
    collisions: list[SessionCollision],
) -> Any:
    explicit_owner = _explicit_owner_for_path(policy_owners, path)
    scalar_claims = _sorted_scalar_claims(node)
    has_children = bool(node.children)
    existing_present = existing_value is not _MISSING

    if scalar_claims and has_children:
        if explicit_owner is not None:
            explicit_scalar = next(
                (value for owner, value in scalar_claims if owner == explicit_owner),
                _MISSING,
            )
            if explicit_scalar is not _MISSING:
                for owner, _value in scalar_claims:
                    if owner != explicit_owner:
                        _add_collision(
                            collisions,
                            path,
                            explicit_owner,
                            owner,
                            "rejected conflicting addon scalar claim in favor of declared owner",
                        )
                for child_key, child in sorted(node.children.items()):
                    for descendant_path, owner in _descendant_claim_paths(child, (*path, child_key)):
                        _add_collision(
                            collisions,
                            descendant_path,
                            explicit_owner,
                            owner,
                            "rejected nested addon claim because declared owner controls the ancestor path",
                        )
                return copy.deepcopy(explicit_scalar)

        for owner, _value in scalar_claims:
            _add_collision(
                collisions,
                path,
                None,
                owner,
                "conflicting addon scalar claim overlaps nested addon state",
            )
        for child_key, child in sorted(node.children.items()):
            for descendant_path, owner in _descendant_claim_paths(child, (*path, child_key)):
                _add_collision(
                    collisions,
                    descendant_path,
                    None,
                    owner,
                    "nested addon claim overlaps a scalar ancestor claim",
                )
        return copy.deepcopy(existing_value) if existing_present else _MISSING

    if scalar_claims:
        if explicit_owner is not None:
            explicit_claim = next(
                ((owner, value) for owner, value in scalar_claims if owner == explicit_owner),
                None,
            )
            if explicit_claim is not None:
                for owner, _value in scalar_claims:
                    if owner != explicit_owner:
                        _add_collision(
                            collisions,
                            path,
                            explicit_owner,
                            owner,
                            "rejected conflicting addon leaf in favor of declared owner",
                        )
                return copy.deepcopy(explicit_claim[1])

        unique_values = {repr(value) for _owner, value in scalar_claims}
        if len(unique_values) == 1:
            return copy.deepcopy(scalar_claims[0][1])

        for owner, _value in scalar_claims:
            _add_collision(
                collisions,
                path,
                None,
                owner,
                "conflicting addon leaf with no declared owner",
            )
        return copy.deepcopy(existing_value) if existing_present else _MISSING

    if has_children:
        if existing_present and not isinstance(existing_value, Mapping):
            for child_key, child in sorted(node.children.items()):
                for descendant_path, owner in _descendant_claim_paths(child, (*path, child_key)):
                    _add_collision(
                        collisions,
                        descendant_path,
                        None,
                        owner,
                        "nested addon claim cannot replace an existing scalar value",
                    )
            return copy.deepcopy(existing_value)

        base = copy.deepcopy(dict(existing_value)) if isinstance(existing_value, Mapping) else {}
        applied = False
        for key, child in sorted(node.children.items()):
            child_path = (*path, key)
            current = base.get(key, _MISSING)
            resolved = _resolve_claim_node(
                child_path,
                current,
                child,
                policy_owners,
                collisions,
            )
            if resolved is _MISSING:
                continue
            base[key] = resolved
            applied = True
        if base or (existing_present and isinstance(existing_value, Mapping)) or applied:
            return base
    return copy.deepcopy(existing_value) if existing_present else _MISSING


def resolve_config_values(
    payload: Mapping[str, Any],
    policies: Mapping[str, SettingPolicy],
    phase: RestorePhase | None = None,
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    document = dict(payload or {})
    for key, policy in policies.items():
        if phase is not None and policy.restore_phase is not phase:
            continue
        related_policies = _related_policies(policy, document, policies)
        if len(related_policies) > 1:
            sources = []
            for related in related_policies:
                sources.extend(related.legacy_sources)
            ordered_sources = sorted(
                sources,
                key=lambda item: (item.priority, len(item.path), item.path),
                reverse=True,
            )
        else:
            ordered_sources = sorted(
                policy.legacy_sources,
                key=lambda item: (item.priority, len(item.path), item.path),
            )
        for source in ordered_sources:
            value = _source_value(document, source.path)
            if value is _MISSING:
                continue
            resolved[key] = value
            break
    return resolved


def canonicalize_session(
    existing: Mapping[str, Any],
    config_values: Mapping[str, Any],
    addon_contributions: tuple[AddonSessionContribution, ...] | list[AddonSessionContribution],
    policies: Mapping[str, SettingPolicy],
) -> SessionMergeResult:
    payload = with_grouped_ditto_settings(existing)
    # A disabled addon supplies no live policies, but its legacy aliases still
    # need ownership and removal after their values have been preserved above.
    policies = {**policies_for_keys(flatten_ditto_settings(existing)), **policies}
    migrated_aliases: list[tuple[str, ...]] = []
    seen_aliases: set[tuple[str, ...]] = set()
    removal_policies: list[SettingPolicy] = list(policies.values())
    seen_policy_keys = {policy.key for policy in removal_policies}
    for key in set(payload).union(str(item) for item in config_values):
        extra = policy_for_key(str(key))
        if extra is None or extra.key in seen_policy_keys:
            continue
        if any(
            policy.canonical_path is not None
            and policy.canonical_path == extra.canonical_path
            for policy in removal_policies
        ):
            removal_policies.append(extra)
            seen_policy_keys.add(extra.key)

    for policy in removal_policies:
        if policy.canonical_path is None:
            root_path = (policy.key,)
            if _nested_delete(payload, root_path) and root_path not in seen_aliases:
                seen_aliases.add(root_path)
                migrated_aliases.append(root_path)
        for source in policy.legacy_sources:
            if not source.remove_after_save:
                continue
            if source.path == policy.canonical_path:
                continue
            if _nested_delete(payload, source.path) and source.path not in seen_aliases:
                seen_aliases.add(source.path)
                migrated_aliases.append(source.path)

    for key, policy in sorted(
        policies.items(),
        key=lambda item: (len(item[1].canonical_path or ()), item[0]),
    ):
        resolved_path = _resolve_canonical_path(policy, payload, config_values)
        if resolved_path is None or policy.lifetime in _EXCLUDED_LIFETIMES:
            continue
        if key not in config_values:
            continue
        _nested_set(payload, resolved_path, sanitize_session_value(config_values.get(key)))

    collisions: list[SessionCollision] = []
    claim_root = _claim_node()
    for contribution in addon_contributions:
        _collect_claims(claim_root, contribution.payload, contribution.addon_id)
    policy_owners = _policy_owner_by_path(policies)
    for key, child in sorted(claim_root.children.items()):
        resolved = _resolve_claim_node(
            (key,),
            payload.get(key, _MISSING),
            child,
            policy_owners,
            collisions,
        )
        if resolved is _MISSING:
            continue
        payload[key] = resolved
    collisions.sort(key=lambda item: (item.path, item.accepted_owner or "", item.rejected_owner, item.reason))

    for policy in policies.values():
        for source in policy.legacy_sources:
            if len(source.path) == 1 and source.path != policy.canonical_path:
                assert _nested_get(payload, source.path) is _MISSING

    return SessionMergeResult(
        payload=payload,
        migrated_aliases=tuple(migrated_aliases),
        collisions=tuple(collisions),
    )


__all__ = [
    "AddonSessionContribution",
    "SessionCollision",
    "SessionMergeResult",
    "canonicalize_session",
    "resolve_config_values",
]
