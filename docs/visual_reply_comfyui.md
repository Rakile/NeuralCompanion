# ComfyUI Visual Reply provider

NeuralCompanion can use a local or LAN ComfyUI server as its **Visual Reply**
image provider. NC sends a prompt and a workflow to ComfyUI, waits for the result,
and displays the image that ComfyUI exposes in its history.

ComfyUI remains a separate application. NC does not install ComfyUI, its custom
nodes, checkpoints, VAEs, or models for you.

## Before you start

You need:

- ComfyUI running with its HTTP API reachable from the NC computer.
- A saved ComfyUI workflow that produces an image.
- The workflow's models and custom nodes installed in that ComfyUI instance.
- A **SaveImage** output so the finished image appears in ComfyUI history.

The default local address is:

```text
http://127.0.0.1:8188
```

A LAN example is `http://192.168.1.50:8188`. Use the address that the NC machine
can reach, not necessarily the address shown inside ComfyUI on another computer.

## Connect and activate

1. Start ComfyUI and confirm its web interface works.
2. In NeuralCompanion, open **Runtime → Runtime Session → Visual reply** and select **ComfyUI**.
3. Set **Server address**.
4. Set **Workflow path** to the saved workflow.
5. Select **Refresh workflow** and wait for inspection to finish.
6. Review **Prompting Rules**, **Detected model**, **Active rules**, and the
   workflow status.
7. Set **Visual reply mode** to **Automatic**.
8. Select **Make active**.
9. Use **Initialize NC** in the header if the session is stopped, then send one simple image request in **Conversation → Main chat**.

Selecting the provider card or opening its settings does not activate it, and
does not prove that ComfyUI can run the workflow. The first successful image is
the end-to-end test.

### Workflow path

Use **Set folder** to choose a local directory of JSON workflows, then select
one from **ComfyUI workflow**. The picker shows JSON files in that folder and
displays the selected full path below it. Changing the folder leaves your
current workflow selected until you choose another file. An empty folder shows
**No JSON workflows in this folder**. You can still enter a path or supported
server reference directly in **Workflow path**.

**Workflow path** accepts:

- a local exported ComfyUI workflow JSON file;
- a UNC/network path or HTTP(S) URL to the JSON;
- a ComfyUI server reference such as `workflows/name.json`,
  `userdata:workflows/name.json`, or `template:name`;
- either a ComfyUI UI workflow or an API-format workflow.

For a first test, an exported JSON file on the NC computer is the easiest to
verify. A UI workflow may contain notes and `PrimitiveNode` helpers; NC converts
it to API format and inlines primitive values where they feed normal node inputs.
A workflow containing custom nodes must have those nodes installed on the
server.

Saved UI subgraphs in `definitions.subgraphs` are expanded before prompt
detection. Each instance retains its promoted values and connections, including
model, LoRA, and sampler settings. For subgraphs with muted or bypassed nodes,
export API-format JSON from ComfyUI instead; NC reports unsupported modes rather
than activating those nodes.

Recognized prompt-enhancer paths through `PrimitiveString`,
`PrimitiveStringMultiline`, `TextGenerate`, `ComfySwitchNode`, and `PreviewAny`
remain connected. NC updates the source scene prompt while preserving the
enhancer's system instructions. Unrecognized text-processing paths use the
existing direct text-encoder fallback.

## Prompting Rules

ComfyUI models often expect different prompt syntax. **Prompting Rules** selects
the prompt style NC uses:

- **Auto Detect**
- **Pony Realism**
- **Pony XL / Pony Diffusion**
- **CyberIllustrious Semi-Realistic - Play V4**
- **SDXL Photorealistic**
- **SDXL General / Artistic**
- **FLUX**
- **SD 1.5**
- **Generic / Custom**

Auto Detect reads the checkpoint/model name in the workflow and selects a known
rule set when it recognizes one; otherwise it falls back to **Generic / Custom**.
You can choose a rule manually when detection is wrong.

**Detected model** and **Active rules** show what NC currently understands. This
detection is guidance, not proof that a checkpoint will behave as its filename
suggests. The prompt rules are sent to the model only as prompt guidance and do
not modify your workflow's connections.

