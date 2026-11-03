"""Immutable prompt records and side-effect-free request assembly."""

from __future__ import annotations
from core.persona_prompt_builder import persona_prompt_text

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from core import conversation_history as conversation_history_runtime
from core.text_tags import persona_mood_instructions
from core.runtime.conversation import (
    AcceptedTurn,
    ConversationMessage,
    ConversationSnapshot,
)
from core.runtime.identifiers import (
    RouteGeneration,
    RunId,
    SessionGeneration,
    TurnId,
    WorkLease,
)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return [_thaw(item) for item in value]
    return value


def _freeze_mapping(values: Mapping[str, object] | None) -> Mapping[str, object]:
    if values is None:
        return MappingProxyType({})
    if not isinstance(values, Mapping):
        raise TypeError("Prompt request options must be mappings.")
    return MappingProxyType(
        {str(key): _freeze(value) for key, value in values.items()}
    )


@dataclass(frozen=True, slots=True)
class PromptMessage:
    """One immutable provider-neutral prompt message."""

    role: str
    content: object
    metadata: Mapping[str, object] = field(default_factory=dict)
    placement: str = "context"
    document_ticket: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        role = str(self.role or "user").strip().lower() or "user"
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "content", _freeze(self.content))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        placement = str(self.placement or "context").strip().lower()
        if placement not in {
            "context",
            "before_user_turn",
            "after_history",
            "after_latest_user",
            "with_latest_user",
        }:
            raise ValueError(f"Unknown prompt message placement: {placement}")
        object.__setattr__(self, "placement", placement)

    @classmethod
    def from_mapping(cls, message: Mapping[str, object]) -> PromptMessage:
        if not isinstance(message, Mapping):
            raise TypeError("Prompt messages must be mappings.")
        metadata = {
            str(key): value
            for key, value in message.items()
            if str(key) not in {"role", "content", "_nc_document_ticket"}
        }
        return cls(
            role=str(message.get("role", "user") or "user"),
            content=message.get("content", ""),
            metadata=metadata,
            document_ticket=message.get("_nc_document_ticket"),
        )

    def to_mapping(self) -> dict[str, object]:
        result = {
            str(key): _thaw(value) for key, value in self.metadata.items() if key != "_nc_document_ticket"
        }
        result["role"] = self.role
        result["content"] = _thaw(self.content)
        return result


@dataclass(frozen=True, slots=True)
class PromptImagePart:
    """One immutable image part attached to the accepted user turn."""

    image_url: str
    detail: str | None = None

    def __post_init__(self) -> None:
        image_url = str(self.image_url or "").strip()
        if not image_url:
            raise ValueError("Prompt image parts require an image URL.")
        detail = str(self.detail or "").strip() or None
        object.__setattr__(self, "image_url", image_url)
        object.__setattr__(self, "detail", detail)

    def to_mapping(self) -> dict[str, object]:
        image: dict[str, object] = {"url": self.image_url}
        if self.detail is not None:
            image["detail"] = self.detail
        return {"type": "image_url", "image_url": image}


@dataclass(frozen=True, slots=True)
class PromptRequest:
    """A detached generic request ready for provider-specific preparation."""

    messages: tuple[PromptMessage, ...]
    model_id: str | None = None
    parameters: Mapping[str, object] = field(default_factory=dict, repr=False)
    additional_parameters: Mapping[str, object] = field(
        default_factory=dict,
        repr=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        if self.model_id is not None:
            object.__setattr__(self, "model_id", str(self.model_id))
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters))
        object.__setattr__(
            self,
            "additional_parameters",
            _freeze_mapping(self.additional_parameters),
        )

    def with_options(
        self,
        *,
        model_id: str | None,
        parameters: Mapping[str, object] | None = None,
        additional_parameters: Mapping[str, object] | None = None,
    ) -> PromptRequest:
        return replace(
            self,
            model_id=model_id,
            parameters=parameters or {},
            additional_parameters=additional_parameters or {},
        )

    def without_document_context(self) -> PromptRequest:
        from core.runtime.document_context import DocumentContextTicket
        return replace(self, messages=tuple(m for m in self.messages if not isinstance(m.document_ticket, DocumentContextTicket)))

    @classmethod
    def from_payload(
        cls,
        params: Mapping[str, object],
        additional_params: Mapping[str, object] | None = None,
    ) -> PromptRequest:
        if not isinstance(params, Mapping):
            raise TypeError("Prompt request payload must be a mapping.")
        source = dict(params)
        raw_messages = source.pop("messages", ())
        if not isinstance(raw_messages, Sequence) or isinstance(
            raw_messages,
            (str, bytes, bytearray),
        ):
            raise TypeError("Prompt request messages must be a sequence.")
        model_id = source.pop("model", None) if "model" in source else None
        return cls(
            messages=tuple(
                PromptMessage.from_mapping(message)
                for message in raw_messages
            ),
            model_id=None if model_id is None else str(model_id),
            parameters=source,
            additional_parameters=additional_params or {},
        )

    def params_copy(self) -> dict[str, object]:
        params = {
            str(key): _thaw(value) for key, value in self.parameters.items()
        }
        if self.model_id is not None:
            params["model"] = self.model_id
        params["messages"] = [message.to_mapping() for message in self.messages]
        return params

    def additional_params_copy(self) -> dict[str, object]:
        return {
            str(key): _thaw(value)
            for key, value in self.additional_parameters.items()
        }


