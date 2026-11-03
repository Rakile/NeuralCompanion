"""Tutorial narration with Chatterbox-first playback and Windows fallback."""

from __future__ import annotations

import base64
import os
import subprocess
import threading
from collections.abc import Callable, Mapping
from typing import Protocol


class _SpeechControl(Protocol):
    done: threading.Event

    def playback_receipt(self) -> object | None: ...

    def cancel(self, reason: str = "") -> bool: ...


class _Stoppable(Protocol):
    def stop(self) -> None: ...


class _WindowsSpeechHandle:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process

    @property
    def active(self) -> bool:
        return self._process.poll() is None

    def stop(self) -> None:
        if self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                pass

    def wait(self) -> int:
        """Wait only from the narration monitor worker, never the UI thread."""
        return self._process.wait()


class WindowsSapiSpeaker:
    """Launch Windows System.Speech without blocking the Qt event loop."""

    def speak(self, text: str) -> _WindowsSpeechHandle:
        content = str(text or "").strip()
        if not content:
            raise ValueError("Tutorial narration text is empty.")
        if os.name != "nt":
            raise RuntimeError("Windows TTS is only available on Windows.")
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        script = (
            "$bytes=[Convert]::FromBase64String('" + encoded + "');"
            "$text=[Text.Encoding]::UTF8.GetString($bytes);"
            "Add-Type -AssemblyName System.Speech;"
            "$speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "try{$speaker.Speak($text)}finally{$speaker.Dispose()}"
        )
        creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        return _WindowsSpeechHandle(process)


class TutorialNarrationController:
    """Own one tutorial narration request and its fallback lifecycle."""

    def __init__(
        self,
        *,
        primary_speak: Callable[[str, Mapping[str, object]], _SpeechControl],
        fallback_speak: Callable[[str], _Stoppable | object | None] | None = None,
    ) -> None:
        self._primary_speak = primary_speak
        self._fallback_speak = fallback_speak or WindowsSapiSpeaker().speak
        self._lock = threading.RLock()
        self._generation = 0
        self._primary_control: _SpeechControl | None = None
        self._fallback_handle: _Stoppable | None = None
        self._on_finished: Callable[[str], None] | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._primary_control is not None or self.fallback_active

    @property
    def fallback_active(self) -> bool:
        with self._lock:
            # Poll is non-blocking. A completed Windows process must not keep
            # suppressing normal playback ownership after narration has ended.
            if (self._fallback_handle is not None
                    and self._on_finished is None
                    and getattr(self._fallback_handle, "active", True) is False):
                self._fallback_handle = None
            return self._fallback_handle is not None

    def speak(self, text: str, runtime_config: Mapping[str, object],
              on_finished: Callable[[str], None] | None = None) -> None:
        content = str(text or "").strip()
        if not content:
            return
        self.stop()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._on_finished = on_finished
        config = dict(runtime_config or {})
        config["tts_backend"] = "chatterbox"
        try:
            control = self._primary_speak(content, config)
        except (OSError, RuntimeError, TypeError, ValueError):
            self._start_fallback(content, generation)
            return
        with self._lock:
            if generation != self._generation:
                self._cancel_control(control)
                return
            self._primary_control = control
        threading.Thread(
            target=self._monitor_primary,
            args=(control, content, generation),
            name="nc-tutorial-narration",
            daemon=True,
        ).start()

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            self._on_finished = None
            control = self._primary_control
            fallback = self._fallback_handle
            self._primary_control = None
            self._fallback_handle = None
        if control is not None:
            self._cancel_control(control)
        if fallback is not None:
            try:
                fallback.stop()
            except (OSError, RuntimeError):
                pass

    @staticmethod
    def _cancel_control(control: _SpeechControl) -> None:
        try:
            control.cancel("tutorial_speech_changed")
        except (AttributeError, RuntimeError):
            pass

    def _monitor_primary(
        self,
        control: _SpeechControl,
        text: str,
        generation: int,
    ) -> None:
        try:
            control.done.wait()
            receipt = control.playback_receipt()
            reason = str(getattr(receipt, "terminal_reason", "") or "")
        except (AttributeError, RuntimeError):
            reason = "backend_failed"
        with self._lock:
            if generation != self._generation or control is not self._primary_control:
                return
            self._primary_control = None
        if self._should_fallback(reason):
            self._start_fallback(text, generation)
        else:
            self._finish(generation, "completed" if reason.strip().lower() == "completed" else "interrupted")

    def _finish(self, generation: int, reason: str) -> None:
        with self._lock:
            if generation != self._generation:
                return
            callback = self._on_finished
            self._on_finished = None
        if callback is not None:
            try:
                callback(reason)
            except RuntimeError:
                # A queued Qt receiver may have been destroyed during shutdown.
                pass

    @staticmethod
    def _should_fallback(reason: str) -> bool:
        normalized = str(reason or "").strip().lower()
        if normalized == "completed":
            return False
        if any(token in normalized for token in ("skip", "cancel", "interrupt", "replace")):
            return False
        return not normalized or any(
            token in normalized
            for token in ("fail", "error", "unavailable", "missing", "backend")
        )

    def _start_fallback(self, text: str, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                return
        try:
            handle = self._fallback_speak(text)
        except (OSError, RuntimeError, TypeError, ValueError):
            self._finish(generation, "failed")
            return
        if handle is None or not callable(getattr(handle, "stop", None)):
            self._finish(generation, "failed")
            return
        with self._lock:
            if generation != self._generation:
                try:
                    handle.stop()
                except (OSError, RuntimeError):
                    pass
                return
            self._fallback_handle = handle
            monitor = self._on_finished is not None
        if monitor:
            threading.Thread(target=self._monitor_fallback, args=(handle, generation),
                             name="nc-tutorial-fallback", daemon=True).start()

    def _monitor_fallback(self, handle: _Stoppable, generation: int) -> None:
        wait = getattr(handle, "wait", None)
        try:
            result = wait() if callable(wait) else None
        except (OSError, RuntimeError):
            result = None
        with self._lock:
            if generation != self._generation or handle is not self._fallback_handle:
                return
            self._fallback_handle = None
        # Unobservable/custom fallback handles cannot certify completion.
        self._finish(generation, "completed" if result == 0 else "failed")


__all__ = ["TutorialNarrationController", "WindowsSapiSpeaker"]
