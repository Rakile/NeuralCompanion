# Neural Face Assets

The male and female PNG files in this folder are topology references for the AI Presence Mode neural face styles. Runtime rendering is done with the existing Qt Quick/QML Canvas overlay, so no separate graphics engine is required.

`female/reference_female_orange_nodes.png` is the current primary template for the Female Neural Face topology. Its orange connector dots and white/light-blue wire paths map to the QML landmark regions for hair, face base, eyes, pupils, brows, nose, mouth, jaw/chin, and neck.

`female/reference_female_avatar_cutout.png` is the transparent runtime cutout made from the orange-node reference. The Female Neural Face preset draws it as the exact blue avatar base, then layers the detected animated topology over it for live glow and voice response.

`female/reference_female_topology.json` is generated from that PNG. It contains normalized connector-node positions and inferred wire edges used directly by the QML renderer for the visible Female Neural Face wireframe.
