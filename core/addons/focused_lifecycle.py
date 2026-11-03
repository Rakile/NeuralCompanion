"""Typed initialization projections for host-owned focused addon UI code."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChatterboxTtsCapabilities:
    runtime_config: object
    shell_session: object
    speech_providers: object
    diagnostics: object


@dataclass(frozen=True, slots=True)
class ChatterboxTtsInitialization:
    logger: object
    ui: object
    capabilities: ChatterboxTtsCapabilities


@dataclass(frozen=True, slots=True)
class ChatterboxMultilingualCapabilities:
    runtime_config: object
    shell_session: object
    speech_providers: object


@dataclass(frozen=True, slots=True)
class ChatterboxMultilingualInitialization:
    logger: object
    ui: object
    tasks: object
    ui_dispatcher: object
    capabilities: ChatterboxMultilingualCapabilities


@dataclass(frozen=True, slots=True)
class PocketTtsCapabilities:
    runtime_config: object
    shell_session: object
    speech_providers: object
    dialogs: object


@dataclass(frozen=True, slots=True)
class PocketTtsInitialization:
    logger: object
    ui: object
    paths: object
    capabilities: PocketTtsCapabilities


@dataclass(frozen=True, slots=True)
class PocketTtsMultilingualCapabilities:
    runtime_config: object
    shell_session: object
    speech_providers: object


@dataclass(frozen=True, slots=True)
class PocketTtsMultilingualInitialization:
    logger: object
    ui: object
    paths: object
    tasks: object
    ui_dispatcher: object
    capabilities: PocketTtsMultilingualCapabilities


@dataclass(frozen=True, slots=True)
class HotkeysCapabilities:
    hotkeys: object


@dataclass(frozen=True, slots=True)
class HotkeysInitialization:
    logger: object
    ui: object
    tasks: object
    capabilities: HotkeysCapabilities


@dataclass(frozen=True, slots=True)
class VisualStorySettingsCapabilities:
    runtime_config: object
    shell_session: object
    visual_reply: object


@dataclass(frozen=True, slots=True)
class VisualStorySettingsInitialization:
    logger: object
    ui: object
    capabilities: VisualStorySettingsCapabilities


@dataclass(frozen=True, slots=True)
class SpotifySenseCapabilities:
    music: object
    prompt_refinement: object
    runtime_config: object
    sensory_targets: object


@dataclass(frozen=True, slots=True)
class SpotifySenseInitialization:
    logger: object
    ui: object
    storage: object
    tasks: object
    ui_dispatcher: object
    events: object
    capabilities: SpotifySenseCapabilities


@dataclass(frozen=True, slots=True)
class SupervisorCapabilities:
    prompt_refinement: object
    sensory_targets: object


@dataclass(frozen=True, slots=True)
class ClipboardSupervisorInitialization:
    addon_id: str
    logger: object
    ui: object
    tasks: object
    ui_dispatcher: object
    capabilities: SupervisorCapabilities


@dataclass(frozen=True, slots=True)
class ScreenSupervisorInitialization:
    addon_id: str
    logger: object
    ui: object
    tasks: object
    ui_dispatcher: object
    capabilities: SupervisorCapabilities


@dataclass(frozen=True, slots=True)
class VisualReplyCapabilities:
    story: object
    visual_reply: object


@dataclass(frozen=True, slots=True)
class VisualReplyInitialization:
    logger: object
    ui: object
    capabilities: VisualReplyCapabilities


@dataclass(frozen=True, slots=True)
class IdentityArtifactsInitialization:
    logger: object
    ui: object
    app_root: object
    storage: object
    dialogs: object
    shell_session: object
    runtime_config: object
    runtime_embedding: object
    runtime_delete_transaction: object
    runtime_derivative_purge: object
    runtime_artifact_controller: object = None
    subject_classifier: object = None
    index_build_request: object = None


@dataclass(frozen=True, slots=True)
class VseefaceAvatarInitialization:
    logger: object


@dataclass(frozen=True, slots=True)
class ChatSessionPlayerCapabilities:
    dialogs: object
    replay: object
    runtime_config: object
    shell: object


@dataclass(frozen=True, slots=True)
class ChatSessionPlayerInitialization:
    logger: object
    ui: object
    capabilities: ChatSessionPlayerCapabilities


@dataclass(frozen=True, slots=True)
class ClipboardSourceCapabilities:
    shell_session: object
    sensory_targets: object
    runtime_config: object
    user_image_turns: object
    replay: object


@dataclass(frozen=True, slots=True)
class ClipboardSourceInitialization:
    logger: object
    ui: object
    manifest_root: object
    capabilities: ClipboardSourceCapabilities


@dataclass(frozen=True, slots=True)
class HeartRateBehaviorCapabilities:
    sensory_targets: object
    shell_session: object


@dataclass(frozen=True, slots=True)
class HeartRateBehaviorInitialization:
    addon_id: str
    logger: object
    ui: object
    manifest_root: object
    capabilities: HeartRateBehaviorCapabilities


@dataclass(frozen=True, slots=True)
class MockHeartRateCapabilities:
    sensory_targets: object


@dataclass(frozen=True, slots=True)
class MockHeartRateInitialization:
    logger: object
    ui: object
    services: object
    events: object
    manifest_root: object
    capabilities: MockHeartRateCapabilities


@dataclass(frozen=True, slots=True)
class RagContextInitialization:
    logger: object
    ui: object
    storage: object
