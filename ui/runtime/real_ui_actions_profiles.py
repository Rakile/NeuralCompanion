"""RealUiActionsProfileMixin extracted from real_ui_actions.py."""

from PySide6 import QtCore


def configure_real_ui_actions_profiles_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiActionsProfileMixin:
    def _on_frontend_chunking_profile_changed(self, _index=None):
            self._sync_single_combo_to_backend("chunking_profile_combo")
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_chunking_value_changed(self, key, value):
            spec = _ui_shell_chunking_slider_spec(key)
            normalized_value = value
            try:
                is_int = bool(spec.get("is_int", True))
                scale = float(spec.get("scale", 1) or 1)
                normalized_value = float(value) / scale
                normalized_value = int(round(normalized_value)) if is_int else round(normalized_value, 2)
                callback = getattr(self.backend, "update_chunking_value", None)
                if callable(callback):
                    callback(str(key), normalized_value, is_int)
                else:
                    update_runtime_config(str(key), normalized_value)
                    self.backend.save_session()
            finally:
                backend_slider = getattr(self.backend, "chunking_sliders", {}).get(str(key))
                if backend_slider is not None and hasattr(backend_slider, "set_value"):
                    try:
                        backend_slider.set_value(normalized_value)
                    except Exception:
                        pass
                _ui_shell_update_chunking_label(self.window, str(key), normalized_value)
                self._refresh_profile_utility_runtime_frontend()

    def _reset_chunking_from_ui_real(self):
            self.backend.reset_chunking_defaults()
            self._mirror_chunking_runtime_widgets(force=True)
            self._refresh_profile_utility_runtime_frontend()

    def _refresh_chunking_profiles_from_ui_real(self):
            self.backend.refresh_performance_profile_list()
            self._mirror_chunking_profile_combo(force=True)
            self._refresh_profile_utility_runtime_frontend()

    def _load_chunking_profile_from_ui_real(self):
            self._sync_single_combo_to_backend("chunking_profile_combo")
            self.backend.load_selected_chunking_profile()
            self._mirror_chunking_runtime_widgets(force=True)
            self._refresh_profile_utility_runtime_frontend()

    def _save_chunking_profile_from_ui_real(self):
            self._sync_single_combo_to_backend("chunking_profile_combo")
            self.backend.save_current_chunking_profile()
            self._mirror_chunking_profile_combo(force=True)
            self._refresh_profile_utility_runtime_frontend()

    def _delete_chunking_profile_from_ui_real(self):
            self._sync_single_combo_to_backend("chunking_profile_combo")
            self.backend.delete_selected_chunking_profile()
            self._mirror_chunking_profile_combo(force=True)
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_performance_profile_changed(self, _index=None):
            self._sync_single_combo_to_backend("performance_profile_combo")
            self.backend.save_session()
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_dry_run_auto_replies_changed(self, _checked):
            self._sync_single_checkbox_to_backend("dry_run_auto_replies_checkbox")
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_dry_run_target_changed(self, _value):
            self._sync_single_spin_to_backend("dry_run_target_spin")
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_musetalk_loop_fade_changed(self, _value):
            self._sync_single_spin_to_backend("musetalk_loop_fade_spin")
            self._refresh_profile_utility_runtime_frontend()