@dataclass(frozen=True, slots=True)
class PromptInputs:
    conversation: ConversationSnapshot
    user_turn: AcceptedTurn | None
    persona_messages: tuple[PromptMessage, ...] = ()
    memory_messages: tuple[PromptMessage, ...] = ()
    identity_messages: tuple[PromptMessage, ...] = ()
    sensory_messages: tuple[PromptMessage, ...] = ()
    addon_messages: tuple[PromptMessage, ...] = ()
    image_parts: tuple[PromptImagePart, ...] = ()
    overflow_policy: str = "rolling_window"
    request_only_continue_cue: bool = False
    strip_conversation_images: bool = False

    def __post_init__(self) -> None:
        for name in (
            "persona_messages",
            "memory_messages",
            "identity_messages",
            "sensory_messages",
            "addon_messages",
            "image_parts",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(
            self,
            "overflow_policy",
            str(self.overflow_policy or "rolling_window").strip().lower(),
        )
        object.__setattr__(
            self,
            "request_only_continue_cue",
            bool(self.request_only_continue_cue),
        )
        object.__setattr__(
            self,
            "strip_conversation_images",
            bool(self.strip_conversation_images),
        )


@dataclass(frozen=True, slots=True)
class PromptRuntimeState:
    """Request-local domain state captured before prompt preparation."""

    history: tuple[Mapping[str, object], ...]
    prompt_state: Mapping[str, object]
    config_state: Mapping[str, object]
    identity_relay_context: Mapping[str, object] | None = None
    provider_context: object | None = None
    request_only_continue_cue: bool = False
    session_lease: object | None = None
    memory_work_context: object | None = None
    accepted_transaction_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "history",
            tuple(
                copy.deepcopy(dict(turn))
                for turn in self.history
                if isinstance(turn, Mapping)
            ),
        )
        object.__setattr__(self, "prompt_state", _freeze_mapping(self.prompt_state))
        object.__setattr__(self, "config_state", _freeze_mapping(self.config_state))
        if self.identity_relay_context is not None:
            object.__setattr__(
                self,
                "identity_relay_context",
                _freeze_mapping(self.identity_relay_context),
            )
        object.__setattr__(
            self,
            "request_only_continue_cue",
            bool(self.request_only_continue_cue),
        )
        object.__setattr__(
            self,
            "accepted_transaction_id",
            str(self.accepted_transaction_id or "").strip(),
        )


@dataclass(frozen=True, slots=True)
class PromptAssemblyCallbacks:
    """Domain collectors used by the provider-neutral assembly policy."""

    resolve_state: Callable[[object], PromptRuntimeState]
    explain_help_lookup: Callable[[Sequence[Mapping[str, object]], bool], Mapping[str, object]]
    build_help_context: Callable[[Sequence[Mapping[str, object]], bool], str]
    collect_addon_contexts: Callable[[Sequence[Mapping[str, object]]], Sequence[Mapping[str, object]]]
    build_continuity_context: Callable[[Mapping[str, object], str], str]
    build_long_term_memory_recall: Callable[
        [Sequence[Mapping[str, object]], object | None, Mapping[str, object]],
        tuple[str, Sequence[Mapping[str, object]], str],
    ]
    visual_instruction: Callable[[Mapping[str, object]], str]
    sensory_instruction: Callable[[Mapping[str, object]], str]
    companion_orb_context: Callable[[Sequence[Mapping[str, object]], Mapping[str, object]], str]
    retained_sensory_context: Callable[[], str]
    active_hidden_context: Callable[[], str]
    build_turn_message: Callable[
        [Mapping[str, object], Mapping[str, object]],
        Mapping[str, object] | None,
    ]
    active_hidden_prompt: Callable[[], Mapping[str, object] | None]
    sensory_messages: Callable[
        [Mapping[str, object], Mapping[str, object]],
        Sequence[Mapping[str, object]],
    ]
    apply_generation_fields: Callable[[dict[str, object], dict[str, object]], None]
    run_id: Callable[[], RunId]
    current_session_generation: Callable[[], SessionGeneration]
    log: Callable[[str], None]