## Generation settings

Each server and workflow has its own saved generation profile. Changing either
**Server address** or **Workflow path** switches to a different profile.

### Output dimensions

- **NC output size** uses NC's size control. **Auto** uses `1024x1024` when a
  supported latent node is present.
- **Use workflow dimensions** keeps the dimensions already in the graph. This is
  the safest choice for a workflow with a resolution picker or unusual latent
  node.
- **Custom dimensions** is available only when NC can edit a standard latent
  width and height. Width and height must be integers, multiples of 8, and
  between 64 and 8192.

Workflow dimensions are the initial latent size. Upscalers, refiner stages, and
later nodes can still change the final image size.

### Seed

- **NC default (existing behavior)** randomizes the primary sampler's seed for
  each request. An Advanced sampler's `noise_seed` remains workflow-controlled.
- **Random each reply** also randomizes the selected sampler seed.
- **Use workflow seed** keeps the seed in the graph.
- **Fixed seed** uses the unsigned 64-bit value you enter.

A fixed seed only makes a comparison repeatable when the rest of the workflow and
server are unchanged. If the seed input is linked or unsupported, NC leaves it
workflow-controlled.

### Sampler overrides

If the workflow contains more than one supported sampler, choose **Sampler node**.
The detected primary is shown as guidance; overrides affect only the selected
target.

Turn on **Override sampler settings** to expose **Steps**, **CFG**, **Denoise**,
**Sampler**, and **Scheduler**. Fields that are linked, unsupported, or lack
server metadata remain read-only. **Reset sampler overrides** removes the saved
Steps/CFG/Denoise/Sampler/Scheduler overrides. It does not change the selected
output dimensions or seed mode.

**Next reply** summarizes the effective dimensions, seed mode, and selected
sampler values. Check it before generating.

### Advanced options

- **Negative prompt**: blank uses the saved workflow/provider negative. NC still
  adds its rendering exclusions.
- **Generation timeout**: how long NC waits for ComfyUI, in seconds.
- **Memory cleanup**: **Keep cache (fast repeat generation)**, **Free unused
  memory**, or **Unload models + free memory (reload next time)**.

Keeping models loaded is faster but uses more VRAM/RAM. Unloading makes the next
image slower because ComfyUI must reload models.

## How NC patches the workflow

This is intentionally pattern-based. It supports common text-to-image graphs but
does not understand every custom-node convention.

For best results, keep the main path explicit:

- **Primary sampler:** `KSampler` or `KSamplerAdvanced`. With several candidates,
  NC prefers the one fed by an empty latent or latent-size picker.
- **Positive prompt:** a `CLIPTextEncode` connected to the primary sampler's
  `positive` input, or reachable through a recognized prompt helper chain.
- **Negative prompt:** a `CLIPTextEncode` connected to the sampler's `negative`
  input, if the workflow uses one.
- **Size:** an `EmptyLatentImage`-style node with editable width and height when
  NC should control dimensions.
- **Seed:** a sampler seed input, randomized or fixed as selected.
- **Output:** a `SaveImage` node, whose result NC fetches from ComfyUI history.

If no supported sampler is found, the workflow can still be used only when NC
can inject a prompt; sampler overrides and dimension controls may remain
unavailable. A workflow that gets its prompt from an unrecognized custom node may
run but ignore NC's prompt.

## Limitations and troubleshooting

- NC generates one image per request.
- Prompt injection requires a traceable prompt path to a normal text encoder.
  Custom prompt nodes that cannot be reached are not patched.
- Multi-stage workflows work best when the base sampler is the branch fed by an
  editable latent. Refiners and upscalers may decide the final size.
- Custom nodes, linked inputs, and server-specific nodes can make fields
  read-only or unavailable.
- A successful queue does not guarantee a useful image. Check ComfyUI's own
  console for node errors, missing models, or out-of-memory failures.
- If **Refresh workflow** cannot inspect the graph, confirm that the server
  address and workflow path point to the same ComfyUI instance and that its API
  is reachable.

If generation fails, first try a simple default workflow, then re-add custom
nodes and refiners one at a time. This makes it clear whether the failure is in
NC's prompt/size injection or in the workflow itself.
