"""Conversation viewport and safe handoff from main chat to a Local room."""
from copy import deepcopy

from PySide6 import QtCore


_START_ACTIONS = frozenset(('discord_local_room_start', 'discord_local_room_new_conversation'))
_ACTIVE_PHASES = frozenset(('starting', 'running', 'stopping'))


class RoomConversationSession(QtCore.QObject):
    changed = QtCore.Signal()
    # View registration can refresh state during a source binding evaluation.
    # Only a real source switch should notify that binding again.
    sourceChanged = QtCore.Signal()
    draftChanged = QtCore.Signal()
    errorRaised = QtCore.Signal(str)

    def __init__(self, runtime_controller, chat_guard, snapshot_provider, dispatch,
                 reset_main, show_conversation, show_room_controls, parent=None):
        super().__init__(parent)
        self._runtime = runtime_controller
        self._guard = chat_guard
        self._snapshot_provider = snapshot_provider
        self._dispatch = dispatch
        self._reset_main = reset_main
        self._show_conversation = show_conversation
        self._show_room_controls = show_room_controls
        self._source = 'main'
        self._state = {}
        self._snapshot_failed = False
        self._draft = ''
        self._sending = None
        self._room_key = 'local'
        self._viewports = {}
        self._drafts = {}
        self._conversation_ids = {}
        self._confirmation = dict(active=False, action='', error='')
        self._pending = None
        self._closed = False
        self._visible_views = set()
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setInterval(350)
        self._refresh_timer.timeout.connect(self.refresh)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)
        self._guard.changed.connect(self._guard_changed)
        self.refresh()

    @QtCore.Property(str, notify=sourceChanged)
    def source(self):
        return self._source

    @QtCore.Property('QVariantMap', notify=changed)
    def state(self):
        return dict(self._state)

    @QtCore.Property(bool, notify=changed)
    def available(self):
        return bool(self._state) and not self._snapshot_failed

    @QtCore.Property(bool, notify=changed)
    def busy(self):
        return self._pending is not None or self._sending is not None

    @QtCore.Property('QVariantMap', notify=changed)
    def confirmation(self):
        return dict(self._confirmation)

    @QtCore.Property('QVariantMap', notify=changed)
    def viewport(self):
        return dict(self._viewports.get(self._room_key, {}))

    @QtCore.Property(str, notify=draftChanged)
    def draft(self):
        return self._draft

    @QtCore.Slot(str)
    def setDraft(self, text):
        text = str(text or '')
        if not self._closed and text != self._draft:
            self._draft = text
            self._drafts[self._room_key] = text
            self.draftChanged.emit()

    @QtCore.Slot('QVariantMap')
    def saveViewport(self, viewport):
        if not self._closed:
            self._viewports[self._room_key] = dict(viewport or {})

    def _show(self, source):
        if self._closed:
            return
        if self._source != source:
            self._source = source
            self.sourceChanged.emit()
        self.changed.emit()
        try:
            self._show_conversation()
        except Exception:
            self._error('Could not open the Conversation tab.')

    @QtCore.Slot()
    def showRoom(self):
        self.refresh()
        self._show('local_room')

    @QtCore.Slot()
    def showMain(self):
        self._show('main')

    @QtCore.Slot()
    def openRoomControls(self):
        if not self._closed:
            try:
                self._show_room_controls()
            except Exception:
                self._error('Could not open Local room controls.')

    @QtCore.Slot(str, bool)
    def setViewVisible(self, view_id, visible):
        if self._closed or not str(view_id or '').strip():
            return
        if visible:
            if view_id in self._visible_views:
                return
            self._visible_views.add(view_id)
            self.refresh()
            self._refresh_timer.start()
        else:
            self._visible_views.discard(view_id)
            if not self._visible_views:
                self._refresh_timer.stop()

    @QtCore.Slot()
    def refresh(self):
        if self._closed:
            return
        try:
            state = deepcopy(dict(self._snapshot_provider() or {}))
            failed = False
        except Exception:
            # Preserve a known active phase so status failure cannot admit main chat.
            state = dict(self._state)
            state.update(error='Local room status is unavailable.')
            state.setdefault('phase', 'unavailable')
            failed = True
        if not failed:
            room_key = str(state.get('room_key') or state.get('mode') or 'local')
            if room_key != self._room_key:
                self._drafts[self._room_key] = self._draft
                self._room_key = room_key
                self._draft = self._drafts.get(room_key, '')
                self.draftChanged.emit()
            conversation_id = str(dict(state.get('conversation') or {}).get('id') or '')
            previous_id = self._conversation_ids.get(room_key, '')
            if conversation_id and previous_id and conversation_id != previous_id:
                self._viewports[room_key] = {}
                self.setDraft('')
            if conversation_id:
                self._conversation_ids[room_key] = conversation_id
        if state != self._state or failed != self._snapshot_failed:
            self._state = state
            self._snapshot_failed = failed
            self.changed.emit()

    def _main_active(self):
        return any(bool(getattr(self._runtime, key, False))
                   for key in ('running', 'starting', 'stopping', 'cleanup_pending'))

    def blocks_main_start(self):
        self.refresh()
        return self._pending is not None or self._state.get('phase') in _ACTIVE_PHASES

    def request_start(self, control_id, payload=None):
        if self._closed or self.busy or control_id not in _START_ACTIONS:
            return False
        self._pending = dict(action=control_id, payload=payload, stage='confirmation', stop_requested=False)
        self._confirmation.update(active=False, action=control_id, error='')
        try:
            active = self._main_active()
        except Exception:
            self._error('Could not check the main chat runtime.')
            return False
        if active:
            self._confirmation['active'] = True
            self.changed.emit()
        else:
            self._request_guard()
        return self._pending is not None or self._source == 'local_room'

    @QtCore.Slot(bool)
    def decideSwitch(self, accepted):
        if self._closed or self._pending is None or not self._confirmation['active']:
            return
        self._confirmation['active'] = False
        if not accepted:
            self._finish()
            return
        self._pending['stage'] = 'stopping'
        self.changed.emit()
        self._timer.start()
        self._poll()

    def _poll(self):
        if self._closed or self._pending is None:
            self._timer.stop()
            return
        if self._pending['stage'] == 'guard':
            self._check_guard_cancelled()
            return
        if self._pending['stage'] != 'stopping':
            return
        try:
            running = bool(self._runtime.running)
            starting = bool(self._runtime.starting)
            stopping = bool(self._runtime.stopping)
            cleanup = bool(self._runtime.cleanup_pending)
            if not self._pending['stop_requested']:
                self._pending['stop_requested'] = bool(self._runtime.request_stop())
                # Startup may become a running session after request_stop rejects.
                if starting:
                    return
                running = bool(self._runtime.running)
                stopping = bool(self._runtime.stopping)
                cleanup = bool(self._runtime.cleanup_pending)
            if running or starting or stopping:
                return
            if cleanup:
                self._error('Main chat cleanup remains incomplete. Resolve cleanup before starting a Local room.')
                return
            self._timer.stop()
            self._request_guard()
        except Exception:
            self._error('Could not stop or clean up the main chat runtime. The Local room was not started.')

    def _request_guard(self):
        if self._closed or self._pending is None:
            return
        if self._guard.state.get('active') or self._guard.state.get('busy'):
            self._error("Finish the current Save / Don't Save / Cancel decision first.")
            return
        pending = self._pending
        pending['stage'] = 'guard'
        self.changed.emit()
        try:
            self._guard.request('starting or continuing a Local room discussion',
                                lambda: self._start_after_guard(pending))
        except Exception:
            self._error('Could not check unsaved main chat changes.')
            return
        if self._pending is pending:
            self._timer.start()
            self._guard_changed()

    def _guard_changed(self):
        # ChatContextGuard emits inactive before invoking its accepted callback.
        # A queued check distinguishes Cancel from Save/Discard without racing it.
        if not self._closed and self._pending is not None and self._pending['stage'] == 'guard':
            QtCore.QTimer.singleShot(0, self._check_guard_cancelled)

    def _check_guard_cancelled(self):
        if (not self._closed and self._pending is not None and self._pending['stage'] == 'guard'
                and not self._guard.state.get('active') and not self._guard.state.get('busy')):
            self._finish()

    def _start_after_guard(self, pending):
        if self._closed or self._pending is not pending:
            return
        try:
            if self._main_active():
                self._error('Main chat became active. The Local room was not started.')
                return
            if not self._reset_main():
                self._error('Could not clear the main chat. The Local room was not started.')
                return
            pending['stage'] = 'dispatch'
            if not self._dispatch(pending['action'], pending['payload']):
                self._error('The Local room request was not accepted.')
                return
        except Exception:
            self._error('Could not start the Local room.')
            return
        if self._source != 'local_room':
            self._source = 'local_room'
            self.sourceChanged.emit()
        self.changed.emit()
        self.refresh()
        try:
            self._show_conversation()
        except Exception:
            self._error('Could not open the Conversation tab.')

    def _finish(self):
        self._timer.stop()
        self._pending = None
        self._confirmation['active'] = False
        self.changed.emit()

    def _error(self, message):
        self._confirmation['error'] = message
        self._finish()
        self.errorRaised.emit(str(message))

    @QtCore.Slot(str, result=bool)
    @QtCore.Slot(str, str, result=bool)
    def send(self, text, sender_id=None):
        if self._closed or self._source != 'local_room' or self.busy or not str(text or '').strip():
            return False
        try:
            if self._main_active():
                self._error('Stop the main chat runtime before sending to the Local room.')
                return False
            self._sending = str(text)
            payload = dict(text=str(text))
            if self._state.get('mode') == 'discord' and sender_id is not None:
                payload['sender_id'] = str(sender_id)
            accepted = bool(self._dispatch('discord_local_room_send', payload))
        except Exception:
            self._sending = None
            self._error('Could not send the Local room message.')
            return False
        if accepted:
            self.setDraft('')
            self.changed.emit()
            self.refresh()
        else:
            self._sending = None
        return accepted

    @QtCore.Slot(str)
    def setTextSender(self, sender_id):
        if self._closed or self.busy or self._state.get('mode') != 'discord':
            return
        try:
            if self._dispatch('discord_local_room_set_sender', dict(participant_id=str(sender_id))):
                self.refresh()
        except Exception:
            self._error('Could not change the Discord message sender.')

    @QtCore.Slot(str)
    def control(self, action):
        control_id = str(action or '')
        if control_id in ('continue', 'start'):
            self.request_start('discord_local_room_start')
            return
        if control_id in ('new', 'new_conversation'):
            self.request_start('discord_local_room_new_conversation')
            return
        if control_id in _START_ACTIONS:
            self.request_start(control_id)
            return
        if control_id in ('pause', 'resume', 'stop'):
            control_id = 'discord_local_room_' + control_id
        if self._closed or self.busy or control_id not in (
                'discord_local_room_pause', 'discord_local_room_resume', 'discord_local_room_stop'):
            return
        try:
            if self._dispatch(control_id, None):
                self.refresh()
        except Exception:
            self._error('Could not update the Local room.')

    @QtCore.Slot(str, bool, str)
    def actionCompleted(self, control_id, accepted, error=''):
        if self._closed:
            return
        if control_id == 'discord_local_room_send' and self._sending is not None:
            sent = self._sending
            self._sending = None
            if not accepted:
                if not self._draft:
                    self.setDraft(sent)
                self._confirmation['error'] = str(error or 'The Local room message was not sent.')
            self.changed.emit()
            self.refresh()
        elif (self._pending is not None and self._pending['stage'] == 'dispatch'
              and control_id == self._pending['action']):
            if not accepted:
                self._confirmation['error'] = str(error or 'The Local room request failed.')
            self._finish()
            self.refresh()
        elif not accepted and control_id.startswith('discord_local_room_'):
            self._confirmation['error'] = str(error or 'The Local room action failed.')
            self.changed.emit()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._refresh_timer.stop()
        self._visible_views.clear()
        self._timer.stop()
        self._pending = None
        self._sending = None
        try:
            self._guard.changed.disconnect(self._guard_changed)
        except (RuntimeError, TypeError):
            pass


__all__ = ['RoomConversationSession']