@dataclass(frozen=True, slots=True)
class PromptStateCaptureCallbacks:
    """Adapters for capturing engine-owned state without composing prompts."""

    transaction_for_request: Callable[[object], object | None]
    identity_relay_metadata: Callable[[object], Mapping[str, object] | None]
    active_continuity_memory_id: Callable[[], str]
    live_history: Callable[[], Sequence[Mapping[str, object]]]
    live_config: Callable[[], Mapping[str, object]]


class FrozenPromptStateUnavailable(RuntimeError):
    """A normal-chat request lost state frozen at turn acceptance."""


def capture_prompt_runtime_state(
    request_context: object,
    callbacks: PromptStateCaptureCallbacks,
) -> PromptRuntimeState:
    """Capture the frozen transaction state or a detached legacy live view."""

    if not isinstance(callbacks, PromptStateCaptureCallbacks):
        raise TypeError("Prompt state capture requires PromptStateCaptureCallbacks.")
    frozen_history = None
    identity_context = None
    provider_context = None
    prompt_state = None
    config_state = None
    cue = False
    session_lease = None
    memory_work_context = None
    accepted_transaction_id = ""
    is_normal_chat = bool(
        isinstance(request_context, dict)
        and request_context.get("kind") == "normal_chat"
    )
    if is_normal_chat:
        transaction = callbacks.transaction_for_request(request_context)
        if not isinstance(transaction, Mapping):
            raise FrozenPromptStateUnavailable(
                "Normal Chat prompt assembly requires its frozen transaction."
            )
        if "history" not in request_context:
            raise FrozenPromptStateUnavailable(
                "Normal Chat prompt assembly requires frozen request history."
            )
        raw_history = request_context.get("history")
        if not isinstance(raw_history, Sequence) or isinstance(
            raw_history,
            (str, bytes, bytearray),
        ):
            raise FrozenPromptStateUnavailable(
                "Normal Chat prompt assembly requires frozen request history."
            )
        session_lease = request_context.get("session_lease")
        if session_lease is None:
            raise FrozenPromptStateUnavailable(
                "Normal Chat prompt assembly requires its frozen session lease."
            )
        accepted_transaction_id = str(
            request_context.get("normal_chat_transaction_id") or ""
        ).strip()
        if not accepted_transaction_id:
            raise FrozenPromptStateUnavailable(
                "Normal Chat prompt assembly requires its frozen transaction ID."
            )
        config_snapshot = transaction.get("config_snapshot")
        config_state = getattr(config_snapshot, "values", None)
        if not isinstance(config_state, Mapping):
            raise FrozenPromptStateUnavailable(
                "Normal Chat prompt assembly requires frozen runtime configuration."
            )
        prompt_state = transaction.get("prompt_state")
        if not isinstance(prompt_state, Mapping) or (
            prompt_state.get("_accepted_turn_frozen") is not True
        ):
            raise FrozenPromptStateUnavailable(
                "Normal Chat prompt assembly requires frozen accepted-turn state."
            )
        provider_context = transaction.get("provider_context")
        if provider_context is None:
            raise FrozenPromptStateUnavailable(
                "Normal Chat prompt assembly requires frozen provider context."
            )
        memory_work_context = transaction.get("memory_work_context")
        if memory_work_context is None:
            raise FrozenPromptStateUnavailable(
                "Normal Chat prompt assembly requires its frozen memory work context."
            )

        frozen_history = copy.deepcopy(list(raw_history))
        cue = bool(request_context.get("request_only_continue_cue", False))
        relay_context = request_context.get("identity_relay_context")
        if isinstance(relay_context, Mapping) and str(
            relay_context.get("context") or ""
        ):
            debug = relay_context.get("debug", {})
            identity_context = {
                "context": str(relay_context.get("context") or ""),
                "debug": dict(debug) if isinstance(debug, Mapping) else {},
            }
        relay_snapshot = request_context.get("identity_relay_snapshot")
        relay_metadata = callbacks.identity_relay_metadata(relay_snapshot)
        if relay_metadata is not None and relay_metadata.get("status") == "ready":
            prompt_text = str(
                (
                    (relay_snapshot or {}).get("prompt_text")
                    if isinstance(relay_snapshot, Mapping)
                    else ""
                )
                or ""
            )
            if prompt_text.strip():
                identity_context = {
                    "context": prompt_text,
                    "debug": {
                        "source": "identity_relay",
                        "artifact_ref": relay_metadata["artifact_ref"],
                        "snapshot_hash": relay_metadata["snapshot_hash"],
                        "schema_version": 2,
                        "projection_kind": "normalized_projection",
                    },
                }
    if config_state is None:
        config_state = callbacks.live_config()
    if prompt_state is None:
        prompt_state = config_state
    if not bool(prompt_state.get("_accepted_turn_frozen", False)):
        prompt_state = dict(prompt_state)
        prompt_state["continuity_memory_id"] = (
            callbacks.active_continuity_memory_id()
        )
    if frozen_history is None:
        frozen_history = copy.deepcopy(list(callbacks.live_history()))
    return PromptRuntimeState(
        history=tuple(frozen_history),
        prompt_state=prompt_state,
        config_state=config_state,
        identity_relay_context=identity_context,
        provider_context=provider_context,
        request_only_continue_cue=cue,
        session_lease=session_lease,
        memory_work_context=memory_work_context,
        accepted_transaction_id=accepted_transaction_id,
    )


