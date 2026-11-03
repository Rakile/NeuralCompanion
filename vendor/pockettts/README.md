# Bundled PocketTTS

NC ships this MIT-licensed PocketTTS 3.3.0 wheel as a deliberate, fixed source
snapshot. Installation uses the local file; there is no moving-branch download
or network fallback for PocketTTS itself. Python dependencies and model/voice
assets remain external, with their original requirements and terms.

- Upstream: https://github.com/kyutai-labs/pocket-tts
- Commit: `b94db177bc0f77517d9b124843e25605d6f9aed8`
- Wheel: `pocket_tts-3.3.0-py3-none-any.whl`
- License: original MIT terms in `LICENSE` and inside the wheel.
- Exact byte lengths and SHA256 values: `manifest.json`.

The original cached source ZIP matches the archive SHA256 recorded by the
working runtime's pip installation. Its Git archive comment identifies the
commit above. All 53 installed package files and the package metadata, entry
point, wheel tags and license were compared byte-for-byte with this wheel.
There are no NC modifications inside the package. NC's integration remains in
`pocket_tts_worker.py` outside this bundle.

## Intentional updates

Choose and review an immutable upstream revision, then build its wheel in a
temporary build environment. Do not copy a user's virtual environment or model
cache. For this snapshot the upstream backend was `hatchling==1.32.4`; the build
used `SOURCE_DATE_EPOCH=315532800` (the ZIP epoch, 1980-01-01) for stable timestamps.
The wheel was built with pip wheel, no runtime dependencies, and an isolated
build constraint fixing that backend version.

Before replacing this bundle, compare package resources, dependency declarations,
Python bounds, worker API signatures and both English/multilingual configs;
preserve the license and record the new source/artifact hashes. Run installer,
bundle integrity, worker and release-preflight regressions. A new version needs
explicit runtime acceptance; a matching version label alone proves no equivalence.

`py3-none-any` makes this PocketTTS wheel platform-independent. The bundled
snapshot requires Python 3.10 through 3.14; dependencies such as PyTorch still
need platform-compatible installations. Model loading/access remains unchanged.
