from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScreenSourceCapabilities:
    runtime_config: object
    sensory_targets: object
    shell_session: object


@dataclass(frozen=True, slots=True)
class ScreenSourceInitialization:
    logger: object
    ui: object
    manifest: object
    app_root: object
    capabilities: ScreenSourceCapabilities