class PromptAssemblyService:
    """Build provider-neutral requests without mutating inputs or shared state."""

    def build(self, inputs: PromptInputs) -> PromptRequest:
        if not isinstance(inputs, PromptInputs):
            raise TypeError("Prompt assembly requires PromptInputs.")

        typed_messages = (
            inputs.persona_messages
            + inputs.addon_messages
            + inputs.identity_messages
            + inputs.memory_messages
            + inputs.sensory_messages
        )
        messages = [
            message.to_mapping()
            for message in typed_messages
            if message.placement == "context"
        ]
        conversation_messages, accepted_is_represented = _conversation_messages(inputs)
        if not accepted_is_represented and inputs.user_turn is not None:
            conversation_messages.append(_accepted_turn_mapping(inputs.user_turn))
        conversation_messages = conversation_history_runtime.repair_model_history_window(
            conversation_messages,
            policy=inputs.overflow_policy,
        )
        if inputs.image_parts and inputs.user_turn is not None:
            _attach_image_parts(
                conversation_messages,
                inputs.user_turn,
                inputs.image_parts,
            )
        _merge_with_latest_user(conversation_messages, typed_messages)
        _insert_before_user_turn(
            conversation_messages,
            inputs.user_turn,
            typed_messages,
        )
        conversation_messages.extend(
            message.to_mapping()
            for message in typed_messages
            if message.placement == "after_history"
        )
        _insert_after_latest_user(conversation_messages, typed_messages)
        if inputs.strip_conversation_images:
            conversation_messages = _strip_image_parts(conversation_messages)
        conversation_messages = (
            conversation_history_runtime.prepare_request_history_messages(
                conversation_messages,
                cue_eligible=inputs.request_only_continue_cue,
            )
        )
        for message in conversation_messages:
            message.pop(_MESSAGE_ID_KEY, None)
        messages.extend(conversation_messages)
        return PromptRequest(
            messages=tuple(message for message in typed_messages if message.placement == "context")
                     + tuple(PromptMessage.from_mapping(message) for message in conversation_messages)
        )

    def build_runtime_request(
        self,
        request_context: object,
        callbacks: PromptAssemblyCallbacks,
    ) -> PromptRequest:
        """Capture typed prompt inputs and build one detached provider request."""

        if not isinstance(callbacks, PromptAssemblyCallbacks):
            raise TypeError("Runtime prompt assembly requires PromptAssemblyCallbacks.")
        state = callbacks.resolve_state(request_context)
        if not isinstance(state, PromptRuntimeState):
            raise TypeError("Prompt state capture returned an invalid value.")
        config = state.config_state
        policy = conversation_history_runtime.chat_context_overflow_policy(config)
        history = conversation_history_runtime.build_model_history_window(
            state.history,
            limit=conversation_history_runtime.chat_context_window_messages(config),
            policy=policy,
            assistant_prefix_anchor_threshold=5,
        )

        from core.provider_prompt_rules import resolve_rules
        rule_config = dict(config)
        rule_config.update(state.prompt_state)
        technical_rules = (str(state.prompt_state.get('emotional_instructions', ''))
                           if state.prompt_state.get('_accepted_turn_frozen')
                           else resolve_rules(rule_config))
        persona_messages: list[PromptMessage] = [
            PromptMessage(
                "system",
                f"{technical_rules}"
                f"{persona_mood_instructions(config)}"
                f"\n\n{persona_prompt_text(state.prompt_state)}",
            )
        ]
        preset_name = str(
            state.prompt_state.get("active_preset_name", "") or ""
        ).strip().lower()
        tutorial_persona = preset_name.replace("_", " ").replace("-", " ") == "tutorial persona"
        help_debug: Mapping[str, object] | None = None
        help_context = ""
        if tutorial_persona:
            help_debug = callbacks.explain_help_lookup(history, True)
            help_context = callbacks.build_help_context(history, True)
        else:
            latest = callbacks.explain_help_lookup(history, False)
            callbacks.log(
                "🧭 [AppHelp] Skipped: active_preset_name="
                f"{state.prompt_state.get('active_preset_name', '')!r} "
                f"query={str(latest.get('query', '') or '')[:120]!r}"
            )
        if help_context:
            topic_titles = ", ".join(
                str(item) for item in list((help_debug or {}).get("topic_titles", ()))
            )
            callbacks.log(
                "🧭 [AppHelp] Injected "
                f"{(help_debug or {}).get('topic_count', 0)} topic(s): {topic_titles}"
            )
            persona_messages.append(PromptMessage("system", help_context))
        elif help_debug is not None:
            callbacks.log(
                "🧭 [AppHelp] No context injected "
                f"(looks_like_app_question={help_debug.get('looks_like_app_question')}, "
                f"query={str(help_debug.get('query', '') or '')[:120]!r})"
            )

        addon_messages: list[PromptMessage] = []
        for addon_context in callbacks.collect_addon_contexts(history):
            if not isinstance(addon_context, Mapping):
                continue
            debug = addon_context.get("debug", {})
            debug = dict(debug) if isinstance(debug, Mapping) else {}
            sources = ", ".join(
                str(item) for item in list(debug.get("sources", ()))[:4]
            )
            callbacks.log(
                "[RAG] Injected "
                f"{debug.get('matches', '?')} matching chunk(s)"
                f"{f' from {sources}' if sources else ''}."
            )
            addon_messages.append(
                PromptMessage("system", addon_context.get("context", ""), document_ticket=addon_context.get("_nc_document_ticket"))
            )
            current_turn_context = addon_context.get("current_turn_context", "")
            if not isinstance(current_turn_context, str):
                raise TypeError("Addon current-turn context must be a string.")
            current_turn_image = (addon_context.get("current_turn_image", "")
                                  if config.get("model_supports_images") is True else "")
            if current_turn_image:
                if not isinstance(current_turn_image, str) or not current_turn_image.startswith("data:image/jpeg;base64,"):
                    raise ValueError("Addon current-turn image must be an inline JPEG image.")
                parts = ([{"type": "text", "text": current_turn_context.strip()}] if current_turn_context.strip() else [])
                parts.append({"type": "image_url", "image_url": {"url": current_turn_image}})
                addon_messages.append(PromptMessage("user", parts, placement="with_latest_user"))
            elif current_turn_context.strip():
                addon_messages.append(PromptMessage("user", current_turn_context.strip(), placement="after_latest_user"))

        identity_messages: list[PromptMessage] = []
        identity_context = state.identity_relay_context
        if identity_context is not None:
            debug = identity_context.get("debug", {})
            debug = dict(debug) if isinstance(debug, Mapping) else {}
            sources = ", ".join(
                str(item) for item in list(debug.get("sources", ()))[:4]
            )
            callbacks.log(
                "[RAG] Injected "
                f"{debug.get('matches', '?')} matching chunk(s)"
                f"{f' from {sources}' if sources else ''}."
            )
            identity_messages.append(
                PromptMessage("system", identity_context.get("context", ""))
            )

        memory_messages: list[PromptMessage] = []
        continuity_id = str(
            state.prompt_state.get("continuity_memory_id", "")
            or config.get("continuity_memory_id", "")
            or ""
        ).strip()
        memory_context = callbacks.build_continuity_context(config, continuity_id)
        if memory_context:
            callbacks.log("🧠 [Memory] Injected Continuity Memory.")
            memory_messages.append(PromptMessage("system", memory_context))
        long_term_context, asset_messages, image_lookup_guard = (
            callbacks.build_long_term_memory_recall(
                history,
                state.memory_work_context or state.session_lease,
                config,
            )
        )
        if long_term_context:
            callbacks.log("🧠 [Memory] Injected Long-Term Memory retrieval.")
            memory_messages.append(PromptMessage("system", long_term_context))
        asset_messages = tuple(asset_messages)
        if asset_messages:
            callbacks.log(
                "🧠 [Memory] Injected "
                f"{len(asset_messages)} Long-Term Memory image asset(s)."
            )
            memory_messages.extend(
                _prompt_message_from_mapping(message)
                for message in asset_messages
                if isinstance(message, Mapping)
            )
        if image_lookup_guard:
            memory_messages.append(
                PromptMessage(
                    "user",
                    image_lookup_guard,
                    placement="after_latest_user",
                )
            )

        sensory_messages: list[PromptMessage] = []
        visual_instruction = str(
            state.prompt_state.get("visual_reply_instruction", "")
            if "visual_reply_instruction" in state.prompt_state
            else callbacks.visual_instruction(config)
        ).strip()
        if visual_instruction:
            sensory_messages.append(PromptMessage("system", visual_instruction))
        sensory_instruction = str(
            state.prompt_state.get("sensory_feedback_instruction", "")
            if "sensory_feedback_instruction" in state.prompt_state
            else callbacks.sensory_instruction(config)
        ).strip()
        if sensory_instruction:
            sensory_messages.append(PromptMessage("system", sensory_instruction))
        companion_orb_context = callbacks.companion_orb_context(history, config)
        if companion_orb_context:
            sensory_messages.append(PromptMessage("system", companion_orb_context))
        retained_context = callbacks.retained_sensory_context()
        if retained_context:
            sensory_messages.append(PromptMessage("system", retained_context))
        hidden_context = callbacks.active_hidden_context()
        hidden_active = bool(hidden_context)
        if hidden_context:
            sensory_messages.append(PromptMessage("system", hidden_context))

        conversation, accepted, image_parts = _captured_conversation(
            history,
            state,
            callbacks,
        )
        if hidden_active:
            callbacks.log(
                "👁️ [Sensory] Skipping fresh sensory injection for hidden proactive "
                "reply; using queued hidden context instead."
            )
            hidden_prompt = callbacks.active_hidden_prompt()
            if isinstance(hidden_prompt, Mapping):
                sensory_messages.append(
                    _prompt_message_from_mapping(
                        hidden_prompt,
                        placement="after_history",
                    )
                )
        else:
            sensory_messages.extend(
                _prompt_message_from_mapping(
                    message,
                    placement="before_user_turn",
                )
                for message in callbacks.sensory_messages(
                    config,
                    state.prompt_state,
                )
                if isinstance(message, Mapping)
            )

        inputs = PromptInputs(
            conversation=conversation,
            user_turn=accepted,
            persona_messages=tuple(persona_messages),
            memory_messages=tuple(memory_messages),
            identity_messages=tuple(identity_messages),
            sensory_messages=tuple(sensory_messages),
            addon_messages=tuple(addon_messages),
            image_parts=image_parts,
            overflow_policy=policy,
            request_only_continue_cue=state.request_only_continue_cue,
            strip_conversation_images=bool(image_lookup_guard),
        )
        model_id = str(
            (
                getattr(state.provider_context, "model_name", "")
                if state.provider_context is not None
                else config.get("model_name", "")
            )
            or ""
        )
        parameters: dict[str, object] = {}
        additional_parameters: dict[str, object] = {}
        if state.provider_context is None:
            callbacks.apply_generation_fields(parameters, additional_parameters)
        return self.build(inputs).with_options(
            model_id=model_id,
            parameters=parameters,
            additional_parameters=additional_parameters,
        )


