"""Widget-independent Dry Run and performance-profile operations."""

from __future__ import annotations

from typing import Any, Callable, Mapping

import dry_run


DRY_RUN_MAX_RESPONSE_TOKENS = 600
_DRY_RUN_SESSION_GUARD_KEYS = frozenset(
    {"limit_response_length", "max_response_tokens"}
)


class NativeDryRunController:
    """Own QML Dry Run actions over the established dry_run module."""

    def __init__(
        self,
        application_facade: Any,
        *,
        persist: Callable[[], object] | None = None,
    ) -> None:
        self._application = application_facade
        self._persist = persist
        self._last_candidate_index: int | None = None

    def _config(self) -> dict[str, object]:
        return dict(self._application.config.snapshot().values)

    def _apply_settings(
        self,
        settings: Mapping[str, object] | None,
        *,
        allowed_keys: set[str] | frozenset[str] | None = None,
    ) -> tuple[str, ...]:
        current = self._config()
        updates = {
            str(key): value
            for key, value in dict(settings or {}).items()
            if str(key) in current
            and (allowed_keys is None or str(key) in allowed_keys)
        }
        if not updates:
            return ()
        result = self._application.config.update_many(updates)
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Could not apply Dry Run settings."))
            )
        if callable(self._persist):
            self._persist()
        return tuple(updates)

    def _append_preview_log(self, message: str) -> None:
        self._application.addons.invoke_service_capability(
            "avatar_provider_registry",
            "runtime.preview.append_log",
            {"message": str(message or "")},
            provider_id="musetalk",
        )

    def _publish_event(
        self,
        event_name: str,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        result = self._application.addons.publish_event(event_name, payload)
        if not result.accepted and self._application.addons.manager_available():
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Could not publish runtime event."))
            )

    def start(self, target_samples: int, auto_replies: bool) -> dict[str, object]:
        config = self._config()
        target = max(1, min(100, int(target_samples)))
        self._publish_event("runtime.heavy_task_starting", {"source": "dry_run"})
        label = (
            f"{str(config.get('avatar_mode') or 'none')} / "
            f"{str(config.get('tts_backend') or 'none')} / "
            f"{'Stream' if bool(config.get('stream_mode', False)) else 'Non-stream'}"
        )
        status = dry_run.start_session(
            config,
            target_samples=target,
            label=label,
            auto_replies=bool(auto_replies),
        )
        self._apply_settings(
            {
                "limit_response_length": True,
                "max_response_tokens": DRY_RUN_MAX_RESPONSE_TOKENS,
            }
        )
        dry_run.log_event(
            "[DryRun] Native QML session armed "
            f"id={status.get('session_id')} profile={status.get('profile_key')} "
            f"target_samples={status.get('target_samples')} "
            f"max_tokens={DRY_RUN_MAX_RESPONSE_TOKENS}"
        )
        self._append_preview_log(
            "Dry Run session armed: "
            f"id={status.get('session_id')} target={status.get('target_samples')}"
        )
        self._publish_event(
            "dry_run_started",
            {
                "session_id": status.get("session_id"),
                "auto_mode": bool(status.get("auto_mode")),
            },
        )
        self._last_candidate_index = None
        self.synchronize()
        return dict(status)

    def stop(self, *, reason: str = "manual_stop") -> dict[str, object]:
        status = dry_run.stop_session(reason=str(reason or "manual_stop"))
        self._last_candidate_index = None
        if not status:
            return {}
        self._apply_settings(dict(status.get("config_snapshot") or {}))
        self._append_preview_log(
            "Dry Run session stopped: "
            f"id={status.get('session_id')} confidence={status.get('confidence')}"
        )
        self._publish_event(
            "dry_run_stopped",
            {
                "session_id": status.get("session_id"),
                "confidence": status.get("confidence"),
            },
        )
        return dict(status)

    def apply_recommendation(self) -> tuple[str, ...]:
        status = dry_run.get_status() or dry_run.get_latest_profile() or {}
        recommendation = dict(status.get("recommendation") or {})
        return self._apply_settings(dict(recommendation.get("settings") or {}))

    def load_profile(self, name: str) -> tuple[str, ...]:
        selected = str(name or "").strip()
        if not selected:
            return ()
        payload = dry_run.load_performance_profile(selected)
        if not payload:
            raise FileNotFoundError(f"Performance profile '{selected}' was not found.")
        changed = self._apply_settings(
            dict(payload.get("settings_to_apply") or {}),
            allowed_keys=dry_run.PERFORMANCE_PROFILE_APPLY_KEYS,
        )
        self._publish_event("performance_profile_loaded", {"name": selected})
        return changed

    def synchronize(self) -> dict[str, object]:
        """Apply one changed candidate and finalize a completed session once."""

        status = dict(dry_run.get_status() or {})
        if not status:
            self._last_candidate_index = None
            return {"active": False, "completed": False}
        if bool(status.get("active")) and not bool(status.get("complete")):
            candidate = dict(dry_run.get_current_candidate_settings() or {})
            candidate_index = candidate.get("index")
            if candidate and candidate_index != self._last_candidate_index:
                candidate_settings = {
                    str(key): value
                    for key, value in dict(candidate.get("settings") or {}).items()
                    if str(key) not in _DRY_RUN_SESSION_GUARD_KEYS
                }
                self._apply_settings(candidate_settings)
                self._last_candidate_index = int(candidate_index or 0)
                dry_run.log_event(
                    "[DryRun] Native QML applying candidate "
                    f"label={candidate.get('label')}"
                )
            return {"active": True, "completed": False}
        if bool(status.get("active")) and bool(status.get("complete")):
            final_status = self.stop(reason="complete")
            return {
                "active": False,
                "completed": True,
                "status": final_status,
            }
        return {"active": False, "completed": bool(status.get("complete"))}


__all__ = ["DRY_RUN_MAX_RESPONSE_TOKENS", "NativeDryRunController"]
