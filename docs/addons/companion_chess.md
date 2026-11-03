# Companion Chess

Companion Chess supplies local games against a saved NC persona, online games
against another NC player, 2D/3D boards and optional Launchpad hardware. Desktop
play does not require MIDI hardware. The addon owns a local chess MCP server;
online matches use a separate authenticated NC Relay service.

This guide covers the **in-app Companion Chess addon**, rather than an older
standalone chess proof of concept. Its local tools and setup are different.

## Set up a local persona game

1. Enable **Companion Chess** and **Chat MCP Tools** if needed, and restart NC
   when requested. MCP Core is required runtime infrastructure; enable **Allow
   MCP access** on its Runtime page rather than looking for a Core load switch.
2. Open **Companion Chess → Setup → Start Companion Chess Server**. The normal
   local endpoint is `http://127.0.0.1:8766/mcp`; use the address shown by your
   setup if you changed it. The server is started by this explicit action.
3. Choose **Show setup credential**. In **Runtime → MCP Core**, save the endpoint
   with bearer authentication, supply that credential and Connect/refresh tools.
4. Return to Chess, refresh, select the connection and **Request access**.
5. In Core, approve **Companion Chess** and grant its seven local chess tools:
   `chess_get_state`, `chess_game_control`, `chess_prepare_turn`,
   `chess_get_candidates`, `chess_choose_move`, `chess_finalize_move`, and
   `chess_get_operation`.
6. Separately grant **Chat MCP Tools** access to `chess_choose_move`, then assign
   that granted tool to the desired saved persona in **Persona → MCP**.
7. Refresh Chess, select the opponent persona and side, then start **New game**.

Core approval alone grants no tools. Chess and the chat bridge are separate
consumers with separate grants. The selected persona's provider, personality
and voice are used without changing the main chat's selected persona. See
[MCP connections and persona tools](mcp.md) for the shared permissions workflow.

The local server uses NC's Python 3.11 interpreter. Its requirements are listed
in `addons/companion_chess/requirements.txt`. It is not a separate Python 3.14
application. An NC-owned server is stopped when the addon shuts down; an
independently running compatible server is not stopped merely because NC closes.
After an NC restart, start/reuse the server and reconnect Core as necessary.

### Optional engine

Stockfish is optional and is not installed by the NC main installer. New setups
use the basic legal-move evaluator. In **Setup → Engine**, choose either:

- **Install Stockfish…** (Windows): select a parent folder. Chess downloads and
  verifies the pinned official Stockfish 19 release for x64 or ARM64 into its
  `Stockfish` subfolder, retains the license and packaged source, and selects
  the installed executable. Internet access is required. Progress and cancellation
  are available; unrelated files are never overwritten. Choose a different parent
  folder if an existing `Stockfish` subfolder contains unrecognized content.
- **Select existing engine…**: browse to a Stockfish executable you already have.
  You can also enter its path directly. Clear the field to use the basic engine.

Opening Chess never starts a download. An intact installation in the selected
folder is reused. Failed or cancelled installations keep your previous engine
selection. If cancellation arrives after installation, the files may remain in
the chosen folder, but the engine selection is kept.

Saved custom paths and legacy **bundled** selections remain supported. A missing
legacy bundle falls back to the basic engine; use the new controls to replace it.
Start a new game after changing the engine. The strength control applies to
Stockfish. See [Installation](../install.md).

## Play and customize the board

Use the **Game**, **Scene**, **Sounds** and **Setup** controls. The board toolbar
switches between 2D, embedded 3D and fullscreen 3D. Scene controls adjust board
and piece appearance, lighting, colours and motion; a visual Launchpad board
model is independent from an actual connected MIDI device.

Mouse-select a piece and destination; use the on-screen promotion choice when
needed. **Resign** awards a win to the opponent. **End game** stops a local
session without awarding a winner, keeps committed moves and cancels unfinished
ones. A finished-game result window can be closed to retain the final board, or
you can explicitly start a new game.

Use the sound preview/import controls before enabling sounds during play. Local
persona announcements use NC's speech path. If another speech owner is active,
resolve that state rather than expecting Chess to replace its audio silently.

## Optional Launchpad

Hardware controls remain dormant until **Connect / Activate hardware** is used.
Select the actual device profile, its input/output ports and board orientation,
then test the corner LEDs. Place the pieces to match the displayed board and
confirm **Physical board matches**.

Supported profiles include MK1/Original (NOVLPD01), S, Mini MK1/MK2, MK2,
original Pro, Mini MK3, X and Pro MK3. **MK1, S and Mini MK1/MK2 have red/green
LED hardware**, so NC approximates scene colours on them. RGB models have a
different protocol; selecting an RGB-looking on-screen board does not change
the physical device's capabilities.

For MK1 on Windows, missing ports can require Novation's USB driver. The optional
`mido` and `python-rtmidi` Python packages do not install an operating-system
driver. Use the appropriate ports for your profile; modern devices can expose
separate DAW and MIDI interfaces. The
[addon README](../../addons/companion_chess/README.md#optional-launchpad-hardware)
has the device-specific port guidance and official programmer-reference links.

The pads do not sense chess pieces. Move the pieces yourself and press the
requested pads. Captures, castling, en passant, promotions and takebacks may
need several physical confirmations. Follow the highlighted step, not just the
final square. A disconnect pauses physical play; restore/reconcile the board
before continuing. **Continue on screen** explicitly resumes digital play
without assuming that unfinished physical movement happened.

## Online play

Choose **Online** separately from the local persona game. It requires the desktop
login/connection in **Main Chat Remote → Internet**; it does not require a phone
or Launchpad. Deployment/service availability must be checked separately from
the presence of the UI.

- **Find players** supports searching and an explicit **Looking to play** listing.
- Challenges can be sent, accepted, declined or cancelled. Joining asks to
  save/pause local play rather than replacing it silently.
- A private invite code lets another player join the intended match.
- **My match** supports legal moves, promotion, draw offers and resignation.
- A disconnect does not itself forfeit. Use **Refresh / synchronize** to recover
  the server's authoritative position.
- Optional local persona commentary reacts to confirmed moves; it does not give
  the commentator online move-write tools or share persona/voice settings with
  the opponent.

Returning to Local does not automatically end the online match. Resolve online
hardware ownership before reconnecting the same device for a local game. See
[secure Internet setup](main_chat_remote_internet_setup.md) for the relay login
and [online deployment notes](../../addons/companion_chess/multiplayer/deploy/README.md)
for operator requirements.

## Recovery and limits

Refresh an uncertain operation before repeating a move. Chess journals operation
IDs and checks receipts so a lost response is not blindly replayed as another
move. A persona saying it moved is not a substitute for a confirmed board update.
Saved game state, selected persona, scene and hardware settings have separate
roles; physical pieces still need reconciliation after a restart.

Desktop/software tests do not establish compatibility with every MIDI device or
an available online deployment. A live check should include one persona game,
speech, a capture/promotion/takeback, the chosen device's LED/confirmation flow
and disconnect recovery. See the
[implementation and validation reference](../../addons/companion_chess/README.md)
for detailed controls, state ownership, supplied asset credits and test commands.
