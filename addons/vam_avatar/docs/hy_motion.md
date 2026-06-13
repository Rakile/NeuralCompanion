# HY-Motion for VaM Avatar

The VaM Avatar addon can launch Tencent HY-Motion 1.0 as an isolated subprocess to generate text-to-motion assets. NC does not import PyTorch or HY-Motion into the main runtime.

## Default Paths

- HY-Motion source: `addons/vam_avatar/tools/hy_motion/HY-Motion-1.0`
- HY-Motion venv: `addons/vam_avatar/.venv-hymotion`
- Addon model cache: `addons/vam_avatar/models/hy_motion/HY-Motion-1.0-Lite`
- User-provided Lite model: `Q:\HY-Motion model`
- Outputs: `addons/vam_avatar/outputs/hy_motion`
- VaM root default: `I:\wam\VaM 1.20.0.6`

The addon will use `Q:\HY-Motion model` when it contains `config.yml` and `latest.ckpt`. Your current Lite checkpoint folder matches that requirement.

## Setup

From the clean NC repo:

```powershell
cd Q:\NeuralCompanion-dev
python addons\vam_avatar\scripts\hymotion_setup.py --check --dry-run
python addons\vam_avatar\scripts\hymotion_setup.py --create-venv
python addons\vam_avatar\scripts\hymotion_setup.py --clone
python addons\vam_avatar\scripts\hymotion_setup.py --install
```

If you want the addon to download Lite into the addon cache instead of using `Q:\HY-Motion model`:

```powershell
python addons\vam_avatar\scripts\hymotion_setup.py --download-model --model-path addons\vam_avatar\models\hy_motion\HY-Motion-1.0-Lite
```

For CUDA-specific PyTorch wheels, install PyTorch in the addon venv before `--install`, or pass a CUDA index URL:

```powershell
python addons\vam_avatar\scripts\hymotion_setup.py --install --torch-index-url https://download.pytorch.org/whl/cu124
```

## Generate Motion

The addon capability is `runtime.hy_motion_prompt_to_motion`. It writes a one-line HY-Motion prompt file and runs:

```powershell
addons\vam_avatar\.venv-hymotion\Scripts\python.exe addons\vam_avatar\tools\hy_motion\HY-Motion-1.0\local_infer.py --model_path "Q:\HY-Motion model" --input_text_dir <run-input> --output_dir <run-output> --cfg_scale 5.0 --num_seeds 1 --device_ids 0 --disable_rewrite --disable_duration_est
```

Defaults are conservative: Lite model, one seed, 4 seconds, prompt rewrite disabled, duration estimation disabled.

## Small Test App

For live testing without starting the full NC UI, use the addon-local HY-Motion test app:

```powershell
cd Q:\new dev_latest\NeuralCompanion-dev
python addons\vam_avatar\scripts\hymotion_test_app.py
```

The app has a prompt box, duration/CFG/seeds/validation-step controls, VaM root field, bridge status check, and buttons for:

- `Generate and Send`: runs HY-Motion from the typed prompt, stages the result, and writes a bridge command to VaM.
- `Generate Only`: runs HY-Motion and stages the result without notifying VaM.
- `Send Latest`: resends the newest staged motion manifest to the VaM bridge.
- `Bridge Status`: reads the current bridge status and last HY-Motion result from VaM.

CLI equivalents:

```powershell
python addons\vam_avatar\scripts\hymotion_test_app.py --status
python addons\vam_avatar\scripts\hymotion_test_app.py --prompt "A friendly wave with relaxed posture" --duration 4 --cfg-scale 5 --num-seeds 1
python addons\vam_avatar\scripts\hymotion_test_app.py --send-latest
```

Use `--dry-run` to validate command construction without running HY-Motion or writing to the VaM inbox:

```powershell
python addons\vam_avatar\scripts\hymotion_test_app.py --prompt "A short test wave" --duration 1 --dry-run
python addons\vam_avatar\scripts\hymotion_test_app.py --send-latest --dry-run
```

Optional real smoke test:

```powershell
$env:NC_VAM_HYMOTION_REAL_INFERENCE='1'
python addons\vam_avatar\smoke_hymotion.py
```

