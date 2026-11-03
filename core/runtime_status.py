"""Read-only runtime status snapshots for UI shells and addon services.

This module intentionally has no dependency on ``engine.py``. Callers pass in
the config values and live flags they already own, which keeps Designer shell
preview code from waking heavy runtime imports just to describe current state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text if text else str(default or "")


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    """Compact, UI-facing view of the active runtime state."""

    lifecycle_state: str = "stopped"
    running: bool = False
    engine_connected: bool = False
    shell_mode: bool = False
    chat_provider: str = ""
    model_name: str = ""
    tts_backend: str = ""
    avatar_engine: str = ""
    input_mode: str = ""
    input_role: str = ""
    stream_mode: bool = False
    microphone_state: str = "idle"
    listening: bool = False
    recording: bool = False
    playback_paused: bool = False
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lifecycle_state": self.lifecycle_state,
            "running": self.running,
            "engine_connected": self.engine_connected,
            "shell_mode": self.shell_mode,
            "chat_provider": self.chat_provider,
            "model_name": self.model_name,
            "tts_backend": self.tts_backend,
            "avatar_engine": self.avatar_engine,
            "input_mode": self.input_mode,
            "input_role": self.input_role,
            "stream_mode": self.stream_mode,
            "microphone_state": self.microphone_state,
            "listening": self.listening,
            "recording": self.recording,
            "playback_paused": self.playback_paused,
            "source": self.source,
            "metadata": dict(self.metadata or {}),
        }

    def status_line(self) -> str:
        lifecycle = "running" if self.running else self.lifecycle_state or "stopped"
        shell = "shell" if self.shell_mode else "runtime"
        model = self.model_name or "no model"
        provider = self.chat_provider or "no provider"
        tts = self.tts_backend or "no tts"
        avatar = self.avatar_engine or "no avatar"
        return (
            f"{shell}: {lifecycle} | chat {provider} / {model} | "
            f"tts {tts} | avatar {avatar} | mic {self.microphone_state}"
        )


def build_runtime_status_snapshot(
    config: Mapping[str, Any] | None = None,
    *,
    running: bool = False,
    engine_connected: bool = False,
    shell_mode: bool = False,
    lifecycle_state: str | None = None,
    listening: bool = False,
    recording: bool = False,
    playback_paused: bool = False,
    source: str = "runtime",
    metadata: Mapping[str, Any] | None = None,
) -> RuntimeStatusSnapshot:
    """Build a normalized runtime status snapshot from config plus live flags."""

    cfg = dict(config or {})
    if recording:
        microphone_state = "recording"
    elif listening:
        microphone_state = "listening"
    else:
        microphone_state = "idle"
    resolved_lifecycle = _text(lifecycle_state, "running" if running else "stopped")
    return RuntimeStatusSnapshot(
        lifecycle_state=resolved_lifecycle,
        running=bool(running),
        engine_connected=bool(engine_connected),
        shell_mode=bool(shell_mode),
        chat_provider=_text(cfg.get("chat_provider", "lmstudio"), "lmstudio"),
        model_name=_text(cfg.get("model_name", "")),
        tts_backend=_text(cfg.get("tts_backend", "chatterbox"), "chatterbox"),
        avatar_engine=_text(cfg.get("avatar_mode", cfg.get("avatar_engine", "none")), "none"),
        input_mode=_text(cfg.get("input_mode", "")),
        input_role=_text(cfg.get("input_message_role", cfg.get("input_role", ""))),
        stream_mode=bool(cfg.get("stream_mode", False)),
        microphone_state=microphone_state,
        listening=bool(listening),
        recording=bool(recording),
        playback_paused=bool(playback_paused),
        source=_text(source, "runtime"),
        metadata=dict(metadata or {}),
    )
