"""Shared app-local WAV discovery without importing the Qt presentation package."""
from pathlib import Path


def local_voice_reference_files(app_root: Path) -> tuple[Path, ...]:
    return tuple(
        path for path in sorted(
            (Path(app_root).resolve() / 'voices').glob('*.wav'),
            key=lambda item: item.name.lower(),
        ) if path.is_file()
    )
