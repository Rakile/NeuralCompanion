"""Composer-only commands. No chat turns are created before explicit draft Send."""
from __future__ import annotations

import json
import threading
import uuid
from typing import Any

from PySide6 import QtCore, QtGui

from core import chat_providers
from core.runtime.contracts import CancellationToken
from core.runtime.prompt_assembly import PromptRequest
from addons.visual_reply.comfyui_prompting import refinement_instruction, rules_for_config
from addons.visual_reply.runtime_config import VisualReplyRuntime
from ui.qml_bridge.conversation_addon_commands import ADDON_SWITCHES, ConversationAddonCommands


# Reuse the same properties/slots as Chat Tools; no second settings store.
TOGGLES = {
    "visualfollow": ("Auto-follow new visuals", "conversationVisualReplyAutoFollow", "toggleConversationVisualReplyAutoFollow"),
    "labels": ("Icon labels", "conversationActionLabelsEnabled", "toggleConversationActionLabels"),
    "guides": ("Placement guides", "conversationResponsePlacementGuidesEnabled", "toggleConversationResponsePlacementGuides"),
    "timestamps": ("Timestamps", "conversationTimestampsEnabled", "toggleConversationTimestamps"),
    "borders": ("Message borders", "conversationMessageBordersEnabled", "toggleConversationMessageBorders"),
    "searchcontrol": ("Show Web Search control", "conversationWebSearchVisible", "toggleConversationWebSearchVisible"),
    "resetbutton": ("Show Reset memory button", "conversationResetButtonVisible", "toggleConversationResetButtonVisible"),
    "autoscroll": ("Conversation autoscroll", "", ""),
    "splitview": ("Split console and conversation", "conversationConsoleVisible", "setConversationConsoleVisible"),
}
PROVIDERS = {"current": "Current chat model", "openai": "OpenAI", "xai": "xAI", "deepseek": "DeepSeek", "claude": "Claude"}
from core.conversation_command_definitions import WRITING

VISUAL_REFINE_COMMAND = "generate_visual_refine"
VISUAL_REFINE_INSTRUCTION = (
    "Refine the supplied text into a single image-generation prompt. Preserve the user's "
    "subjects, composition, style, exclusions and explicit constraints. Improve visual clarity "
    "and useful detail without contradicting the request. Return only the image prompt, "
    "without explanations, Markdown or slash commands. Do not answer or carry out the prompt."
)


