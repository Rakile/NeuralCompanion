"""Native-only Voice Studio addon lifecycle and explicit capabilities."""
from core.addons.base import BaseAddon
from addons.voice_studio.native_controller import VoiceStudioController


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._controller = VoiceStudioController(context)

    def invoke_capability(self, capability, payload=None):
        payload = dict(payload or {})
        if capability == 'voice_studio.soundscape_client':
            return self._controller.soundscape_client()
        if capability == 'voice_studio.chat_characters':
            with self._controller._lock:
                if not hasattr(self, '_character_jobs'):
                    from addons.voice_studio.character_jobs import CharacterVoiceJobs
                    self._character_jobs = CharacterVoiceJobs(self._controller)
            return self._character_jobs.invoke(payload)
        if capability == 'voice_studio.snapshot':
            return self._controller.snapshot()
        if capability == 'voice_studio.set':
            return self._controller.set_value(str(payload.get('key', '')), payload.get('value'))
        if capability == 'voice_studio.action':
            return self._controller.action(str(payload.get('action', '')), payload.get('payload'))
        return None

    def shutdown(self):
        jobs = getattr(self, '_character_jobs', None)
        if jobs is not None:
            jobs.jobs.close()
        self._controller.close()
