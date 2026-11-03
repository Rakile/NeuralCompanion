# Companion Chess — NC desktop addon

For user setup and play, start with the [Companion Chess guide](../../docs/addons/companion_chess.md). This README contains the implementation and hardware reference.

Play locally with a saved NeuralCompanion persona or online against another NC player. The native QML addon supplies 2D, embedded 3D and fullscreen 3D boards. The existing local Companion Chess MCP Server owns local games; the separate multiplayer Chess MCP service owns online matches through NC Relay.

## Runtime and setup

Use NC's **Python 3.11** interpreter. The addon launches its server with `sys.executable`, so there is no Python 3.14 requirement or separate launcher environment. The existing NC installation supplies PySide6, MCP Core and JSON Schema. The server additionally needs `chess==1.11.2`. Optional Launchpad support needs `mido` and `python-rtmidi`; no MIDI backend is imported or enumerated before activation. See `requirements.txt`; installing dependencies into an existing environment requires the owner's authorization.

1. Restart NC after the addon files and host integration are installed. Enable **Companion Chess** and **Chat MCP Tools** in the addon manager if needed. MCP Core stays loaded; turn on **Allow MCP access** in its Runtime page.
2. Open **Companion Chess → Setup → Start Companion Chess Server**. The default endpoint is `http://127.0.0.1:8766/mcp`. The server starts only on this explicit action.
3. Choose **Show setup credential**. In **Runtime → MCP Core**, add that endpoint as a Streamable HTTP connection using Bearer authentication, paste the credential, and connect/discover tools. Credentials use NC's existing Windows vault adapter. Do not put them in source control.
4. Refresh Companion Chess, select the connection, and choose **Request access**. In MCP Core approve Companion Chess access to the seven chess tools listed below.
5. Also grant **Chat MCP Tools** access to `chess_choose_move`, and assign that tool to the desired saved persona under **Persona → MCP**. Existing grants and persona assignments remain authoritative; the addon never grants itself access.
6. Refresh the chess page, select the opponent and side, then start **New game**. The saved persona's provider configuration, personality and voice are used without switching the main chat's selected persona.
7. Stockfish is optional and is not installed by the NC main installer. New setups use the basic engine. In Setup, **Install Stockfish…** (Windows) installs official Stockfish 19 in a `Stockfish` subfolder of a parent folder you choose and selects it. **Select existing engine…** browses to an executable you already have. A custom path can still be entered, and clearing the field selects the basic engine. Start a new game to apply engine changes.

Existing custom paths and legacy bundled selections are preserved. The legacy bundled marker resolves from the current NC folder; if its engine is missing, Chess remains playable with the basic engine and Setup offers install/select controls. The strength slider applies to Stockfish.

The explicit addon setup reuses `installer_stockfish.py` to verify pinned official x64/ARM64 universal archives, retain upstream Copying.txt and packaged source files, and reuse intact installations. Installation and file checks run in the existing Chess worker; progress/cancellation use its snapshot and cancellation token. Failed/cancelled installs keep the previous engine preference. Choose **Install Stockfish…** and the same parent folder to repair missing/corrupt NC-owned files; unrecognized content is preserved. Stockfish is installed into the chosen folder, not a Python environment. Official release: https://github.com/official-stockfish/Stockfish/releases/tag/sf_19.

The server is stopped when the addon shuts down if this addon launched it. On a later NC run, start it again and reconnect MCP Core as needed. An independently running server with the matching installation identity may be reused and is not stopped by this addon.

## Desktop experience

Local game endings open a result window naming the winner and showing checkmate, resignation, or the draw reason. Close keeps the final board visible; New game starts another game explicitly. End game in the status strip stops a local session without awarding a winner, including while the persona is thinking or a physical move is unfinished. It keeps committed moves and cancels any unfinished move. Resign remains a separate action that awards the opponent a win.

After updating, restart NC and its local Companion Chess Server, then reconnect/discover its tools in MCP Core so the new chess_game_control end action is available. Pairing credentials and grants are unchanged.

The normal workspace and fullscreen controls follow NC's active Midnight, Dark Gray, Forest or custom theme. A compact 2D/3D/fullscreen toolbar sits above the board; Game, Scene, Sounds and Setup share NC's standard controls. The inspector stacks below the board on narrow windows, while the persona/commentary and recovery strip stays visible. Board materials retain the chosen chess style's colors.