def _conversation_messages(
    inputs: PromptInputs,
) -> tuple[list[dict[str, object]], bool]:
    snapshot = inputs.conversation
    source_messages: Sequence[object] = tuple(
        getattr(snapshot, "messages", ()) or ()
    )
    accepted_message_id = str(
        getattr(getattr(inputs.user_turn, "message", None), "message_id", "") or ""
    )
    represented = False
    messages: list[dict[str, object]] = []
    for message in source_messages:
        message_id = str(getattr(message, "message_id", "") or "")
        if accepted_message_id and message_id == accepted_message_id:
            represented = True
        metadata = getattr(message, "metadata", {})
        prepared = (
            {str(key): _thaw(value) for key, value in metadata.items()}
            if isinstance(metadata, Mapping)
            else {}
        )
        prepared.update(
            {
                "role": str(getattr(message, "role", "user") or "user"),
                "content": _thaw(getattr(message, "content", "")),
                _MESSAGE_ID_KEY: message_id,
            }
        )
        messages.append(prepared)
    return messages, represented


def _prompt_message_from_mapping(
    message: Mapping[str, object],
    *,
    placement: str = "context",
) -> PromptMessage:
    prepared = PromptMessage.from_mapping(message)
    return replace(prepared, placement=placement)


def _captured_conversation(
    history: Sequence[Mapping[str, object]],
    state: PromptRuntimeState,
    callbacks: PromptAssemblyCallbacks,
) -> tuple[
    ConversationSnapshot,
    AcceptedTurn | None,
    tuple[PromptImagePart, ...],
]:
    prepared: list[tuple[Mapping[str, object], ConversationMessage]] = []
    accepted_transaction_id = state.accepted_transaction_id
    accepted_prepared_index: int | None = None
    for source_index, raw_turn in enumerate(history):
        if not isinstance(raw_turn, Mapping):
            continue
        built = callbacks.build_turn_message(raw_turn, state.config_state)
        if not isinstance(built, Mapping):
            continue
        metadata = {
            str(key): value
            for key, value in built.items()
            if str(key) not in {"role", "content"}
        }
        raw_transaction_id = str(
            raw_turn.get("normal_chat_transaction_id", "") or ""
        ).strip()
        is_accepted = bool(
            accepted_transaction_id
            and raw_transaction_id == accepted_transaction_id
        )
        message_id = (
            f"accepted-prompt-{accepted_transaction_id}"
            if is_accepted
            else f"runtime-prompt-{source_index}"
        )
        message = ConversationMessage(
            message_id=message_id,
            role=str(built.get("role", "user") or "user"),
            content=_freeze(built.get("content", "")),
            metadata=_freeze_mapping(metadata),
        )
        prepared.append((raw_turn, message))
        if is_accepted:
            accepted_prepared_index = len(prepared) - 1

    if accepted_prepared_index is None and prepared:
        accepted_prepared_index = len(prepared) - 1
    image_parts: tuple[PromptImagePart, ...] = ()
    if accepted_prepared_index is not None:
        raw_turn, accepted_message = prepared[accepted_prepared_index]
        del raw_turn
        accepted_message, image_parts = _extract_accepted_image_parts(
            accepted_message
        )
        prepared[accepted_prepared_index] = ({}, accepted_message)

    lease_generation = getattr(state.session_lease, "session_generation", None)
    session_generation = (
        lease_generation
        if isinstance(lease_generation, SessionGeneration)
        else callbacks.current_session_generation()
    )
    messages = tuple(message for _raw, message in prepared)
    snapshot = ConversationSnapshot(
        session_generation=session_generation,
        revision=0,
        messages=messages,
    )
    accepted: AcceptedTurn | None = None
    if accepted_prepared_index is not None:
        accepted_message = messages[accepted_prepared_index]
        turn_id = TurnId(accepted_message.message_id)
        accepted = AcceptedTurn(
            turn_id=turn_id,
            lease=WorkLease(
                run_id=callbacks.run_id(),
                session_generation=session_generation,
                turn_id=turn_id,
                route_generation=RouteGeneration(0),
            ),
            message=accepted_message,
        )
    return snapshot, accepted, image_parts


