"""Register Ditto through the existing avatar-provider contract."""
from core.addons.base import BaseAddon
from core.avatar_runtime import AvatarRuntimeContext
from addons.ditto_avatar.adapter import DittoAdapter
from addons.ditto_avatar.service import get_service
from addons.ditto_avatar.session_schema import flatten_ditto_settings


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.controller = get_service(context)
        context.services.register('ditto_resources', self.controller,
                                  metadata={'kind': 'runtime_resource'})
        self._avatar_service = context.capabilities.avatar
        if self._avatar_service is not None:
            self._avatar_service.register_provider(provider_id='ditto', label='Ditto',
                description='Prepared Ditto avatars with local desktop playback at 25 FPS.', order=225,
                factory=lambda construction_input: DittoAdapter(self.controller, construction_input),
                construction_input_type=AvatarRuntimeContext,
                metadata={'kind': 'avatar', 'native_qml': True, 'local_only': True})

    def invoke_capability(self, capability, payload=None):
        data = dict(payload or {})
        if capability == 'runtime.available_pack_emotion_names':
            return self.controller.available_pack_emotion_names(data.get('default_names', ()))
        if capability == 'runtime.preview.current_state':
            return self.controller.preview_state()
        if capability == 'runtime.pipeline_snapshot':
            return self.controller.pipeline_snapshot()
        if capability == 'runtime.ditto.subscribe':
            return self.controller.changes.subscribe(data.get('callback'))
        if capability == 'runtime.ditto.snapshot':
            return self.controller.snapshot()
        if capability == 'runtime.ditto.update':
            return self.controller.update(str(data.get('key') or ''), data.get('value'))
        if capability == 'runtime.ditto.action':
            if data.get('action') == 'delete_package':
                try:
                    return self.controller.action('delete_package', data.get('payload'))
                except Exception as error:
                    return {'ok':False, 'error':str(error)}
            return self.controller.action(str(data.get('action') or ''), data.get('payload'))
        return None

    def export_session_state(self):
        return self.controller.settings()

    export_preset_state = export_session_state

    def import_session_state(self, payload):
        self.controller.restore_settings(flatten_ditto_settings(payload))

    import_preset_state = import_session_state

    def shutdown(self):
        service = getattr(self, '_avatar_service', None)
        if service is not None:
            service.unregister_provider('ditto')
        controller = getattr(self, 'controller', None)
        if controller:
            controller.unload()
