"""Qt presentation and effect audio; command calls only enqueue addon work."""
from PySide6 import QtCore
from collections import deque
from ui.qml_bridge.native_contracts import NativeSurface
from ui.qml_bridge.native_registry import NativeSurfaceAdapter
from .sounds import SOUND_KEYS
from .midi_profiles import profile_options


class ChessNativeAdapter(NativeSurfaceAdapter):
    stateChanged=QtCore.Signal()
    onlineModeChanged=QtCore.Signal()

    def __init__(self, application):
        super().__init__('companion_chess_tab','nc.companion_chess')
        self.application=application
        self._state={}
        self._online_mode=False
        self._seen_event=None
        self._played_events=deque(maxlen=256)
        self._player=None
        self._timer=QtCore.QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def _invoke(self, capability, payload):
        response=self.application.addons.invoke_addon_capability(self.addon_id,capability,payload)
        return response.value if response.accepted else None

    @QtCore.Property('QVariantMap',notify=stateChanged)
    def state(self): return self._state

    @QtCore.Property(bool, notify=onlineModeChanged)
    def onlineMode(self) -> bool:
        return self._online_mode

    @onlineMode.setter
    def onlineMode(self, value: bool) -> None:
        if self._online_mode != value:
            self._online_mode = value
            self.onlineModeChanged.emit()

    @QtCore.Property('QStringList',constant=True)
    def soundKeys(self): return list(SOUND_KEYS)

    @QtCore.Property('QVariantList', constant=True)
    def hardwareModels(self) -> list[dict[str, str]]:
        return profile_options()

    def snapshot(self):
        return NativeSurface(self.surface_id,'Companion Chess',self.addon_id,('Play',),(),
                             description='Chess with your favourite persona.',revision=self._state.get('revision',0))

    @QtCore.Slot()
    def _poll(self):
        try: state=self._invoke('chess.snapshot',{}) or {}
        except (RuntimeError,AttributeError): state={}
        if state!=self._state:
            event=state.get('sound_event') or {}
            event_id=event.get('id','')
            prefs=state.get('preferences') or {}
            self._state=state
            if self._seen_event is not None and event_id and event_id not in self._played_events and prefs.get('sound_enabled',True):
                self.previewSound(event.get('key',''))
            if event_id and event_id not in self._played_events: self._played_events.append(event_id)
            self._seen_event=event_id
            if not state or state.get('closed'): self.stopSound()
            self.stateChanged.emit()
            self.changed.emit()

    @QtCore.Slot(str,'QVariantMap',result=bool)
    def command(self, action, fields):
        values=dict(fields)
        if isinstance(values.get('path'),str) and values['path'].startswith('file:'):
            values['path']=QtCore.QUrl(values['path']).toLocalFile()
        try:
            result=self._invoke('chess.command',dict(values,action=action))
            return bool(result and result.get('accepted'))
        except (RuntimeError,AttributeError,ValueError): return False

    @QtCore.Slot(str)
    def previewSound(self, key):
        prefs=self._state.get('preferences') or {}
        path=(prefs.get('sounds') or {}).get(key,'')
        if not path: return
        try:
            if self._player is None:
                from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
                self._player=QMediaPlayer(self)
                output=QAudioOutput(self)
                self._player.setAudioOutput(output)
            self._player.stop()
            self._player.audioOutput().setVolume(float(prefs.get('volume',.65)))
            self._player.setSource(QtCore.QUrl.fromLocalFile(path))
            self._player.play()
        except (ImportError,RuntimeError): pass

    @QtCore.Slot()
    def stopSound(self):
        if self._player is not None: self._player.stop()
