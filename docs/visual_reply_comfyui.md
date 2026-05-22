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

## How Workflow Patching Works

NC loads the workflow, converts it to ComfyUI API format when needed, then patches the workflow before queueing it. This first version is intentionally pattern-based: it supports common text-to-image graphs, but it does not understand every possible custom-node convention.

For best results, keep the main text-to-image path explicit:

- primary sampler: a `KSampler` or `KSamplerAdvanced`; if there are several samplers, NC prefers the one whose `latent_image` comes from an empty latent or latent-size picker node
- positive prompt: a `CLIPTextEncode` node connected to, or traceable upstream from, the primary sampler `positive` input
- negative prompt: a `CLIPTextEncode` node connected to, or traceable upstream from, the primary sampler `negative` input, if the workflow uses one
- NC-controlled size: an `EmptyLatentImage` node connected to the primary sampler `latent_image` input
- seed: a sampler `seed` input, randomized per request when present
- output: a `SaveImage` node that writes an image ComfyUI exposes through its history API

The generated image is fetched from ComfyUI history and displayed in the Visual Reply dock.

ComfyUI UI workflow JSON may contain helper nodes such as `PrimitiveNode` or notes. NC converts UI workflows to API format, skips note-only nodes, and inlines primitive widget values where they feed normal node inputs. A workflow can therefore use a ComfyUI `PrimitiveNode` as a visible prompt box as long as that value ultimately feeds a normal `CLIPTextEncode` prompt path.

`EmptyLatentImage -> sampler latent_image` is required only when NC should control `Image Size` through a standard latent node. If the workflow gets its latent size from a resolution picker, uploaded image, ControlNet/img2img path, upscaler, fixed-resolution custom node, or another branch after the primary sampler, the workflow may still run, but its own nodes decide the final size. In other words: for custom size nodes, ComfyUI wins the size battle.

For ComfyUI, `Image Size` offers presets and accepts manual `WIDTHxHEIGHT` values. Custom values must be multiples of 8 between 64 and 8192, for example `832x1216` or `1280x720`.

## Version 1 Limitations

- Prompt injection expects the generation prompt to reach a normal `CLIPTextEncode` node. Custom prompt nodes that do not end in a traceable `CLIPTextEncode` path are not patched.
- Multi-stage workflows are supported best when the base sampler is the branch fed by an empty latent or latent-size picker. Refiners can still work, but NC treats the base sampler as the primary prompt and size target.
- If several positive CLIP nodes start with the same original prompt text, NC updates those matching CLIP nodes together. Separate refinement/detail CLIP nodes with different text are left alone.
- Image size control works for standard `EmptyLatentImage` width and height inputs. Resolution pickers, fixed-size custom nodes, img2img, upscalers, and post-processing branches may still determine the final output size.
- The final image must be available through a `SaveImage` output in ComfyUI history.

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
