# Corsair Visual Instrument

For the current UI entry point, see [Tools and integrations](../../docs/addons/tools-and-integrations.md). Enable the addon in Addon Manager, then open **Addons → Corsair LEDs**. The SDK and rendering reference follows.

This NeuralCompanion addon turns Corsair keyboard lighting into visual AI
feedback. It drives every keyboard that iCUE exposes with controllable LED
positions, while keeping normal keyboard input untouched.

## What it displays

- **Idle:** a soft teal breathing field on per-key keyboards.
- **Listening:** blue/cyan feedback with an inward focus.
- **Thinking:** a violet scan across per-key keyboards.
- **Speaking:** a high-fidelity audio-reactive **Equalizer** by default, with
  Classic, Living Wave, Center Ripple, Dual Comet, Plasma Field, and Audio
  Columns alternatives. Center Shockwave, Twin Voicefront, and Voice Bloom add
transient-driven waves that expand across the keyboard layout.
- **Zone State Lanes:** left = listening, center = thinking, right = speaking.
- **Zone Unified:** all lighting zones become one animated instrument: breathing
  while idle, inward focus while listening, a traveling thinking pulse, and a
  three-step speech meter.

Recognizable state colors can optionally receive a bounded tint from
NeuralCompanion's current mood.

## Install the official iCUE SDK

1. Install and run Corsair iCUE.
2. In iCUE settings, enable SDK/game integrations (the label varies by iCUE
   version).
3. Download the current SDK release from the
   [official Corsair iCUE SDK repository](https://github.com/CorsairOfficial/cue-sdk/releases).
4. Copy its 64-bit Windows DLL and accompanying license/notice files into
   `addons/corsair_visual_instrument/sdk/`, or select the DLL in this addon's
   settings tab.
5. Restart NeuralCompanion, open **Corsair LEDs**, and press **Rescan**.

The Corsair DLL is deliberately not included in this repository. The addon has
no extra Python package dependency.

## Device discovery and rendering

Automatic assignment uses the LED positions reported by iCUE instead of model
names. Coarse layouts with up to eight controllable LEDs use the zone renderer;
larger layouts use the spatial per-key renderer. With automatic assignment,
every detected keyboard with controllable LEDs receives output. Optional
overrides retain the older single-device assignment behavior for that renderer
class and preserve existing K55/K65 selections.

The settings tab lists each detected model, its controllable LED count, and the
renderer selected for it. Keyboards that iCUE reports without controllable LEDs
remain untouched and are identified in the status instead of being reported as
active lighting targets.

The addon uses the iCUE SDK's shared-lighting layer with priority 180. It does
not request exclusive lighting, subscribe to keys, intercept input, or create
macros.

## Speech level fallback

While the AI is speaking, the WASAPI output meter provides 48 logarithmic
frequency bands from the PC's mixed output. It first preserves the existing
sounddevice capture path, then uses SoundCard WASAPI loopback when Windows does
not expose a compatible sounddevice loopback or monitor input. Every selectable K65
Speaking effect uses those bands. Silence settles into a dim fixed frame; it
does not keep moving independently of the audio. The meter stops outside the
Speaking state and keeps only the newest pending audio block.

The per-key Equalizer scales to the physical coordinates reported by iCUE: quiet speech
uses one or two rows, ordinary TTS approximately three or four, and loud peaks
can reach all five. Lit rows use the configured brightness directly instead of
being faded a second time. In Equalizer mode, Intensity controls brightness,
Bar height controls vertical reach, Spectrum gain supports 0–400%, and Band
contrast separates strong and weak frequencies. Speed and Trail are disabled
for Equalizer because its band positions remain fixed and release is controlled
by Speech smoothing.

The three wave effects react only to detected audio rises or spectral changes;
elapsed time alone cannot launch a wave. Center Shockwave expands from the
keyboard center, Twin Voicefront sends two fronts toward the sides, and Voice
Bloom layers a softer center-out response. They retain at most eight recent
pulses for no more than two seconds. Their controls map to Expansion speed,
Brightness, Wave size, Wave trail, Audio sensitivity, and the selected effect's
shape/detail. Without a captured transient they remain on a fixed dim frame.

Loopback capture measures audio actually leaving the PC. Other audible PC audio
can therefore influence the keyboard during speech, and TTS routed only to a
phone is not captured. If spectrum analysis is unavailable, the addon falls
back to NeuralCompanion's scalar speech level. If both sources are unavailable,
the state-only Speaking indication remains visible and the rest of
NeuralCompanion continues normally.

## Failure behavior

Missing DLLs, disabled iCUE integrations, disconnected keyboards, and per-device
write failures are shown in the settings status. Connection work and LED writes
run on one bounded-rate background thread, so they do not block the Qt UI. The
worker retries with capped backoff and treats each keyboard independently.

Turning off the master switch or unloading the addon releases only its active
keyboard layers and disconnects from iCUE. Removing the addon directory fully
uninstalls it; no settings migration is required.
