# Release Notes Template

Use this as the starting point for a public GitHub release.

## Neural Companion vX.Y.Z

### Status

- Release type: beta / release candidate / stable
- Recommended platform: Windows, Python 3.11
- Primary UI path: `py qt_app.py --ui-real main.ui`

### Highlights

- Addon-driven chat, TTS, avatar, visuals, sensory, and workspace surfaces.
- MuseTalk, VaM, VSeeFace, and No Avatar provider support.
- Chatterbox, PocketTTS, Gemini TTS Preview, and addon TTS backend support.
- Visual Reply and Audio Story workflows.
- Addon-disabled smoke coverage for major addon categories.

### Required External Setup

- Install Python 3.11.
- Install FFmpeg and ensure it is on PATH.
- Install or configure at least one chat provider, such as LM Studio or an API provider.
- Install MuseTalk model weights separately if using MuseTalk.
- Install external avatar applications/plugins separately if using VSeeFace or VaM.
- Provide your own voice samples and avatar packs only if you have rights to use them.

### Demo Assets

The main repository does not ship voice samples, model weights, generated media,
or prepared avatar packs. Demo MuseTalk avatar packs are distributed separately:

```text
https://github.com/Rakile/NeuralCompanion-AvatarPacks
```

### Validation Performed

- `python tools/release_preflight.py`
- `python tools/addon_smoke.py`
- Startup with all addons enabled
- Startup with MuseTalk disabled
- Startup with VaM disabled
- Startup with Visual Reply disabled
- Startup with Audio Story disabled
- Chat provider/model selection
- TTS backend selection
- Visual Reply dock open/update
- Audio Story transcription and Visual Reply handoff
- MuseTalk preview/focus, if MuseTalk assets are installed
- VaM bridge controls, if VaM is installed

### Known Limitations

- Setup is still Windows/Python-heavy.
- MuseTalk requires separate model weights and benefits strongly from CUDA.
- External providers may change pricing, availability, or API behavior independently.
- Voice and avatar assets are user-supplied and must be rights-cleared by the user.

### Upgrade Notes

- Back up `runtime/`, `presets/`, `performance_profiles/`, `tutorials/`, and
  any local `avatar_packs/` or `voices/` before replacing an older checkout.
- Do not commit local `runtime/`, `avatar_packs/`, or `voices/` contents.

### Release Integrity

- Git commit:
- Git tag:
- Release date:
- Preflight result:
- Addon smoke result:
