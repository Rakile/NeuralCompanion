# Visual Reply slash commands

The desktop conversation composer supports two image commands. Select a command
from the `/` menu, enter the prompt, then press Enter or Run.

## Generate directly

```text
/generate_visual A red ceramic teapot beside a sunlit window
```

This queues one image through the existing Visual Reply pipeline using the
current image provider and generation settings. It does not ask the chat LLM to
rewrite the prompt or create a normal LLM chat turn. Provider-specific prompt
formatting and the existing Visual Reply rendering rules still apply.

NC must be initialized and the active image provider must be configured in
**Runtime → Runtime Session → Visual reply**. This
explicit image request works even when automatic Visual Reply is off, without
changing that saved setting. A rejected request stays in the composer so it can
be corrected or retried. Selecting the command without a prompt only completes
`/generate_visual ` in the composer.

When generation succeeds, the image appears as its own image-only message in the
conversation, using the same Visual Reply display mode, image actions and
auto-follow behavior as a regular generated reply. No LLM response or TTS is
created. Failed generation does not leave a blank chat message.

## Refine, review, then generate

```text
/generate_visual_refine A red teapot, warm morning light
```

This uses the selected slash-command LLM provider to refine the image prompt in
the existing background draft worker. The resulting draft is **not generated or
sent to chat automatically**.

1. Review or edit the image prompt in the draft editor.
2. Choose **Generate image** to queue the edited prompt with the current Visual
   Reply image provider and settings.
3. Use **Copy**, **Regenerate**, **Restore original**, or **Discard** as needed.
   **Cancel** stops a
   pending refinement without generating an image.

The slash-command LLM provider and the Visual Reply image provider are separate
selections. For example, a chat LLM can refine the prompt while ComfyUI generates
the image. Existing writing commands retain their **Send draft** behavior.

Refinement follows the existing session, shutdown and composer-change cancellation
rules. A failed refinement preserves the original request. A rejected image queue
request preserves the refined draft for retry. Images follow the current Visual
Reply display and auto-show behavior.

## Show generated images in chat

Under conversation **Controls**, **Show generated images in chat** is On by
default. It applies to normal Visual Reply images and both generation commands.
Off hides generated previews and image-only rows; text messages and user image
attachments remain visible. It does not delete images or change generation or
the Visual Reply dock. On restores existing generated images immediately. The
preference is saved between sessions.

For ordinary persona-driven images, image-to-image settings, and sensory
permissions, see [Visual Reply and sensory awareness](visual-reply-and-sensory.md).
