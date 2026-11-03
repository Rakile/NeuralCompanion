# Avatars and Avatar Preview

An avatar is the visual side of a spoken reply: a still expression image, a
prepared talking face, or motion sent to an external avatar application. It is
optional. A working text conversation and working speech are the best starting
point; add an avatar route after those work.

Open **Runtime → Runtime Session → Avatar** to inspect the available routes. Selecting a provider
card only opens its settings. **Use this avatar** makes that provider the active
route. No model is loaded merely because a provider or pack list was viewed.

| Route | What it produces | What you need |
| --- | --- | --- |
| **None** (No Avatar addon) | Text chat or speech without avatar rendering | No avatar runtime or pack |
| **Scenic** | Tagged still images selected from a Scenic pack | A discovered pack in `ScenicPacks/` |
| **MuseTalk** | A locally rendered talking face | Isolated MuseTalk runtime, model weights, and a prepared MuseTalk pack |
| **Ditto** | A locally animated portrait or short video | Isolated Ditto runtime, models, and a prepared Ditto package |
| **VSeeFace** | Motion sent to an external VMC avatar | VSeeFace or another compatible VMC receiver, already configured |

Only one route is active at a time. A MuseTalk pack cannot be used by Ditto, and
a Scenic image pack is not a talking-avatar package.

## Prepare, select, activate

These are separate stages:

1. **Prepare the assets.** MuseTalk and Ditto use their own creator workspaces.
   Stop the conversation runtime first, including cleanup. Preparing or previewing
   an avatar in a creator does not make it the chat avatar.
2. **Select the route.** In **Runtime → Runtime Session → Avatar**, select the provider you want to
   inspect. This does not change what chat is using yet.
3. **Choose the asset.** Pick the prepared pack, package, or base avatar. Use
   **Refresh avatar packs** if the asset was created after the page was opened.
4. **Activate it.** Stop the runtime and finish cleanup before changing a heavy
   avatar route or prepared asset. Select **Use this avatar**, then initialize
   the configured runtime so the provider loads.
5. **Test one short reply.** Send a short sentence with working speech and watch
   **Avatar Preview**. This is the first point where the whole route is proven.

## Avatar Preview

**Avatar Preview** is a separate top-level workspace. It shows output produced by
the active avatar route; it does not prepare an avatar, select a provider, or
start the conversation runtime.

- **Float preview** opens the preview in its own window.
- To keep the workspace above other applications, right-click the **Avatar Preview** tab and choose **Detach to floating window**. That window has **Always on top**. This is a separate route from **Float preview**.
- **Avatar only** hides the controls and padding for a compact companion. Hover
  the window or press **Esc** to restore them.
- **Reset zoom** fits and centers the image. Hold the middle mouse button and drag
  to pan, or use Alt + mouse wheel to zoom at the pointer.
- **Avatar focus** moves attention to the avatar's own window.

A stopped session, a route that has not produced frames yet, or an external
route may show a still image or no live output. The preview can remain idle while
the creator has a separate clean preview; a creator render is not proof that
chat is using that avatar.

## Scenic and VSeeFace

For **Scenic**, choose a discovered pack, inspect **Pack availability** and its
preview, then select **Use this avatar**. A reply with a matching emotion tag
should select the corresponding image. Scenic packs live under `ScenicPacks/`
and use `scenic_pack.json`; they do not require MuseTalk preprocessing.
Create and edit image packs in the separate [Scenic Pack Creator](../addons/scenic_pack_creator.md).
See [Scenic Avatar](../addons/scenic_avatar.md) for a minimal pack example and
emotion-image fallback behavior.

For **VSeeFace**, follow the [VSeeFace provider guide](../addons/vseeface.md) for
the Echo test avatar, receiver settings, speech bridge and body presets.
Configure the avatar and VMC receiver in VSeeFace first, then
activate the NC route and test a short spoken reply. Body, dynamics, and hand
controls tune that external integration. They do not create MuseTalk or Ditto
assets. If the external avatar does not move, check the receiver and connection
before changing pose settings.

## Packs, rights, and troubleshooting

MuseTalk and Ditto prepared assets normally live under
`avatar_packs/<pack_id>/`. Keep the entire pack folder together when moving or
backing it up. See [Avatar packs](../avatar_packs.md) for installation, engine
differences, and the separately distributed Echo/Eon demo packs. Voice and
persona assets are covered by the [release asset policy](../release_asset_policy.md);
they are not talking-avatar packs.

If there is no avatar output:

1. Confirm the active route and the selected prepared asset in **Runtime → Runtime Session → Avatar**.
2. Confirm that speech itself works with avatar provider **None**.
3. Check whether the session was initialized after changing the route.
4. For MuseTalk or Ditto, confirm the isolated runtime and models are ready.
5. For an external route, check the receiving application before changing NC
   pose or animation settings.

**Clear cache** in the MuseTalk Avatar Creator removes prepared acceleration data
for a selected MuseTalk avatar; it is not a general GPU-unload command. If GPU
memory remains occupied, stop chat, let creator work finish, and use the
engine-specific cleanup actions. For preparation details, see
[MuseTalk](musetalk.md) and [Ditto](ditto.md).
