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
6. Set `Mode` to `Auto`.

The default ComfyUI welcome workflow is supported. Both ComfyUI UI workflow JSON and API-format workflow JSON are accepted.

## How Prompt Injection Works

NC loads the workflow, converts it to ComfyUI API format when needed, then tries to infer common nodes:

- positive prompt: the `CLIPTextEncode` node connected to the sampler `positive` input
- negative prompt: the `CLIPTextEncode` node connected to the sampler `negative` input
- size: the `EmptyLatentImage` node connected to the sampler latent input
- seed: the sampler `seed` input, randomized per request
- output: the `SaveImage` node

The generated image is fetched from ComfyUI history and displayed in the Visual Reply dock.

## Notes

- NC does not need direct access to ComfyUI internals when using a reachable server URL and workflow path.
- Keep the first proof-of-concept workflow simple before using heavy custom-node workflows.
- If generation fails, check that ComfyUI is running, the workflow path is valid, and the workflow contains a prompt path to a `SaveImage` output.
