"""Native preparation controls for still portraits and known frame loops."""

from addons.ditto_avatar.native_adapter import DittoAvatarNativeAdapter, DittoNativeAdapter, Kind, NativeControl
from addons.ditto_avatar.config import AVATAR_TUNING_KEYS
from ui.qml_bridge.native_contracts import choices
from PySide6.QtCore import QUrl


class DittoPreprocessNativeAdapter(DittoNativeAdapter):
    title = "Ditto Avatar Creator"
    snapshot_capability = 'creator.snapshot'
    section_order = ('Package','Package avatar','Source','Import','Native emotion mapping','Test','Animation','Generation','Preview','Runtime','Crop','Advanced')
    creator_fields = frozenset(('ditto_creator_pack','ditto_creator_variant','ditto_package_name',
        'ditto_variant_name','ditto_variant_tags','ditto_variant_default','ditto_import_path'))
    creator_actions = {'ditto_create_package':'create_package','ditto_new_variant':'new_variant',
        'ditto_save_variant':'save_variant','ditto_save_package':'save_package','ditto_prepare_variant':'prepare_variant',
        'ditto_import_prepared':'import_prepared','ditto_use_package':'use_package',
        'ditto_test_render':'test_render', 'ditto_preview_crop':'preview_crop',
        'ditto_package_prepare_convert':'prepare_convert','ditto_package_prepare_keep':'prepare_keep',
        'ditto_package_prepare_cancel':'prepare_cancel', 'ditto_wizard_prepare':'guided_prepare',
        'ditto_wizard_media':'choose_media','ditto_wizard_import':'guided_import',
        'ditto_wizard_discard':'discard_emotion', 'ditto_wizard_back':'back_to_media',
        'ditto_remove_variant':'remove_variant', 'ditto_delete_variant':'delete_variant',
        'ditto_redo_variant':'redo_variant','ditto_replace_variant':'replace_variant',
        'ditto_make_base':'make_base','ditto_cancel_replacement':'cancel_replacement'}
    setting_ids = frozenset(("ditto_repo_path", "ditto_python_path", "ditto_source_path", "ditto_output_path", "ditto_test_audio", "ditto_avatar_path", "ditto_loop_mode", "ditto_max_size", "ditto_crop_scale", "ditto_crop_x", "ditto_crop_y", "ditto_crop_rotate", "ditto_source_frames"))
    actions = {"ditto_load": "load", "ditto_unload": "unload", "ditto_cancel": "cancel", "ditto_prepare": "prepare", "ditto_test_render": "test_render", "ditto_activate": "activate", "ditto_prepare_convert": "prepare_convert", "ditto_prepare_keep": "prepare_keep", "ditto_prepare_cancel": "prepare_cancel", "ditto_stop_preview":"stop_preview"}
    pickers = {"ditto_choose_media": "ditto_source_path", "ditto_choose_frames": "ditto_source_path", "ditto_choose_output": "ditto_output_path", "ditto_choose_audio": "ditto_test_audio", "ditto_choose_avatar": "ditto_avatar_path", 'ditto_choose_import':'ditto_import_path'}
    setting_ids = setting_ids | {'ditto_test_emotion'}

    def __init__(self, application_facade, *, persist=None, parent=None):
        super().__init__(application_facade, "ditto_preprocess_tab", "nc.ditto_preprocess", persist=persist, parent=parent)

    def set_value(self, control_id, value):
        if control_id == 'ditto_preview_muted':
            try:
                self._invoke('action', {'action':'set_preview_muted','payload':{'muted':value}})
            finally:
                self._changed()
            return
        if control_id in self.creator_fields or control_id in AVATAR_TUNING_KEYS or control_id.startswith('ditto_map_'):
            try:
                self._invoke('creator.update', {'key':control_id,'value':value})
            finally:
                self._changed()
            return
        return super().set_value(control_id,value)

    def trigger_with_payload(self, control_id, payload):
        if control_id == 'ditto_replace_variant':
            payload = dict(payload or {})
            url = QUrl(str(payload.get('source_path') or ''))
            if url.isLocalFile():
                payload['source_path'] = url.toLocalFile()
        if control_id == 'ditto_wizard_media':
            data = dict(payload or {})
            url = QUrl(str(data.get('path') or ''))
            payload = {'path':url.toLocalFile() if url.isLocalFile() else str(data.get('path') or ''),
                       'emotion':str(data.get('emotion') or '')}
        if control_id in self.creator_actions:
            try:
                self._invoke('creator.action', {'action':self.creator_actions[control_id],'payload':payload})
                if self._persist:
                    self._persist()
            finally:
                self._changed()
            return
        return super().trigger_with_payload(control_id,payload)

    def _wizard_control(self, state):
        creator = state.get('creator') or {}
        wizard = dict(creator.get('wizard') or {})
        wizard.update(status=state.get('status',''), busy=bool(state.get('busy')),
            loaded=bool(state.get('loaded')), testing=bool(state.get('test_preview_active')),
            worker_running=bool(state.get('worker_running')),
            muted=bool(state.get('preview_muted')),
            chat_active=bool(state.get('session_running') and not state.get('test_preview_active')),
            progress=state.get('progress',0), fps_choice=state.get('fps_choice'),
            packages=creator.get('packages',[]), variants=creator.get('variants',[]),
            emotion_entries=creator.get('emotion_entries',[]),
            selected_package=creator.get('selected_package',''), selected_variant=creator.get('selected_variant',''),
            preview_url=state.get('creator_preview_url',''))
        crop = dict(wizard.get('crop_preview') or {})
        if crop:
            crop['image_url'] = QUrl.fromLocalFile(crop['preview_path']).toString()
        wizard['crop_preview'] = crop
        wizard['still_url'] = QUrl.fromLocalFile(wizard['still_path']).toString() if wizard.get('still_path') else ''
        source = wizard.get('source','')
        wizard['source_url'] = QUrl.fromLocalFile(source).toString() if source.lower().endswith(('.png','.jpg','.jpeg','.webp','.bmp')) else ''
        return NativeControl('ditto_wizard_state','Creator',Kind.DISPLAY,'Source',value=wizard,
                             metadata={'presentationHidden':True})

    def _preview_controls(self, state):
        controls = super()._preview_controls(state)
        if state.get('creator_preview_url'):
            from dataclasses import replace
            controls = (replace(controls[0],value=state['creator_preview_url']), *controls[1:])
        return controls

    def _package_controls(self, state):
        creator = state.get('creator') or {}
        mapping = creator.get('native_emotion_map',{})
        return (
            self._wizard_control(state),
            self._button('ditto_wizard_media','Choose media','Source',presentationHidden=True),
            self._button('ditto_wizard_prepare','Prepare avatar','Source',presentationHidden=True),
            self._button('ditto_preview_crop','Preview crop','Source',presentationHidden=True),
            self._button('ditto_wizard_import','Import prepared avatar','Import'),
            self._button('ditto_wizard_discard','Discard unfinished emotion','Source',presentationHidden=True),
            self._button('ditto_wizard_back','Back to Choose media','Source',presentationHidden=True),
            self._button('ditto_remove_variant','Remove avatar','Package avatar',presentationHidden=True),
            *(self._button(key,label,'Package avatar',presentationHidden=True) for key,label in (
                ('ditto_delete_variant','Delete emotion'),('ditto_redo_variant','Redo emotion'),
                ('ditto_replace_variant','Replace source'),('ditto_make_base','Use as base'),
                ('ditto_cancel_replacement','Cancel replacement'))),

            self._button('ditto_stop_preview','Stop preview','Test',presentationHidden=True),
            NativeControl('ditto_preview_muted','Mute preview',Kind.BOOLEAN,'Test',
                          value=bool(state.get('preview_muted')),metadata={'presentationHidden':True}),
            NativeControl('ditto_package_intro','Avatar packages',Kind.DISPLAY,'Package',
                value='Create a package, add named avatars, assign reply emotions, then prepare their source media.'),
            self._field(creator,'ditto_creator_pack','Existing package',Kind.CHOICE,'Package','',choices=choices(
                (p['id'],p['display_name']) for p in creator.get('packages',()))),
            self._field(creator,'ditto_package_name','Package name',Kind.TEXT,'Package',''),
            self._button('ditto_create_package','Create new package','Package'),
            self._button('ditto_save_package','Save package and emotion mapping','Package'),
            self._field(creator,'ditto_creator_variant','Avatar in this package',Kind.CHOICE,'Package avatar','',choices=choices(
                (v['id'],v['display_name'] + (' (prepared)' if v.get('prepared') else ' (needs preparation)')) for v in creator.get('variants',()))),
            self._button('ditto_new_variant','Add another avatar','Package avatar'),
            self._field(creator,'ditto_variant_name','Avatar name',Kind.TEXT,'Package avatar',''),
            self._field(creator,'ditto_variant_tags','Reply emotions (comma separated)',Kind.TEXT,'Package avatar','',
                description='For example happy, joyful. Each tag can belong to one avatar in the package.'),
            self._field(creator,'ditto_variant_default','Default avatar',Kind.BOOLEAN,'Package avatar',False),
            self._button('ditto_save_variant','Save avatar entry','Package avatar'),
            NativeControl('ditto_package_destination','Managed destination',Kind.DISPLAY,'Package avatar',value=creator.get('destination','')),
            *(self._choice({'ditto_map_'+tag:mapping.get(tag,'Automatic')},'ditto_map_'+tag,tag+' → generated expression',
                'Native emotion mapping','Automatic',('Automatic','Angry','Disgust','Fear','Happy','Neutral','Sad','Surprise','Contempt'))
                for tag in creator.get('emotion_tags',mapping)),
            self._field(creator,'ditto_import_path','Existing prepared avatar',Kind.TEXT,'Import',''),
            self._button('ditto_choose_import','Choose prepared avatar to import','Import',execution='ui',folderPicker=True,dialogTitle='Select prepared Ditto avatar'),
            self._button('ditto_import_prepared','Copy into selected package avatar','Import'),
            self._button('ditto_use_package','Use this package for chat','Test'),
            self._field(state,'ditto_test_emotion','Test reply emotion',Kind.TEXT,'Test','neutral',
                description='Tests this package with the runtime source and expression selection modes.'),
        )

    def controls(self, state):
        state = {**state, **(state.get('creator', {}).get('render_settings') or {})}
        fps_choice = state.get('fps_choice')
        prefix = 'ditto_package_prepare_' if fps_choice and fps_choice.get('package_id') else 'ditto_prepare_'
        fps_section = 'Source' if fps_choice and fps_choice.get('package_id') else 'Crop'
        prepare_controls = (
            NativeControl('ditto_fps_question', 'Video frame rate', Kind.DISPLAY, fps_section, value=fps_choice['message']),
            self._button(prefix+'convert', 'Convert with FFmpeg to 25 FPS (preserve duration)', fps_section),
            self._button(prefix+'keep', 'Use original frames (change playback speed)', fps_section),
            self._button(prefix+'cancel', 'Cancel preparation', fps_section),
        ) if fps_choice else (self._button('ditto_prepare', 'Prepare standalone avatar', 'Advanced'),)
        return (
            *self._package_controls(state),
            *(control for control in DittoAvatarNativeAdapter.controls(self, state)
              if control.id in AVATAR_TUNING_KEYS),
            *self._runtime_controls(state),
            NativeControl("ditto_prepare_intro", "Prepare once", Kind.DISPLAY, "Source", value="Prepare one still image, a video, or a numerically ordered PNG frame folder. Runtime emotion settings do not require preparing again."),
            self._field(state, "ditto_source_path", "Source image, video, or frame folder", Kind.TEXT, "Source", ""),
            self._button("ditto_choose_media", "Choose image or video", "Source", execution="ui", filePicker=True, dialogTitle="Select Ditto source media", nameFilters=["Image or video (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mov *.mkv *.avi *.webm)", "All files (*)"]),
            self._button("ditto_choose_frames", "Choose PNG frame folder", "Source", execution="ui", folderPicker=True, dialogTitle="Select ordered frame folder"),
            self._field(state, "ditto_output_path", "Standalone preparation destination", Kind.TEXT, "Advanced", "", description="Compatibility workflow outside packages. Existing prepared avatars are not overwritten."),
            self._button("ditto_choose_output", "Choose standalone destination parent", "Advanced", execution="ui", folderPicker=True, dialogTitle="Select parent for a new ditto-avatar folder"),
            self._choice(state, "ditto_loop_mode", "Source loop mode", "Source", "pingpong", ("pingpong", "forward"), description="Use pingpong for a forward-only clip. Use forward when the input already contains its reverse half; do not ping-pong it again."),
            self._field(state, "ditto_source_frames", "Maximum source frames", Kind.INTEGER, "Source", -1, minimum=-1, maximum=100000, metadata={"skipZero": True}, description="-1 prepares all available frames; positive values limit the count. The step buttons skip zero. A still image produces one frame."),
            *((self._button('ditto_prepare_variant','Prepare selected package avatar','Source'),) if not fps_choice else ()),
            self._field(state, "ditto_max_size", "Maximum source size", Kind.INTEGER, "Advanced", 1920, minimum=256, maximum=8192),
            self._field(state, "ditto_crop_scale", "Face crop scale", Kind.NUMBER, "Advanced", 2.3, minimum=0.5, maximum=5, step=0.05),
            self._field(state, "ditto_crop_x", "Horizontal crop offset", Kind.NUMBER, "Advanced", 0.0, minimum=-2, maximum=2, step=0.025),
            self._field(state, "ditto_crop_y", "Vertical crop offset", Kind.NUMBER, "Advanced", -0.125, minimum=-2, maximum=2, step=0.025),
            self._field(state, "ditto_crop_rotate", "Align face rotation", Kind.BOOLEAN, "Advanced", True),
            *prepare_controls,
            self._field(state, "ditto_avatar_path", "Standalone prepared Ditto avatar", Kind.TEXT, "Advanced", ""),
            self._button("ditto_choose_avatar", "Choose standalone prepared avatar", "Advanced", execution="ui", folderPicker=True, dialogTitle="Select prepared Ditto avatar"),
            self._field(state, "ditto_test_audio", "Test audio", Kind.TEXT, "Test", ""),
            self._button("ditto_choose_audio", "Choose test audio", "Test", execution="ui", filePicker=True, dialogTitle="Select WAV test audio", nameFilters=["WAV audio (*.wav)"]),
            self._button("ditto_test_render", "Preview speaking", "Test"),
            self._button("ditto_activate", "Use standalone avatar", "Advanced"),
            *self._preview_controls(state),
        )


def build_ditto_preprocess_adapter(application_facade, persist=None, parent=None):
    return DittoPreprocessNativeAdapter(application_facade, persist=persist, parent=parent)


__all__ = ["DittoPreprocessNativeAdapter", "build_ditto_preprocess_adapter"]
