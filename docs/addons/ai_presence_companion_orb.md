# AI Presence, Neural Face, And Companion Orb

The presence visuals are split into three ADDONS tabs:

- **AI Presence** controls the fullscreen/floating overlay shell, non-face visual styles, transparency, mood colors, computer audio sync, and main TTS audio reactivity.
- **Neural Face** controls the wireframe face renderer, face variant, lip sync, blink, gaze, glow, and female reference topology settings.
- **Companion Orb** controls the small desktop orb, movement, particles, voice sync, sensory target, and orb hotkeys.

Each addon tab exports and imports only its own settings so changing the Companion Orb no longer rewrites Neural Face controls, and Neural Face settings no longer rewrite the Companion Orb.

## Neural Face Presence

The **Neural Face** addon tab owns the animated wireframe face presets:

- **Neural Face - Male**
- **Neural Face - Female**
- **Neural Face - Auto Persona**

The **Neural Face Presence** controls face size, face opacity, animation intensity, lip-sync strength, eye movement, blink, glow, emotion reaction, TTS emotion metadata, fallback audio lip-sync, and reduced face animation. The female-specific controls also let you enable the female face, use reference-style orange connector nodes, show or hide wire nodes/lines, enable node glow, enable wire pulse, and enable subtle depth/parallax. The faces are drawn by the existing Qt Quick/QML Canvas visualizer using vector landmark topology. The bundled male and female PNGs under `addons/ai_presence_mode/assets/neural_face/` are reference templates only.

When **Fallback audio lip-sync** is enabled, the mouth follows the TTS audio amplitude that already drives AI Presence. Blink and gaze are lightweight timed animation, and mood/state changes adjust brows, eyes, and mouth shape when **Emotion reaction** is enabled.

The improved **Neural Face - Female** preset uses `reference_female_orange_nodes.png` as the topology guide and loads `reference_female_topology.json` for the visible wireframe. That topology is generated from the reference image's orange connector dots and inferred white/light-blue wire paths, so the rendered female mesh follows the blue avatar structure instead of a small hand-made approximation. The mouth and eye anchors still receive subtle QML animation for TTS amplitude, blink, gaze, and mood/state changes.

## Display Modes

The **Companion Orb** addon tab has its own display modes:

- **Off** disables the orb.
- **Docked only** keeps it parked at the selected screen corner.
- **During interaction only** shows it while NC is listening, thinking, or speaking.
- **Always visible** keeps it visible until disabled.

The orb is click-through by default so it does not block the desktop. Use **Edit Mode** or the edit hotkey to drag it, and **Placement Mode** to select a Hidden Sensory target.

## Motion And Particles

**Movement enabled** gives the orb a subtle floating drift around its base position. **Movement Range** controls how far it can wander, while **Movement Speed** controls how quickly it breathes around that spot. **Reset Position** clears the custom position and returns the orb to the selected corner on a curved animated path instead of snapping straight back.

**Falling particles** adds slow drip-like particles from the orb. **Drip Particles** controls how many falling particles are drawn. This is separate from the normal orbiting **Orb Particles** field.

## Independent Voice Sync

**Orb voice sync** is separate from the main AI Presence audio sync. The engine sends audio levels to the main fullscreen/floating AI Presence visual and the Companion Orb through separate runtime channels. **Orb Sync Rate** controls only the orb's voice-level update rate.

## Hidden Sensory Focus Target

When **Use Companion Orb as sensory focus target** is enabled, the addon registers a sensory provider named **Companion Orb Target**. This provider captures only the window or region selected with the orb. If no target is selected, the target disappears, or capture fails, it returns a warning payload instead of silently falling back to full-screen capture.

The HOST > Vision panel also has a **Use Companion Orb as sensory focus target** checkbox. Checking it selects the Companion Orb Target provider when available; unchecking it removes only that provider from Hidden Sensory Feedback.

## Hotkeys

Default app-local hotkeys:

- `Ctrl+Alt+O`: toggle the orb.
- `Ctrl+Alt+Shift+O`: toggle edit mode.
- `Ctrl+Alt+P`: toggle placement mode.
- `Ctrl+Alt+Backspace`: clear the selected target.
- `Ctrl+Alt+C`: toggle click-through.
- `Ctrl+Alt+R`: reset position.
- `Esc`: leave edit/placement mode, or hide the visible orb.

Hotkeys are ignored while typing in text fields so normal chat and settings input are not interrupted.

## Notes

The orb settings are stored with normal NC session settings. Target metadata is saved, but captures are always made from the current local desktop target and are not treated as a direct user message.
