"""Process environment configuration for the native QML launcher."""

from __future__ import annotations

import os
import warnings
from pathlib import Path


_NAHIMIC_OSD_DLL_NAMES = (
    "NahimicOSD.dll",
    "Nahimic2OSD.dll",
    "NahimicMSIOSD.dll",
)


def _nahimic_osd_present(program_data: str | os.PathLike[str] | None = None) -> bool:
    """Return whether an A-Volute/Nahimic graphics overlay is installed."""

    if os.name != "nt":
        return False
    base_path = Path(
        program_data
        or os.environ.get("PROGRAMDATA")
        or r"C:\ProgramData"
    ) / "A-Volute"
    if not base_path.is_dir():
        return False
    for dll_name in _NAHIMIC_OSD_DLL_NAMES:
        try:
            if next(base_path.rglob(dll_name), None) is not None:
                return True
        except OSError:
            continue
    return False


def _configure_qt_quick_compatibility() -> None:
    """Avoid Nahimic's crash-prone multi-threaded Qt Quick injection path."""

    if "QSG_RENDER_LOOP" in os.environ or not _nahimic_osd_present():
        return
    os.environ["QSG_RENDER_LOOP"] = "basic"
    print(
        "[Qt Quick] Nahimic audio overlay detected; using the basic GPU "
        "render loop for stability."
    )


def configure_runtime_environment() -> None:
    """Apply process-wide warning and progress settings before runtime imports."""

    _configure_qt_quick_compatibility()
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    warnings.filterwarnings(
        "ignore",
        message=r".*LoRACompatibleLinear.*deprecated.*",
        category=FutureWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*Reference mel length is not equal to 2 \* reference token length\..*",
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*pkg_resources is deprecated as an API.*",
        category=UserWarning,
    )


__all__ = ["configure_runtime_environment"]