def _extract_accepted_image_parts(
    message: ConversationMessage,
) -> tuple[ConversationMessage, tuple[PromptImagePart, ...]]:
    content = _thaw(message.content)
    if not isinstance(content, list):
        return message, ()
    retained: list[object] = []
    images: list[PromptImagePart] = []
    for part in content:
        if not isinstance(part, Mapping) or str(
            part.get("type", "") or ""
        ).strip().lower() not in {"image", "image_url"}:
            retained.append(part)
            continue
        image_payload = part.get("image_url", part.get("image", ""))
        if isinstance(image_payload, Mapping):
            image_url = str(image_payload.get("url", "") or "").strip()
            detail = str(image_payload.get("detail", "") or "").strip() or None
        else:
            image_url = str(image_payload or "").strip()
            detail = None
        if not image_url:
            retained.append(part)
            continue
        images.append(PromptImagePart(image_url, detail=detail))
    if not images:
        return message, ()
    return (
        ConversationMessage(
            message_id=message.message_id,
            role=message.role,
            content=_freeze(retained),
            metadata=message.metadata,
        ),
        tuple(images),
    )


def _accepted_turn_mapping(turn: AcceptedTurn) -> dict[str, object]:
    message = turn.message
    result = {
        str(key): _thaw(value) for key, value in message.metadata.items()
    }
    result.update({
        "role": str(message.role or "user"),
        "content": _thaw(message.content),
        _MESSAGE_ID_KEY: str(message.message_id or ""),
    })
    return result


