"""Native command/snapshot boundary for the Scenic creator."""
from copy import deepcopy
import threading
from ui.qml_bridge.native_registry import NativeSurfaceAdapter
from ui.qml_bridge.native_contracts import NativeControl,NativeControlKind,NativeSurface

class ScenicCreatorNativeAdapter(NativeSurfaceAdapter):
    def __init__(self, application, *, persist=None, can_edit=lambda: True):
        super().__init__('scenic_pack_creator_tab','nc.scenic_pack_creator')
        self.application,self.persist,self.can_edit=application,persist,can_edit
        self._lock=threading.RLock()
        self._state=dict(available=True,busy=False,packs=[],images=[],selected='',name='',revision=0,status='Open a pack or create one.',error='')

    def _invoke(self, capability, payload=None):
        result=self.application.addons.invoke_addon_capability(self.addon_id,capability,dict(payload or {}))
        if not result.accepted:raise ValueError(str(getattr(result.failure,'message','Scenic creator is unavailable. Enable its addon first.')))
        return result.value

    def snapshot(self):
        with self._lock:state=deepcopy(self._state)
        return NativeSurface(self.surface_id,'Scenic Pack Creator',self.addon_id,('Editor',),(
            NativeControl('scenic_creator_state','Scenic creator state',NativeControlKind.DISPLAY,'Editor',value=state,metadata={'presentationHidden':True}),
            NativeControl('scenic_creator_command','Edit Scenic pack',NativeControlKind.ACTION,'Editor'),
            NativeControl('scenic_creator_select_runtime','Select for Scenic',NativeControlKind.ACTION,'Editor',metadata={'execution':'ui'}),
        ))

    def pack_catalog(self):
        with self._lock:return deepcopy(self._state.get('packs',[]))

    def set_value(self,control_id,value):raise KeyError('Scenic creator state is read-only. Use an editor action.')

    def trigger_with_payload(self,control_id,payload):
        data=dict(payload or {})
        if control_id=='scenic_creator_select_runtime':
            if not self.can_edit():raise ValueError('Stop the chat engine before changing the selected Scenic pack.')
            identity=str(data.get('pack_id') or '')
            if identity not in {row['id'] for row in self.pack_catalog()}:raise ValueError('Refresh and choose an existing Scenic pack.')
            previous=self.application.config.get('scenic_pack_id','')
            result=self.application.config.update('scenic_pack_id',identity)
            if not result.accepted:raise ValueError('Could not select this Scenic pack.')
            try:
                if self.persist is not None and self.persist() is False:raise ValueError('Could not save the selected Scenic pack.')
            except Exception:
                self.application.config.update('scenic_pack_id',previous);raise
            self.changed.emit();return
        if control_id!='scenic_creator_command':raise KeyError('Unknown Scenic creator action.')
        action=str(data.get('action') or '')
        if action not in ('refresh','select') and not self.can_edit():raise ValueError('Stop the chat engine before editing Scenic packs.')
        with self._lock:self._state.update(busy=True,error='')
        self.changed.emit()
        try:
            result=self._invoke('scenic.creator.command',dict(action=action,payload=data.get('payload',{})))
            with self._lock:self._state=deepcopy(result['state'])
            if not result.get('ok'):raise ValueError(result.get('error') or 'Could not edit the pack.')
        finally:
            with self._lock:self._state['busy']=False
            self.changed.emit()

def build_scenic_pack_creator_adapter(application,*,persist=None,can_edit=lambda:True):
    return ScenicCreatorNativeAdapter(application,persist=persist,can_edit=can_edit)
