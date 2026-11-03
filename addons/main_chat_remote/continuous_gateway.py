"""Authenticated phone adapter; the runtime remains the sole chat/speech owner."""
from __future__ import annotations
from collections import OrderedDict
import hashlib
import json
import threading
from core.runtime.contracts import CancellationToken
from core.runtime.continuous_next_reply import voice_settings_fingerprint
from core.runtime.structured_character_voice import VoiceContext

from .continuous import ContinuousController, preserves_current_reply
from .continuous_generator import AutoReplyGenerator
from .continuous_settings import SettingsStore
from .continuous_speech import ContinuousUserSpeech
from .story_progress_context import recent_story_replies


class ContinuousGateway:
    def __init__(self, host, provider, *, autostart=True):
        self.host = host
        store = SettingsStore(host.runtime_dir / "continuous-settings.json")
        self.controller = ContinuousController(settings=store.load(), save_settings=store.save)
        self.generator = AutoReplyGenerator(provider)
        self.speech = ContinuousUserSpeech(host.runtime_dir / "continuous_audio", self._resolve_voice)
        self._lock = threading.RLock()
        self._owner = ""
        self._auth = None
        self._acks: OrderedDict[str, tuple] = OrderedDict()
        self._pending_acks: OrderedDict[str, tuple] = OrderedDict()
        self._commands: OrderedDict[tuple, tuple] = OrderedDict()
        self._claims: OrderedDict[tuple, dict | None] = OrderedDict()
        self._closed = threading.Event()
        self._generation_thread = None
        self._generation_timer = None
        self._thread = None
        self._last_diagnostic = None
        self._speech_prefetched = None
        self._staging = None
        if autostart and self.available:
            self._thread = threading.Thread(target=self._run, name="nc-continuous", daemon=True)
            self._thread.start()

    def _trace(self, event: str, details: dict) -> None:
        try:
            writer = getattr(self.host, "_write_phone_debug_event", None)
            if callable(writer): writer("info", event, details)
        except Exception:
            pass  # Diagnostics cannot affect a chat or playback transition.

    @property
    def available(self):
        return bool(getattr(self.host.host, "conditional_input_available", False)
                    and getattr(self.host, "_shared_manual_queue_supported", False))

    def _authenticate(self, body):
        if self._closed.is_set() or not self.available: raise ValueError("Continuous Mode is unavailable")
        auth = body.get("auth")
        owner = self.host._phone_reply.authenticate(auth)
        if not self.host._phone_reply.registry.shared_queue_enabled(auth):
            raise ValueError("Continuous Mode requires Backend HQ with shared reply controls")
        return owner, auth

    def _resolve_voice(self, voice_id):
        def resolve():
            state = self.host.remote_commands.voice_state()
            if not voice_id or not state.get("available"):
                raise ValueError("Choose an available desktop user voice.")
            for item in state.get("items") or []:
                value = item.get("value")
                if isinstance(value, str) and self.host._voice_token(value) == voice_id:
                    return self.host.host.user_speech_runtime(), value
            raise ValueError("Selected desktop voice is unavailable.")
        return self.host._invoke_main(resolve)

    def _user_voice_context(self, job) -> VoiceContext | None:
        def capture():
            config = self.host.runtime_config.snapshot()
            if voice_settings_fingerprint(config) != job['boundary'].get('voice_fingerprint'):
                raise ValueError('Continuous voice settings changed.')
            conversation = str(config.get('chat_character_conversation_id') or '')
            if not conversation:
                return None
            try:
                snapshot = self.host.remote_commands.chat_characters(dict(
                    action='voice-context', conversation_id=conversation,
                    tts_backend=str(config.get('tts_backend') or 'chatterbox')))
            except (RuntimeError, LookupError):
                return None  # Optional character addon unavailable: retain user voice.
            return VoiceContext.from_snapshot(job['id'], snapshot)
        return self.host._invoke_main(capture)

    def observe_ack(self, auth, request_id):
        try:
            protocol = self.host._phone_reply
            owner = protocol.authenticate(auth)
            status = protocol.registry.status(auth, request_id)
            if status["phase"] != "complete" or status.get("playback_stop_requested"): return
            scope = protocol.registry.scope(auth, request_id)
            # Retain only a confirmed completion, before reading the independently
            # published history snapshot. A transient read failure must not lose it.
            with self._lock:
                self._pending_acks[owner] = (request_id, scope)
                while len(self._pending_acks) > 64: self._pending_acks.popitem(last=False)
            snapshot = protocol.conversation_actions_snapshot(include_history=True)
            self._reconcile_ack(owner, snapshot)
        except Exception:
            return  # An observer must never change an existing playback result.

    def _reconcile_ack(self, owner, snapshot):
        history = snapshot.get("_history") or []
        last = history[-1] if history else {}
        with self._lock:
            pending = self._pending_acks.get(owner)
            if pending is None: return
            request_id, scope = pending
            if snapshot.get("session_generation") != scope.session_generation:
                self._pending_acks.pop(owner, None)
                return
            if last.get("role") != "assistant": return
            transaction = last.get("normal_chat_transaction_id")
            if transaction and transaction != scope.normal_chat_transaction_id: return
            self._acks[owner] = (request_id, last.get("id"), scope.session_generation)
            self._pending_acks.pop(owner, None)
            while len(self._acks) > 64: self._acks.popitem(last=False)

    def observe_skip(self, auth, request_id):
        try:
            owner = self.host._phone_reply.authenticate(auth)
            self._cancel_staging("reply_skipped")
            self.controller.reply_interrupted(owner, request_id)
            with self._lock:
                if self._pending_acks.get(owner, (None,))[0] == request_id:
                    self._pending_acks.pop(owner, None)
                if self._acks.get(owner, (None,))[0] == request_id:
                    self._acks.pop(owner, None)
        except Exception:
            return

    def observe_manual_input(self, auth, request_id):
        owner = self.host._phone_reply.authenticate(auth)
        self._cancel_staging("manual_input")
        self.controller.manual_input_accepted(owner, request_id)
        self._trace("continuous_manual_input", {"request_id": request_id,
                    "state": self.controller.snapshot(owner)["state"]})

    @staticmethod
    def _producer_complete(protocol, auth, assistant: dict, session: int) -> bool:
        transaction = assistant.get("normal_chat_transaction_id")
        if not transaction:
            return False
        try:
            replies = protocol.registry.diagnostic_snapshot().get("replies", ())
            for row in reversed(replies):
                if row.get("phase") != "complete" or not row.get("bound"):
                    continue
                identity = row.get("reply_id")
                scope = protocol.registry.scope(auth, identity)
                if (scope.normal_chat_transaction_id == transaction
                        and scope.session_generation == session):
                    status = protocol.registry.status(auth, identity)
                    return status.get("phase") == "complete" and not status.get("playback_stop_requested")
        except Exception:
            return False
        return False

    def _story_complete(self):
        plans = getattr(self.host, '_story_plans', None)
        if plans is None or getattr(plans, 'store', None) is None:
            return False
        scope = self.host._story_plan_scope()
        plan = plans.store.snapshot(str(scope.get('conversation_id') or ''))
        return bool(plan and plan.get('status') == 'complete')

    def _completed_story_snapshot(self, owner):
        reason = 'Story finished. Open Story Plan to add more beats.'
        with self.controller._lock:
            if self.controller._state not in {'paused', 'stopped'} or (
                    self.controller._state == 'paused' and self.controller._reason != reason):
                if self.controller._state != 'stopped':
                    self.controller._pause(reason)
        result = self.controller.snapshot(owner)
        result['story_complete'] = True
        return result

    def _final_story_assessment_pending(self, last, history=()):
        plans = getattr(self.host, '_story_plans', None)
        if plans is None or getattr(plans, 'store', None) is None or last.get('role') != 'assistant':
            return False
        scope = self.host._story_plan_scope()
        plan = plans.store.snapshot(str(scope.get('conversation_id') or ''))
        pending = bool(plan and plan.get('status') == 'active'
            and plan.get('progression') == 'automatic'
            and plan.get('current_beat') == len(plan.get('beats', [])) - 1
            and plan.get('last_assessed_reply_id') != last.get('id'))
        if pending:
            plans.observe(str(scope.get('conversation_id') or ''), str(last.get('id') or ''),
                          str(last.get('content') or ''), scope.get('session_generation'),
                          recent_assistant_turns=recent_story_replies(history, str(last.get('id') or '')))
        return pending

    def poll_once(self, *, force=False):
        if self._closed.is_set(): return
        with self._lock: owner = self._owner
        if not owner: return
        if not force and self.controller.snapshot(owner)["state"] in {"stopped", "paused"} and not self.controller._awaiting_reply:
            return
        protocol = self.host._phone_reply
        snapshot = protocol.conversation_actions_snapshot(include_history=True)
        self._reconcile_ack(owner, snapshot)
        runtime = self.host._continuous_runtime()
        history = snapshot.get("_history") or []
        last = history[-1] if history else {}
        with self._lock:
            ack = self._acks.get(owner)
            if not ack or ack[1] != last.get("id") or ack[2] != snapshot.get("session_generation"):
                # A relay reconnect creates a new phone client epoch. Reuse only
                # an already confirmed drain for this exact conversation reply.
                ack = next((item for item in reversed(tuple(self._acks.values()))
                            if item[1] and item[1] == last.get("id")
                            and item[2] == snapshot.get("session_generation")), None)
        ready = bool(ack and last.get("role") == "assistant" and ack[1] == last.get("id")
                     and ack[2] == snapshot.get("session_generation") and not snapshot.get("disabled_reason"))
        boundary = {"session": snapshot.get("session_generation"), "revision": snapshot.get("revision"),
                    "retired_revision": snapshot.get("_retired_revision"),
                    "persona": runtime.get("persona"), "persona_name": runtime.get("persona_name", ""),
                    "persona_identity": runtime.get("persona_identity", ""),
                    "assistant_id": last.get("id") if last.get("role") == "assistant" else "",
                    "content": last.get("content", ""), "history": history,
                    "provider_id": runtime.get("provider_id"), "model_id": runtime.get("model_id"),
                    "voice_fingerprint": runtime.get("voice_fingerprint"),
                    "ready": ready, "reply_id": ack[0] if ready else "",
                    "forceable": bool(runtime.get("running") and last.get("role") == "assistant"
                                      and not snapshot.get("disabled_reason"))}
        boundary["generation_ready"] = boundary["forceable"]
        boundary["manual_input_pending"] = snapshot.get("disabled_reason") == "manual_input_pending"
        if not runtime.get("running"): boundary["error"] = "Main conversation is not running"
        with self._lock: auth = self._auth
        waiting_reply = self.controller._manual_reply or self.controller._awaiting_reply
        if auth and waiting_reply:
            try:
                reply = protocol.registry.status(auth, waiting_reply)
                phase = reply["phase"]
                if phase in {"cancelled", "superseded"} or reply.get("playback_stop_requested"):
                    boundary.update(error="Current reply was cancelled or replaced", reply_ended=True)
                elif phase == "complete" and last.get("role") != "assistant":
                    boundary.update(error="Main model ended without an assistant response", reply_ended=True)
            except Exception:
                boundary.update(error="Reply ownership ended. Reconnect and resume.", reply_ended=True)
        story_complete = self._story_complete()
        if story_complete:
            boundary['generation_ready'] = False
        self.controller.observe(boundary)
        if story_complete:
            # Text assessment may finish while audio is still playing. Retire
            # speculation and stop waiting for a receipt that may never arrive;
            # pausing Continuous Mode does not interrupt the phone's audio.
            self._cancel_staging('story_finished')
            self._completed_story_snapshot(owner)
            return
        if self._final_story_assessment_pending(last, history):
            boundary.update(ready=False, generation_ready=False)
            self.controller.observe(boundary)
            self._cancel_staging('story_assessment_pending')
            with self.controller._lock:
                self.controller._invalidate()
            return
        self.controller.tick()
        candidate = self.controller.next_candidate(owner)
        settings = self.controller.settings
        if candidate is None:
            self._speech_prefetched = None
        if (candidate and self._speech_prefetched != (owner, candidate["id"])
                and auth is not None and settings.speak_user_messages and settings.mode != "off"
                and not self.controller._single and not snapshot.get("disabled_reason")
                and self._producer_complete(protocol, auth, last, boundary["session"])):
            try:
                self.speech.prefetch(owner, candidate, settings.user_voice)
                self._speech_prefetched = (owner, candidate["id"])
            except Exception as error:
                self._trace("continuous_speech_prefetch_failed", {"operation_id": candidate["id"],
                            "error_type": type(error).__name__})
        controller_state = self.controller.snapshot(owner)
        self._maybe_stage_assistant(owner, runtime, controller_state, settings)
        diagnostic = {"state": controller_state["state"], "reason": controller_state.get("reason", ""),
                      "prepared_id": controller_state.get("prepared_id"), "ready": ready,
                      "prefetch_ready": self.controller._prefetched is not None,
                      "generation_running": self.controller._job is not None,
                      "manual_reply": self.controller._manual_reply,
                      "awaiting_reply": self.controller._awaiting_reply,
                      "ack_reply": ack[0] if ack else "", "history_is_assistant": last.get("role") == "assistant",
                      "conversation_blocked": bool(snapshot.get("disabled_reason")),
                      "conversation_block_reason": str(snapshot.get("disabled_reason") or "")}
        if diagnostic != self._last_diagnostic:
            self._last_diagnostic = diagnostic
            try:
                self.host._write_phone_debug_event("info", "continuous_boundary", diagnostic)
            except Exception:
                pass  # Diagnostics never determine admission or playback.
        if self._generation_thread is None or not self._generation_thread.is_alive():
            job = self.controller.generation_job()
            if job:
                self._generation_thread = threading.Thread(target=self._generate, args=(job,), name="nc-auto-reply", daemon=True)
                self._generation_thread.start()

    def _maybe_stage_assistant(self, owner, runtime, state, settings):
        """Prepare one private successor after user speech production has completed."""
        prepared_id = state.get("prepared_id") if state.get("state") == "ready" else None
        port = getattr(self.host.host, "stage_continuous_next", None)
        with self._lock:
            current = self._staging
            if current and (current["owner"] != owner or current["operation_id"] != prepared_id):
                current["token"].cancel("continuous_changed")
                self._staging = current = None
        if (not prepared_id or not callable(port) or settings.mode == "off"
                or not state.get("user_speech")
                or self.controller._single or not runtime.get("voice_fingerprint")):
            return
        try:
            prepared, _ = self.controller.speech_preparation(owner, prepared_id)
            speech = self.speech.status(owner, prepared_id)
            if not speech.get("done") or speech.get("error"):
                return
            boundary = prepared["boundary"]
            binding = dict(session_generation=boundary["session"],
                conversation_revision=boundary["revision"],
                source_turn_id=boundary["assistant_id"], owner_id=owner,
                persona_id=boundary["persona"], provider_id=boundary["provider_id"],
                model_id=boundary["model_id"], settings_revision=state["revision"],
                voice_fingerprint=boundary["voice_fingerprint"])
            proposed = dict(content=prepared["text"], role="user", origin="input",
                phone_reply_control=True, phone_shared_queue=True, source=prepared["source"])
            if "auto_reply_guidance" in prepared:
                proposed["auto_reply_guidance"] = dict(prepared["auto_reply_guidance"])
        except (KeyError, ValueError):
            return
        job = dict(owner=owner, operation_id=prepared_id, token=CancellationToken(),
            binding=binding, stage_id=None)
        with self._lock:
            current = self._staging
            if (current and current["owner"] == owner
                    and current["operation_id"] == prepared_id
                    and current["binding"] != binding):
                # The controller preserves a candidate only for a certified,
                # history-preserving route retirement. Retry with that exact
                # new boundary instead of retaining a stale failed attempt.
                current["token"].cancel("continuous_boundary_changed")
                self._staging = None
            if self._staging is not None:
                return
            self._staging = job
        def run():
            try:
                stage_id = port(proposed, binding, job["token"])
                if isinstance(stage_id, str) and not job["token"].cancelled:
                    promoted = False
                    with self._lock:
                        if self._staging is job:
                            job["stage_id"] = stage_id
                            promoted = True
                    if promoted:
                        self._trace("continuous_assistant_stage", {
                            "phase": "ready", "operation_id": prepared_id,
                            "stage_id": stage_id})
                elif not job["token"].cancelled:
                    self._trace("continuous_assistant_stage", {
                        "phase": "fallback", "operation_id": prepared_id})
            except Exception as error:
                self._trace("continuous_assistant_stage_failed", {
                    "operation_id": prepared_id, "error_type": type(error).__name__})
        threading.Thread(target=run, name="nc-continuous-next-assistant", daemon=True).start()

    def _cancel_staging(self, reason):
        operation_id = None
        with self._lock:
            if self._staging is not None:
                operation_id = self._staging["operation_id"]
                self._staging["token"].cancel(reason)
                self._staging = None
        if operation_id is not None:
            self._trace("continuous_assistant_stage", {
                "phase": "cancelled", "operation_id": operation_id,
                "reason": reason})

    def _generate(self, job):
        result = None
        timer = threading.Timer(120, lambda: (self._trace("continuous_generation_timeout", {"job_id": job["id"]}),
            self.controller.generation_finished(job), job["token"].cancel("timeout")))
        timer.daemon = True; self._generation_timer = timer; timer.start()
        try:
            context = dict(job["boundary"])
            plans = getattr(self.host, "_story_plans", None)
            if plans is not None:
                if plans.context():
                    scope = self.host._story_plan_scope()
                    plans.observe(str(scope.get("conversation_id") or ""),
                                  str(context.get("assistant_id") or ""),
                                  str(context.get("content") or ""),
                                  recent_assistant_turns=recent_story_replies(
                                      context.get('history') or [], str(context.get('assistant_id') or '')))
                    if not plans.wait_for_observation(15):
                        # The next director prompt must see the assessed beat.
                        # Pause rather than silently continuing with stale
                        # context or falling back to a generic user message.
                        with self.controller._lock:
                            self.controller._pause(
                                "Story progress is still being checked. Resume Continuous Mode shortly.")
                        self._trace("continuous_story_assessment_timeout", {"job_id": job["id"]})
                        return
                context["story_plan"] = plans.context()
                if self._story_complete():
                    with self.controller._lock:
                        if self.controller._job is job:
                            self.controller._job = None
                            job['token'].cancel('story_finished')
                    return
            settings = job["settings"]
            if settings.speak_user_messages:
                context['user_voice_context'] = self._user_voice_context(job)
            # The main chat model has just handled this image. A separate
            # text-only Auto-Reply model must not silently lose visual context.
            has_user_image = any(
                turn.get("role") == "user" and turn.get("attachment_image_path")
                for turn in list(context.get("history") or [])[-settings.recent_turns:]
            )
            if settings.separate_model and not has_user_image:
                context["provider_id"], context["model_id"] = self.host._continuous_model(settings.provider_id, settings.model_id)
            result = self.generator.generate(settings, context, job["token"])
        except Exception as error:
            self._trace("continuous_generation_failed", {"job_id": job.get("id", ""),
                        "error_type": type(error).__name__})
            # Provider exception text may contain credentials. State uses safe copy.
        finally:
            timer.cancel()
            self.controller.generation_finished(job, result)

    def _run(self):
        while not self._closed.wait(.2):
            try: self.poll_once()
            except Exception:
                with self.controller._lock: self.controller._pause("Continuous Mode could not read the conversation")

    def handle(self, method, body):
        if not isinstance(body, dict) or len(json.dumps(body)) > 100000: raise ValueError("Invalid Continuous request")
        owner, auth = self._authenticate(body)
        if method == "models": return self.host.llm_model_snapshot()
        if method == "speech":
            identity = body.get("operation_id")
            if type(identity) is not str or not 1 <= len(identity) <= 128:
                raise ValueError("Invalid speech operation ID")
            action = body.get("action")
            prepared, settings = self.controller.speech_preparation(owner, identity, begin=action == "start")
            if not self.controller.snapshot(owner).get("user_speech"):
                raise ValueError("User speech is disabled.")
            if action == "start":
                result = self.speech.start(owner, prepared, settings.user_voice)
                self._trace("continuous_speech", {"operation_id": identity, "phase": "start"})
                return result
            if action == "played":
                self.speech.acknowledge(owner, identity, body.get("chunk_count"))
                self._trace("continuous_speech", {"operation_id": identity, "phase": "played",
                            "chunk_count": body.get("chunk_count")})
            elif action != "status": raise ValueError("Invalid speech action")
            return self.speech.status(owner, identity)
        if method == "status":
            self.controller.heartbeat(owner)
            if self._story_complete():
                return self._completed_story_snapshot(owner)
            result = self.controller.snapshot(owner)
            result['story_complete'] = False
            return result
        if method == "claim": return self._claim(owner, auth, body.get("operation_id"))
        if method != "command": raise ValueError("Unknown Continuous request")
        identity = body.get("operation_id")
        if type(identity) is not str or not 1 <= len(identity) <= 128: raise ValueError("Invalid operation ID")
        if body.get('kind') in {'start', 'resume', 'force_continue'} and self._story_complete():
            return self._completed_story_snapshot(owner)
        fingerprint = hashlib.sha256(json.dumps({k: v for k, v in body.items() if k != "auth"}, sort_keys=True).encode()).digest()
        key = (owner, identity)
        with self._lock:
            old = self._commands.get(key)
            if old:
                if old[0] != fingerprint: raise ValueError("Operation ID already used")
                return self.controller.snapshot(owner)
        # Capture a current session before arming; no fabricated first turn.
        with self._lock:
            current_owner = self._owner
            if (not current_owner or current_owner == owner or self.controller.snapshot(owner)["owned"]
                    or self.controller.snapshot(current_owner)["state"] == "stopped"):
                self._owner = owner; self._auth = dict(auth)
        self.poll_once(force=True)
        response = self.controller.command(owner, body.get("kind"), body, body.get("revision"))
        if body.get("kind") == "settings" and preserves_current_reply(body.get("settings")):
            with self._lock:
                if self._staging and self._staging["operation_id"] != response.get("prepared_id"):
                    self._cancel_staging("guidance_changed")
        if (body.get("kind") in {"settings", "pause", "stop", "disconnect", "force_continue"}
                and not (body.get("kind") == "settings" and preserves_current_reply(body.get("settings")))):
            self._cancel_staging("continuous_command_changed")
        self._trace("continuous_command", {"kind": body.get("kind"), "state": response["state"],
                    "operation_id": identity, "revision": response["revision"]})
        with self._lock:
            self._commands[key] = (fingerprint, True)
            while len(self._commands) > 512: self._commands.popitem(last=False)
        response['story_complete'] = self._story_complete()
        return response

    def _claim(self, owner, auth, identity):
        if type(identity) is not str or len(identity) > 128: raise ValueError("Invalid operation ID")
        key = owner, identity
        with self._lock:
            if key in self._claims:
                return self._claims[key] or {"accepted": False, "status": "pending"}
        if getattr(self.host, '_story_plans', None) is not None:
            history = self.host._phone_reply.conversation_actions_snapshot(include_history=True).get('_history') or []
            if self._story_complete() or self._final_story_assessment_pending(history[-1] if history else {}, history):
                return {'accepted': False, 'status': 'busy'}
        with self._lock:
            if key in self._claims:
                return self._claims[key] or {"accepted": False, "status": "pending"}
            if self.controller.snapshot(owner).get("user_speech") and not self.speech.played(owner, identity):
                return {"accepted": False, "status": "busy"}
            prepared = self.controller.claim(owner, identity)
            if prepared is None: return {"accepted": False, "status": "stale"}
            self._claims[key] = None
            staged = self._staging if self._staging and self._staging["owner"] == owner \
                and self._staging["operation_id"] == identity else None
            if staged is not None:
                self._staging = None
            if staged and not staged["stage_id"]:
                staged["token"].cancel("stage_not_ready_at_admission")
        protocol = self.host._phone_reply
        capture_id = ""
        def finish(result):
            if not isinstance(result, dict): result = {"status": "unavailable"}
            if result.get("status") != "accepted" and capture_id: protocol.cancel(capture_id)
            if staged and result.get("status") != "accepted":
                staged["token"].cancel("admission_rejected")
            response = {"accepted": result.get("status") == "accepted", "status": result.get("status"),
                        "phone_request_id": capture_id if result.get("status") == "accepted" else ""}
            with self._lock:
                self._claims[key] = response
                while len(self._claims) > 512: self._claims.popitem(last=False)
            self.controller.settle(identity, result)
            self._trace("continuous_claim", {"operation_id": identity,
                        "request_id": response["phone_request_id"], "status": response["status"]})
            return response
        try:
            capture_id = protocol.register(auth)
            boundary = prepared["boundary"]
            def admit():
                metadata = {"remote_capture_id": capture_id, "phone_reply_control": True,
                            "phone_shared_queue": True, "source": prepared["source"]}
                if "auto_reply_guidance" in prepared:
                    metadata["auto_reply_guidance"] = dict(prepared["auto_reply_guidance"])
                if staged and staged["stage_id"] and not staged["token"].cancelled:
                    metadata.update(continuous_stage_id=staged["stage_id"],
                        continuous_stage_binding=dict(staged["binding"]),
                        continuous_owner_id=owner)
                result = self.host.host.submit_if_current_and_idle(
                    prepared["text"], operation_id=identity, expected_revision=boundary["revision"],
                    expected_session=boundary["session"], cancellation=prepared["token"],
                    metadata=metadata)
                return finish(result)
            response = self.host._invoke_main(admit)
            return response if isinstance(response, dict) else finish({"status": "unavailable"})
        except TimeoutError:
            # The queued Qt callback may still run. Cancel before publication,
            # retain this ID, and let that same callback publish its final result.
            prepared["token"].cancel("admission_timeout")
            with self._lock:
                return self._claims.get(key) or {"accepted": False, "status": "pending"}
        except Exception:
            prepared["token"].cancel("admission_failed")
            return finish({"status": "unavailable"})

    def close(self):
        self._closed.set(); self.controller.close()
        with self._lock:
            if self._staging is not None:
                self._staging["token"].cancel("continuous_closed")
                self._staging = None
        self.speech.close()
        if self._generation_timer: self._generation_timer.cancel()
