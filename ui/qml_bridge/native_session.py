"""Atomic session persistence for the native QML application."""

from __future__ import annotations

import copy
import json
import os
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from addons.visual_reply.session_schema import with_flat_visual_reply_settings
from core.ai_presence_session_schema import with_flat_ai_presence_settings
from core.chat_runtime_session_schema import (
    with_flat_chat_runtime_settings,
)
from core.chunking_session_schema import with_flat_chunking_settings
from core.companion_orb_session_schema import with_flat_companion_orb_settings
from core.dry_run_session_schema import with_flat_dry_run_settings
from core.musetalk_session_schema import with_flat_musetalk_settings
from core.persona_session_schema import with_flat_persona_settings
from core.runtime_controls_session_schema import with_flat_runtime_controls_settings
from core.sensory_session_schema import with_flat_sensory_settings
from core.session_document import (
    AddonSessionContribution,
    canonicalize_session,
    resolve_config_values,
)
from core.session_persistence_contract import (
    ACTIVE_CHAT_PROVIDER,
    ACTIVE_VISUAL_REPLY_PROVIDER,
    RestorePhase,
    policies_for_keys,
    policy_for_key,
    sanitize_session_value,
)
from core.stt_session_schema import with_flat_stt_runtime_settings
from core.tts_session_schema import with_flat_tts_runtime_settings
from core.ua_companion_orb_session_schema import with_flat_ua_companion_orb_settings
from core.ui_session_schema import with_flat_ui_settings


_FLATTENERS = (
    with_flat_chat_runtime_settings,
    with_flat_sensory_settings,
    with_flat_ai_presence_settings,
    with_flat_companion_orb_settings,
    with_flat_ua_companion_orb_settings,
    with_flat_musetalk_settings,
    with_flat_stt_runtime_settings,
    with_flat_tts_runtime_settings,
    with_flat_visual_reply_settings,
    with_flat_persona_settings,
    with_flat_runtime_controls_settings,
    with_flat_dry_run_settings,
    with_flat_chunking_settings,
    with_flat_ui_settings,
)

_PROCESS_LOCK = threading.RLock()

