from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WebcamSupervisorCapabilities:
    sensory_targets: object
    shell_session: object


@dataclass(frozen=True, slots=True)
class WebcamSupervisorInitialization:
    logger: object
    ui: object
    manifest: object
    capabilities: WebcamSupervisorCapabilities
