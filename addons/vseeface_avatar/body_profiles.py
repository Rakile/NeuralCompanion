"""Complete existing VSeeFace pose/preset data without overwriting saved values."""
from core import avatar_hand_state


# Restore engine.DEFAULT_POSE from before the production-owner extraction
# (034aedcf). The UI spec's zero values are slider placeholders, not a pose.
DEFAULT_POSE = {
    'idle_arm_down': 71.0, 'idle_elbow_bend': 124.0, 'idle_arm_twist': 19.0,
    'idle_fwd_left': -75.0, 'idle_fwd_right': 80.0,
    'idle_speed': 1.0, 'idle_intensity': 2.0,
    'spine_sway_mult': 1.3, 'spine_twist_mult': 0.7, 'neck_stabilize': 1.5,
    'shoulder_lift': 1.5, 'breath_speed': 1.2,
    'idle_shoulder_back': 0.0, 'eye_activity': 1.0,
}
BODY_EMOTIONS = ('neutral', 'happy', 'sad', 'angry', 'shy', 'surprised')


def complete_body_profile(profile):
    supplied = dict(profile or {})
    neutral = dict(DEFAULT_POSE)
    neutral.update(dict(supplied.get('neutral') or {}))
    emotions = dict.fromkeys(list(BODY_EMOTIONS) + list(supplied))
    result = {}
    for emotion in emotions:
        pose = dict(neutral)
        pose.update(dict(supplied.get(emotion) or {}))
        result[emotion] = pose
    return result


def complete_hand_calibration(calibration):
    result = {key: dict(value) for key, value in avatar_hand_state.hand_calibration().items()}
    for key, value in dict(calibration or {}).items():
        result.setdefault(key, {}).update(dict(value or {}))
    return result
