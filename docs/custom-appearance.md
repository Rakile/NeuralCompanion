# Custom appearance themes

NeuralCompanion includes three built-in themes and an optional custom palette.
The custom editor changes the colors of the desktop interface; it does not change
personas, models, audio, addons, or the Companion Orb's own theme.

Open **Runtime > Appearance themes** and find **Custom theme** below the preset
cards.

## Create a custom theme

1. Select **Accent**, **Background**, **Panels**, or **Text**.
2. Choose a color with the color wheel, the **Brightness** slider, or a
   six-digit hex value such as `#31d5f4`.
3. Check the **Live preview** card. It previews the four colors as a small
   workspace with a panel and a button.
4. Select **Save and apply** when the palette looks right.

The wheel is keyboard-accessible: Left/Right change hue and Up/Down change
saturation. The hex field accepts six hexadecimal digits and restores the valid
value if an invalid entry loses focus.

The editor's preview is local to the draft. Other windows keep the current theme
until you save.

## Save, cancel, and reset

- **Save and apply** writes the four colors and updates the shared desktop
  palette.
- **Cancel** discards unsaved draft changes. It is available only when the draft
  differs from the saved colors.
- **Reset colors** restores the four base colors from **Midnight** in the draft.
  It does not apply them until you select **Save and apply**.

If a save fails, the error is shown in the editor and the current palette is not
replaced. A read-only session cannot save appearance preferences.

## Built-in themes

The preset cards are:

- **Midnight** — blue-black workspace with cyan focus cues.
- **Forest** — deep green studio palette with mint accents.
- **Dark Gray** — neutral graphite workspace with restrained contrast.

Applying a preset saves that choice immediately. The last saved custom colors are
retained when you switch to a built-in preset, so you can return to them later.

## What changes

The custom palette supplies the accent, window/background, panel surface, and
primary text colors. Related button states, borders, selection colors, and
contrast-adjusted shades are derived automatically.

Text, panel, and accent shades may adjust from the exact values you choose to
keep content readable. Status colors such as success, warning, and error remain
fixed. Addon-specific colors and independent Orb themes are not recolored by this
editor.

The custom theme applies to the main interface and detached workspaces that use
the shared theme. It is a presentation preference, not a per-persona or
per-session style.

## Persistence and limits

Appearance preferences are stored locally in:

```text
runtime/qml_appearance.json
```

The file is created after you save a custom theme or apply a preset. Without it,
the session keeps its existing theme choice. The write is atomic, so a failed
save does not leave a half-written preference file.

There is no import/export for custom themes, no separate color for every control,
and no way to recolor fixed addon artwork or the Companion Orb through this page.
Use a built-in preset if you want to restore an exact known palette.
