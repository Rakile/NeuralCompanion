# Official iCUE SDK files

This addon bundles the Windows x64 redistributable and reference manual from
Corsair's official **iCUE SDK v4.0.84** release:

https://github.com/CorsairOfficial/cue-sdk/releases/tag/v4.0.84

- DLL: `iCUESDK.x64_2019.dll`
- Reference: `iCUE SDK - Overview and Reference.pdf`
- Authenticode signer: `Corsair Memory, Inc.`
- SHA-256: `D72FD819B91FD1D3B0C3DB2EA17A47DCFE3B38E26269AA967ECFEE10D2E93884`

The bundled DLL is auto-detected. A different official x64 DLL can be selected
from the addon's settings tab when an explicit path override is needed.

Keep iCUE running and enable its SDK/game integrations. This addon uses shared
lighting control at priority 180 and never requests exclusive keyboard or
key-event access.
