"""Addon-owned settings; the host environment never imports Ditto or CUDA."""
import math

DEFAULTS = {
    'ditto_repo_path': 'Ditto',
    'ditto_python_path': '', 'ditto_avatar_path': '', 'ditto_source_path': '',
    'ditto_output_path': '', 'ditto_test_audio': '', 'ditto_loop_mode': 'pingpong',
    'ditto_max_size': 1920, 'ditto_crop_scale': 2.3, 'ditto_crop_x': 0.0,
    'ditto_crop_y': -0.125, 'ditto_crop_rotate': True, 'ditto_source_frames': -1,
    'ditto_emotion': 'Neutral', 'ditto_expression': 1.0, 'ditto_motion': 'Automatic',
    'ditto_relative': True, 'ditto_eyes': 'Automatic',
    'ditto_blink_style': 'Checkpoint blink sequence', 'ditto_conditioning': 'Source face',
    'ditto_pitch_strength': 1.0, 'ditto_yaw_strength': 1.0,
    'ditto_roll_strength': 1.0, 'ditto_translation_strength': 1.0,
    'ditto_blink_open': 0, 'ditto_pitch_offset': 2.0,
    'ditto_yaw_offset': 0.0, 'ditto_roll_offset': 0.0,
    'ditto_fade_in': 0, 'ditto_fade_out': 0,
    'ditto_fade_target': 'Initial generated pose',
    'ditto_fade_keys': 'Expression only',
    'ditto_eye_first_frame': False, 'ditto_stitching': True,
    'ditto_steps': 50, 'ditto_smoothing': 3, 'ditto_seed': '', 'ditto_source_smoothing': 13,
    'ditto_pack_id': '', 'ditto_variant_id': '', 'ditto_avatar_selection': 'Fixed',
    'ditto_emotion_selection': 'Manual', 'ditto_test_emotion': 'neutral',
    'ditto_enabled_pack_emotions': {},
}

def validate_setting(key, value):
    if key not in DEFAULTS:
        raise KeyError(key)
    default = DEFAULTS[key]
    if key == 'ditto_enabled_pack_emotions':
        from addons.musetalk_avatar.pack_runtime import normalize_enabled_pack_emotions
        if not isinstance(value, dict):
            raise ValueError('Enabled package emotions must be a package-to-tags mapping.')
        return normalize_enabled_pack_emotions(value)
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f'{key} must be true or false')
        return value
    if isinstance(default, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f'{key} must be finite')
        if isinstance(default, int):
            if not number.is_integer():
                raise ValueError(f'{key} must be a whole number')
            number = int(number)
        limits = {'ditto_expression': (0, 2), 'ditto_steps': (1, 1000),
                  'ditto_smoothing': (1, 101), 'ditto_source_smoothing': (1, 101),
                  'ditto_max_size': (256, 8192), 'ditto_crop_scale': (.1, 10),
                  'ditto_crop_x': (-2, 2), 'ditto_crop_y': (-2, 2),
                  'ditto_source_frames': (-1, 1000000),
                  'ditto_pitch_strength': (0, 2), 'ditto_yaw_strength': (0, 2),
                  'ditto_roll_strength': (0, 2), 'ditto_translation_strength': (0, 2),
                  'ditto_pitch_offset': (-90, 90), 'ditto_yaw_offset': (-90, 90),
                  'ditto_roll_offset': (-90, 90), 'ditto_blink_open': (-1, 10000),
                  'ditto_fade_in': (0, 1000000), 'ditto_fade_out': (0, 1000000)}
        low, high = limits[key]
        if not low <= number <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
        if key == 'ditto_source_frames' and number == 0:
            raise ValueError('Source frame limit must be -1 or a positive integer')
        return number
    text = str(value or '').strip()
    options = {
        'ditto_avatar_selection': ('Fixed', 'From reply emotion'),
        'ditto_emotion_selection': ('Manual', 'From reply emotion'),
        'ditto_loop_mode': ('pingpong', 'forward'),
        'ditto_emotion': ('Neutral', 'Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Contempt'),
        'ditto_motion': ('Automatic', 'Expression only', 'Animate head and expression'),
        'ditto_eyes': ('Automatic', 'Enabled', 'Disabled'),
        'ditto_blink_style': ('Checkpoint blink sequence', 'Generated eye motion'),
        'ditto_conditioning': ('Source face', 'Checkpoint reference'),
        'ditto_fade_target': ('Initial generated pose', 'Source pose'),
        'ditto_fade_keys': ('Expression only', 'Expression and head motion'),
    }
    if key in options and text not in options[key]:
        raise ValueError(f'Invalid {key}: {text}')
    if key == 'ditto_seed' and text and (not text.isdecimal() or not 0 <= int(text) <= 2**32-1):
        raise ValueError('Seed must be blank or an integer from 0 to 4294967295')
    return text

def render_settings(config, emotion='neutral'):
    keys = {'expression': 'expression', 'emotion': 'emotion', 'motion': 'motion',
            'relative': 'relative', 'eyes': 'eyes', 'blink_style': 'blink_style',
            'conditioning': 'conditioning', 'steps': 'steps', 'smoothing': 'smoothing',
            'seed': 'seed', 'source_smoothing': 'source_smoothing',
            'pitch_strength': 'pitch_strength', 'yaw_strength': 'yaw_strength',
            'roll_strength': 'roll_strength', 'translation_strength': 'translation_strength',
            'blink_open': 'blink_open', 'pitch_offset': 'pitch_offset',
            'yaw_offset': 'yaw_offset', 'roll_offset': 'roll_offset',
            'fade_in': 'fade_in', 'fade_out': 'fade_out',
            'fade_target': 'fade_target', 'fade_keys': 'fade_keys',
            'eye_first_frame': 'eye_first_frame', 'stitching': 'stitching'}
    return {target: config.get('ditto_' + source, DEFAULTS['ditto_' + source])
            for target, source in keys.items()}

# Rendering is per avatar; routing policies remain package-wide.
AVATAR_TUNING_KEYS = frozenset('ditto_' + key for key in render_settings({}))
PACKAGE_TUNING_KEYS = AVATAR_TUNING_KEYS | {
    'ditto_avatar_selection', 'ditto_emotion_selection'}


def package_tuning(values):
    if not isinstance(values, dict):
        raise ValueError('Ditto package render settings must be a mapping.')
    return {key: validate_setting(key, values.get(key, DEFAULTS[key]))
            for key in sorted(PACKAGE_TUNING_KEYS)}


def avatar_tuning(values, fallback=None):
    if not isinstance(values, dict):
        raise ValueError('Ditto avatar render settings must be a mapping.')
    fallback = fallback or DEFAULTS
    return {key: validate_setting(key, values.get(key, fallback.get(key, DEFAULTS[key])))
            for key in sorted(AVATAR_TUNING_KEYS)}


def prepare_settings(config):
    keys = {'max_size': 'max_size', 'crop_scale': 'crop_scale', 'crop_vx_ratio': 'crop_x',
            'crop_vy_ratio': 'crop_y', 'crop_flag_do_rot': 'crop_rotate',
            'loop_mode': 'loop_mode', 'source_frames': 'source_frames'}
    return {target: config.get('ditto_' + source, DEFAULTS['ditto_' + source])
            for target, source in keys.items()}