## VaM Bridge Behavior

Generated motion metadata can be packaged as a VaM bridge payload with `runtime.hy_motion_build_vam_bridge_payload`. HY-Motion output assets are staged into:

```text
I:\wam\VaM 1.20.0.6\Custom\PluginData\NeuralCompanionBridge\motion\<run_id>
```

The VaM-side `NeuralCompanionBridge.cs` handler can receive `hy_motion_generated`, verify the staged FBX/NPZ files, write `outbox\last_hy_motion.json`, and update `outbox\status.json`.

Because VaM does not expose a reliable runtime FBX importer to a normal MVRScript, the addon now creates native motion data from the HY-Motion NPZ:

- `motion_smpl.json`: flat SMPL-H motion data with `frameCount`, `fps`, `poses`, `trans`, and `Rh`.
- `motion_proxy.json`: a smaller controller proxy fallback.
- `motion_timeline_clip.json`: readable AcidBubbles Timeline clip export using controller keyframe objects.
- `motion_timeline_storable.json`: Timeline storable wrapper containing the generated clip.

The bridge prefers `motion_smpl.json` and drives common Person controllers directly. It falls back to `motion_proxy.json` when SMPL playback is disabled or unavailable.

SMPL playback targets:

- hip / pelvis
- abdomen / chest / neck / head
- shoulders / arms / elbows / hands
- thighs / knees / feet

Proxy fallback targets:

- hip / pelvis
- chest / abdomen
- head / neck
- left hand
- right hand

The FBX is still staged as a reference asset for later retargeting/import workflows.

The bridge plugin exposes:

- `Play Latest HY-Motion`: VaM action/button that replays the latest generated/staged motion.
- `Stop HY-Motion`: VaM action/button that stops playback and optionally returns to the saved pose.
- `Reset HY-Motion Pose`: VaM action/button that smoothly returns controlled body controllers to their saved pose.
- `Load HY-Motion By Name`: VaM action/button that loads `Custom/PluginData/NeuralCompanionBridge/motion/<name>`.
- `Set HY-Motion Strength`: master strength slider. VaM triggers can set this float directly.
- `Loop HY-Motion`: loop toggle. VaM triggers can set this bool directly.
- `HY-Motion SMPL Playback`: enables/disables SMPL playback.
- `HY-Motion Rotation Strength`: scales SMPL axis-angle rotation.
- `HY-Motion Proxy Playback`: enables/disables proxy playback.
- `HY-Motion Proxy Strength`: scales controller movement from 0.0 to 2.0.
- `HY-Motion Blend Seconds`: smooth blend-in/reset timing.
- `HY-Motion Drive Root`, `HY-Motion Drive Upper Body`, `HY-Motion Drive Arms`, `HY-Motion Drive Legs`: body-part masks for safer blending with scene animation.
- `HY-Motion Conflict Guard`: temporarily disables obvious jaw/lip-sync conflicts and logs likely Timeline/BodyLanguage/Glance/IK peers.
- `Open HY-Motion Started Trigger`, `Open HY-Motion Finished Trigger`, `Open HY-Motion Missing/Failed Trigger`: opens VaM trigger panels so scenes can react to HY-Motion events.

The bridge actions are normal VaM receiver targets, so Timeline, LogicBricks, buttons, or other scene triggers can call them the same way the Voxta demo scene calls plugin actions.

HY-Motion event triggers:

- `On HY-Motion Started`: fires when SMPL/proxy playback starts.
- `On HY-Motion Finished`: fires when playback finishes or is stopped through the bridge.
- `On HY-Motion Missing/Failed`: fires when no playable HY-Motion file exists, a file cannot be read, or native playback is unavailable.

The bridge also writes the latest event to:

```text
I:\wam\VaM 1.20.0.6\Custom\PluginData\NeuralCompanionBridge\outbox\hy_motion_event.json
I:\wam\VaM 1.20.0.6\Custom\PluginData\NeuralCompanionBridge\outbox\hy_motion_events.log
```

The Windows test app can also send those commands through the inbox:

