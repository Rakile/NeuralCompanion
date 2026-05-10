"""Host shims for the VaM avatar addon runtime."""


from ui.runtime.engine_access import engine_module as _engine


def _runtime_config():
    return getattr(_engine(), "RUNTIME_CONFIG", {})


class BackendVamRuntimeMixin:
    def _invoke_vam_runtime(self, method_name, *args, default=None, **kwargs):
        callback = getattr(self, "_invoke_addon_service_capability", None)
        if not callable(callback):
            return default
        return callback(
            "avatar_provider_registry",
            f"runtime.backend.{method_name}",
            {"backend": self, "args": list(args), "kwargs": dict(kwargs)},
            default=default,
            provider_id="vam",
        )

    # Legacy backend widget construction asks for these values before addon
    # capabilities are available, so keep the pure path calculations local.
    def _current_vam_root_value(self):
        engine = _engine()
        raw = self._live_text(
            "vam_root_edit",
            _runtime_config().get("vam_root", getattr(engine, "DEFAULT_VAM_ROOT", "")) or getattr(engine, "DEFAULT_VAM_ROOT", ""),
        ).strip()
        return engine.normalize_vam_root(raw)

    def _current_vam_bridge_root_value(self):
        return _engine().derive_vam_bridge_root(self._current_vam_root_value())

    def on_vam_vmc_enabled_changed(self, enabled):
        return self._invoke_vam_runtime("on_vam_vmc_enabled_changed", enabled)

    def on_vam_bridge_enabled_changed(self, enabled):
        return self._invoke_vam_runtime("on_vam_bridge_enabled_changed", enabled)

    def on_vam_play_audio_in_vam_changed(self, enabled):
        return self._invoke_vam_runtime("on_vam_play_audio_in_vam_changed", enabled)

    def on_vam_timeline_auto_resume_changed(self, enabled):
        return self._invoke_vam_runtime("on_vam_timeline_auto_resume_changed", enabled)

    def on_vam_vmc_host_changed(self):
        return self._invoke_vam_runtime("on_vam_vmc_host_changed")

    def on_vam_vmc_port_changed(self, value):
        return self._invoke_vam_runtime("on_vam_vmc_port_changed", value)

    def _refresh_vam_path_widgets(self):
        return self._invoke_vam_runtime("_refresh_vam_path_widgets")

    def _ensure_vam_root_for_launch(self):
        return self._invoke_vam_runtime("_ensure_vam_root_for_launch", default=self._current_vam_root_value())

    def on_vam_root_changed(self):
        return self._invoke_vam_runtime("on_vam_root_changed")

    def on_vam_bridge_root_changed(self):
        return self._invoke_vam_runtime("on_vam_bridge_root_changed")

    def _launch_vam_target(self, launch_name, title):
        return self._invoke_vam_runtime("_launch_vam_target", launch_name, title)

    def on_start_vam_desktop_clicked(self):
        return self._invoke_vam_runtime("on_start_vam_desktop_clicked")

    def on_start_vam_vr_clicked(self):
        return self._invoke_vam_runtime("on_start_vam_vr_clicked")

    def on_vam_target_atom_uid_changed(self):
        return self._invoke_vam_runtime("on_vam_target_atom_uid_changed")

    def on_vam_target_storable_id_changed(self):
        return self._invoke_vam_runtime("on_vam_target_storable_id_changed")