Fullscreen provides Scene, Audio and Game panels with space reserved beside the board (below it on narrow screens). The stage scrolls on short screens while commentary remains pinned. Promotion and confirmation dialogs belong to the window being used. Escape dismisses a dialog first, then settings, then exits fullscreen. Both views use the same selected persona, position, settings and commands.

Setup shows the actual connection state; a failed refresh marks it disconnected without discarding the last board. New game is disabled while disconnected, without a selected persona, during a pending physical move or while settings are being saved. Persona MCP tool assignment remains an explicit setup step. Scene changes preview immediately and coalesce while the addon worker is busy, preserving the final value.

- **Classic:** ivory/black Spiral Chess pieces and a wooden board/table. **Modern:** the same sculpted set with metallic materials and a stone surface. **Fantasy:** the spiral set in green/plum on a natural earth surface. Reduced detail retains the original lightweight procedural pieces. The six meshes are bundled assets; there is no model-import UI or runtime conversion.
- Scene controls select spotlight, study, studio or moon lighting, plus brightness, warmth, direction, elevation, fill and shadows. Settings are saved separately for each style. The spotlight preset lights only the board and pieces, leaving the surroundings black; other presets reveal the ground/table.
- Orbit, tilt and distance controls adjust the camera. Fullscreen keeps move interaction and promotion choices available; Escape exits. Use 2D or reduced detail for slower graphics hardware.
- Sounds has 25 assignable slots, volume, enable/disable and preview controls. **Import from I:/chess** copies files referenced by the original app's `sound_settings.json` into addon storage. Original files are not changed. Voice commentary continues through NC's existing speech pipeline.
- Persona commentary is shown after a legal candidate has been accepted. An invalid model choice gets one repair attempt, then a clearly labelled engine fallback. Provider/network failures require Retry. Voice is optional and yields to existing NC speech; a displayed move can proceed when voice is skipped.

## Optional Launchpad hardware

All hardware settings stay unloaded and hidden until **Connect / Activate hardware** is pressed. Desktop play needs no Launchpad.

After activation, choose your actual hardware model: Launchpad MK1 / Original (NOVLPD01), S, Mini MK1, Mini MK2, MK2, Pro (original), Mini MK3, X or Pro MK3. Local and Online use the same hardware catalog. The visual board model is a separate appearance setting and does not select the MIDI protocol.

MK1, S and Mini MK1/MK2 use XY notes and red/green LEDs. MK1 output is paced to its documented 400-message/second USB limit. The new legacy profiles reset to XY mapping when explicitly connected. Existing S and original Pro messages are preserved.

Original Pro uses its Standalone USB pair, not Live or DIN. MK2 uses its Session grid layout. Mini MK3 and X use the second Windows interface (USB MIDI), not the first interface (DAW); Pro MK3 uses the first USB MIDI pair, rather than DIN or DAW. MIDI port names vary by OS: choose the matching input and output explicitly. Modern devices enter Programmer mode on Connect and return to Live on Disconnect; this does not restore a previous custom layout.

For the original MK1/NOVLPD01 on Windows, the Novation USB driver must expose its MIDI ports. The NC installer now includes mido and python-rtmidi, but those Python packages do not install the operating-system USB driver. Obtain the driver from https://downloads.novationmusic.com/novation/launchpad-mk1/launchpad if its ports are missing. No driver or package is installed merely by opening the chess page.

Test corner LEDs and select white/black orientation. Match the physical pieces to the displayed board, then press Physical board matches. Pads confirm your actions; they do not sense the printed pieces. Protocol and simulated-port checks cover all nine models; physical-device verification remains required.

