"""LiquidAI's native settings surface. Installation progress is signalled."""
from dataclasses import replace
from collections import Counter

from addons.liquidai_tts.config import DEFAULTS, LANGUAGES, normalize_settings
from addons.liquidai_tts.voices import matching_voices
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import NativeChoice, NativeControl, NativeControlKind, NativeSurface


class LiquidAINativeAdapter(RuntimeConfigNativeAdapter):
    def __init__(self, application, surface, persist=None):
        super().__init__(application,surface,persist=persist)
        self._setup_checked=False
        self._setup_busy=False
        self._setup={'status':'Not checked'}
        self._setup_message=''
        self._available=True
        self._voices=[]

    def _notify(self):
        self._revision+=1
        try: self.changed.emit()
        except RuntimeError: pass  # The UI may already have closed during cancellation.

    def _invoke(self, capability, payload=None):
        result=self._application.addons.invoke_addon_capability(self.addon_id,capability,payload or {})
        if not result.accepted:
            failure=getattr(result,'failure',None)
            raise RuntimeError(str(getattr(failure,'message','LiquidAI action failed.')))
        value=result.value
        if not isinstance(value,dict):
            raise RuntimeError('LiquidAI addon is unavailable. Enable it in Addons, then check setup again.')
        if not value.get('ok',False):
            self._setup=dict(value.get('setup') or self._setup)
            raise RuntimeError(str(value.get('error') or 'LiquidAI setup did not complete.'))
        return value

    def _check(self):
        self._setup_checked=True
        try:
            result=self._invoke('runtime.liquidai.status')
            self._setup=dict(result['setup'])
            self._voices=list(result.get('voices') or [])
            self._available=True
        except Exception as error:
            self._setup={'status':'Unavailable','error':str(error)}
            self._available=False

    def snapshot(self):
        # Check once when first opened, then only on explicit actions/path edits.
        if not self._setup_checked: self._check()
        surface=super().snapshot()
        status=str(self._setup.get('status') or 'Not installed')
        error=str(self._setup.get('error') or '')
        if error: status+=': '+error
        values={'liquidai_setup_status':self._setup_message or status,
                'liquidai_managed_python':str(self._setup.get('python') or 'Automatic managed environment'),
                'liquidai_managed_model':str(self._setup.get('model_dir') or 'Automatic managed model folder')}
        controls=[]
        for control in surface.controls:
            if control.id in values: control=replace(control,value=values[control.id])
            if control.id=='liquidai_tts_voice':
                choices=[NativeChoice(value='female',label='Female'),NativeChoice(value='male',label='Male')]
                names=Counter(v['name'].casefold() for v in self._voices)
                for voice in self._voices:
                    name=voice['name']
                    if names[name.casefold()]>1 or name.casefold() in ('female','male'):
                        name+=f" ({voice['id'][8:]})"
                    choices.append(NativeChoice(value=voice['id'],label=name))
                selected=str(control.value)
                matches=matching_voices(selected,self._voices)
                if len(matches)==1: selected=matches[0]['id']
                if selected not in {str(c.value) for c in choices}:
                    choices.append(NativeChoice(value=selected,label=selected+' (not found)'))
                control=replace(control,value=selected,choices=tuple(choices))
                self._controls[control.id]=control
            if control.id in {'liquidai_tts_voice','liquidai_tts_language'}:
                control=replace(control,metadata={**dict(control.metadata), 'providerAvailable':self._available})
            if control.id in {'liquidai_install','liquidai_check_setup','liquidai_refresh_voices'}:
                control=replace(control,enabled=not self._setup_busy)
            if control.id=='liquidai_cancel_setup': control=replace(control,enabled=self._setup_busy)
            if control.id in DEFAULTS and self._setup_busy: control=replace(control,enabled=False)
            controls.append(control)
        return replace(surface,controls=tuple(controls))

    def set_value(self, control_id, value):
        if control_id not in DEFAULTS: raise KeyError(control_id)
        if self._setup_busy: raise RuntimeError('Wait for LiquidAI setup to finish before changing settings.')
        values={key:self._application.config.get(key,default) for key,default in DEFAULTS.items()}
        values[control_id]=value
        normalized=normalize_settings(values)
        if control_id=='liquidai_tts_voice':
            self.snapshot()
            matches=matching_voices(normalized[control_id],self._voices)
            if len(matches)==1: normalized[control_id]=matches[0]['id']
        if control_id in {'liquidai_tts_python','liquidai_tts_model_dir'}: self._setup_checked=False
        super().set_value(control_id,normalized[control_id])

    def _progress(self, message):
        self._setup_message=str(message)
        self._notify()

    def trigger(self, control_id):
        if control_id in {'liquidai_check_setup','liquidai_refresh_voices'}:
            if self._setup_busy: raise RuntimeError('Wait for LiquidAI setup to finish before refreshing.')
            self._setup_message=''; self._check(); self._notify(); return
        if control_id=='liquidai_cancel_setup':
            self._invoke('runtime.liquidai.cancel_setup')
            self._setup_message='Cancelling LiquidAI setup…'; self._notify(); return
        if control_id!='liquidai_install': raise KeyError(control_id)
        if self._setup_busy: raise RuntimeError('LiquidAI setup is already running.')
        self._setup_busy=True; self._setup_message='Starting LiquidAI setup…'; self._notify()
        try:
            self._setup=dict(self._invoke('runtime.liquidai.setup',{'progress_callback':self._progress})['setup'])
            self._setup_message=''
        except Exception as error:
            self._setup_message=str(error)
            raise
        finally:
            self._setup_busy=False; self._setup_checked=True; self._notify()


