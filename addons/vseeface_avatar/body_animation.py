"""VSeeFace/VMC body animation helpers.

This belongs with the VSeeFace avatar provider, not core: the bone names,
blend behavior, and hand calibration assumptions are all VMC-specific.
"""

from __future__ import annotations

import math
import random


def animate_vseeface_body(
    adapter,
    *,
    avatar_profile,
    current_body_state,
    edit_emotion,
    force_edit_mode,
    hand_debug,
    hand_calibration,
    now,
):
    """Drive VSeeFace/VMC body pose from the mutable avatar pose state."""
    dt = now - adapter.last_anim_time
    adapter.last_anim_time = now

    if not hasattr(adapter, "breath_phase"):
        adapter.breath_phase = 0.0

    if not hasattr(adapter, "eye_target_x"):
        adapter.eye_target_x = 0.0
        adapter.eye_target_y = 0.0
        adapter.eye_current_x = 0.0
        adapter.eye_current_y = 0.0
        adapter.next_saccade_time = now + 1.0

    if force_edit_mode:
        target_key = edit_emotion
    else:
        target_key = adapter.current_emotion if adapter.current_emotion in avatar_profile else "neutral"

    target_pose = avatar_profile.get(target_key, avatar_profile["neutral"])

    lerp_speed = 0.1
    for key in avatar_profile["neutral"]:
        target_val = target_pose.get(key, avatar_profile["neutral"][key])
        if key not in current_body_state:
            current_body_state[key] = target_val
        current_body_state[key] += (target_val - current_body_state[key]) * lerp_speed

    base_speed = current_body_state.get("idle_speed", 1.0)
    base_intensity = current_body_state.get("idle_intensity", 2.0)

    s_sway_mult = current_body_state.get("spine_sway_mult", 1.0)
    s_twist_mult = current_body_state.get("spine_twist_mult", 0.7)
    n_stabilize = current_body_state.get("neck_stabilize", 1.0)

    sh_lift_amp = current_body_state.get("shoulder_lift", 1.5)
    b_speed = current_body_state.get("breath_speed", 1.2)
    sh_manual_back = current_body_state.get("idle_shoulder_back", 0.0)

    eye_amp = current_body_state.get("eye_activity", 1.0)

    current_speed = base_speed
    sway_z = base_intensity
    sway_x = base_intensity * 0.5
    sway_twist = base_intensity * 1.5
    sway_bend = 2.0

    is_talking = adapter.is_speaking
    if is_talking:
        current_speed = base_speed * 2.5
        sway_twist += 20.0
        sway_z *= 1.5
        sway_x += 1.0
        sway_bend = 8.0

    adapter.anim_phase += dt * current_speed
    adapter.breath_phase += dt * b_speed

    gravity_phase = adapter.anim_phase - 0.5 * math.sin(adapter.anim_phase)
    noise_x = math.cos(adapter.anim_phase * 0.8)
    noise_z = math.sin(gravity_phase)
    noise_bend = math.sin(adapter.anim_phase * 1.1 + 1.5)
    noise_twist = math.sin(adapter.anim_phase * 0.7 + 2.0)
    wave_grip = 0.5 - 0.5 * noise_x

    if eye_amp > 0.1:
        if now > adapter.next_saccade_time:
            range_mult = 3.0 if is_talking else 1.0
            tgt_yaw = random.uniform(-3, 3) * eye_amp * range_mult
            tgt_pitch = random.uniform(-1.5, 1.5) * eye_amp * range_mult

            adapter.eye_target_x = tgt_pitch
            adapter.eye_target_y = tgt_yaw

            min_wait = 0.2 if is_talking else 0.5
            max_wait = 1.0 if is_talking else 2.5
            adapter.next_saccade_time = now + random.uniform(min_wait, max_wait)

        snap_speed = 0.3
        adapter.eye_current_x += (adapter.eye_target_x - adapter.eye_current_x) * snap_speed
        adapter.eye_current_y += (adapter.eye_target_y - adapter.eye_current_y) * snap_speed
    else:
        adapter.eye_current_x *= 0.9
        adapter.eye_current_y *= 0.9

    q_eyes = adapter._euler_to_quaternion(adapter.eye_current_x, adapter.eye_current_y, 0)
    adapter.client.send_message("/VMC/Ext/Bone/Pos", ["LeftEye", 0.0, 0.0, 0.0] + q_eyes)
    adapter.client.send_message("/VMC/Ext/Bone/Pos", ["RightEye", 0.0, 0.0, 0.0] + q_eyes)

    amplified_lift = sh_lift_amp * 6.0
    breath_wave = (math.sin(adapter.breath_phase) + 0.2) * amplified_lift
    speech_shrug = (10.0 * wave_grip) if is_talking else 0.0
    total_lift_z = breath_wave + speech_shrug

    auto_roll = total_lift_z * -0.5
    total_roll_y = auto_roll - sh_manual_back

    q_sh_l = adapter._euler_to_quaternion(0, total_roll_y, total_lift_z)
    q_sh_r = adapter._euler_to_quaternion(0, -total_roll_y, -total_lift_z)

    adapter.client.send_message("/VMC/Ext/Bone/Pos", ["LeftShoulder", 0.0, 0.0, 0.0] + q_sh_l)
    adapter.client.send_message("/VMC/Ext/Bone/Pos", ["RightShoulder", 0.0, 0.0, 0.0] + q_sh_r)

    spine_z = noise_z * (sway_z * s_sway_mult)
    spine_x = noise_x * (sway_x * s_sway_mult)
    spine_y = noise_twist * (sway_twist * s_twist_mult)

    neck_z = -1 * spine_z * n_stabilize
    neck_x = -1 * spine_x * n_stabilize
    neck_y = -1 * spine_y * n_stabilize

    if is_talking:
        neck_x += 5.0 * wave_grip

    adapter.client.send_message("/VMC/Ext/Bone/Pos", ["Spine", 0.0, 0.0, 0.0] + adapter._euler_to_quaternion(spine_x, spine_y, spine_z))
    adapter.client.send_message("/VMC/Ext/Bone/Pos", ["Neck", 0.0, 0.0, 0.0] + adapter._euler_to_quaternion(neck_x, neck_y, neck_z))

    l_z = current_body_state["idle_arm_down"] + (noise_z * sway_z)
    l_x = current_body_state["idle_fwd_left"] + (noise_x * sway_x)
    l_bend = current_body_state["idle_elbow_bend"] + (noise_bend * sway_bend)
    l_y = current_body_state["idle_arm_twist"] + (noise_twist * sway_twist)

    r_z = -1 * (current_body_state["idle_arm_down"] + (math.sin(gravity_phase + 2.0) * sway_z))
    r_x = -1 * (current_body_state["idle_fwd_right"] + (math.cos(adapter.anim_phase * 0.9 + 1.0) * sway_x))
    r_bend = -1 * (current_body_state["idle_elbow_bend"] + (math.sin(adapter.anim_phase * 1.2 + 0.5) * sway_bend))
    r_y = -1 * (current_body_state["idle_arm_twist"] + (noise_twist * sway_twist))

    adapter.client.send_message("/VMC/Ext/Bone/Pos", ["LeftUpperArm", 0.0, 0.0, 0.0] + adapter._euler_to_quaternion(l_x, l_y, l_z))
    adapter.client.send_message("/VMC/Ext/Bone/Pos", ["RightUpperArm", 0.0, 0.0, 0.0] + adapter._euler_to_quaternion(r_x, r_y, r_z))
    adapter.client.send_message("/VMC/Ext/Bone/Pos", ["LeftLowerArm", 0.0, 0.0, 0.0] + adapter._euler_to_quaternion(0, 0, l_bend))
    adapter.client.send_message("/VMC/Ext/Bone/Pos", ["RightLowerArm", 0.0, 0.0, 0.0] + adapter._euler_to_quaternion(0, 0, r_bend))

    if hand_debug["active"]:
        t_x, t_y, t_z = hand_debug["thumb_x"], hand_debug["thumb_y"], hand_debug["thumb_z"]
        f_x, f_y, f_z = hand_debug["finger_x"], hand_debug["finger_y"], hand_debug["finger_z"]
    else:
        target_grip = 0.0
        if is_talking:
            target_grip = 0.2 + (0.5 * wave_grip) if target_key not in ["angry", "shy"] else (0.5 + 0.4 * wave_grip)
        else:
            target_grip = {"angry": 0.8, "shy": 0.5}.get(target_key, 0.05)

        target_grip = max(0.0, min(1.0, target_grip))

        def lerp_h(key):
            return hand_calibration["relaxed"][key] + (hand_calibration["fist"][key] - hand_calibration["relaxed"][key]) * target_grip

        f_x, f_y, f_z = lerp_h("finger_x"), lerp_h("finger_y"), lerp_h("finger_z")
        t_x, t_y, t_z = lerp_h("thumb_x"), lerp_h("thumb_y"), lerp_h("thumb_z")

    ql = adapter._euler_to_quaternion(t_x, t_y, t_z)
    qr = adapter._euler_to_quaternion(t_x, -t_y, -t_z)
    fl = adapter._euler_to_quaternion(f_x, f_y, f_z)
    fr = adapter._euler_to_quaternion(f_x, -f_y, -f_z)

    for bone in adapter.FINGER_BONES:
        adapter.client.send_message("/VMC/Ext/Bone/Pos", [f"Left{bone}", 0.0, 0.0, 0.0] + (ql if "Thumb" in bone else fl))
        adapter.client.send_message("/VMC/Ext/Bone/Pos", [f"Right{bone}", 0.0, 0.0, 0.0] + (qr if "Thumb" in bone else fr))