class ConversationCommands(QtCore.QObject):
    changed = QtCore.Signal()
    draftChanged = QtCore.Signal()
    _finished = QtCore.Signal(int, object, str, str)

    def __init__(self, owner: Any) -> None:
        super().__init__(owner)
        self._owner = owner
        self._application = owner._application
        self._provider = "current"
        self._status = ""
        self._draft: dict[str, Any] = {"busy": False, "text": "", "original": "", "error": "", "ideas": []}
        self._serial = 0
        self._token: CancellationToken | None = None
        self._thread: threading.Thread | None = None
        self._session: object | None = None
        self._source_composer = ""
        self._closed = False
        self._voice_refresh_pending = False
        self._addons = ConversationAddonCommands(owner, self._message)
        self._addons.changed.connect(self.changed)
        self._finished.connect(self._receive, QtCore.Qt.ConnectionType.QueuedConnection)
        owner.configurationChanged.connect(self.changed)
        owner.providersChanged.connect(self.changed)
        owner.conversationChanged.connect(self._check_session)
        owner.conversationDraftStateChanged.connect(self._check_composer)
        owner.runtimeChanged.connect(self._check_runtime)
        owner.applicationClosingChanged.connect(self._check_shutdown)
        owner.quickPersonaChanged.connect(self.changed)

    @QtCore.Property(str, notify=changed)
    def selectedProvider(self) -> str:
        return self._provider

    @QtCore.Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @QtCore.Property("QVariantMap", notify=draftChanged)
    def draft(self) -> dict[str, Any]:
        return dict(self._draft)

    def _provider_option(self, choice: str) -> dict[str, Any]:
        values = self._application.config.snapshot().values
        active = str(values.get("chat_provider") or "lmstudio")
        provider = active if choice == "current" else choice
        settings = values.get("chat_provider_settings", {}).get(provider, {})
        model = str(values.get("model_name") if provider == active else settings.get("model_name") or "").strip()
        reason = ""
        if chat_providers.get_provider(provider) is None:
            reason = "Provider is not enabled"
        elif provider in PROVIDERS and provider != "current" and not chat_providers.provider_api_key(provider):
            reason = "API key not configured"
        elif not model or model.lower() in {"none", "select model", "select a model"}:
            reason = "No model configured"
        return {"id": choice, "label": PROVIDERS[choice], "provider": provider,
                "model": model, "enabled": not reason, "detail": reason or model}

    @QtCore.Property("QVariantList", notify=changed)
    def providerOptions(self) -> list[dict[str, Any]]:
        return [self._provider_option(key) for key in PROVIDERS]

    @QtCore.Slot(str)
    def selectProvider(self, choice: str) -> None:
        if choice not in PROVIDERS:
            return
        option = self._provider_option(choice)
        if not option["enabled"]:
            self._message(option["detail"])
            return
        self._provider = choice
        self._message(f"Command provider: {option['label']} · {option['model']}")

    def _message(self, text: str) -> None:
        self._status = text
        self.changed.emit()

    def _runtime_option(self, command: str) -> dict[str, Any]:
        running = bool(self._owner.systemRunning)
        starting = bool(getattr(self._owner, "runtimeStarting", False))
        stopping = bool(getattr(self._owner, "runtimeStopping", False))
        cleanup = bool(getattr(self._owner, "runtimeCleanupPending", False))
        reason = ""
        if self._closed or self._owner.applicationClosing:
            reason = "NC is closing"
        elif stopping:
            reason = "NC is stopping"
        elif command == "initialize":
            if starting:
                reason = "NC is already starting"
            elif running:
                reason = "NC is already running"
            elif cleanup:
                reason = "Finish runtime cleanup before initializing NC"
        elif not running:
            reason = "NC is starting" if starting else "NC is already stopped"
        return {"command": f"/{command} NC",
                "description": "Initialize NeuralCompanion" if command == "initialize" else "Stop the NC runtime",
                "detail": reason or ("Start NC" if command == "initialize" else "Keep the app open"),
                "enabled": not reason}

    @QtCore.Slot(str, bool, result="QVariantList")
    def choices(self, text: str, autoscroll: bool) -> list[dict[str, Any]]:
        query = text.strip().lower()
        if query == "/persona" or query.startswith("/persona "):
            return self._persona_choices(query[len("/persona"):].strip())
        if query == "/voice" or query.startswith("/voice "):
            return self._voice_choices(query[len("/voice"):].strip())
        if query == "/audiostory" or query.startswith("/audiostory "):
            return self._addons.choices(query[1:])
        if not query.startswith("/") or any(char.isspace() for char in text.lstrip()):
            return []
        prefix = query[1:]
        if prefix == "commands":
            prefix = ""
        rows = [{"command": "/commands", "description": "Show all commands", "detail": "", "enabled": True}]
        rows += [{"command": "/" + key, "description": item[0], "detail": "Editable draft", "enabled": True} for key, item in WRITING.items()]
        rows += [{"command": "/" + item["id"], "description": item["label"],
                  "detail": ("Selected · " if item["id"] == self._provider else "") + item["detail"],
                  "enabled": item["enabled"]} for item in self.providerOptions]
        for key, (label, prop, _slot) in TOGGLES.items():
            value = autoscroll if key == "autoscroll" else bool(getattr(self._owner, prop, False))
            rows.append({"command": "/" + key, "description": label,
                         "detail": "On" if value else "Off", "enabled": True})
        rows += [self._runtime_option(key) for key in ("initialize", "stop")]
        rows += self._addons.choices(prefix)
        rows.append({"command": "/persona", "description": "Choose and activate a saved persona",
                     "detail": "Show personas", "enabled": not self._owner.applicationClosing})
        rows.append({"command": "/voice", "description": "Choose the conversation voice",
                     "detail": "Persona changes restore its saved voice", "enabled": not self._owner.applicationClosing})
        config = self._visual_config()
        unavailable = self._visual_unavailable(config)
        rows.append({"command": "/generate_visual", "description": "Generate an image from your prompt",
                     "detail": unavailable or "Uses the current Visual Reply provider and settings", "enabled": not unavailable})
        rows.append({"command": "/" + VISUAL_REFINE_COMMAND, "description": "Refine an image prompt for review",
                     "detail": "Edit the refined prompt, then choose Generate image",
                     "enabled": not self._closed and not self._owner.applicationClosing and bool(self._owner.systemRunning)})
        rows.append({"command": "/restart_nc", "description": "Restart the NeuralCompanion desktop",
                     "detail": "Confirm with Enter; cancel with Esc",
                     "enabled": not self._closed and not self._owner.applicationClosing
                     and callable(getattr(self._owner, "requestDesktopRestartConfirmation", None))})
        return [row for row in rows if row["command"][1:].startswith(prefix)]

    def _visual_config(self) -> dict[str, Any]:
        config = dict(self._application.config.snapshot().values)
        # An explicit request follows the existing visual-variation behavior;
        # automatic Visual Reply settings are never changed or persisted.
        config.update(visual_reply_mode="auto", visual_replies_enabled=True)
        return config

    def _visual_unavailable(self, config: dict[str, Any]) -> str:
        if self._closed or self._owner.applicationClosing:
            return "NC is closing."
        if not self._owner.systemRunning or getattr(self._owner, "runtimeStopping", False):
            return "Initialize NeuralCompanion before generating an image."
        if self._owner.conversationEditMode or self._owner.conversationContextBusy:
            return "Finish the conversation edit or context operation first."
        if not callable(getattr(getattr(self._application, "addon_visual_request", None), "request_generation", None)):
            return "Visual Reply is unavailable."
        if not VisualReplyRuntime(lambda: config).generation_available():
            return "Configure the active Visual Reply provider before generating an image."
        return ""

    def _generate_visual(self, prompt: str) -> dict[str, Any]:
        config = self._visual_config()
        unavailable = self._visual_unavailable(config)
        if unavailable:
            return self._error(unavailable)
        try:
            # The runtime owner submits to the existing VisualService worker queue.
            accepted = bool(self._application.addon_visual_request.request_generation(
                prompt, source_text=prompt, request_id="visual_command_" + uuid.uuid4().hex,
                runtime_config_override=config,
                asset_metadata={"standalone_visual_reply": True},
            ))
        except (OSError, RuntimeError, TypeError, ValueError):
            return self._error("Visual Reply could not queue the image. Check the active provider and connection.")
        if not accepted:
            return self._error("Visual Reply did not accept the image request. Check the active provider and runtime.")
        self._message("Image generation queued")
        return {"action": "local"}

    def _refresh_voice_choices(self) -> None:
        self._voice_refresh_pending = False
        if not self._closed:
            self.changed.emit()

    def _voice_choices(self, query: str) -> list[dict[str, Any]]:
        state = self._owner._remote_voice_state()
        if state.get("loading") and not self._voice_refresh_pending and not self._closed:
            self._voice_refresh_pending = True
            QtCore.QTimer.singleShot(250, self._refresh_voice_choices)
        rows = []
        self._voice_command_items = list(state.get("items", []))
        for index, item in enumerate(self._voice_command_items, 1):
            label = str(item["label"])
            if query.strip('"').casefold() not in label.casefold() and not str(index).startswith(query):
                continue
            rows.append({"command": f"/voice {index}", "description": label,
                         "detail": "Current voice" if item["value"] == state.get("selected") else "Use this voice",
                         "enabled": bool(state.get("available")) and not self._closed and not self._owner.applicationClosing})
        return rows or [{"command": "/voice", "description": "Loading voices…" if state.get("loading") else "No matching voices",
                        "detail": "Choose from the desktop voice library", "enabled": False}]

    def _activate_voice(self, argument: str) -> dict[str, Any]:
        if self._closed or self._owner.applicationClosing:
            return self._error("NC is closing")
        if not argument:
            return {"action": "complete", "text": "/voice "}
        query = argument.strip('"').casefold()
        state = self._owner._remote_voice_state()
        items = getattr(self, "_voice_command_items", state.get("items", []))
        matches = ([items[int(query) - 1]] if query.isdigit() and 0 < int(query) <= len(items) else
                   [item for item in items if item["label"].casefold() == query])
        if len(matches) != 1:
            return self._error("Choose a voice from /voice using its number or unique full name.")
        try:
            result = self._owner._remote_apply_voice(matches[0]["value"])
        except (OSError, RuntimeError, TypeError, ValueError):
            result = {"accepted": False}
        if not result.get("accepted"):
            return self._error("Voice was not changed. Check the app notification.")
        self._message(f"Conversation voice: {matches[0]['label']}. Switching persona restores its voice.")
        return {"action": "local"}

    def _persona_choices(self, query: str) -> list[dict[str, Any]]:
        rows = []
        for persona in self._owner.quickPersonaChoices:
            slot = int(persona["slot"]) + 1
            name = str(persona.get("name") or f"Persona {slot}")
            if query.strip('"').casefold() not in name.casefold() and not str(slot).startswith(query):
                continue
            rows.append({"command": f"/persona {slot}", "description": name,
                         "detail": "Active" if persona.get("active") else f"Slot {slot}",
                         "enabled": not self._closed and not self._owner.applicationClosing})
        return rows or [{"command": "/persona", "description": "No matching saved personas",
                        "detail": "Save a persona in Persona settings", "enabled": False}]

    def _activate_persona(self, argument: str) -> dict[str, Any]:
        if self._closed or self._owner.applicationClosing:
            return self._error("NC is closing")
        if not argument:
            return {"action": "complete", "text": "/persona "}
        query = argument.strip('"').casefold()
        matches = [p for p in self._owner.quickPersonaChoices
                   if str(int(p["slot"]) + 1) == query or str(p.get("name") or "").casefold() == query]
        if len(matches) != 1:
            return self._error("Choose a persona from /persona using its slot number or unique full name.")
        persona = matches[0]
        try:
            self._owner.applyQuickPersona(int(persona["slot"]))
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            return self._error(f"Persona activation failed: {error}")
        if self._owner.activeQuickPersona.get("slot") != persona["slot"]:
            return self._error("Persona was not activated. Check the app notification for details.")
        self._message(f"Persona activated: {persona.get('name') or argument}")
        return {"action": "local"}

    def _error(self, message: str) -> dict[str, Any]:
        self._message(message)
        return {"action": "error", "message": message}

    @QtCore.Slot(str, bool, result="QVariantMap")
    def execute(self, text: str, autoscroll: bool) -> dict[str, Any]:
        value = text.strip()
        if not value.startswith("/"):
            return {"action": "chat"}
        parts = value[1:].split(maxsplit=1)
        command = parts[0].lower() if parts else "commands"
        argument = parts[1].strip() if len(parts) > 1 else ""
        if command == "commands" and not argument:
            return {"action": "menu"}
        if command == "restart_nc":
            if argument:
                return self._error("Use /restart_nc without extra text.")
            if self._closed or self._owner.applicationClosing:
                return self._error("NC is already closing.")
            request = getattr(self._owner, "requestDesktopRestartConfirmation", None)
            if not callable(request) or not request():
                return self._error("Desktop restart is unavailable.")
            self._message("Confirm the desktop restart with Enter, or cancel with Esc.")
            return {"action": "local"}
        if command in {"generate_visual", VISUAL_REFINE_COMMAND}:
            if not argument:
                return {"action": "complete", "text": f"/{command} "}
            if command == "generate_visual":
                return self._generate_visual(argument)
            return self._generate(command, argument, value)
        if command == "persona":
            return self._activate_persona(argument)
        if command == "voice":
            return self._activate_voice(argument)
        if command in ADDON_SWITCHES or command == "audiostory":
            return self._addons.execute(command, argument)
        if command in {"initialize", "stop"}:
            if argument.lower() not in {"", "nc"}:
                return self._error(f"Use /{command} NC.")
            option = self._runtime_option(command)
            if not option["enabled"]:
                return self._error(option["detail"])
            if command == "initialize":
                self._owner.initializeSystem()
                self._message("NC initialization requested")
            else:
                self.cancel()
                self._owner.terminateSystem()
                self._message("NC stop requested")
            return {"action": "local"}
        if command in PROVIDERS:
            if argument:
                return self._error(f"Use /{command} without extra text.")
            option = self._provider_option(command)
            if not option["enabled"]:
                return self._error(option["detail"])
            self.selectProvider(command)
            return {"action": "local"}
        if command in TOGGLES:
            if argument.lower() not in {"", "on", "off"}:
                return self._error(f"Use /{command}, /{command} on or /{command} off.")
            label, prop, slot = TOGGLES[command]
            current = autoscroll if command == "autoscroll" else bool(getattr(self._owner, prop))
            desired = not current if not argument else argument.lower() == "on"
            if command != "autoscroll" and current != desired:
                callback = getattr(self._owner, slot)
                callback(desired) if command == "splitview" else callback()
            actual = desired if command == "autoscroll" else bool(getattr(self._owner, prop))
            self._message(f"{label}: {'On' if actual else 'Off'}")
            return {"action": "autoscroll" if command == "autoscroll" else "local", "value": actual}
        if command in WRITING:
            if not argument:
                return {"action": "complete", "text": f"/{command} "}
            return self._generate(command, argument, value)
        return self._error("Unknown command. Type /commands to see the available choices.")

    def _generate(self, command: str, argument: str, original: str) -> dict[str, Any]:
        if self._closed or self._owner.applicationClosing or not self._owner.systemRunning:
            return self._error("Initialize NeuralCompanion before creating a draft.")
        if self._owner.conversationEditMode or self._owner.conversationContextBusy:
            return self._error("Finish the conversation edit or context operation first.")
        if self._thread is not None and self._thread.is_alive():
            return self._error("The previous command request is still finishing. Please wait.")
        option = self._provider_option(self._provider)
        if not option["enabled"]:
            return self._error(option["detail"])
        api = self._application.addon_chat
        try:
            config = self._application.config.snapshot()
            selection = api.capture_provider_selection(config, provider_id=option["provider"], model_id=option["model"])
            instruction = VISUAL_REFINE_INSTRUCTION if command == VISUAL_REFINE_COMMAND else WRITING[command][1]
            if command == VISUAL_REFINE_COMMAND:
                rules = rules_for_config(config.values)
                if rules:
                    instruction += " " + refinement_instruction(rules)
            params: dict[str, Any] = {"model": selection.model_id, "messages": [
                {"role": "system", "content": instruction + " Preserve explicit constraints and the user's intent. Return only the requested draft, without a preamble. Do not invent factual claims."},
                {"role": "user", "content": argument},
            ]}
            additional: dict[str, Any] = {}
            api.apply_provider_generation_fields(selection, params, additional)
            prepared = api.prepare_provider_request(selection, PromptRequest.from_payload(params, additional))
            session = self._application.chat.snapshot().session_generation
        except Exception:
            return self._error("Could not prepare this provider. Check its configuration and model.")
        self._serial += 1
        serial = self._serial
        token = CancellationToken()
        self._token = token
        self._session = session
        self._source_composer = str(self._owner.conversationDraftState.get("composerText") or "")
        if command == VISUAL_REFINE_COMMAND:
            # A cancelled/failed image refinement must not expose a previous
            # writing draft under the new Generate image action.
            self._draft.update(text="", ideas=[])
        self._draft.update(busy=True, original=original, command=command, error="", provider=f"{option['label']} · {option['model']}")
        self.draftChanged.emit()
        self._message("Preparing draft; waiting for active chat turns to finish if needed…")
        application = self._application

        def worker() -> None:
            result_text, error = "", ""
            try:
                while application.chat.has_active_turns() or application.interaction.pending_count():
                    if token.wait(.1):
                        return
                if token.cancelled:
                    return
                # Detached frozen request: no turn acceptance, model preparation,
                # history mutation, persona reply delivery or shared cancellation.
                result = api.complete_provider_request(prepared, token)
                if not result.accepted:
                    error = str(getattr(result.failure, "message", "Provider request failed."))
                else:
                    result_text = str(result.value or "").strip()
                    if not result_text:
                        error = "The provider returned an empty draft. Your original request is preserved."
            except Exception:
                error = "Draft generation failed. Check the provider configuration and connection, then retry."
            if not token.cancelled:
                try:
                    self._finished.emit(serial, session, result_text, error)
                except RuntimeError:
                    pass  # The UI may have been destroyed during shutdown.

        self._thread = threading.Thread(target=worker, name="nc-command-draft", daemon=True)
        self._thread.start()
        return {"action": "draft"}

    @QtCore.Slot(int, object, str, str)
    def _receive(self, serial: int, session: object, text: str, error: str) -> None:
        if self._closed or serial != self._serial:
            return
        if session != self._application.chat.snapshot().session_generation:
            self.discard()
            return
        self._token = None
        self._draft.update(busy=False, error=error)
        if not error:
            ideas: list[str] = []
            if self._draft.get("command") == "ideas":
                try:
                    value = json.loads(text.removeprefix("```json").removeprefix("```").removesuffix("```").strip())
                    if isinstance(value, list):
                        ideas = [x for x in value if isinstance(x, str) and x.strip()][:5]
                except ValueError:
                    pass
            self._draft.update(text="" if ideas else text, ideas=ideas)
            if str(self._owner.conversationDraftState.get("composerText") or "").strip() == self._draft["original"]:
                self._owner.setConversationComposerDraft("")
        self.draftChanged.emit()
        self._message(error or ("Image prompt ready · Review before generating" if self._draft.get("command") == VISUAL_REFINE_COMMAND else "Draft ready · Not sent"))

    @QtCore.Slot(str)
    def setDraftText(self, text: str) -> None:
        if not self._draft["busy"]:
            self._draft["text"] = text
            self.draftChanged.emit()

    @QtCore.Slot(int)
    def chooseIdea(self, index: int) -> None:
        ideas = self._draft.get("ideas", [])
        if 0 <= index < len(ideas):
            self._draft.update(text=ideas[index], ideas=[])
            self.draftChanged.emit()

    @QtCore.Slot()
    def regenerate(self) -> None:
        self.execute(str(self._draft["original"]), True)

    @QtCore.Slot()
    def cancel(self) -> None:
        self._serial += 1
        if self._token is not None:
            self._token.cancel("command_cancelled")
            self._token = None
        self._draft["busy"] = False
        self.draftChanged.emit()

    @QtCore.Slot()
    def discard(self) -> None:
        self.cancel()
        self._draft.update(text="", original="", error="", ideas=[])
        self._session = None
        self.draftChanged.emit()

    @QtCore.Slot()
    def restore(self) -> None:
        current = str(self._owner.conversationDraftState.get("composerText") or "")
        original = str(self._draft["original"])
        if current and current != original:
            self._message("Keep or clear your newer message before restoring the original request.")
            return
        self.discard()
        self._owner.setConversationComposerDraft(original)

    @QtCore.Slot()
    def copy(self) -> None:
        QtGui.QGuiApplication.clipboard().setText(str(self._draft["text"]))

    @QtCore.Slot(result=bool)
    def sendDraft(self) -> bool:
        self._check_session()
        text = str(self._draft["text"]).strip()
        if not text or self._draft["busy"] or not self._owner.systemRunning or self._owner.conversationEditMode or self._owner.conversationContextBusy:
            return False
        if self._draft.get("command") == VISUAL_REFINE_COMMAND:
            result = self._generate_visual(text)
            if result["action"] != "local":
                self._draft["error"] = result.get("message", "Image generation was not started.")
                self.draftChanged.emit()
                return False
            self.discard()
            self._message("Image generation queued")
            return True
        if self._owner.submitConversationTurn(text):
            self.discard()
            self._message("Draft sent")
            return True
        return False

    def _check_composer(self) -> None:
        if self._draft["busy"] and self._owner.conversationDraftState.get("composerText", "") != self._source_composer:
            self.cancel()
            self._message("Draft request cancelled because the input changed.")

    def _check_session(self) -> None:
        if self._session is not None and self._session != self._application.chat.snapshot().session_generation:
            self.discard()

    def _check_runtime(self) -> None:
        if not self._owner.systemRunning and self._draft["busy"]:
            self.cancel()
        self.changed.emit()

    def _check_shutdown(self) -> None:
        # Shutdown can be rejected by another workspace; keep this controller usable.
        if self._owner.applicationClosing:
            self.cancel()

    def close(self) -> None:
        self._closed = True
        self._addons.close()
        self.cancel()
