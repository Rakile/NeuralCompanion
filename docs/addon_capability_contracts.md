# Addon Capability Contracts

This document names the addon capability surfaces that are intentionally
available to host code. It complements `docs/addon_lego_box_contract.md`, which
describes the wider addon boundary.

## Invocation Rules

Host code should reach addon-owned behavior through `AddonManager`:

- `invoke_capability(capability, payload)` broadcasts to initialized addons and
  returns the first non-`None` result.
- `invoke_all_capabilities(capability, payload)` broadcasts to initialized
  addons and returns every non-`None` result.
- `invoke_addon_capability(addon_id, capability, payload)` targets one known
  addon.
- `invoke_service_capability(service_id, capability, payload, **metadata_match)`
  targets the initialized addon that declares a matching manifest service.

Payloads are plain dictionaries. Callers should pass only the host surfaces that
the capability needs, such as `backend`, `bridge`, `runtime_config`, `settings`,
`args`, or `kwargs`. Addons may normalize or copy payload data before using it.

Unsupported, disabled, or unavailable capabilities return `None`. Addons should
not raise for missing optional host surfaces; failures are logged by the manager
and treated as no result.

## Capability Namespaces

- `runtime.*`: non-UI runtime requests, config snapshots, provider state, and
  backend delegation.
- `real_ui.*`: runtime-backed Qt Designer UI binding and dock/window behavior.
- `legacy.*`: compatibility builders for older Python-built shell surfaces.
- `ui.*`: addon-local widget event handlers or exported UI helper classes.
- `dry_run.*`: non-mutating or preview-only profile/tutorial helpers.
- `tutorial.*`: tutorial runtime state and safe-default application.
- `shell.*`: shell-preview service factories used by designer/shell mode.
- `backend.*`: backend host integration points that are not generic runtime
  methods.

Keep capability names stable. Add a new capability when behavior changes shape;
do not silently change payload or return semantics for an existing name.

## Manifest Service IDs

These service IDs are currently used as routing boundaries:

- `avatar_provider_registry`: avatar provider addons such as MuseTalk, VaM,
  VSeeFace, and No Avatar. Match with `provider_id`.
- `tts_backend_service`: TTS backend addons such as PocketTTS, Chatterbox, and
  Gemini preview. Match with `backend_id`.
- `chat_provider_registry`: chat provider addons.
- `sensory_registry`: sensory source addons.
- `sensory_prompt_contributor`: sensory prompt contribution addons.
- `service_registry`: addon-published peer services.

Manifest metadata may include helper hints such as `real_ui_bridge_module`, but
host code should prefer service routing over static imports.

## Avatar Provider Capabilities

Common avatar-provider capabilities:

- `runtime.create_adapter`
- `runtime.estimate_overhead_gib`
- `runtime.collect_config`
- `runtime.update_config_from_widgets`
- `runtime.status_snapshot`
- `runtime.restart_sensitive_widgets`
- `runtime.refresh_resource_widgets`
- `real_ui.bind_runtime_controls`
- `real_ui.set_provider_controls_enabled`
- `real_ui.apply_provider_selected_defaults`
- `runtime.backend.<method>`

MuseTalk owns the avatar-pack catalog, preview runtime, performance dry-run, and
tutorial policy capabilities:

- `runtime.discover_avatar_packs`
- `runtime.get_avatar_pack`
- `runtime.normalize_enabled_pack_emotions`
- `runtime.enabled_pack_emotions`
- `runtime.available_pack_emotion_names`
- `runtime.pack_catalog`
- `runtime.select_pack`
- `runtime.vram_mode`
- `runtime.chunk_limits_for_index`
- `runtime.preview.stream_frames`
- `runtime.preview.stream_delegated_audio_progress`
- `runtime.preview.prime_frame`
- `runtime.preview.estimate_displayed_frames`
- `runtime.preview.current_source_index`
- `runtime.preview.current_state`
- `runtime.preview.set_state`
- `runtime.preview.append_log`
- `runtime.pipeline_snapshot`
- `runtime.apply_settings`
- `dry_run.performance_apply_keys`
- `dry_run.performance_summary_keys`
- `dry_run.performance_label_fragment`
- `dry_run.performance_log_fragment`
- `dry_run.add_performance_override`
- `tutorial.runtime_state`
- `tutorial.apply_safe_defaults`
- `ui.apply_vram_mode_change`
- `ui.apply_loop_fade_change`
- `ui.apply_frame_cache_change`
- `ui.refresh_avatar_pack_list`
- `ui.apply_avatar_pack_change`
- `ui.chunking_slider_specs`
- `ui.preview_panel_exports`