def _attach_image_parts(
    messages: list[dict[str, object]],
    turn: AcceptedTurn,
    image_parts: tuple[PromptImagePart, ...],
) -> None:
    target_message_id = str(turn.message.message_id or "")
    target_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if str(messages[index].get(_MESSAGE_ID_KEY, "") or "")
            == target_message_id
        ),
        None,
    )
    if target_index is None:
        return
    content = messages[target_index].get("content")
    if isinstance(content, list):
        parts = copy_prompt_parts(content)
    elif str(content or ""):
        parts = [{"type": "text", "text": str(content)}]
    else:
        parts = []
    parts.extend(part.to_mapping() for part in image_parts)
    messages[target_index] = {
        **messages[target_index],
        "content": parts,
    }


_MESSAGE_ID_KEY = "_nc_prompt_message_id"


def _insert_before_user_turn(
    messages: list[dict[str, object]],
    turn: AcceptedTurn | None,
    typed_messages: tuple[PromptMessage, ...],
) -> None:
    additions = [
        message.to_mapping()
        for message in typed_messages
        if message.placement == "before_user_turn"
    ]
    if not additions:
        return
    target_message_id = str(
        getattr(getattr(turn, "message", None), "message_id", "") or ""
    )
    target_index = next(
        (
            index
            for index, message in enumerate(messages)
            if target_message_id
            and str(message.get(_MESSAGE_ID_KEY, "") or "") == target_message_id
        ),
        None,
    )
    if target_index is None:
        target_index = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if str(messages[index].get("role", "") or "").strip().lower()
                == "user"
            ),
            len(messages),
        )
    messages[target_index:target_index] = additions


