"""Finite composition root for the extracted production desktop runtime."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from core.runtime.conversation_addons import ConversationAddonBinding
from core.runtime.production_composer import ProductionApplicationBindingEdges
from core.runtime.production_desktop_compatibility_ports import (
    ProductionDesktopCompatibilityPorts,
)
from core.runtime.production_desktop_addon_ports import (
    ProductionDesktopAddonManagerPort,
)
from core.runtime.production_desktop_graph import (
    ProductionDesktopGraphInputs,
    build_default_production_desktop_application_composer,
)
from core.runtime.production_desktop_graph_ports import ProductionDesktopGraphPorts
from core.runtime.production_desktop_identity import build_production_desktop_identity
from core.runtime.production_desktop_realtime import (
    build_production_desktop_realtime_owners,
)
from core.runtime.production_desktop_realtime_ports import (
    ProductionDesktopRealtimeBindings,
    ProductionDesktopRealtimePorts,
    build_production_desktop_realtime_inputs,
)
from core.runtime.production_defaults import ProductionRuntimeDefaults
from core.runtime.production_factory import (
    ProductionFactoryInputs,
    build_default_production_bootstrap,
)
from core.runtime.production_bootstrap import ProductionBootstrap
from core.runtime.production_identity import (
    FrozenIdentityRelayTokenCounter,
    ProductionIdentityRelayRuntimeOwners,
)

@dataclass(frozen=True, slots=True)
class ProductionDesktopBootstrapInputs:
    """Named inputs for one real desktop runtime graph."""

    app_root: str | Path
    defaults: ProductionRuntimeDefaults
    realtime_ports: ProductionDesktopRealtimePorts
    realtime_bindings: ProductionDesktopRealtimeBindings
    addon_manager: ProductionDesktopAddonManagerPort
    graph_ports: ProductionDesktopGraphPorts
    compatibility_ports: ProductionDesktopCompatibilityPorts
    binding_edges: ProductionApplicationBindingEdges
    conversation_addon_binding: ConversationAddonBinding
    avatar_hand_debug: Mapping[str, object]
    identity_request_json: Callable[..., object]
    memory_embedding_request_json: Callable[..., object] | None = None
    memory_refresh_assets: Callable[[object], object] | None = None
    identity_clock: Callable[[], float] = time.time
    logger: Callable[[str], object] = print

    def __post_init__(self) -> None:
        if not isinstance(self.app_root, (str, Path)) or not str(self.app_root).strip():
            raise TypeError("app_root must be a non-empty path.")
        expected = (
            ("defaults", self.defaults, ProductionRuntimeDefaults),
            ("realtime_ports", self.realtime_ports, ProductionDesktopRealtimePorts),
            (
                "realtime_bindings",
                self.realtime_bindings,
                ProductionDesktopRealtimeBindings,
            ),
            (
                "addon_manager",
                self.addon_manager,
                ProductionDesktopAddonManagerPort,
            ),
            ("graph_ports", self.graph_ports, ProductionDesktopGraphPorts),
            (
                "compatibility_ports",
                self.compatibility_ports,
                ProductionDesktopCompatibilityPorts,
            ),
            ("binding_edges", self.binding_edges, ProductionApplicationBindingEdges),
            (
                "conversation_addon_binding",
                self.conversation_addon_binding,
                ConversationAddonBinding,
            ),
        )
        invalid = tuple(
            name for name, value, kind in expected if not isinstance(value, kind)
        )
        if invalid:
            raise TypeError(
                "Invalid production desktop bootstrap inputs: " + ", ".join(invalid)
            )
        if not isinstance(self.avatar_hand_debug, Mapping):
            raise TypeError("avatar_hand_debug must be a mapping.")
        callbacks = {
            "identity_request_json": self.identity_request_json,
            "identity_clock": self.identity_clock,
            "logger": self.logger,
        }
        if self.memory_embedding_request_json is not None:
            callbacks["memory_embedding_request_json"] = (
                self.memory_embedding_request_json
            )
        if self.memory_refresh_assets is not None:
            callbacks["memory_refresh_assets"] = self.memory_refresh_assets
        invalid_callbacks = tuple(
            name for name, callback in callbacks.items() if not callable(callback)
        )
        if invalid_callbacks:
            raise TypeError(
                "Invalid production desktop callbacks: "
                + ", ".join(invalid_callbacks)
            )


@dataclass(frozen=True, slots=True)
class ProductionDesktopApplicationBootstrap:
    """Retain the process bootstrap and lifecycle-owned Relay boundary."""

    bootstrap: ProductionBootstrap
    identity_runtime: ProductionIdentityRelayRuntimeOwners
    compatibility_ports: ProductionDesktopCompatibilityPorts


def build_production_desktop_bootstrap(
    inputs: ProductionDesktopBootstrapInputs,
) -> ProductionDesktopApplicationBootstrap:
    """Compose every extracted desktop boundary without importing the engine."""

    if not isinstance(inputs, ProductionDesktopBootstrapInputs):
        raise TypeError("Production desktop bootstrap inputs are required.")

    compatibility_ports = inputs.compatibility_ports
    identity_runtime = build_production_desktop_identity(
        compatibility_ports.identity_inputs(
            request_json=inputs.identity_request_json,
            logger=inputs.logger,
            clock=inputs.identity_clock,
        )
    )
    compatibility = compatibility_ports.compatibility(identity_runtime)
    realtime = build_production_desktop_realtime_owners(
        build_production_desktop_realtime_inputs(inputs.realtime_ports)
    )
    graph_ports = inputs.graph_ports
    graph_inputs = ProductionDesktopGraphInputs(
        app_root=inputs.app_root,
        realtime=realtime,
        realtime_bindings=inputs.realtime_bindings,
        addon_manager=inputs.addon_manager,
        compatibility=compatibility,
        compatibility_bindings=compatibility_ports.bindings,
        binding_edges=inputs.binding_edges,
        conversation_addon_binding=inputs.conversation_addon_binding,
        dry_run=graph_ports.dry_run,
        avatar_runtime_actions=graph_ports.avatar_runtime_actions,
        avatar_preview_state=graph_ports.avatar_preview_state,
        avatar_addon_gateway=graph_ports.avatar_addon_gateway,
        avatar_hand_debug=dict(inputs.avatar_hand_debug),
        presence_visual=graph_ports.presence_visual,
        reply_notifier=graph_ports.reply_notifier,
        speech_latency=graph_ports.speech_latency,
        sensory_history=graph_ports.sensory_history,
        push_to_talk_hold=graph_ports.push_to_talk_hold,
        push_to_talk_held=graph_ports.push_to_talk_held,
        contextual_replies=graph_ports.contextual_replies,
        avatar_emotions=graph_ports.avatar_emotions,
        seam_debug_directory=(
            Path(inputs.app_root).resolve() / "MuseTalk" / "runtime" / "seam_debug"
        ),
        logger=inputs.logger,
    )
    bootstrap = build_default_production_bootstrap(
        ProductionFactoryInputs(
            app_root=inputs.app_root,
            initial_config=inputs.defaults.config,
            realtime=realtime,
            identity_runtime=identity_runtime,
            application_composer=(
                build_default_production_desktop_application_composer(graph_inputs)
            ),
            identity_token_counter=FrozenIdentityRelayTokenCounter(),
            memory_embedding_request_json=inputs.memory_embedding_request_json,
            memory_refresh_assets=inputs.memory_refresh_assets,
            logger=inputs.logger,
        )
    )
    return ProductionDesktopApplicationBootstrap(
        bootstrap=bootstrap,
        identity_runtime=identity_runtime,
        compatibility_ports=compatibility_ports,
    )


__all__ = [
    "ProductionDesktopApplicationBootstrap",
    "ProductionDesktopBootstrapInputs",
    "build_production_desktop_bootstrap",
]
