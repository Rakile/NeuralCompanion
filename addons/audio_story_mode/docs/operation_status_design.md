# Audio Story Operation Status Design

Date: 2026-07-28

## Goal

Replace the generic `Working...` project-header message with compact, accurate,
animated operation feedback inside the Audio Story Mode addon.

## Scope

The change is limited to:

- `addons/audio_story_mode/controller.py`
- `addons/audio_story_mode/ui/audio_story_mode.ui`
- Audio Story Mode smoke tests
- this addon-local design document

No core runtime, shared addon framework, provider, preset, or unrelated addon
behavior will change.

## Header Layout

The project header remains directly below the Audio Story introduction. It becomes
left-aligned and width-bounded to 420 logical pixels instead of
stretching across the page. It continues to show:

- the current project name on the left;
- the current operation or save state on the right.

Existing colors and rounded-frame styling remain intact.

## Status States

The controller owns one addon-local status presenter with these states:

1. **Idle/saved:** static muted green text such as `Saved`, `Opened`, or
   `No project open`.
2. **Active:** accurate operation text such as `Checking 4 audio files...` or
   `Importing 4 audio files...`. While active, only the status text cycles through
   green, coral red, and amber.
3. **Success:** a specific static green result such as
   `Imported 4 audio files`. After 3,000 ms, it returns to
   `Saved` if the same project and operation generation still own the label.
4. **Failure:** animation stops and the existing useful error remains visible in
   static red.

The text itself does not flash or disappear. Only its color changes. A single
`QTimer`, owned by the controller and executed on the Qt UI thread, drives the
color cycle. Starting a new state cancels any pending completion reset from an
older state.

## Operation Text

The existing project-job launcher receives optional display text rather than
deriving UI copy in worker threads. Default text is mapped for project operations,
including:

- refreshing projects;
- creating, opening, renaming, closing, and deleting a project;
- validating selected audio;
- importing validated audio;
- relinking, archiving, restoring, or reordering chapters;
- saving recovery state and legacy-project migration.

Audio import reports both existing phases:

1. `Checking N audio file(s)...`
2. `Importing N audio file(s)...`

After the commit succeeds it reports `Imported N audio file(s)` briefly, then
returns to `Saved`.

## Threading and Ownership

All filesystem validation and project mutations continue to run through the
existing background project-job pipeline. Workers never touch widgets. Status
changes occur only before launch or in existing Qt completion slots.

The transient success reset carries an incrementing status generation. Its timer
callback updates the label only when that generation is still current. This
prevents a stale `Saved` reset from overwriting a newer operation, error, project
switch, or shutdown state.

## Error Handling

Existing project errors continue to be sent to the main Audio Story status output.
The compact header also shows the useful failure text in red. Starting another
valid operation replaces the error with that operation's active state.

If the header label is unavailable during initialization or shutdown, status
helpers return safely without affecting project work.

## Tests

Addon smoke tests will verify:

- the Designer header is width-bounded and left-aligned;
- generic `Working...` is no longer used by the project-job launcher;
- import validation and commit receive distinct, count-aware text;
- active states start color cycling;
- success and failure stop color cycling;
- a stale completion timer cannot overwrite a newer status;
- the existing background project-job and audio import behavior remains intact.

The full Audio Story Mode smoke-test set and Python compilation checks will run
after implementation.
