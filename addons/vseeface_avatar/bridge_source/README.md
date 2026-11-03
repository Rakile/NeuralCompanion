# NC VSeeFace Bridge source and self-build

This is the complete NC bridge source, shipped alongside the prebuilt DLL in Neural Companion.
NC's repository license applies to NC's source; third-party notices are in `../bridge_payload/`.

You need Windows x64, your own extracted VSeeFace 1.13.38c4/c5 and the Windows .NET Framework
4.x C# compiler. The script uses the pinned BepInEx loader already included in the NC package.
It does not download/install an SDK, VSeeFace or other packages, and does not install the bridge.
No VSeeFace assemblies are included or copied into the resulting package.

From the NC folder, run:

```powershell
.\addons\vseeface_avatar\bridge_source\Build-Bridge.ps1 -VSeeFacePath 'C:\Tools\VSeeFace'
```

The folder must contain `VSeeFace.exe` and `VSeeFace_Data`. The script verifies the inspected
application and loader hashes and builds the production DLL,
and updates `../bridge_payload/NCVSeeFaceBridge.dll` and `manifest.json` with your rebuilt DLL
and the source checksums. Intermediate files stay in the ignored `build/` folder; an optional
`-OutputDirectory` selects another output folder. Preserve the entire source and payload folders
when copying a package. Deliberate source edits require rebuilding/updating the manifest before use.

Use the VSeeFace addon's setup/repair action to review and approve installation of your build.
Close VSeeFace first. A self-build changes the binary hash, so a previously installed build is
updated only with your consent. Do not copy game assemblies or the intermediate build directory
into distributed NC packages. Unsupported VSeeFace releases require inspection before support
is added; changing a hash without inspection is not a compatibility check.

The plugin ID retains its earlier `prototype` suffix only to preserve existing BepInEx settings.
NC remains the audible player. The persistent mute filter, clock watchdog, interruption handling
and selective incoming VMC emotions are the same mechanisms tested with the original bridge.

Automated bridge build tests are maintained in the development repository.
