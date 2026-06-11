"""Theme helpers and theme application behavior for the Qt main window."""

from ui.runtime.engine_access import RUNTIME_CONFIG, update_runtime_config
from ui.theme_support import (
    APP_THEME_PRESET_LABELS,
    APP_THEME_PRESET_WIDGETS,
    DEFAULT_APP_THEME_PRESET,
    app_theme_palette as _app_theme_palette,
    apply_engine_action_button_accents as _theme_apply_engine_action_button_accents,
    apply_inline_theme_styles as _theme_apply_inline_theme_styles,
    install_app_wide_slider_styling as _theme_install_app_wide_slider_styling,
    apply_readable_input_palettes as _theme_apply_readable_input_palettes,
    build_app_stylesheet_for_preset as _build_app_stylesheet_for_preset,
    canonical_theme_base_stylesheet as _canonical_theme_base_stylesheet,
    configure_theme_support,
    normalize_app_theme_preset_id as _normalize_app_theme_preset_id,
    replace_theme_colors_in_stylesheet as _replace_theme_colors_in_stylesheet,
    split_collapsible_section_text as _theme_split_collapsible_section_text,
)
from ui.widgets.basic import set_combo_popup_palette_callback


def _apply_inline_theme_styles(root, palette):
    _theme_apply_inline_theme_styles(
        root,
        palette,
        theme_preset_widgets=APP_THEME_PRESET_WIDGETS,
        canonicalize_stylesheet=_canonical_theme_base_stylesheet,
        replace_theme_colors=_replace_theme_colors_in_stylesheet,
    )


def _apply_readable_input_palettes(root, palette):
    _theme_apply_readable_input_palettes(root, palette)


def _apply_engine_action_button_accents(root):
    _theme_apply_engine_action_button_accents(root)


def _install_app_wide_slider_styling(root=None):
    _theme_install_app_wide_slider_styling(root)


def _split_collapsible_section_text(text, fallback_title):
    return _theme_split_collapsible_section_text(text, fallback_title)


def _apply_combo_popup_palette(combo):
    _apply_readable_input_palettes(combo.window(), _app_theme_palette())


def configure_main_window_theme_support():
    configure_theme_support(RUNTIME_CONFIG)
    set_combo_popup_palette_callback(_apply_combo_popup_palette)
    _install_app_wide_slider_styling()


class MainWindowThemeMixin:
    def current_app_theme_preset(self):
        return _normalize_app_theme_preset_id(getattr(self, "_active_app_theme_preset", DEFAULT_APP_THEME_PRESET))

    def apply_app_theme_preset(self, preset_id, *, save_session=True):
        resolved_preset = _normalize_app_theme_preset_id(preset_id)
        if bool(getattr(self, "_theme_apply_in_progress", False)):
            self._active_app_theme_preset = resolved_preset
            update_runtime_config("ui_theme_preset", resolved_preset)
            return resolved_preset
        preset_dirty_state = getattr(self, "_preset_dirty_state", None)
        self._theme_apply_in_progress = True
        stylesheet = _build_app_stylesheet_for_preset(resolved_preset)
        try:
            self.setStyleSheet(stylesheet)
            self._active_app_theme_preset = resolved_preset
            update_runtime_config("ui_theme_preset", resolved_preset)
            _apply_inline_theme_styles(self, _app_theme_palette(resolved_preset))
            _apply_readable_input_palettes(self, _app_theme_palette(resolved_preset))
            _apply_engine_action_button_accents(self)
            _install_app_wide_slider_styling(self)
            self._apply_legacy_dock_title_widgets()
            for widget in (
                getattr(self, "embedded_musetalk_preview", None),
                getattr(self, "visual_reply_panel", None),
            ):
                if widget is not None and hasattr(widget, "apply_theme_palette"):
                    try:
                        widget.apply_theme_palette()
                    except Exception:
                        pass
            if save_session:
                self.save_session()
            print(f"[QtGUI] Applied UI theme: {APP_THEME_PRESET_LABELS.get(resolved_preset, resolved_preset.title())}")
            return resolved_preset
        finally:
            self._theme_apply_in_progress = False
            self._preset_dirty_state = preset_dirty_state
            apply_dirty_style = getattr(self, "_apply_preset_dirty_button_style", None)
            if callable(apply_dirty_style):
                apply_dirty_style()