def build_liquidai_adapter(application_facade, *, persist=None):
    K=NativeControlKind
    def setting(key,label,kind,section,help_text,**options):
        return NativeControl(key,label,kind,section,description=help_text,default_value=DEFAULTS[key],**options)
    controls=(
        NativeControl('liquidai_intro','LiquidAI LFM3 Audio',K.DISPLAY,'Overview',
            description='Local text-to-speech with built-in and installed voice adapters. NC still controls speech chunks, playback and avatar lip-sync.',
            default_value='Built-in and installed voices • mono 24 kHz • dedicated environment and process'),
        setting('liquidai_tts_language','Speech language',K.CHOICE,'Voice',
            'Choose the language/accent spoken by LiquidAI. This does not translate text; use text written in the selected language.',
            choices=tuple(NativeChoice(value=x,label=x) for x in LANGUAGES)),
        setting('liquidai_tts_voice','Voice',K.CHOICE,'Voice',
            'Female and Male use built-in voices. Put compatible voice LoRA folders in models, then refresh voices. Use the language the adapter was trained for. The shared reference-audio setting does not apply.',
            choices=(NativeChoice(value='female',label='Female'),NativeChoice(value='male',label='Male'))),
        NativeControl('liquidai_refresh_voices','Refresh voices',K.ACTION,'Voice',
            description='Look for added or removed voice adapter folders in models and refresh this list.'),
        setting('liquidai_tts_seed','Seed (0 = random)',K.INTEGER,'Generation',
            'Zero chooses a fresh seed for each speech chunk. A fixed seed makes voice variation more repeatable for the same text and setup.',minimum=0,maximum=2147483647,step=1),
        setting('liquidai_tts_temperature','Audio temperature',K.NUMBER,'Generation',
            'Controls variation in generated speech. Lower values are steadier; higher values vary more and may reduce clarity. Start at 1.0.',minimum=.05,maximum=2,step=.05),
        setting('liquidai_tts_top_k','Audio top-k (0 = off)',K.INTEGER,'Generation',
            'Limits each audio choice to the most likely candidates. Lower values constrain variation. Zero disables this filter; the default is 128.',minimum=0,maximum=2016,step=1),
        setting('liquidai_tts_repetition_penalty','Audio repetition penalty',K.NUMBER,'Generation',
            'Discourages repeated audio patterns. 1.0 disables the penalty; start with 1.1. Excessive penalties may distort speech.',minimum=1,maximum=3,step=.05),
        setting('liquidai_tts_max_tokens','Generation budget',K.INTEGER,'Generation',
            'Maximum generation slots for one NC speech chunk. A slot can contain a text token or about 80 ms of audio. Increase for unusually long chunks; reaching the limit reports an error instead of silently clipping speech.',minimum=32,maximum=4096,step=32),
        setting('liquidai_tts_prewarm_on_start','Prewarm when chat starts',K.BOOLEAN,'Generation',
            'Load the worker and model, then run discarded speech synthesis when NC starts chat. When progressive audio is enabled, also warm that path. Disabled: load on the first speech request. Stopping chat releases the worker.'),
        setting('liquidai_tts_stream_audio','Experimental progressive audio',K.BOOLEAN,'Generation',
            'Opt in to start local No Avatar, Scenic, Ditto or MuseTalk speech while LiquidAI is still generating. Scenic switches still images when each speech chunk starts, without waiting for animation frames. Ditto waits for matching animation frames and holds speech if rendering falls behind. MuseTalk uses its existing frame files and clock. Phone, Discord and file-based addon routes keep completed audio. Disabled by default.'),
        setting('liquidai_tts_startup_buffer_seconds','Progressive startup audio (seconds)',K.NUMBER,'Generation',
            'Sound to buffer before progressive local playback starts. More audio gives extra underrun protection; this is audio duration, not a fixed wait. Used only when experimental progressive audio is enabled.',minimum=.2,maximum=2.,step=.1),
        NativeControl('liquidai_setup_status','Managed setup status',K.DISPLAY,'Setup'),
        NativeControl('liquidai_managed_python','Managed Python',K.DISPLAY,'Setup'),
        NativeControl('liquidai_managed_model','Managed model',K.DISPLAY,'Setup'),
        NativeControl('liquidai_check_setup','Check setup',K.ACTION,'Setup',description='Refresh the managed environment/model status. Normal UI updates do not repeatedly check files.'),
        NativeControl('liquidai_install','Install / Repair',K.ACTION,'Setup',description='Create LiquidAI’s private Python environment and download the pinned model (about 4.2 GB). Requires installed Python 3.12 and internet. NC’s main environment and external overrides are preserved.'),
        NativeControl('liquidai_cancel_setup','Cancel setup',K.ACTION,'Setup',description='Stop the active LiquidAI installer and its owned subprocesses. Downloaded files can be reused by a later repair.'),
        setting('liquidai_tts_python','Python executable override',K.TEXT,'Advanced',
            'Leave blank to use the managed LiquidAI environment. An override must contain compatible LiquidAI dependencies. Install / Repair updates only the managed environment.'),
        setting('liquidai_tts_model_dir','Model folder override',K.TEXT,'Advanced',
            'Leave blank for the managed pinned LFM3 Audio checkpoint. An override needs all model and codec files plus the matching PINNED_REVISION marker. Install / Repair preserves external folders.'),
    )
    surface=NativeSurface('liquidai_tts_tab','LiquidAI','nc.liquidai_tts',
        ('Overview','Voice','Generation','Setup','Advanced'),controls,
        description='LiquidAI text-to-speech with built-in and installed voices in an isolated runtime.')
    return LiquidAINativeAdapter(application_facade,surface,persist=persist)
