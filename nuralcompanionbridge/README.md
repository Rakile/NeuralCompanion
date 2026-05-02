# VaM Integration Scaffold

This folder contains the VaM-side bridge plugin source for Neural Companion.

The current design uses two channels:

1. VMC for motion, head, and hands.
2. A small file bridge plugin for emotion, speaking state, Timeline hooks, and in-VaM audio playback.

## What This Covers

- VaM plugin source: `NeuralCompanionBridge.cs`
- VaM plugin manifest: `NeuralCompanionBridge.cslist`
- NC-side engine/UI wiring lives in the main Python app:
  - `engine.py`
  - `qt_app.py`

## Recommended First Pass

Recommended current setup:

- `vam_vmc_enabled = true`
- `vam_bridge_enabled = true`
- `vam_play_audio_in_vam = true`

With that setup:

- motion/head/hands come through VMC
- speech audio is staged by NC and played by VaM
- VaM lip sync can be enabled on the character through `Auto Behaviour -> Lip Sync`

## Config Keys

These are stored in `RUNTIME_CONFIG` and can also be persisted in `qt_session.json`.

- `vam_vmc_enabled`
- `vam_vmc_host`
- `vam_vmc_port`
- `vam_bridge_enabled`
- `vam_bridge_root`
- `vam_play_audio_in_vam`
- `vam_target_atom_uid`
- `vam_target_storable_id`
- `vam_timeline_auto_resume`
- `vam_emotion_preset_map`
- `vam_timeline_clip_map`

Suggested initial values:

```json
{
  "vam_vmc_enabled": true,
  "vam_vmc_host": "127.0.0.1",
  "vam_vmc_port": 39539,
  "vam_bridge_enabled": true,
  "vam_bridge_root": "<VaM>/Custom/PluginData/NeuralCompanionBridge",
  "vam_play_audio_in_vam": true,
  "vam_target_atom_uid": "Person",
  "vam_target_storable_id": "plugin#0_NeuralCompanionBridge",
  "vam_timeline_auto_resume": true,
  "vam_emotion_preset_map": {
    "neutral": "nc_neutral",
    "happy": "nc_happy",
    "angry": "nc_angry",
    "sad": "nc_sad",
    "surprised": "nc_surprised",
    "shy": "nc_shy",
    "default": "nc_neutral"
  },
  "vam_timeline_clip_map": {
    "happy": "talk_happy",
    "angry": "talk_angry",
    "sad": "talk_sad",
    "default": "talk_default"
  }
}
```

## Bridge Folder Contract

The Python side writes command files into:

- `<vam_bridge_root>/inbox`

The VaM side can write status into:

- `<vam_bridge_root>/outbox/status.json`

Commands are written atomically as individual JSON files so nothing depends on sockets or live localhost permissions.

## Command Protocol

Each command file looks like:

```json
{
  "session_id": "abc123",
  "command_id": "1744230000000_deadbeef",
  "sent_at": 1744230000.123456,
  "action": "speech_chunk",
  "payload": {
    "target_atom_uid": "Person",
    "target_storable_id": "plugin#0_NeuralCompanionBridge",
    "emotion": "happy",
    "speaking": true,
    "timeline_auto_resume": true,
    "audio_path": "<VaM>/Custom/PluginData/NeuralCompanionBridge/audio/speech_1.wav",
    "audio_duration_seconds": 2.184,
    "text": "Hello there.",
    "expression_preset": "nc_happy",
    "timeline_clip": "talk_happy",
    "play_audio_in_vam": false
  }
}
```

Actions currently sent by the adapter:

- `session_start`
- `session_stop`
- `set_emotion`
- `set_speaking`
- `speech_chunk`
- `play_timeline_clip`
- `follow_state`

## VaM Setup Order

1. Install and configure the VaM VMC receiver plugin.
2. Make sure it listens on the same host/port as `vam_vmc_host` / `vam_vmc_port`.
3. Build or paste the bridge plugin sketch onto the Person atom you want to control.
4. Point the bridge plugin at the same `vam_bridge_root`.
5. Select `VaM` in Neural Companion and test emotion + speaking + motion.
6. Enable `Auto Behaviour -> Lip Sync` on the Person atom if you want built-in VaM lip sync.
7. After that works, refine emotion presets and Timeline hooks.

## Important Constraint

This scaffold is intentionally conservative:

- it does not replace the existing VSeeFace or MuseTalk paths
- it does not add a large new UI surface
- it does not assume any single VaM expression or Timeline plugin layout

You will still need to map your chosen Person atom, expression presets, and Timeline clip names on the VaM side.
