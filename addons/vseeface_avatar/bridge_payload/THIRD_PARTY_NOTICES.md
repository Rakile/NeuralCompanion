# VSeeFace bridge dependencies

The original BepInEx 5.4.23.3 Windows x64 loader archive is bundled without modification.
Upstream: https://github.com/BepInEx/BepInEx/releases/tag/v5.4.23.3
SHA256: 41a089e5b1b1f0713b331346baf6677b1184c69eabebf51101097954e854c749

Its bundled components include BepInEx, BepInEx.Harmony/HarmonyXInterop, UnityDoorstop,
Harmony/HarmonyX, Mono.Cecil and MonoMod. Their upstream notices/licenses are retained in
`licenses/`. Dependency references are recorded in BepInEx's tagged README and project files:
https://github.com/BepInEx/BepInEx/tree/v5.4.23.3

VSeeFace itself is not included. Users obtain it from https://www.vseeface.icu/ and grant NC
permission to add this bridge/loader. The original EXE/managed assemblies are not modified.
VSeeFace's extension policy requests that mods remain freely available:
https://www.vseeface.icu/#extending-functionality

UnityDoorstop's LGPL-2.1 corresponding source is included as
`third_party_source/UnityDoorstop-851712b.zip`, from commit
851712bfef21c90e01c951e024609e76716d55f9 (the commit named by BepInEx 5.4.23.3).
Upstream source: https://github.com/NeighTools/UnityDoorstop/tree/851712bfef21c90e01c951e024609e76716d55f9
Its upstream README/build files are inside that archive. The installed native loader remains
replaceable independently. BepInEx is MIT; the loader archive contains dependencies with their
own licenses, including UnityDoorstop's LGPL-2.1. These notices apply in addition to NC's license.
