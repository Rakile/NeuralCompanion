"""Native memory workspace over the finite application facade.

Provider/storage work stays off the Qt thread. Completion receipts and a local
epoch prevent old-session results from leaking into a newly selected context.
"""
from __future__ import annotations

import base64
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
import uuid

from PySide6 import QtCore
from ui.qml_bridge.memory_presentation import (
    ACTION_TITLES, describe_memory, format_archive, format_search, format_operation_result, format_save_result,
)


def _plain(value):
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _text(value):
    return format_operation_result(_plain(value))


def _accepted(result):
    if not result.accepted:
        failure = result.failure
        raise RuntimeError(failure.message if failure else "The runtime rejected this operation.")
    return getattr(result, "value", None)


class MemoryWorkspaceController(QtCore.QObject):
    changed = QtCore.Signal()
    imageReviewChanged = QtCore.Signal()
    contextChanged = QtCore.Signal(str)
    contextSaved = QtCore.Signal(object)
    saveFileRequested = QtCore.Signal()
    loadFileRequested = QtCore.Signal()
    notificationRaised = QtCore.Signal(str, str, str)
    _finished = QtCore.Signal(object)
    _reviewRequested = QtCore.Signal(object)
    _reviewExpired = QtCore.Signal(str)
    _contextReady = QtCore.Signal(object)
    _updatesRequested = QtCore.Signal(object)
    _statusReady = QtCore.Signal(object)

    def __init__(self, application, *, parent=None):
        super().__init__(parent)
        self._application = application
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="native-memory")
        self._future = None
        self._refresh_future = None
        self._embedding_warning = ''
        self._closed = False
        self._epoch = 0
        self._generation = self._session_generation()
        self._action = ""
        self.departure_guard = None
        self._review_lock = threading.Lock()
        self._pending_review = None
        self._state = dict(status="Not refreshed", busy=False, busyLabel="", summaryText="", summaryStatus="",
                           archiveText="", resultText="", embeddingModels=[], contextPath="",
                           contextName="", error="")
        self._state.update(archiveStatus='', embeddingStatus='', progressText='', repairStatus='', resultTitle='')
        self._state.update(summaryHeadline='', searchNeedsAttention=False, totalMessages=0,
                           technicalDetails='', embeddingDiagnostics='', resultDetails='', repairHeadline='')
        self._state.update(self._context_identity())
        self._image_review = dict(active=False, requestId="", prompt="", images=[])
        self._finished.connect(self._apply_result)
        self._reviewRequested.connect(self._show_review)
        self._reviewExpired.connect(self._expire_review)
        self._contextReady.connect(self._context_changed)
        self._review_binding = application.memory.bind_image_review(self._review_images)
        self._updatesRequested.connect(self._memory_updated)
        self._statusReady.connect(self._apply_status)
        self._update_binding = application.memory.bind_updates(lambda payload=None:
            self._updatesRequested.emit((dict(payload or {}), self._session_generation())))
        self._update_timer = QtCore.QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(100)
        self._update_timer.timeout.connect(self._refresh_update)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._check_generation)
        self._timer.start()

    @QtCore.Property("QVariantMap", notify=changed)
    def state(self):
        return dict(self._state)

    @QtCore.Property("QVariantMap", notify=imageReviewChanged)
    def imageReview(self):
        return dict(self._image_review)

    def _session_generation(self):
        return self._application.chat.snapshot().session_generation

    def _context_identity(self):
        config = self._application.config.snapshot().values
        path = str(config.get('active_chat_context_path', '') or '')
        name = str(config.get('active_chat_context_name', '') or '') if path else ''
        return dict(contextPath=path, contextName=name or (Path(path).stem if path else ''))

    def _current(self, epoch, generation, *, allow_transition=False):
        return (not self._closed and epoch == self._epoch
                and (allow_transition or self._session_generation() == generation))

    @QtCore.Slot()
    def _check_generation(self):
        if self._closed or self._action == "load_context":
            return
        if self._session_generation() != self._generation:
            self.invalidate()
        elif self._state['busy'] and not self._update_timer.isActive():
            self.requestRefresh()

    def _read_state(self):
        memory = self._application.memory
        config = self._application.config.snapshot().values
        status = memory.status_view()
        summary = memory.continuity_snapshot()
        conversation = memory.conversation_status()
        embedding = memory.embedding_status()
        simple = describe_memory(config, summary, conversation, status, embedding)
        return dict(**simple, status=str(status.get("status_text", "")),
                    technicalDetails=str(conversation.status_text) + '\n\n' + str(status.get('status_text', '')),
                    embeddingDiagnostics=str(status.get('embedding_text', '')),
                    progressText=str(status.get('progress_text', '')),
                    summaryStatus=str(conversation.status_text),
                    summaryText=str(summary.get("summary", "") or ""),
                    contextPath=str(config.get("active_chat_context_path", "") or ""),
                    contextName=str(config.get("active_chat_context_name", "") or ""))

    @QtCore.Slot()
    def refresh(self):
        self.runAction("refresh", {})

    @QtCore.Slot()
    def saveConversation(self):
        if self._closed or self._state['busy']:
            return
        path = str(self._application.config.snapshot().values.get('active_chat_context_path', '') or '')
        if path:
            self.runAction('save_context', {'path': path})
        else:
            self.saveFileRequested.emit()

    @QtCore.Slot()
    def saveConversationAs(self):
        if not self._closed and not self._state['busy']:
            self.saveFileRequested.emit()

    @QtCore.Slot()
    def loadConversation(self):
        if not self._closed and not self._state['busy']:
            self.loadFileRequested.emit()

    @QtCore.Slot()
    def requestRefresh(self):
        if not self._closed:
            self._update_timer.start()

    @QtCore.Slot()
    def _refresh_update(self):
        if self._closed:
            return
        if (self._future is not None and not self._future.done()) or (self._refresh_future is not None and not self._refresh_future.done()):
            self._update_timer.start()
        else:
            epoch, generation = self._epoch, self._session_generation()
            self._refresh_future = self._executor.submit(self._read_state)
            def complete(task):
                try:
                    payload = task.result()
                except Exception:
                    return
                if not self._closed:
                    self._statusReady.emit((epoch, generation, payload))
            self._refresh_future.add_done_callback(complete)

    @QtCore.Slot(object)
    def _apply_status(self, event):
        epoch, generation, payload = event
        if self._current(epoch, generation):
            self._state.update(payload)
            self._warn_embedding()
            self.changed.emit()

    def _warn_embedding(self):
        text = str(self._state.get('embeddingDiagnostics', ''))
        warning = text if 'EMBEDDINGS LOCKED' in text else ''
        if warning and warning != self._embedding_warning:
            self.notificationRaised.emit('warning', 'Memory search embeddings are locked', warning)
        self._embedding_warning = warning

    @QtCore.Slot(object)
    def _memory_updated(self, event):
        payload, generation = event
        if self._closed or generation != self._session_generation():
            return
        repair = payload.get('history_repair')
        if repair:
            phase = repair.get('phase', '')
            count = repair.get('chunks_rebuilt', 0)
            message = f"History memory repair: {phase}. {count} affected archive chunk(s) rebuilt; unaffected chunks retained."
            if repair.get('unknown_provenance'):
                message += f" {repair['unknown_provenance']} item(s) with unknown source were retained."
            if repair.get('summary_disabled'):
                message += ' The summary is empty because conversation summaries are disabled.'
            if repair.get('error'):
                message += '\n' + str(repair['error']) + '\nThe old summary is excluded. Retry Summarize Recent or Rebuild Embeddings as needed.'
            self._state['repairStatus'] = message
            self._state['repairHeadline'] = ('Updating memory after your edits…' if phase in {'queued', 'running'}
                else 'Some memory updates need attention. Open Advanced settings for details.' if phase == 'failed'
                else 'Memory updated after your edits.')
            self.changed.emit()
        self.requestRefresh()

    @QtCore.Slot(str, "QVariantMap")
    def runAction(self, action, params):
        if self._closed:
            return
        if action == 'load_context' and self.departure_guard is not None and not params.get('_confirmed'):
            self.departure_guard.request('loading another conversation',
                lambda: self.runAction(action, {**params, '_confirmed': True}))
            return
        if self._state["busy"] or (self._future is not None and not self._future.done()):
            self.notificationRaised.emit("warning", "Memory", "Wait for the current memory operation to finish.")
            return
        allowed = {"refresh", "review_summary", "summarize_recent", "forget_summary", "search_archive",
                   "review_archive", "export_report", "refresh_models", "rebuild_embeddings", "rebuild_archive",
                   "save_context", "load_context"}
        if action not in allowed:
            self._state["error"] = f"Unsupported memory action: {action}"
            self.changed.emit()
            return
        if action == "load_context":
            # Image review may hold the runtime's publication guard. Release it
            # before importing, otherwise context replacement can deadlock.
            self.invalidate()
        self._generation = self._session_generation()
        self._action = action
        self._state.update(busy=True, busyLabel=ACTION_TITLES.get(action, 'Refreshing memory') + '…', error='')
        if action != "refresh":
            self._state["resultText"] = ""
            self._state['resultDetails'] = ''
            self._state['resultTitle'] = ACTION_TITLES.get(action, 'Memory results')
        self.changed.emit()
        epoch, generation = self._epoch, self._generation
        self._future = self._executor.submit(self._run, action, dict(params), epoch, generation)

    def _complete(self, action, epoch, generation, payload=None, error=None, stale=False):
        if not self._closed:
            self._finished.emit((action, epoch, generation, payload or {}, error, stale))

    def _scheduled_callback(self, action, epoch, generation, *, result_prefix="", saved_path=""):
        def complete(receipt, result, error):
            try:
                # Consume even obsolete receipts: the facade owns a bounded receipt map.
                current = self._application.memory.work_context_is_current(receipt)
                if receipt is None and error is not None and self._current(epoch, generation):
                    raise RuntimeError(str(error))
                if not current or not self._current(epoch, generation):
                    self._complete(action, epoch, generation, stale=True)
                    return
                if error is not None:
                    raise RuntimeError(str(error))
                payload = self._read_state()
                if action == 'save_context':
                    payload['resultText'] = format_save_result(saved_path, result, payload)
                    payload['resultDetails'] = f'Saved context: {saved_path}\nMemory flush:\n' + _text(result)
                else:
                    payload["resultText"] = result_prefix + _text(result)
                self._complete(action, epoch, generation, payload)
            except Exception as exc:
                self._complete(action, epoch, generation, error=str(exc))
        return complete

    @staticmethod
    def _integer(params, key, default, maximum=10000, minimum=1):
        value = int(params.get(key, default))
        if not minimum <= value <= maximum:
            raise ValueError(f"{key} must be between {minimum} and {maximum}.")
        return value

    def _run(self, action, params, epoch, generation):
        memory = self._application.memory
        try:
            if not self._current(epoch, generation):
                self._complete(action, epoch, generation, stale=True)
                return
            payload = {}
            callback = self._scheduled_callback(action, epoch, generation)
            if action in {"refresh", "review_summary"}:
                payload = self._read_state()
                if action == "review_summary":
                    payload["resultText"] = payload["summaryText"] or "No conversation summary saved."
            elif action == "summarize_recent":
                _accepted(memory.schedule_continuity_batch(self._integer(params, "turnCount", 40), on_complete=callback))
                return
            elif action == "forget_summary":
                _accepted(memory.clear_continuity())
                payload = self._read_state()
                payload["resultText"] = "Conversation summary forgotten. Chat history and archive are unchanged."
            elif action == "search_archive":
                query = str(params.get("query", "")).strip()
                if not query:
                    raise ValueError("Enter a search query.")
                results = memory.retrieve(query, record_limit=30, chunk_limit=30)
                payload["resultText"] = format_search(query, results) if results else "No matching archive memories."
            elif action == "review_archive":
                archive = memory.archive_snapshot(record_limit=200, chunk_limit=200)
                payload["archiveText"] = f'{len(archive.records)} memory record(s), {len(archive.chunks)} archived chunk(s) shown.'
                payload["resultText"] = format_archive(archive)
            elif action == "refresh_models":
                payload["embeddingModels"] = list(memory.list_embedding_models(quiet=False))
                payload["resultText"] = f"Found {len(payload['embeddingModels'])} embedding model(s)."
            elif action == "export_report":
                path = self._local_path(params.get("path", "")) or memory.export_default_path()
                if not path:
                    raise ValueError("Save or load a named chat context before exporting a report.")
                payload["resultText"] = _text(_accepted(memory.export_session_report(path)))
            elif action == "rebuild_embeddings":
                _accepted(memory.schedule_embedding_rebuild(limit=self._integer(params, "limit", 0, 1000000, 0),
                          clear_existing=bool(params.get("clearExisting", False)), on_complete=callback))
                return
            elif action == "rebuild_archive":
                from core.long_term_memory_archive_rebuild import prepare_archive_rebuild
                config = self._application.config.snapshot().values
                path = self._local_path(params.get("path") or config.get("active_chat_context_path", ""))
                if not path:
                    raise ValueError("Choose a complete saved chat context for the inactive archive candidate.")
                prepared = prepare_archive_rebuild(path, chunk_size=self._integer(params, "chunkSize",
                           int(config.get("long_term_memory_archive_batch_turns", 40) or 40)))
                _accepted(memory.schedule_archive_candidate(prepared, on_complete=self._scheduled_callback(
                    action, epoch, generation, result_prefix="Inactive archive candidate (active database unchanged):\n")))
                return
            elif action in {"save_context", "load_context"}:
                from ui.qml_bridge.native_chat_context import save_chat_context, load_chat_context
                path = self._local_path(params.get("path", ""))
                if not path:
                    raise ValueError("Choose a chat context JSON file.")
                helper = save_chat_context if action == "save_context" else load_chat_context
                helper_options = dict(is_current=lambda: self._current(epoch, generation))
                if action == "load_context":
                    def imported(before, after):
                        nonlocal generation
                        before_value = getattr(before, "value", before)
                        after_value = getattr(after, "value", after)
                        if (before != generation or after_value != before_value + 1
                                or not self._current(epoch, after)):
                            raise RuntimeError("The chat context changed during import; its completion was discarded.")
                        generation = after
                    helper_options["on_imported"] = imported
                result = helper(self._application, path, **helper_options)
                from core.chat_context_safety import history_signature
                self.contextSaved.emit((result.get('saved_history_signature') or history_signature(result['history']), generation))
                self._contextReady.emit((action, epoch, generation))
                if action == "save_context":
                    config = self._application.config.snapshot().values
                    if any(bool(config.get(key, False)) for key in ("continuity_memory_enabled",
                           "long_term_memory_auto_archive_enabled")):
                        _accepted(memory.schedule_context_flush(result["history"], on_complete=self._scheduled_callback(
                            action, epoch, generation, saved_path=result['path'])))
                        return
                payload = self._read_state()
                payload["resultText"] = (format_save_result(result['path'], {}, payload) if action == 'save_context'
                                         else f"Loaded conversation: {Path(result['path']).name}")
                payload['resultDetails'] = f"File: {result['path']}"
                migration = {key: result[key] for key in ('conversation_content_migration', 'long_term_memory_content_migration') if result.get(key)}
                if migration:
                    payload['resultText'] += '\n\nSaved memory format update:\n' + _text(migration)
                    payload['resultText'] += '\nIf search embeddings were invalidated, use Rebuild Embeddings.'
            self._complete(action, epoch, generation, payload)
        except Exception as exc:
            self._complete(action, epoch, generation, error=str(exc))

    @staticmethod
    def _local_path(value):
        raw = str(value or "").strip()
        if raw.startswith("file:"):
            return QtCore.QUrl(raw).toLocalFile()
        if "://" in raw:
            raise ValueError("Choose a local file, not a remote URL.")
        return raw

    @QtCore.Slot(object)
    def _context_changed(self, event):
        action, epoch, generation = event
        if self._current(epoch, generation):
            self.contextChanged.emit(action)

    @QtCore.Slot(object)
    def _apply_result(self, event):
        action, epoch, generation, payload, error, stale = event
        if not self._current(epoch, generation):
            if epoch == self._epoch and not self._closed:
                self.invalidate()
            return
        self._generation = self._session_generation()
        self._action = ""
        self._state.update(busy=False, busyLabel="")
        if stale:
            self._state["error"] = "Memory operation completed for an obsolete context; its result was discarded."
        elif error:
            self._state["error"] = str(error)
            self.notificationRaised.emit("error", "Memory operation failed", str(error))
        else:
            self._state.update(payload)
            self._warn_embedding()
        self.changed.emit()

    def _review_images(self, payload=None, **kwargs):
        # A synchronous runtime callback must never block the GUI thread.
        cancelled = {"cancelled": True, "asset_ids": []}
        if self._closed or QtCore.QThread.currentThread() == self.thread():
            return cancelled
        pending = dict(id=uuid.uuid4().hex, payload=dict(payload or kwargs), event=threading.Event(),
                       result=cancelled, epoch=self._epoch, generation=self._session_generation())
        with self._review_lock:
            if self._closed or self._pending_review is not None:
                return cancelled
            self._pending_review = pending
        self._reviewRequested.emit(pending)
        deadline = time.monotonic() + 300
        while not pending["event"].wait(.1):
            if not self._current(pending["epoch"], pending["generation"]) or time.monotonic() >= deadline:
                break
        with self._review_lock:
            if self._pending_review is pending:
                self._pending_review = None
        if not self._closed:
            self._reviewExpired.emit(pending["id"])
        return dict(pending["result"])

    @QtCore.Slot(object)
    def _show_review(self, pending):
        if (pending is not self._pending_review
                or not self._current(pending["epoch"], pending["generation"])):
            pending["event"].set()
            return
        payload = pending["payload"]
        selected = set(payload.get("selected_asset_ids") or [])
        images = []
        for candidate in payload.get("candidates") or []:
            asset_id = str(candidate.get("asset_id", ""))
            source = ""
            mime = str(candidate.get("mime_type", ""))
            blob = candidate.get("blob")
            if blob and mime in {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"}:
                source = f"data:{mime};base64," + base64.b64encode(bytes(blob)).decode("ascii")
            else:
                path = str((candidate.get("link_metadata") or {}).get("original_path")
                           or (candidate.get("metadata") or {}).get("original_path") or "")
                if path and Path(path).is_file():
                    source = QtCore.QUrl.fromLocalFile(str(Path(path).resolve())).toString()
            if asset_id:
                images.append(dict(id=asset_id, source=source,
                              label=str(candidate.get("visualization_prompt") or asset_id), selected=asset_id in selected))
        self._image_review = dict(active=True, requestId=pending["id"],
                                  prompt=str(payload.get("latest_user_request") or payload.get("decision_reason") or "Review recalled images"),
                                  images=images)
        self.imageReviewChanged.emit()

    @QtCore.Slot(str, "QVariantList", bool)
    def answerImageReview(self, requestId, selectedIds, accepted):
        with self._review_lock:
            pending = self._pending_review
            if pending is None or pending["id"] != requestId:
                return
            valid = [str(item.get("asset_id", "")) for item in pending["payload"].get("candidates") or []]
            current = self._current(pending["epoch"], pending["generation"])
            pending["result"] = dict(cancelled=not accepted or not current,
                    asset_ids=[item for item in valid if item in selectedIds] if accepted and current else [])
            self._pending_review = None
            pending["event"].set()
        self._expire_review(requestId)

    @QtCore.Slot(str)
    def _expire_review(self, request_id):
        if self._image_review["requestId"] == request_id:
            self._image_review = dict(active=False, requestId="", prompt="", images=[])
            self.imageReviewChanged.emit()

    @QtCore.Slot()
    def invalidate(self):
        self._epoch += 1
        self._generation = self._session_generation()
        self._action = ""
        with self._review_lock:
            pending = self._pending_review
            self._pending_review = None
            if pending is not None:
                pending["event"].set()
        if self._future is not None:
            self._future.cancel()
        self._image_review = dict(active=False, requestId="", prompt="", images=[])
        self._state.update(busy=False, busyLabel="", summaryText="", summaryStatus="", archiveText="", resultText="", error="",
                           status="Context changed; refresh memory status.", contextPath="", contextName="",
                           archiveStatus='', embeddingStatus='', progressText='', repairStatus='', resultTitle='')
        self._state.update(summaryHeadline='', searchNeedsAttention=False, totalMessages=0,
                           technicalDetails='', embeddingDiagnostics='', resultDetails='', repairHeadline='')
        # Engine generations invalidate in-flight work, not the loaded chat.
        self._state.update(self._context_identity())
        self.changed.emit()
        self.imageReviewChanged.emit()
        if not self._closed:
            self.requestRefresh()

    @QtCore.Slot()
    def close(self):
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self._update_timer.stop()
        self.invalidate()
        self._review_binding.close()
        self._update_binding.close()
        self._executor.shutdown(wait=False, cancel_futures=True)
