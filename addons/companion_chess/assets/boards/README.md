# Authored Launchpad visualization models

Seven original procedural models: Launchpad S, MK2, Mini MK1, Mini MK2,
Mini MK3, X and Pro MK3. These are additional Scene → Board model choices.
The previous styled boards and user-supplied original Pro remain available.

These are simplified visualizations, not exact CAD, printable replacement cases,
or a claim of additional MIDI hardware support. The grid uses the same 100-unit
chess spacing on every model. Mini devices therefore fill the same board area;
their case proportions, thickness, round/rectangular controls and lower-case
colour distinguish them. Mini MK1/MK2 share their basic outer layout.

All new geometry and text were authored for NeuralCompanion with DeepSeek design
and review assistance; no downloaded mesh, logo, texture or image is embedded.
New generated geometry is CC0-1.0. This does not change the separate licensing
of the existing user-supplied Pro model or Spiral chess pieces. Launchpad names
identify the represented products; no endorsement is implied.

Reference layouts:
- https://support.novationmusic.com/hc/en-gb/articles/360000777685-Launchpad-Comparison
- https://userguides.novationmusic.com/hc/en-gb/articles/25494505681042-Launchpad-Pro-MK3-hardware-overview
- https://us.novationmusic.com/products/launchpad-x
- https://novationmusic.com/products/launchpad-mini

Each directory contains five Qt meshes, a complete portable GLB and model.json
(provenance, counts and coordinate contract). The runtime loads only Qt meshes.
One pad mesh is reused for all 64 selectable squares. The Pro MK3 has 42
decorative surrounding controls; the other authored devices have 16.
Materials, square highlights, camera and lighting remain controlled by Board3D.

## Offline reproduction

Use the existing Blender 5 installation and NC Python/PySide6. These tools are
never run by the addon and require no new runtime dependency:



Blender uses Z-up; the OBJ writer maps world vertices once to `(x,z,-y)` for Qt.
The standard glTF exporter performs the equivalent Y-up conversion for GLB.
Pad tops are Y19 to match existing pieces. The slightly offset non-Pro housing
allows extra space for top/right controls while keeping the game grid centred.

Validation from the project root:
```powershell
& .venv/Scripts/python.exe -B -m addons.companion_chess.tests.check_board_picking
```
The D3D11 picking fixture checks every square on all nine choices, both camera
orientations and reduced detail. It does not activate NC, a model server or MIDI.
