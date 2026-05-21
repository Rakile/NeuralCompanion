# ComfyUI Visual Reply Provider

NeuralCompanion can use a local or LAN ComfyUI server as a Visual Reply image provider.

## Requirements

- ComfyUI running with its HTTP API available.
- A saved ComfyUI workflow JSON.

Default local server URL:

```text
http://127.0.0.1:8188
```

LAN servers work too, for example:

```text
http://192.168.1.50:8188
```

## Basic Setup

1. Start ComfyUI.
2. In NeuralCompanion, open `Visual Reply Runtime`.
3. Set `Provider` to `ComfyUI`.
4. Set `Server URL` to the ComfyUI server.
5. Set `Workflow JSON` to a saved ComfyUI workflow.
6. Choose a `ComfyUI Cleanup` mode.
7. Set `Mode` to `Auto`.

These Visual Reply runtime choices are session state. They restore on restart,
but saving/loading a preset does not change them.

The default ComfyUI welcome workflow is supported. Both ComfyUI UI workflow JSON and API-format workflow JSON are accepted.

## How Prompt Injection Works

NC loads the workflow, converts it to ComfyUI API format when needed, then tries to infer common nodes:

- positive prompt: the `CLIPTextEncode` node connected to the sampler `positive` input
- negative prompt: the `CLIPTextEncode` node connected to the sampler `negative` input
- size: the `EmptyLatentImage` node connected to the sampler latent input
- seed: the sampler `seed` input, randomized per request
- output: the `SaveImage` node

The generated image is fetched from ComfyUI history and displayed in the Visual Reply dock.

## Memory Cleanup

ComfyUI keeps models loaded after generation so the next image is much faster. That can make VRAM/RAM look like it keeps climbing even when the second generation is working from cache.

The `ComfyUI Cleanup` setting controls what NC asks ComfyUI to do after each finished image:

- `Keep cache`: fastest repeat generations; ComfyUI keeps models warm.
- `Free memory`: asks ComfyUI to clear unused memory after each image.
- `Unload models + free memory`: releases more memory, but the next image will reload models and be slower.

You can also set `NC_VISUAL_REPLY_COMFYUI_CLEANUP` to `keep_cache`, `free_memory`, or `unload_models`.

## Notes

- NC does not need direct access to ComfyUI internals when using a reachable server URL and workflow path.
- Keep the first proof-of-concept workflow simple before using heavy custom-node workflows.
- If generation fails, check that ComfyUI is running, the workflow path is valid, and the workflow contains a prompt path to a `SaveImage` output.