Protocol sources: [MK1 programmer reference](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/launchpad-programmers-reference.pdf), [MK2 reference](https://downloads.novationmusic.com/novation/launchpad-mk2/launchpad-mk2), [Mini MK3 reference](https://downloads.novationmusic.com/novation/launchpad-mk3/launchpad-mini-mk3-0), [X reference](https://downloads.novationmusic.com/novation/launchpad-mk3/launchpad-x), and [Pro MK3 reference](https://fael-downloads-prod.focusrite.com/customer/prod/s3fs-public/downloads/LPP3_prog_ref_guide_200415.pdf).

Occupied squares stay lit continuously: **green for white pieces, red for black pieces**. Empty squares are off. The selected piece and active physical step are amber; empty legal destinations use dim green and capture targets amber. After a completed move the occupancy lights update immediately, and the worker refreshes them periodically while connected, including when paused.

While a physical move is pending, its entire route stays dim amber, with the next pad to press bright amber. Sliding moves include the intervening squares; knights show their endpoints. Capture and castling steps are included. The route remains visible through pickup/place steps and pauses, then returns to the piece colors once the full move is confirmed. Intermediate route pads are guidance; only the instructed step confirms movement.

For your move, press its source and destination. For a persona move, follow the highlighted steps, move the pieces yourself and press each indicated pad. Captures, en passant, castling, promotion and physical takebacks have explicit extra steps. When promotion is needed, select the new piece on screen. Source/destination presses already received are retained; replace the pawn with the chosen piece and press its destination pad once more to confirm the replacement.

Disconnects and restart recovery pause the game. Restore the displayed uncommitted position before reconciling. **Continue on screen** explicitly disables physical play and completes an announced pending move digitally. No physical move is silently accepted on reconnect.

A rejected or unconfirmed chess/MCP operation keeps MIDI connected and preserves the lights. While an operation is unconfirmed, pad presses are discarded until Refresh resolves the server receipt; press the instructed pad again afterward. Actual MIDI read/write failures disconnect the device and attempt to pause the game. If the server is unreachable, Refresh is required to resolve the outstanding operation before continuing.

## Integration and recovery

The MCP tools are `chess_get_state`, `chess_game_control`, `chess_prepare_turn`, `chess_get_candidates`, `chess_choose_move`, `chess_finalize_move` and `chess_get_operation`.

The server uses loopback-only authenticated JSON Streamable HTTP, bounded requests, fixed schemas, revision checks, persisted operation receipts, atomic game saves and an exclusive storage lock. Browser-origin requests are rejected. A chosen persona move remains pending until its announcement has been handed to NC or explicitly skipped, then waits for hardware confirmation if enabled. Claimable chess draws are treated as ended games.

The addon journals operations before sending them. If completion is uncertain, Refresh/Pause checks the receipt and current server state without blindly replaying the move. Engine work, model calls, network requests, storage and MIDI polling run outside the Qt UI thread. Only the selected server/tool is offered to the persona for its move. Closing the addon cancels its own work and speech ownership.

Most code lives here. Small host hooks in `ui/qml_bridge/chess_persona_service.py`, `native_host_services.py`, `application_bridge.py`, `core/runtime/addons.py` and `ui/qml/workspaces/AddonsWorkspace.qml` expose the native page and existing persona pipeline. Chat MCP Tools gains optional offer scoping. Playback, speech routes, facade and addon speech owner gain an opt-in idle-only admission path so chess announcements do not replace existing audio. Default callers retain their existing behavior.

## Bundled Spiral Chess assets

Spiral Chess Set by **BigBadBison**, Thingiverse thing470700, supplied by the user.
The archive identifies the license as **Creative Commons Attribution - Non-Commercial**.
Original credit/license text and conversion metadata are preserved in `assets/spiral`.
The non-commercial restriction applies to these bundled assets.

The six STL files were converted offline through OBJ to Qt Quick3D `.mesh` using
the installed PySide6 Balsam, with smooth normals and generated levels of detail.
Meshes use a uniform1.55 scale, their bases centered at Y0 and Z-up rotated to Y-up.
Board3D retains its existing placement, opposing-side rotation, square picking,
materials and lighting controls. Reduced detail loads only the procedural fallback.

## Bundled Launchpad board

The additional **Scene → Board model → Launchpad Pro** choice uses the supplied `23-launchpad-.rar` Blender model:
black casing, perimeter controls, detail geometry and a shared beveled pad mesh.
Its 8×8 pad centers are aligned to the existing a1–h8 coordinates (100 units apart),
with pad tops at Y19 so the spiral pieces rest on them. Selection, legal-target
and last-move colors remain active. Perimeter controls are decorative. The 2D
board and camera/lighting controls retain their behavior. No asset import UI or
runtime Blender/OBJ conversion is provided. Source and conversion notes are in
`assets/launchpad/models.json`; the supplied archive included no author/license text.

The board model is independent of the hardware model and piece style. **Style
default** remains the default, preserving the wooden, stone and earth boards.
Choosing Launchpad never changes the connected MIDI device profile.

## Online play — Python 3.11 Chess MCP

The **Local / Online** switch separates the existing local persona game from
online human opponents. Local remains the default and works without the relay.
Online requires the existing NC Relay desktop login/connection in **Main Chat
Remote → Internet**. No phone or MIDI device is required. Existing refresh
credentials stay exclusively in the managed relay worker; chess never copies
tokens or creates a competing refresh session.

- **Find players:** explicitly enable Looking to play to list your NC username
  and preferred side. Browse/search without listing yourself; results are paged.
  Availability is refreshed every 20 seconds and expires after 75 seconds if the
  client disconnects. It can remain enabled while playing locally.
- **Challenges:** send, accept, decline or cancel. Pending challenges expire after
  60 seconds. Starting/joining requires confirmation to save/pause the local game.
  Receiving a challenge does not interrupt it or take ownership of MIDI hardware.
- **Private invite:** share the generated ten-character code. Invitations expire
  after ten minutes. Either side gives the creator White by default.
- **My match:** mouse-select a piece/destination on either board, choose promotion,
  offer/accept/decline draws or resign. Matches are initially untimed. Disconnect
  does not forfeit; Refresh / synchronize restores the authoritative position.
- **Commentator:** your selected local persona reacts only to confirmed moves.
  Text/voice are optional and asynchronous, without engine suggestions or MCP
  write tools. Commentary and persona settings are not shared with the opponent.
- **Optional Launchpad:** activate/connect explicitly in My match. Match physical
  pieces to the display and confirm Physical board matches after each online
  move. Disconnect the online Launchpad before returning its ownership to Local.
  The online hardware driver is separate; mouse play never requires activation.

Online MCP logic is in `multiplayer/store.py` and `multiplayer/transport.py`, a
separate transactional authority with lobby/challenge tools and `chess_online_*`
match tools. The authenticated relay route `/v1/chess/mcp` forwards only chess
JSON-RPC to the private Python 3.11 container. It derives identities from the
account login and current desktop registration. Phone signaling keeps its
same-account restrictions. No local MCP port is exposed to opponents.

`online_controller.py` owns a separate worker, commentary queue, and per-account
operation journal under `online/<account-hash>.json`. Uncertain operations retry
their original ID, and changing accounts cannot replay the previous user's
intent. The original local `game-v1.json`, local MCP tools and engine path remain
independent. Returning Local leaves the online match active; explicitly resume
the saved local game when ready.

Deployment sources and rollback notes are in `multiplayer/deploy/README.md`.
The online authority uses its own persistent SQLite volume; no chats, memories,
presets, API keys or persona records are uploaded to it.

## Launchpad device profiles

On Launchpad boards the bundled spiral pieces use clear resin: dielectric
transmission, a slightly frosted surface, soft clearcoat and a subtle cool/warm tint
to distinguish the two sides. Occupied pads glow cyan/amber and update with
piece positions; selection, legal targets and last-move colours retain priority.
Four shadow-free upward lights approximate the pad array's illumination and
are scoped to the pieces. This is a real-time approximation, not ray-traced
caustics or a change to physical MIDI colours. Reduced detail keeps its simple
piece geometry and resin material but omits the four extra lights. Styled
wood/stone/earth boards keep their existing opaque piece materials.

### 3D atmosphere

Scene → Atmosphere offers **Drifting dust motes**, **Ambient occlusion**,
**Soft LED glow**, and **Screen-space reflections**. These use the existing
per-style lighting preferences and settings queue. Existing lighting values
remain intact; missing atmosphere preferences use dust/AO/glow on and reflections
off. Effects are visual only and do not change physical Launchpad colours.

Launchpad resin uses a small bundled studio reflection texture, softened surface
highlights, thickness absorption and restrained ACES/glow. Dust uses at most 72
native 3D sprite particles with slow drift and fades. Animation stops when the
board or its window is hidden/minimized, and reduced detail disables dust, AO,
glow and screen-space reflections. The existing 2D board is unchanged.

Screen-space reflections require Qt 6.11+ and are guarded on older Qt versions;
Qt 6.12 also allows bounded reflection steps and thickness. They are optional,
off by default, and **not hardware ray tracing**: off-camera objects cannot be
reflected, and thin geometry/transmission may show screen-space artifacts. AO
is also an approximation and cannot promise physically accurate shadowing
through frosted resin. No new dependencies or renderer replacement are required.

### Antialiasing, depth of field and movement

Scene → Rendering & movement provides off/2x/4x/8x MSAA and 1.5x supersampling.
The default remains 4x MSAA. Supersampling costs more GPU time and memory;
actual MSAA sample support depends on the graphics device. Optional depth of
field is off by default, with background blur strength 0..6 and automatic focus
at the board centre as the camera zooms. Reduced detail disables AA and DOF.
For graphics compatibility, screen-space reflections pause while depth of field
is enabled. Both saved choices are retained; turning depth of field off restores
reflections automatically if they were enabled. This avoids a reproduced native
Qt 6.12/D3D11 crash when the two effects are active together.

Animate piece moves is on by default, with adjustable 100..800 ms duration
(default 280 ms). Stable visual slots retain stationary meshes and animate only
a confirmed single forward move in the same game, validated against complete
move history and the resulting board. Captures/en passant remove the captured
piece immediately, castling moves both king and rook, and promotions switch the
moving pawn to the authoritative promoted geometry. Loading/resetting, undo,
missing move metadata and multi-move catch-up snapshots snap directly to the
confirmed position. Hidden/minimized windows, reduced detail and disabling
animation stop active movement at its authoritative destination. Rendering
never advances or delays the game, and geometric picking keeps using the
authoritative destination square. Local, online and fullscreen use the same
renderer; the 2D board remains unchanged.

### Batched board pads

The 64 3D pads are rendered in up to seven material batches, using native Qt
InstanceList tables. Each square appears once, with the original transform,
texture, roughness, metalness and emissive colour. Grouping retains selected >
pending highlight > legal target > occupied/checker priority. Identical groups
skip table uploads and entries are reused on updates. Empty groups do not draw.

Picking maps each batch's instance index back to its current square list;
piece picking retains its existing square names. No game, hardware or setting
contracts change. A same-scene D3D11 fixture reduced Launchpad draw calls from
252 to 81 and styled-board calls from 198 to 80; this is rendering overhead
reduction, not a guaranteed frame-rate increase. Pixel comparisons retained the
appearance, and GPU click tests covered every square on the original Pro,
Pro MK3 and styled board, plus existing piece clicks.

Seven additional original lightweight visual models are available: Launchpad S,
MK2, Mini MK1/MK2/MK3, X and Pro MK3. Their portable GLB files, baked Qt meshes,
provenance and offline reproduction instructions are in `assets/boards/README.md`.
These simplified visualizations add board choices only, preserving the existing
two MIDI profiles below. Every model keeps the same selectable chess-square grid.

Hardware setup now offers **Launchpad S** (existing default) and **Launchpad Pro
(original)**. These are distinct, extensible profiles in `midi_profiles.py`; other
models, including Pro MK3, are not silently treated as either device. Old saved
settings retain Launchpad S and the original styled board. The selected hardware
model and board model are persisted independently. Disconnect before changing the
hardware model. No MIDI library is imported or port opened until explicit activation.

Launchpad S keeps its original 16-stride address mapping, red/green colour bytes
and disconnect reset. Original Pro uses the Standalone USB port pair (second
input/output pair), explicitly selected by the user; Live and DIN ports are not
automatically chosen. On connect, the driver selects standalone mode and Programmer
layout with the original Pro `00 20 29 02 10` SysEx header. Grid addresses are11–18
for rank1 through81–88 for rank8; black orientation rotates the grid. Perimeter
CCs, aftertouch and releases do not trigger chess moves.

Pro chess colours are translated to6-bit RGB (white pieces green, black red,
guidance amber). Changed pads are batched into one RGB SysEx message; disconnect
clears the64 owned grid LEDs. `Hardware.set_rgb_leds` also accepts explicit0–63
RGB triples, including blue. Flash/pulse controls and RGB colour editing UI are
not added by this change. No physical Pro is available: protocol and fake-port
tests pass, but real device/firmware/USB-port testing remains pending.

Protocol source: Novation original Launchpad Pro Programmer's Reference, document
FFFA001331-01, pages4–5,17,20–23:
https://fael-downloads-prod.focusrite.com/customer/prod/s3fs-public/novation/downloads/10598/launchpad-pro-programmers-reference-guide_0.pdf
# LED pad surface

Tile sidewalls use separate nondegenerate UV projections so frosted normal-map shading does not produce black speckles. Top geometry, bevels and picking stay unchanged.

Pawn promotion opens a modal picture picker for Queen, Rook, Bishop or Knight in local and online play, including fullscreen. Preview pictures use the existing transparent resin pieces in the promoting side's colour. A Choose promotion button reopens a dismissed picker. Choosing a piece uses the existing game command; rejected commands keep the picker open.

Camera settings include optional Continuous camera movement (off by default): Soft orbit, Side-to-side sway, Figure-eight and Breathing zoom. Motion loops continuously until switched off, including during mouse input and reduced detail. A saved per-style speed slider ranges from 0.25× to 3× (96–8 seconds per cycle; default 24 seconds). Speed changes preserve phase. Offsets remain within five degrees of yaw, two degrees of tilt or 25 scene units of distance and leave manual camera settings intact. Hidden views pause animation; toggle/pattern changes blend smoothly.


Launchpad board models use subtly grained frosted rubber. Board & atmosphere offers LED brightness (0–100%, default 55%) and Low/Soft/Full presets. This changes pad emission and upward spill onto pieces independently of the spotlight. It is saved per piece style using the existing lighting preferences; the colour controls below also apply it to physical LEDs. Styled boards retain their existing materials. Batched square picking remains unchanged.

## Mouse, colour and resin controls

In the 3D board, left-click your piece and then a legal destination. Right-drag orbits and tilts; wheel changes distance; Ctrl+wheel changes field of view (30–70 degrees). Camera sliders remain synchronized, including fullscreen and online black-side views. Reset restores orbit 0, tilt 53, distance 1350 and FOV 48. Camera drags never submit a chess move.

Board colours & move path stores semantic colours separately for Classic, Modern and Fantasy. A native chooser edits square, occupancy, selected, legal destination, pending-step and path colours. Reset affects only the current setup. These colours and LED brightness now also drive connected hardware: original Pro receives 6-bit RGB; S uses its nearest available 2-bit red/green combination, keeping nonzero unsupported colours visible. Other visual board models do not imply additional MIDI protocol support.

Slow flowing move path is off by default. When enabled, a three-second travelling pulse follows the pending/latest move; knight paths use endpoints. Selection, legal destinations and current physical instructions override it. Physical castling/capture instructions remain available when flow is off. Screen flow pauses while hidden or reduced detail; hardware uses bounded delta updates on its existing worker, and can pause briefly during a blocking chess/network operation. Local and online sessions retain separate hardware ownership. One additional instanced material group handles the route; no individual pad models were added.

Resin refraction exposes the existing Qt transmission/IOR pipeline: toggle, light transmission and refraction index. Defaults remain transmission .8 and IOR 1.49 with the frosted surface; reduced detail disables transmission. This is rasterized scene refraction, not hardware ray tracing. Opaque styled pieces and the existing DOF/SSR compatibility guard are preserved.

References: [Qt material optics](https://doc.qt.io/qt-6.12/qml-qtquick3d-principledmaterial.html), [Novation Launchpad S protocol](https://fael-downloads-prod.focusrite.com/customer/dev/s3fs-public/novation/downloads/10753/launchpad-s-prm.pdf).



### Physical captures and move commentary
For a normal AI move or capture, press the source pad, move the piece (removing a captured piece if present), then press the destination pad once. Capture removal and placement on that same square are confirmed atomically. En passant still needs its separate captured-pawn square, castling needs the rook steps, and promotion needs replacement confirmation. Existing pending/undo records remain compatible.

The Game controls include **Comment on my moves** (off by default). The companion reacts to the user's last confirmed move as part of its existing move-choice commentary and announcement, with the existing persona voice setting. It adds no second model request or overlapping speech stream. There is no turn response after a game-ending human move, so this setting does not add separate post-game narration.