MuseTalk also owns preview/focus UI capabilities:

- `real_ui.build_preview_dock`
- `real_ui.ensure_stage_window`
- `real_ui.attach_preview_to_host`
- `real_ui.sync_stage_window_geometry_from_preview`
- `real_ui.bind_preview_controls`
- `real_ui.redirect_preview_runtime_surface`
- `real_ui.set_focus_button_text`
- `real_ui.show_preview`
- `real_ui.enter_avatar_focus`
- `real_ui.exit_avatar_focus`
- `real_ui.toggle_avatar_focus`
- `real_ui.show_main_interface_from_focus`
- `real_ui.stop_preview`

VaM owns VaM bridge/runtime configuration capabilities:

- `runtime.vam_config`
- `real_ui.sync_widget_names`
- `real_ui.mirror_runtime_widgets`
- `legacy.build_runtime_widgets`
- `runtime.backend.<method>`

VSeeFace currently exposes:

- `runtime.create_adapter`
- `runtime.estimate_overhead_gib`
- `real_ui.bind_runtime_controls`
- `real_ui.set_provider_controls_enabled`
- `ui.hand_doctor_dialog_class`

No Avatar currently exposes `runtime.estimate_overhead_gib`.

## TTS Backend Capabilities

TTS backends register `tts_backend_service` with `backend_id` metadata.

Common TTS backend capabilities:

- `runtime.estimate_overhead_gib`
- `runtime.collect_config`
- `runtime.update_config_from_widgets`
- `runtime.status_snapshot`
- `runtime.restart_sensitive_widgets`
- `runtime.refresh_resource_widgets`

PocketTTS also owns interpreter-setting UI actions:

- `ui.browse_python`
- `ui.apply_python_changed`
- `ui.ensure_python_path`
- `ui.reset_python_to_default`

Chatterbox and Gemini preview currently expose `runtime.estimate_overhead_gib`
only.

## Visual Reply Capabilities

Visual Reply owns its runtime state, shared-state bridge, UI dock, and shell
service factory:

- `runtime.engine_bridge`
- `runtime.apply_settings`
- `runtime.status_snapshot`
- `runtime.generation`
- `runtime.current_state`
- `runtime.set_state`
- `runtime.output_base`
- `runtime.client`
- `runtime.apply_style_anchor`
- `runtime.story_style_guide`
- `runtime.story_prompt`
- `runtime.normalize_prompt`
- `runtime.write_image_from_response`
- `runtime.backend.<method>`
- `real_ui.sync_widget_names`
- `real_ui.bind_runtime_controls`
- `real_ui.build_dock`
- `real_ui.bind_show_button`
- `real_ui.show_dock`
- `real_ui.redirect_runtime_surface`
- `legacy.build_utility_button`
- `legacy.build_settings_tab`
- `legacy.build_runtime_widgets`
- `ui.panel_class`
- `shell.create_visual_reply_service`

## Shell And Host-Service Capabilities

Shell-preview mode should ask addon entrypoints for local service factories
instead of importing addon UI modules directly:

- `shell.create_visual_reply_service`
- `shell.create_hotkey_service`
- `shell.create_chat_replay_service`

Runtime-backed host services are provided through manifest `host_services` and
`core.addons.qt_host_services`. Addons that need Qt host services should declare
the service in `addon.json`; host startup builds those services and passes them
through addon context.

## UI Bridge Conventions

Designer-backed runtime UI capabilities should follow these rules:

- Use `real_ui.sync_widget_names` for compatibility aliases that map Designer
  widgets back to legacy object names.
- Use `real_ui.build_*` only when the addon owns an optional dock/window/panel.
- Use `real_ui.bind_*` for signal-slot binding against already-created widgets.
- Use `real_ui.redirect_*` when an addon-owned runtime surface must replace a
  legacy host placeholder.
- Keep `legacy.build_*` capabilities as compatibility only; new runtime UI
  should use manifest `ui` entries and `real_ui.*` bindings.

## Boundary Rules

- Core, engine, and shared UI runtime modules must not statically import addon
  implementations.
- Host code should route by manifest service metadata or a known addon ID.
- Addon compatibility facades may exist only to protect existing sessions,
  presets, external routes, or legacy UI object names.
- Compatibility facades should delegate lazily to addon-owned modules and should
  not grow new behavior.
- Addons should fail safely when disabled, absent, or partially configured.
- Runtime-visible config keys should remain stable unless an explicit migration
  is added.
