"""Explicit ownership of process-wide startup environment configuration."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
import locale
import os
from pathlib import Path
import subprocess
from typing import Protocol


class AudioSegmentTarget(Protocol):
    converter: str
    ffmpeg: str
    ffprobe: str


class SubprocessTarget(Protocol):
    Popen: Callable[..., object]


@dataclass(frozen=True, slots=True)
class FfmpegTools:
    ffmpeg: Path
    ffprobe: Path


class StartupProcessEnvironment:
    """Apply the finite process-wide configuration required during startup."""

    def __init__(
        self,
        application_root: Path,
        *,
        environ: MutableMapping[str, str] | None = None,
        os_name: str | None = None,
        path_separator: str | None = None,
        preferred_encoding: Callable[[], str | None] | None = None,
        subprocess_target: SubprocessTarget | None = None,
    ) -> None:
        self._application_root = Path(application_root)
        self._environ = os.environ if environ is None else environ
        self._os_name = os.name if os_name is None else os_name
        self._path_separator = os.pathsep if path_separator is None else path_separator
        self._preferred_encoding = (
            (lambda: locale.getpreferredencoding(False))
            if preferred_encoding is None
            else preferred_encoding
        )
        self._subprocess_target = (
            subprocess if subprocess_target is None else subprocess_target
        )

    def apply(self, audio_segment: AudioSegmentTarget) -> FfmpegTools | None:
        """Apply both startup effects and return any discovered FFmpeg tools."""

        tools = self.configure_audio_segment(audio_segment)
        self.install_safe_text_mode_popen()
        return tools

    def configure_audio_segment(
        self,
        audio_segment: AudioSegmentTarget,
    ) -> FfmpegTools | None:
        """Discover bundled FFmpeg tools and configure pydub's target class."""

        tools = self._discover_ffmpeg_tools()
        if tools is None:
            return None

        bin_path = tools.ffmpeg.parent
        current_path = self._environ.get("PATH", "")
        bin_text = str(bin_path)
        path_parts = [
            part for part in current_path.split(self._path_separator) if part
        ]
        if bin_text not in path_parts:
            self._environ["PATH"] = bin_text + (
                self._path_separator + current_path if current_path else ""
            )

        audio_segment.converter = str(tools.ffmpeg)
        audio_segment.ffmpeg = str(tools.ffmpeg)
        audio_segment.ffprobe = str(tools.ffprobe)
        return tools

    def install_safe_text_mode_popen(self) -> None:
        """Install idempotent text decoding defaults on the subprocess target."""

        current_popen = self._subprocess_target.Popen
        if getattr(current_popen, "_nc_safe_text_mode_popen", False):
            return

        is_windows = self._os_name == "nt"
        preferred_encoding = self._preferred_encoding

        def _safe_text_mode_popen(*args, **kwargs):
            text_mode = bool(kwargs.get("text")) or bool(
                kwargs.get("universal_newlines")
            )
            if text_mode and kwargs.get("errors") is None:
                kwargs["errors"] = "replace"
            if text_mode and kwargs.get("encoding") is None and is_windows:
                kwargs["encoding"] = preferred_encoding() or "utf-8"
            return current_popen(*args, **kwargs)

        _safe_text_mode_popen._nc_safe_text_mode_popen = True
        self._subprocess_target.Popen = _safe_text_mode_popen

    def _discover_ffmpeg_tools(self) -> FfmpegTools | None:
        configured_bin = str(self._environ.get("NC_FFMPEG_BIN", "") or "").strip()
        bin_path = (
            Path(configured_bin)
            if configured_bin
            else self._application_root / "tools" / "ffmpeg" / "bin"
        )
        executable_suffix = ".exe" if self._os_name == "nt" else ""
        tools = FfmpegTools(
            ffmpeg=bin_path / f"ffmpeg{executable_suffix}",
            ffprobe=bin_path / f"ffprobe{executable_suffix}",
        )
        if not tools.ffmpeg.exists() or not tools.ffprobe.exists():
            return None
        return tools
