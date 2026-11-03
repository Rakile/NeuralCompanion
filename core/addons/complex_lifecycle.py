"""Typed initialization projections for host-owned complex addon code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BuddyChatCapabilities:
    runtime_config: object
    providers: object
    conversation: object
    visual_reply: object
    prompt_refinement: object


@dataclass(frozen=True, slots=True)
class MultiPersonaRoleplayCapabilities:
    runtime_config: object
    providers: object
    conversation: object
    speech: object
    playback: object
    accepted_turns: object
    visual_reply: object
    story: object
    memory: object
    replay: object
    prompt_refinement: object
    music_commands: object
    dialogs: object
    shell: object
    diagnostics: object


@dataclass(frozen=True, slots=True)
class CompanionOrbCapabilities:
    runtime_config: object
    sensory_targets: object
    speech: object
    playback: object
    accepted_turns: object
    realtime: object
    user_image_turns: object
    shell: object
    tutorials: object
    orb_runtime: object


@dataclass(frozen=True, slots=True)
class AiPresenceCapabilities:
    runtime_config: object


@dataclass(frozen=True, slots=True)
class ScenicAvatarCapabilities:
    runtime_config: object
    dialogs: object
    shell: object
    avatar: object
    host_operations: object


@dataclass(frozen=True, slots=True)
class AudioStoryCapabilities:
    runtime_config: object
    audio_story: object
    providers: object
    prompt_refinement: object
    visual_reply: object
    story: object
    dialogs: object
    shell: object
    visual_commands: object


@dataclass(frozen=True, slots=True)
class MainChatRemoteCapabilities:
    runtime_config: object
    runtime_status: object
    interaction: object
    engine_lifecycle: object
    replay: object
    file_transcription: object
    visual_reply: object
    user_image_turns: object
    shell: object
    remote_commands: object
    llm_status: object
    tts_status: object
    avatar_status: object
    host: object


@dataclass(frozen=True, slots=True)
class BuddyChatInitialization:
    addon_id: str
    app_root: Path
    logger: object
    ui: object
    storage: object
    tasks: object
    ui_dispatcher: object
    capabilities: BuddyChatCapabilities


@dataclass(frozen=True, slots=True)
class MultiPersonaRoleplayInitialization:
    addon_id: str
    addon_version: str
    app_root: Path
    addon_root: Path
    logger: object
    ui: object
    storage: object
    tasks: object
    ui_dispatcher: object
    events: object
    capabilities: MultiPersonaRoleplayCapabilities


@dataclass(frozen=True, slots=True)
class CompanionOrbInitialization:
    addon_id: str
    app_root: Path
    logger: object
    ui: object
    storage: object
    tasks: object
    ui_dispatcher: object
    events: object
    capabilities: CompanionOrbCapabilities


@dataclass(frozen=True, slots=True)
class AiPresenceInitialization:
    addon_id: str
    app_root: Path
    logger: object
    ui: object
    storage: object
    tasks: object
    ui_dispatcher: object
    capabilities: AiPresenceCapabilities


@dataclass(frozen=True, slots=True)
class ScenicAvatarInitialization:
    addon_id: str
    app_root: Path
    logger: object
    ui: object
    storage: object
    tasks: object
    ui_dispatcher: object
    capabilities: ScenicAvatarCapabilities


@dataclass(frozen=True, slots=True)
class AudioStoryInitialization:
    addon_id: str
    app_root: Path
    logger: object
    ui: object
    storage: object
    tasks: object
    ui_dispatcher: object
    events: object
    shell_preview: bool
    capabilities: AudioStoryCapabilities


@dataclass(frozen=True, slots=True)
class MainChatRemoteInitialization:
    addon_id: str
    app_root: Path
    logger: object
    ui: object
    storage: object
    tasks: object
    ui_dispatcher: object
    events: object
    capabilities: MainChatRemoteCapabilities
