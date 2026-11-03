# User Identity

**User Identity** is a local profile for the human user: a name, preferred form
of address, short biography, interaction notes, and an optional portrait. It can
provide request-scoped context to the companion and a reference image for
Visual Replies.

It is not a Persona, a login, or an imported assistant identity. It describes
**you**, not the companion. For imported companion continuity, use
[NC Identity Relay](identity_relay.md).

## Setup Versus Activation

Open **Addons → User Identity** to reach this workspace.

1. **Addon setup:** enable **User Identity** in the Addons workspace and restart
   NC if requested.
2. **Profile setup:** fill in **Profile & portrait** and optionally import or
   generate a portrait.
3. **Activation:** keep **Enable User Identity** on for the parts you want to
   use, and separately choose whether profile text is included in requests and
   whether Visual Replies may use the portrait.

The profile can be stored while the master switch is off. Turning it off stops
profile context, the user avatar, and image references without deleting the
saved values.

## Profile Fields

Open **Profile & portrait**:

- **Name** — the name the companion should associate with you.
- **Preferred form of address** — an optional nickname, title, or form.
- **Short bio** — compact background useful in ordinary conversation.
- **Interaction notes** — preferences for how the companion should speak with
  you.
- **Enable User Identity** — master switch for profile context, user avatar, and
  user image references.

Keep the first test small. A preferred nickname and one useful interaction note
are easier to verify than a long biography.

## User Portrait

The **Accepted user portrait** preview shows the current saved image.

- **Choose portrait** imports an existing PNG, JPG, JPEG, WEBP, or BMP.
- **Generate portrait** requests a new portrait through the configured Visual
  Reply provider. It does not change that provider's saved selection.
- **Clear portrait** removes the profile's portrait reference. Previously
  generated images and past outputs are separate artifacts and are not deleted.

**Stable visual identity prompt** should describe stable appearance and style:
face, hair, age, body traits, signature clothing motifs, and art style. Leave
poses, scenes, actions, temporary moods, and backgrounds to individual image
requests. **Refine identity prompt** asks the active LLM to keep only those
stable traits; review the refined text before relying on it.

**Request transparent portrait background** applies to newly generated
portraits. Imported images are left unchanged. A transparent request is not an
edit operation on an existing file. Check the preview and inspect the actual
result; a provider can return an opaque image even when transparency was
requested.

## Visual Replies

The **Visual Replies** section controls image use:

- **Show the user avatar on user messages** — a conversation display choice. It
  does not send the image to the model.
- **Allow Visual Replies to use the user portrait** — permits the portrait as an
  image reference.
- **When the user may appear**:
  - **Include user when asked**
  - **LLM may include user**
  - **Never include user**
- **User reference strength** — how strongly the portrait should influence a
  generated image. A higher value can preserve identity but can also reduce
  pose or scene flexibility.

For a first test, use **Include user when asked** and explicitly request
something such as "Show me and the persona in a park." Review the result before
changing the policy to a broader one.

The portrait option and the **Allow Visual Replies** switch are separate from
the normal Persona visual identity. A configured Visual Reply provider is still
required.

## Privacy

**Include name and bio in current LLM requests** adds permitted profile fields
to the current request context. The addon does **not** append that profile to
canonical chat history, continuity memory, or Long-Term Memory.

That distinction matters:

- The fields are request-scoped context, not a permanent transcript entry.
- A remote provider can still receive the permitted context or image reference.
- Turning off the context switch stops profile text from being added, but it
  does not remove text that was already sent in an earlier request.
- **Never include user** for images is the narrowest image policy.
- Turning off **Enable User Identity** is the broadest stop for this addon's
  profile, avatar, and reference behavior.

This addon is local storage. It is not an account, cloud sync, authentication
method, or access-control boundary. Do not put passwords, tokens, or other
credentials in the biography or notes.

## Update Or Remove A Reference

- Change profile details in this addon rather than asking chat to "remember" a
  correction. The profile remains the local source.
- **Choose portrait** replaces the current portrait reference with the selected
  file.
- **Clear portrait** removes the addon-owned portrait reference.
- Earlier generated images, chat messages, and saved outputs are separate
  artifacts. Clearing the portrait does not rewrite them.
- Recheck the accepted preview and the Visual Replies policy before the next
  image request.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| The companion does not use your name | **Enable User Identity** and **Include name and bio in current LLM requests** must both allow the context |
| No user portrait appears | Choose or generate a portrait and confirm the **Accepted user portrait** preview |
| Generate portrait is unavailable | Configure a working Visual Reply provider and check its readiness |
| The portrait is not used in an image | Enable **Allow Visual Replies to use the user portrait**, use an appropriate **When the user may appear** policy, and request the user explicitly |
| The image ignores the portrait | Check **User reference strength**, the provider, and whether the request's pose or scene is overriding the reference |
| Transparent background did not work | Transparency is a request for new generations; imported images are unchanged, and provider output can still be opaque |
| Clearing the portrait did not remove old images | Past images and history are separate; clear those outputs where they are stored |

## Current Limits

- The profile is local to this NC installation. It is not account-synced or
  independently editable from the phone app.
- Request context is temporary. It does not become canonical chat history or
  memory.
- A remote provider can receive the permitted profile context or image
  reference; turning off local inclusion does not retract earlier requests.
- Portrait generation depends on the configured Visual Reply provider and can
  cost money.
- Transparency is a generation request, not an image editor.
- The user avatar on messages is a display choice and is not the same as a
  model-visible image reference.

## Related Guides

- [NC Identity Relay](identity_relay.md)
- [Voice Studio](voice_studio.md)
- [Addon setup and index](../manual/addons.md)