def _merge_with_latest_user(
    messages: list[dict[str, object]],
    typed_messages: tuple[PromptMessage, ...],
) -> None:
    additions = [message.to_mapping()["content"] for message in typed_messages
                 if message.placement == "with_latest_user"]
    if not additions:
        return
    current = next((message for message in reversed(messages) if message.get("role") == "user"), None)
    if current is None:
        return  # Evidence without a user question must not create a synthetic turn.
    content = current.get("content", "")
    parts = list(content) if isinstance(content, list) else [{"type": "text", "text": str(content)}]
    for addition in additions:
        parts.extend(addition if isinstance(addition, list) else [{"type": "text", "text": str(addition)}])
    current["content"] = parts


def _insert_after_latest_user(
    messages: list[dict[str, object]],
    typed_messages: tuple[PromptMessage, ...],
) -> None:
    additions = [
        message.to_mapping()
        for message in typed_messages
        if message.placement == "after_latest_user"
    ]
    if not additions:
        return
    target_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if str(messages[index].get("role", "") or "").strip().lower()
            == "user"
        ),
        None,
    )
    if target_index is None:
        messages.extend(additions)
    else:
        messages[target_index + 1:target_index + 1] = additions


def _strip_image_parts(
    messages: list[dict[str, object]],
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for source in messages:
        message = dict(source)
        content = message.get("content")
        if isinstance(content, list):
            message["content"] = [
                dict(item) if isinstance(item, Mapping) else item
                for item in content
                if not (
                    isinstance(item, Mapping)
                    and str(item.get("type", "") or "").strip().lower()
                    in {"image", "image_url"}
                )
            ]
            if not message["content"]:
                continue
        filtered.append(message)
    return filtered


def copy_prompt_parts(parts: Sequence[object]) -> list[object]:
    return [_thaw(_freeze(part)) for part in parts]


def prompt_inputs_from_message_mappings(
    *,
    context_messages: Sequence[Mapping[str, object]],
    history_messages: Sequence[Mapping[str, object]],
    run_id: RunId | None = None,
    session_generation: SessionGeneration | None = None,
) -> PromptInputs:
    """Adapt an already captured legacy request without retaining mutable payloads."""

    resolved_run_id = run_id or RunId(0)
    resolved_session = session_generation or SessionGeneration(0)
    prepared_history: list[ConversationMessage] = []
    for index, item in enumerate(history_messages):
        if not isinstance(item, Mapping):
            continue
        metadata = {
            str(key): value
            for key, value in item.items()
            if str(key) not in {"role", "content"}
        }
        prepared_history.append(
            ConversationMessage(
                message_id=f"legacy-prompt-{index}",
                role=str(item.get("role", "user") or "user"),
                content=_freeze(item.get("content", "")),
                metadata=_freeze_mapping(metadata),
            )
        )
    snapshot = ConversationSnapshot(
        session_generation=resolved_session,
        revision=0,
        messages=tuple(prepared_history),
    )
    accepted: AcceptedTurn | None = None
    if prepared_history:
        accepted_message = prepared_history[-1]
        turn_id = TurnId(accepted_message.message_id)
        accepted = AcceptedTurn(
            turn_id=turn_id,
            lease=WorkLease(
                run_id=resolved_run_id,
                session_generation=resolved_session,
                turn_id=turn_id,
                route_generation=RouteGeneration(0),
            ),
            message=accepted_message,
        )
    return PromptInputs(
        conversation=snapshot,
        user_turn=accepted,
        persona_messages=tuple(
            PromptMessage.from_mapping(message)
            for message in context_messages
            if isinstance(message, Mapping)
        ),
    )


__all__ = [
    "FrozenPromptStateUnavailable",
    "PromptAssemblyCallbacks",
    "PromptAssemblyService",
    "PromptImagePart",
    "PromptInputs",
    "PromptMessage",
    "PromptRequest",
    "PromptRuntimeState",
    "PromptStateCaptureCallbacks",
    "capture_prompt_runtime_state",
    "prompt_inputs_from_message_mappings",
]
