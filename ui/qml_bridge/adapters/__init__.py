"""Native QML adapters for addon and runtime surfaces."""

from ui.qml_bridge.adapters.ai_presence import build_ai_presence_adapter
from ui.qml_bridge.adapters.audio_story_mode import build_audio_story_mode_adapter
from ui.qml_bridge.adapters.buddy_chat import build_buddy_chat_adapter
from ui.qml_bridge.adapters.chatterbox import build_chatterbox_adapter
from ui.qml_bridge.adapters.chatterbox_multilingual import (
    build_chatterbox_multilingual_adapter,
)
from ui.qml_bridge.adapters.chat_replay import build_chat_replay_adapter
from ui.qml_bridge.adapters.clipboard_source import build_clipboard_source_adapter
from ui.qml_bridge.adapters.companion_orb import build_companion_orb_adapter
from ui.qml_bridge.adapters.corsair_visual_instrument import (
    build_corsair_visual_instrument_adapter,
)
from ui.qml_bridge.adapters.discord_voice_bridge import (
    build_discord_voice_bridge_adapter,
)
from ui.qml_bridge.adapters.elevenlabs_tts import build_elevenlabs_tts_adapter
from ui.qml_bridge.adapters.gemini_tts import build_gemini_tts_adapter
from ui.qml_bridge.adapters.hotkeys import HotkeysNativeAdapter
from ui.qml_bridge.adapters.identity_artifacts import build_identity_artifacts_adapter
from ui.qml_bridge.adapters.main_chat_remote import build_main_chat_remote_adapter
from ui.qml_bridge.adapters.mock_heart_rate import build_mock_heart_rate_adapter
from ui.qml_bridge.adapters.multi_persona_roleplay import (
    build_multi_persona_roleplay_adapter,
)
from ui.qml_bridge.adapters.musetalk_avatar import build_musetalk_avatar_adapter
from ui.qml_bridge.adapters.musetalk_preprocess import build_musetalk_preprocess_adapter
from ui.qml_bridge.adapters.pockettts import build_pockettts_adapter
from ui.qml_bridge.adapters.pockettts_multilingual import (
    build_pockettts_multilingual_adapter,
)
from ui.qml_bridge.adapters.rag_context import build_rag_context_adapter
from ui.qml_bridge.adapters.screen_source import build_screen_source_adapter
from ui.qml_bridge.adapters.scenic_avatar import build_scenic_avatar_adapter
from ui.qml_bridge.adapters.spotify_sense import build_spotify_sense_adapter
from ui.qml_bridge.adapters.supervisors import build_supervisor_adapters
from ui.qml_bridge.adapters.user_identity import build_user_identity_adapter
from ui.qml_bridge.adapters.vseeface_avatar import build_vseeface_avatar_adapter
from ui.qml_bridge.adapters.visual_reply_core import build_visual_reply_core_adapter
from ui.qml_bridge.adapters.visual_story import build_visual_story_adapter
from ui.qml_bridge.adapters.web_intelligence import build_web_intelligence_adapter
from ui.qml_bridge.adapters.webcam_source import build_webcam_source_adapter

__all__ = [
    "HotkeysNativeAdapter",
    "build_identity_artifacts_adapter",
    "build_ai_presence_adapter",
    "build_audio_story_mode_adapter",
    "build_buddy_chat_adapter",
    "build_chatterbox_adapter",
    "build_chatterbox_multilingual_adapter",
    "build_chat_replay_adapter",
    "build_clipboard_source_adapter",
    "build_companion_orb_adapter",
    "build_corsair_visual_instrument_adapter",
    "build_discord_voice_bridge_adapter",
    "build_elevenlabs_tts_adapter",
    "build_gemini_tts_adapter",
    "build_main_chat_remote_adapter",
    "build_mock_heart_rate_adapter",
    "build_multi_persona_roleplay_adapter",
    "build_musetalk_avatar_adapter",
    "build_musetalk_preprocess_adapter",
    "build_pockettts_adapter",
    "build_pockettts_multilingual_adapter",
    "build_rag_context_adapter",
    "build_screen_source_adapter",
    "build_scenic_avatar_adapter",
    "build_spotify_sense_adapter",
    "build_supervisor_adapters",
    "build_user_identity_adapter",
    "build_vseeface_avatar_adapter",
    "build_visual_reply_core_adapter",
    "build_visual_story_adapter",
    "build_web_intelligence_adapter",
    "build_webcam_source_adapter",
]
