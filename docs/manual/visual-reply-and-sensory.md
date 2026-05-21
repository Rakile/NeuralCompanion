# Visual Reply And Sensory Features

Neural Companion includes optional visual and sensory workflows through addons.

Examples include:

- Visual Reply
- screen source
- webcam source
- clipboard source
- screen supervisor
- webcam supervisor
- clipboard supervisor
- heart-rate behavior

Enable these after basic chat, speech, and avatar setup are working.

## Privacy

Screen, webcam, and clipboard features can inspect local user context. Enable
only the sources you intend to use.

## Provider Requirements

Some visual or sensory workflows may require external models, API keys, or local
runtime configuration. Check each addon panel for its current settings.

Visual Reply supports hosted providers and local ComfyUI workflows. For ComfyUI,
run the ComfyUI server, select `ComfyUI` as the Visual Reply provider, enter the
server URL, point `Workflow JSON` at a saved workflow, and choose whether ComfyUI
should keep its model cache or free/unload models after each image. See
[`docs/visual_reply_comfyui.md`](../visual_reply_comfyui.md) for setup details.

Visual Reply provider/runtime choices are saved in the local session, not in
presets. Changing provider, workflow/model, image size, or auto-show should
survive restart without making the selected preset dirty.

## Good Testing Order

1. Start with text chat and speech.
2. Enable one sensory source.
3. Verify the source updates as expected.
4. Enable one supervisor or visual feature.
5. Test before combining multiple sources.
