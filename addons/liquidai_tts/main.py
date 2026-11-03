"""LiquidAI speech provider: discovery is lightweight; setup is explicit."""
import threading

from core.addons.base import BaseAddon
from addons.liquidai_tts.config import DEFAULTS, normalize_settings
from addons.liquidai_tts.config import managed_paths
from addons.liquidai_tts.voices import discover_voice_adapters
from addons.liquidai_tts.installer import LiquidAIInstaller
from addons.liquidai_tts.service import LiquidAITTSService


class Addon(BaseAddon):
    SERVICE_NAME = 'liquidai'

    def initialize(self, context):
        super().initialize(context)
        self._runtime_config=context.capabilities.runtime_config
        self.service=LiquidAITTSService(context)
        self.installer=LiquidAIInstaller(context.paths.app_root)
        self._setup_lock=threading.Lock()
        self._setup_cancel=threading.Event()
        self._setup_busy=False
        self._closing=False
        context.capabilities.speech_providers.register_provider('liquidai',self.service,metadata={
            'kind':'tts','backend_id':'liquidai','label':'LiquidAI','provider':'local',
            'supports_streaming':False,'supports_incremental_audio':True,'preferred_for_streaming':False,
            'preferred_for_non_streaming':False,'supports_voice_reference':False,
            'supported_speech_tags':[],'runtime_overhead_gib':5.0})
        context.logger.info('LiquidAI TTS provider initialized; model setup and loading are deferred.')

    def invoke_capability(self, capability, payload=None):
        name=str(capability or '').strip(); request=dict(payload or {})
        if name=='runtime.estimate_overhead_gib': return 5.0
        if name in {'runtime.collect_config','runtime.status_snapshot','runtime.refresh_resource_widgets',
                    'runtime.update_config_from_widgets'}:
            values=normalize_settings(request.get('runtime_config'))
            if name=='runtime.update_config_from_widgets':
                for key,value in values.items(): self._runtime_config.update(key,value)
            return values
        if name=='runtime.restart_sensitive_widgets':
            return ['liquidai_tts_python','liquidai_tts_model_dir']
        if name=='runtime.liquidai.status':
            paths=managed_paths(self.context.paths.app_root)
            model_dir=self._runtime_config.get('liquidai_tts_model_dir','') or paths.model_dir
            return {'ok':True,'setup':self.installer.snapshot(),
                    'voices':discover_voice_adapters(paths.root/'models',model_dir)}
        if name=='runtime.liquidai.cancel_setup':
            self._setup_cancel.set(); self.installer.cancel()
            return {'ok':True}
        if name=='runtime.liquidai.setup':
            with self._setup_lock:
                if self._closing: return {'ok':False,'error':'NC is closing.'}
                if self._setup_busy: return {'ok':False,'error':'LiquidAI setup is already running.'}
                self._setup_busy=True
                self._setup_cancel=threading.Event()
            reserved=False
            try:
                self.service.begin_setup(); reserved=True
                callback=request.get('progress_callback')
                if not callable(callback): callback=lambda message: self.context.logger.info('LiquidAI setup: %s',message)
                setup=self.installer.install(self._setup_cancel,callback)
                return {'ok':bool(setup.get('installed')),'setup':setup,
                        'error':str(setup.get('error') or '')}
            except Exception as error:
                return {'ok':False,'error':str(error),'setup':self.installer.snapshot()}
            finally:
                if reserved: self.service.end_setup()
                with self._setup_lock: self._setup_busy=False
        return None

    def shutdown(self):
        with self._setup_lock:
            self._closing=True
            self._setup_cancel.set()
        self.installer.cancel()
        self.service.close()