```powershell
python addons\vam_avatar\scripts\hymotion_test_app.py --play-latest
python addons\vam_avatar\scripts\hymotion_test_app.py --stop
python addons\vam_avatar\scripts\hymotion_test_app.py --reset-pose
python addons\vam_avatar\scripts\hymotion_test_app.py --load-name motion_1781296916_1f5c44b0
python addons\vam_avatar\scripts\hymotion_test_app.py --verify-actions
```

`--verify-actions` sends a self-test command, waits until VaM consumes the command file, checks the bridge version/status, and then sends `hy_motion_play_latest`. If the self-test command is not consumed, VaM is closed, polling is off, or the bridge plugin is not loaded. If VaM reports `Unknown bridge command` or the version is old, the updated script file is installed but the plugin has not been reloaded yet.

To install a small HY-Motion lab scene into VaM from the safest existing one-Person bridge scene:

```powershell
python addons\vam_avatar\scripts\hymotion_install_lab_scene.py
```

It writes:

```text
I:\wam\VaM 1.20.0.6\Saves\scene\NeuralCompanion\HY_Motion_Lab.json
```

The lab scene includes one bridge-equipped Person atom plus simple scene buttons:

- `Self Test`
- `Play Latest`
- `Stop`
- `Reset Pose`
- `Loop On`
- `Loop Off`
- `Started Event`
- `Finished Event`
- `Missing/Failed Event`

Those buttons use normal VaM trigger receiver targets on `Person/plugin#0_NeuralCompanionBridge`, so they exercise the same action surface that Timeline or LogicBricks would use.

The event buttons open the bridge trigger panels. Wire those panels to scene lights, UI labels, audio, expressions, or Timeline reactions to make the lab scene behave like a normal VaM action router.

## Timeline Export

Every staged HY-Motion run now includes Timeline-friendly JSON artifacts next to `motion_smpl.json`:

```text
Custom\PluginData\NeuralCompanionBridge\motion\<run_id>\motion_timeline_clip.json
Custom\PluginData\NeuralCompanionBridge\motion\<run_id>\motion_timeline_storable.json
```

The export uses Timeline's readable full keyframe format (`t`, `v`, `c`) instead of Timeline's optimized encoded strings. That makes it inspectable and avoids depending on Timeline internals. Treat this as an editable/import helper: runtime playback is still handled by the bridge from `motion_smpl.json` / `motion_proxy.json`.

The addon also copies the SMPL JSON into Voxta's debug animation folder when VaM is configured:

```text
I:\wam\VaM 1.20.0.6\Saves\PluginData\Voxta\Animation\<run_id>.json
```

If Voxta is installed on the Person atom, its Animate tab can load that file from the debug animation dropdown. This is an interoperability route; NeuralCompanion does not copy Voxta source code.

If VaM was already running when the bridge script was updated, reload/re-add the `NeuralCompanionBridge.cs` plugin or restart VaM before testing the HY-Motion command. VaM keeps the old loaded script in memory until it is reloaded.

To resend the newest generated HY-Motion result to the VaM bridge:

```powershell
python addons\vam_avatar\scripts\hymotion_send_bridge.py
```

To send a specific run:

```powershell
python addons\vam_avatar\scripts\hymotion_send_bridge.py --manifest "Q:\new dev_latest\NeuralCompanion-dev\addons\vam_avatar\outputs\hy_motion\motion_1781276836_52231da5\motion_manifest.json"
```

## Hardware Notes

The HY-Motion README lists HY-Motion-1.0-Lite at about 24 GB minimum VRAM. To reduce memory use, keep `num_seeds=1`, prompts short, and motion duration under 5 seconds.

## Troubleshooting

- CUDA or PyTorch mismatch: verify the addon venv with `addons\vam_avatar\.venv-hymotion\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"`.
- Missing Git LFS: install Git LFS, then run `git lfs pull` in the HY-Motion checkout.
- Hugging Face auth/rate limits: login with `huggingface-cli login` or set `HF_TOKEN`.
- FBX output missing: HY-Motion falls back when FBX SDK is unavailable. Check the run output for HTML/dict files and import/convert manually.
- Prompt engineering errors: keep rewrite and duration estimation disabled unless you configure a prompt engineering host or model path.
