"""Addon-local installers for the optional Web Search MCP servers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.addons.installer_process import InstallerResult, run_owned_installer


@dataclass(frozen=True, slots=True)
class WebSearchServerPaths:
    root: Path
    node_root: Path
    searxng_launcher: Path
    duck_venv: Path
    duck_python: Path
    duck_launcher: Path


def server_paths(install_root: Path) -> WebSearchServerPaths:
    """Return platform-correct paths without creating anything."""

    root = Path(install_root).resolve()
    node_root = root / "searxng_mcp"
    duck_venv = root / "duckduckgo_mcp"
    if os.name == "nt":
        searxng_launcher = node_root / "node_modules" / ".bin" / "mcp-searxng.cmd"
        duck_python = duck_venv / "Scripts" / "python.exe"
        duck_launcher = duck_venv / "Scripts" / "duckduckgo-mcp-server.exe"
    else:
        searxng_launcher = node_root / "node_modules" / ".bin" / "mcp-searxng"
        duck_python = duck_venv / "bin" / "python"
        duck_launcher = duck_venv / "bin" / "duckduckgo-mcp-server"
    return WebSearchServerPaths(
        root=root,
        node_root=node_root,
        searxng_launcher=searxng_launcher,
        duck_venv=duck_venv,
        duck_python=duck_python,
        duck_launcher=duck_launcher,
    )


def _hidden_process_options() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def _result_message(result: InstallerResult) -> str:
    if result.cancelled:
        return "Installation was cancelled."
    if result.timed_out:
        return "Installation timed out."
    if result.returncode not in {0, None}:
        detail = str(result.output_tail or "").strip().splitlines()
        suffix = f" {detail[-1]}" if detail else ""
        return f"Installer exited with code {result.returncode}.{suffix}".strip()
    return ""


class WebSearchServerInstaller:
    """Install both server launchers under the addon's private runtime folder."""

    def __init__(
        self,
        install_root: Path,
        *,
        tasks: Any,
        environ: Mapping[str, str] | None = None,
        executable_resolver: Callable[[str], str | None] = shutil.which,
        installer_runner: Callable[..., InstallerResult] = run_owned_installer,
        process_factory: Callable[..., Any] = subprocess.Popen,
        python_executable: str = sys.executable,
    ) -> None:
        self.paths = server_paths(install_root)
        self._tasks = tasks
        self._environ = dict(os.environ if environ is None else environ)
        self._resolve_executable = executable_resolver
        self._installer_runner = installer_runner
        self._process_factory = process_factory
        self._python_executable = str(python_executable)

    def _resolve(self, *names: str) -> str:
        for name in names:
            value = self._resolve_executable(name)
            if value:
                return str(value)
        return ""

    def _run(self, command: tuple[str, ...], cancel: Any) -> InstallerResult:
        def process_factory(argv, **kwargs):
            options = dict(kwargs)
            options["env"] = dict(self._environ)
            options.update(_hidden_process_options())
            return self._process_factory(argv, **options)

        return self._installer_runner(
            command,
            tasks=self._tasks,
            cancel=cancel,
            timeout_seconds=900.0,
            process_factory=process_factory,
        )

    @staticmethod
    def _cancelled(cancel: Any) -> bool:
        return bool(getattr(cancel, "cancelled", False))

    def install(
        self,
        cancel: Any,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        report: dict[str, dict[str, object]] = {}
        notify = progress if callable(progress) else lambda _message: None
        self.paths.root.mkdir(parents=True, exist_ok=True)

        notify("Installing the SearXNG MCP bridge")
        report["mcp_searxng"] = self._install_searxng(cancel)
        if self._cancelled(cancel):
            return self._report(report, cancelled=True)

        notify("Installing the DuckDuckGo MCP server")
        report["duckduckgo_mcp"] = self._install_duckduckgo(cancel)
        return self._report(report, cancelled=self._cancelled(cancel))

    def _install_searxng(self, cancel: Any) -> dict[str, object]:
        if self.paths.searxng_launcher.is_file():
            return {
                "installed": True,
                "message": "SearXNG MCP bridge is already installed.",
            }
        npm = self._resolve("npm.cmd", "npm")
        if not npm:
            return {
                "installed": False,
                "message": "Node.js/npm is required to install the optional SearXNG MCP bridge.",
            }
        self.paths.node_root.mkdir(parents=True, exist_ok=True)
        result = self._run(
            (
                npm,
                "install",
                "--no-audit",
                "--no-fund",
                "--prefix",
                str(self.paths.node_root),
                "mcp-searxng",
            ),
            cancel,
        )
        error = _result_message(result)
        installed = self.paths.searxng_launcher.is_file()
        return {
            "installed": installed,
            "message": (
                "SearXNG MCP bridge installed. A SearXNG search instance is still required."
                if installed
                else error or "npm completed but the SearXNG MCP launcher was not created."
            ),
        }

    def _install_duckduckgo(self, cancel: Any) -> dict[str, object]:
        if not self.paths.duck_python.is_file():
            result = self._run(
                (
                    self._python_executable,
                    "-m",
                    "venv",
                    str(self.paths.duck_venv),
                ),
                cancel,
            )
            error = _result_message(result)
            if error or not self.paths.duck_python.is_file():
                return {
                    "installed": False,
                    "message": error or "Python could not create the DuckDuckGo server environment.",
                }
        if self._cancelled(cancel):
            return {"installed": False, "message": "Installation was cancelled."}
        result = self._run(
            (
                str(self.paths.duck_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "--upgrade",
                "duckduckgo-mcp-server[browser]",
            ),
            cancel,
        )
        error = _result_message(result)
        installed = self.paths.duck_launcher.is_file()
        return {
            "installed": installed,
            "message": (
                "DuckDuckGo MCP server installed in its private environment."
                if installed
                else error or "pip completed but the DuckDuckGo MCP launcher was not created."
            ),
        }

    @staticmethod
    def _report(
        servers: Mapping[str, Mapping[str, object]],
        *,
        cancelled: bool,
    ) -> dict[str, object]:
        values = {key: dict(value) for key, value in servers.items()}
        installed = sum(bool(value.get("installed")) for value in values.values())
        total = len(values)
        if cancelled:
            message = "Web Search server installation was cancelled."
        elif installed == total and total:
            message = "Both Web Search server launchers are installed."
        elif installed:
            message = f"Web Search server installation completed partially ({installed}/{total})."
        else:
            message = "No Web Search server launcher could be installed."
        return {
            "ok": installed == total and total > 0,
            "partial": 0 < installed < total,
            "cancelled": bool(cancelled),
            "installed_count": installed,
            "server_count": total,
            "message": message,
            "servers": values,
        }


__all__ = [
    "WebSearchServerInstaller",
    "WebSearchServerPaths",
    "server_paths",
]