_LEGACY_PERSISTED_PROVIDER_CREDENTIAL_PATHS = (
    ("visual_reply_provider_settings", "{provider}", "api_key"),
    ("visual_reply", "providers", "settings", "{provider}", "api_key"),
    ("gemini_tts_preview_settings", "api_key"),
    ("tts_runtime", "gemini_tts_preview", "settings", "api_key"),
    ("elevenlabs_tts_settings", "api_key"),
    ("tts_runtime", "elevenlabs_tts", "settings", "api_key"),
)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _nested_set(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = payload
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = copy.deepcopy(value)


def _resolve_policy_path(
    policy,
    *,
    current_values: Mapping[str, Any],
    legacy_values: Mapping[str, Any],
) -> tuple[str, ...] | None:
    canonical_path = getattr(policy, "canonical_path", None)
    if canonical_path is None:
        return None
    resolved: list[str] = []
    for part in canonical_path:
        if part == ACTIVE_CHAT_PROVIDER:
            provider = str(
                current_values.get("chat_provider")
                or legacy_values.get("chat_provider")
                or ""
            ).strip().lower()
            if not provider:
                return None
            resolved.append(provider)
            continue
        if part == ACTIVE_VISUAL_REPLY_PROVIDER:
            provider = str(
                current_values.get("visual_reply_provider")
                or legacy_values.get("visual_reply_provider")
                or ""
            ).strip().lower()
            if not provider:
                return None
            resolved.append(provider)
            continue
        resolved.append(part)
    return tuple(resolved)


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
            continue
        break
    return True


def _sanitize_legacy_combined_export(payload: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_session_value(
        _plain(payload),
        allowed_credential_paths=_LEGACY_PERSISTED_PROVIDER_CREDENTIAL_PATHS,
    )
    return dict(sanitized) if isinstance(sanitized, Mapping) else {}


def _sanitize_legacy_setting(key: str, value: Any) -> Any:
    allowed_paths: tuple[tuple[str, ...], ...] = ()
    if key == "visual_reply_provider_settings":
        allowed_paths = (("{provider}", "api_key"),)
    elif key in {"gemini_tts_preview_settings", "elevenlabs_tts_settings"}:
        allowed_paths = (("api_key",),)
    return sanitize_session_value(
        value,
        allowed_credential_paths=allowed_paths,
    )


def _replace_chat_provider_api_keys(
    payload: Mapping[str, Any],
    config_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Overlay only explicit chat-provider API keys after general redaction."""

    updated = copy.deepcopy(dict(payload or {}))
    chat_runtime = updated.get("chat_runtime")
    if not isinstance(chat_runtime, dict):
        chat_runtime = {}
        updated["chat_runtime"] = chat_runtime
    persisted_settings = chat_runtime.get("provider_settings")
    if not isinstance(persisted_settings, dict):
        persisted_settings = {}
        chat_runtime["provider_settings"] = persisted_settings

    for values in persisted_settings.values():
        if isinstance(values, dict):
            values.pop("api_key", None)

    configured_settings = config_values.get("chat_provider_settings")
    if isinstance(configured_settings, Mapping):
        for raw_provider, raw_values in configured_settings.items():
            provider = str(raw_provider or "").strip().lower()
            if not provider or not isinstance(raw_values, Mapping):
                continue
            api_key = str(raw_values.get("api_key") or "").strip()
            if not api_key:
                continue
            provider_values = persisted_settings.get(provider)
            if not isinstance(provider_values, dict):
                provider_values = {}
                persisted_settings[provider] = provider_values
            provider_values["api_key"] = api_key

    if not persisted_settings:
        chat_runtime.pop("provider_settings", None)
    if not chat_runtime:
        updated.pop("chat_runtime", None)
    return updated


class NativeSessionStore:
    """Persist native QML edits without consulting a widget hierarchy."""

    def __init__(
        self,
        app_root: str | Path,
        application_facade: Any,
        *,
        read_only: bool = False,
    ) -> None:
        self._path = Path(app_root).resolve() / "qt_session.json"
        self._application = application_facade
        self._read_only = bool(read_only)

    @property
    def path(self) -> Path:
        return self._path

    def first_run(self) -> bool:
        with _PROCESS_LOCK:
            payload = self._read_existing()
        updates = resolve_config_values(payload, policies_for_keys(("first_run",)))
        return bool(updates.get("first_run", not self._path.exists()))

    def restore_config_phase(self, phase: RestorePhase) -> bool:
        return self._restore_policies(None, phase)

    def restore_config_values(self, keys: set[str] | frozenset[str]) -> bool:
        """Restore a narrow set of persisted UI preferences into runtime config."""
        requested = {str(key or "").strip() for key in keys if str(key or "").strip()}
        if not requested:
            return True
        return self._restore_policies(policies_for_keys(requested), None)

    def addon_import_payload(self) -> dict[str, Any]:
        with _PROCESS_LOCK:
            payload = self._read_existing()
        return self._compatibility_payload(payload)

    def save(self, *, config_overrides: Mapping[str, Any] | None = None) -> bool:
        if self._read_only:
            return False
        with _PROCESS_LOCK:
            existing = self._read_existing()
            config_values = _plain(self._application.config.snapshot().values)
            if config_overrides is not None:
                config_values.update(_plain(config_overrides))
            config_values["first_run"] = False
            addon_contributions = self._addon_contributions(config_values=config_values)
            policies = policies_for_keys(config_values)
            policies.update(self._contribution_policies(addon_contributions))
            result = canonicalize_session(
                existing,
                config_values,
                addon_contributions,
                policies,
            )
            payload = _replace_chat_provider_api_keys(result.payload, config_values)
            self._atomic_write(payload)
        return True

    def _read_existing(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

    @staticmethod
    def _flatten(payload: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(payload or {})
        for transform in _FLATTENERS:
            result = dict(transform(result) or {})
        return result

    def _compatibility_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._flatten(_plain(payload))

    def _restore_policies(
        self,
        requested_policies: Mapping[str, Any] | None,
        phase: RestorePhase | None,
    ) -> bool:
        with _PROCESS_LOCK:
            payload = self._read_existing()
        compatibility = self._compatibility_payload(payload)
        policies = (
            dict(requested_policies)
            if requested_policies is not None
            else policies_for_keys(
                {
                    **compatibility,
                    **_plain(self._application.config.snapshot().values),
                }
            )
        )
        # Addon-owned imports validate their own selections and resolve package data.
        # Raw config restoration must not pre-seed or overwrite those projections.
        policies = {
            key: policy for key, policy in policies.items()
            if policy.restore_phase != RestorePhase.ADDON_IMPORT
        }
        updates = resolve_config_values(payload, policies, phase=phase)
        if not updates:
            return True
        result = self._application.config.update_many(_plain(updates))
        return bool(getattr(result, "accepted", False))

    def _addon_contributions(
        self,
        *,
        config_values: Mapping[str, Any] | None = None,
    ) -> tuple[AddonSessionContribution, ...]:
        provider = getattr(self._application, "addons", None)
        if provider is None:
            return ()
        exported = self._export_addon_payload(provider)
        if exported is None:
            return ()
        if isinstance(exported, tuple) and all(
            isinstance(item, AddonSessionContribution) for item in exported
        ):
            return exported
        if isinstance(exported, list) and all(
            isinstance(item, AddonSessionContribution) for item in exported
        ):
            return tuple(exported)
        if isinstance(exported, Mapping):
            return (
                AddonSessionContribution(
                    addon_id="core.addons.manager",
                    payload=self._canonicalize_legacy_addon_export(
                        exported,
                        config_values=config_values,
                    ),
                ),
            )
        return ()

    @staticmethod
    def _export_addon_payload(provider: Any) -> Any:
        contributions = getattr(provider, "export_session_state_contributions", None)
        if callable(contributions):
            result = contributions()
            accepted = getattr(result, "accepted", None)
            if accepted is not False:
                return getattr(result, "value", result)
        exporter = getattr(provider, "export_session_state", None)
        if not callable(exporter):
            return None
        result = exporter()
        accepted = getattr(result, "accepted", None)
        if accepted is False:
            return None
        return getattr(result, "value", result)

    def _contribution_policies(
        self,
        contributions: tuple[AddonSessionContribution, ...],
    ) -> dict[str, Any]:
        policies: dict[str, Any] = {}
        for contribution in contributions:
            for path in self._leaf_paths(contribution.payload):
                for key in self._candidate_policy_keys(path):
                    policy = policy_for_key(key)
                    canonical_path = getattr(policy, "canonical_path", None)
                    if policy is None or canonical_path is None:
                        continue
                    if not self._path_matches(canonical_path, path):
                        continue
                    policies.setdefault(key, policy)
        return policies

    @staticmethod
    def _leaf_paths(payload: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> tuple[tuple[str, ...], ...]:
        paths: list[tuple[str, ...]] = []
        for key, value in payload.items():
            path = (*prefix, str(key))
            if isinstance(value, Mapping) and value:
                paths.extend(NativeSessionStore._leaf_paths(value, path))
                continue
            paths.append(path)
        return tuple(paths)

    @staticmethod
    def _candidate_policy_keys(path: tuple[str, ...]) -> tuple[str, ...]:
        candidates: set[str] = set()
        if not path:
            return ()
        for index in range(len(path)):
            candidates.add("_".join(path[index:]))
        if len(path) >= 2:
            candidates.add(f"{path[0]}_{path[-1]}")
        return tuple(sorted(candidate for candidate in candidates if candidate))

    @staticmethod
    def _path_matches(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
        if len(pattern) != len(path):
            return False
        for expected, actual in zip(pattern, path):
            if expected.startswith("{") and expected.endswith("}"):
                continue
            if expected != actual:
                return False
        return True

    @staticmethod
    def _canonicalize_legacy_addon_export(
        payload: Mapping[str, Any],
        *,
        config_values: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        canonical = _sanitize_legacy_combined_export(payload)
        flat_values = dict(canonical)
        current_values = _plain(config_values or {})
        overlay_keys = {
            key
            for key in flat_values
            if getattr(policy_for_key(key), "canonical_path", None) is not None
        }
        policies = policies_for_keys(overlay_keys)
        for key, policy in sorted(
            policies.items(),
            key=lambda item: (len(item[1].canonical_path or ()), item[0]),
        ):
            resolved_path = _resolve_policy_path(
                policy,
                current_values=current_values,
                legacy_values=flat_values,
            )
            if resolved_path is None:
                continue
            if key in current_values:
                _nested_set(
                    canonical,
                    resolved_path,
                    _sanitize_legacy_setting(key, current_values[key]),
                )
                continue
            if key in flat_values:
                _nested_set(
                    canonical,
                    resolved_path,
                    _sanitize_legacy_setting(key, flat_values[key]),
                )
        for policy in policies.values():
            for source in policy.legacy_sources:
                if not source.remove_after_save or source.path == policy.canonical_path:
                    continue
                _nested_delete(canonical, source.path)
        return canonical

    def _atomic_write(self, payload: Mapping[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                handle.write(json.dumps(_plain(payload), indent=4, ensure_ascii=True))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = ["NativeSessionStore"]
