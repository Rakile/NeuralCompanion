#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent
COMPANION_VENV = REPO_ROOT / ".venv"
POCKETTTS_VENV = REPO_ROOT / ".venvs" / "pockettts"
MUSETALK_VENV = REPO_ROOT / "MuseTalk" / ".venv"
MUSETALK_ROOT = REPO_ROOT / "MuseTalk"
MUSETALK_MODELS = MUSETALK_ROOT / "models"
AVATAR_PACKS_ROOT = REPO_ROOT / "avatar_packs"
AVATAR_PACK_RELEASE_TAG = "v0.1.0"
AVATAR_PACK_BASE_URL = (
    "https://github.com/Rakile/NeuralCompanion-AvatarPacks/releases/download/"
    f"{AVATAR_PACK_RELEASE_TAG}"
)
AVATAR_PACK_REPO = "Rakile/NeuralCompanion-AvatarPacks"
AVATAR_PACK_RELEASE_API_URL = f"https://api.github.com/repos/{AVATAR_PACK_REPO}/releases/tags/{AVATAR_PACK_RELEASE_TAG}"
FFMPEG_TOOLS_DIR = REPO_ROOT / "tools" / "ffmpeg"
FFMPEG_BIN_DIR = FFMPEG_TOOLS_DIR / "bin"
FFMPEG_WINDOWS_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
MAIN_TORCH_CU126_PACKAGES = ("torch==2.6.0", "torchaudio==2.6.0", "torchvision==0.21.0")
MAIN_TORCH_CU126_INDEX_URL = "https://download.pytorch.org/whl/cu126"
MAIN_TORCH_CU128_PACKAGES = ("torch", "torchaudio", "torchvision")
MAIN_TORCH_CU128_INDEX_URL = "https://download.pytorch.org/whl/cu128"
MUSETALK_TORCH_CU118_PACKAGES = ("torch==2.0.1+cu118", "torchaudio==2.0.2+cu118", "torchvision==0.15.2+cu118")
MUSETALK_TORCH_CU118_INDEX_URL = "https://download.pytorch.org/whl/cu118"
MUSETALK_TORCH_CU128_PACKAGES = ("torch==2.10.0", "torchaudio==2.10.0", "torchvision==0.25.0")
MUSETALK_TORCH_CU128_INDEX_URL = "https://download.pytorch.org/whl/cu128"
MUSETALK_CU128_SKIP_REQUIREMENT_NAMES = {
    "gast",
    "jax",
    "jaxlib",
    "keras",
    "mmdet",
    "mmengine",
    "mmpose",
    "opendatalab",
    "openxlab",
    "tensorboard",
    "tensorboard-data-server",
    "tensorboard-plugin-wit",
    "tensorflow",
    "tensorflow-estimator",
    "tensorflow-intel",
    "tensorflow-io-gcs-filesystem",
    "xtcocotools",
}
MUSETALK_RUNTIME_COMPAT_PACKAGES = (
    "numpy==1.26.4",
    "opencv-python==4.9.0.80",
    "pillow==11.2.1",
)
MAIN_BINARY_COMPAT_PACKAGES = (
    "numpy==1.24.4",
    "pandas==1.5.3",
    "scipy==1.11.4",
    "scikit-learn==1.3.2",
)
MAIN_RUNTIME_PIN_PACKAGES = (
    "pillow==11.2.1",
    "PyAudio==0.2.14",
)


DEFAULT_AVATAR_PACKS = {
    "echo": {
        "id": "Echo",
        "label": "Echo",
        "filename": "neural-companion-avatar-pack-Echo.zip",
    },
    "eon": {
        "id": "Eon",
        "label": "Eon",
        "filename": "neural-companion-avatar-pack-Eon.zip",
    },
}


def style(text: str, color: str) -> str:
    colors = {
        "cyan": "\033[96m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "gray": "\033[90m",
        "reset": "\033[0m",
    }
    if os.name != "nt":
        return f"{colors[color]}{text}{colors['reset']}"
    return f"{colors[color]}{text}{colors['reset']}"


def headline(text: str) -> None:
    print()
    print(style(text, "cyan"))


def note(text: str) -> None:
    print(style(text, "gray"))


def warn(text: str) -> None:
    print(style(text, "yellow"))


def fail(text: str) -> None:
    print(style(text, "red"))


def ok(text: str) -> None:
    print(style(text, "green"))


def run_command(
    cmd: Iterable[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=capture,
        check=check,
        env=env,
    )


def prompt_yes_no(question: str, default: bool) -> bool:
    if not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"{question} {suffix} ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def get_python_minor_version(cmd: list[str]) -> str:
    try:
        result = run_command(
            cmd + ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _add_unique_path(paths: list[str], candidate: str | Path | None) -> None:
    if candidate is None:
        return
    raw = str(candidate or "").strip().strip('"')
    if not raw:
        return
    normalized = str(Path(raw))
    if normalized.lower() not in {item.lower() for item in paths}:
        paths.append(normalized)


def _python_launcher_paths() -> list[str]:
    if not shutil.which("py"):
        return []
    try:
        result = run_command(["py", "-0p"], capture=True, check=False)
    except Exception:
        return []
    paths: list[str] = []
    for line in (result.stdout or "").splitlines():
        match = re.search(r"([A-Za-z]:\\.*?python\.exe)\s*$", line.strip(), re.IGNORECASE)
        if match:
            _add_unique_path(paths, match.group(1))
    return paths


def find_python311_executables() -> list[str]:
    """Return likely Python 3.11 executable paths without requiring user input."""
    candidates: list[str] = []
    for path in _python_launcher_paths():
        if get_python_minor_version([path]) == "3.11":
            _add_unique_path(candidates, path)

    for executable_name in ("python3.11", "python"):
        resolved = shutil.which(executable_name)
        if resolved and get_python_minor_version([resolved]) == "3.11":
            _add_unique_path(candidates, resolved)

    common_roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
        Path(os.environ.get("ProgramFiles", "")) / "Python311",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Python311",
        Path("C:/Python311"),
    ]
    for root in common_roots:
        if not root:
            continue
        for pattern in ("Python311/python.exe", "python.exe"):
            for candidate in root.glob(pattern):
                if candidate.exists() and get_python_minor_version([str(candidate)]) == "3.11":
                    _add_unique_path(candidates, candidate)
    return candidates


def resolve_python_command(python_exe: str) -> list[str]:
    if python_exe:
        cmd = [python_exe]
        version = get_python_minor_version(cmd)
        if version != "3.11":
            raise SystemExit(
                f"The provided --python-exe points to Python {version or 'unknown'}. "
                "Neural Companion currently expects Python 3.11."
            )
        return cmd

    candidates = [[path] for path in find_python311_executables()]
    candidates.extend([
        ["py", "-3.11"],
        ["python3.11"],
        ["python"],
    ])
    for candidate in candidates:
        if shutil.which(candidate[0]) and get_python_minor_version(candidate) == "3.11":
            return candidate

    detected = ""
    if shutil.which("python"):
        detected = get_python_minor_version(["python"])
    extra = f" Detected default python version: {detected}." if detected else ""
    raise SystemExit(
        "Neural Companion installer requires Python 3.11."
        f"{extra} Install Python 3.11 and rerun this script, "
        "or use --python-exe <path-to-python-3.11>."
    )


@dataclass
class DoctorFinding:
    name: str
    status: str
    detail: str


class Installer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.python_cmd = resolve_python_command(args.python_exe)
        self.findings: list[DoctorFinding] = []
        self.pockettts_auth_status = "not_checked"
        self.pockettts_auth_detail = "PocketTTS cloning access was not checked."

    def selected_python_label(self) -> str:
        if len(self.python_cmd) == 1:
            return self.python_cmd[0]
        return " ".join(self.python_cmd)

    def invoke_selected_python(self, *args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
        return run_command(self.python_cmd + list(args), cwd=REPO_ROOT, capture=capture)

    def preflight(self) -> None:
        headline("Preflight Checks")
        version = get_python_minor_version(self.python_cmd)
        self.findings.append(
            DoctorFinding("Python 3.11", "OK", f"Using {self.selected_python_label()} ({version})")
        )

        ffmpeg_path = self.resolve_ffmpeg_binary("ffmpeg")
        ffprobe_path = self.resolve_ffmpeg_binary("ffprobe")
        ffmpeg_ok = ffmpeg_path is not None and ffprobe_path is not None
        self.findings.append(
            DoctorFinding(
                "FFmpeg",
                "OK" if ffmpeg_ok else "WARN",
                f"Found ffmpeg={ffmpeg_path}, ffprobe={ffprobe_path}" if ffmpeg_ok else "Missing ffmpeg or ffprobe",
            )
        )

        nvidia_summary = self.detect_nvidia()
        self.findings.append(nvidia_summary)

        lm_studio_summary = self.detect_lm_studio()
        self.findings.append(lm_studio_summary)

        vseeface_dir = REPO_ROOT / "VSeeFace-v1.13.38c4"
        self.findings.append(
            DoctorFinding(
                "VSeeFace bundle",
                "OK" if vseeface_dir.exists() else "WARN",
                str(vseeface_dir)
                if vseeface_dir.exists()
                else "Bundled VSeeFace folder missing (optional if you use an external install)",
            )
        )

        for finding in self.findings:
            printer = ok if finding.status == "OK" else warn
            printer(f"[{finding.name}] {finding.detail}")

    def detect_nvidia(self) -> DoctorFinding:
        if not shutil.which("nvidia-smi"):
            return DoctorFinding(
                "NVIDIA / CUDA",
                "WARN",
                "nvidia-smi not found. GPU acceleration may be unavailable.",
            )
        try:
            result = run_command(["nvidia-smi"], capture=True)
            first_lines = [line.strip() for line in result.stdout.splitlines() if "CUDA Version" in line]
            if first_lines:
                return DoctorFinding("NVIDIA / CUDA", "OK", first_lines[0])
            return DoctorFinding("NVIDIA / CUDA", "OK", "nvidia-smi responded successfully")
        except Exception as exc:
            return DoctorFinding("NVIDIA / CUDA", "WARN", f"nvidia-smi failed: {exc}")

    def detect_blackwell_gpu(self) -> tuple[bool, str]:
        if not shutil.which("nvidia-smi"):
            return False, "nvidia-smi not found"
        try:
            result = run_command(
                [
                    "nvidia-smi",
                    "--query-gpu=name,compute_cap",
                    "--format=csv,noheader",
                ],
                capture=True,
                check=False,
            )
        except Exception as exc:
            return False, f"nvidia-smi query failed: {exc}"

        details: list[str] = []
        for line in result.stdout.splitlines():
            raw = line.strip()
            if not raw:
                continue
            parts = [part.strip() for part in raw.split(",")]
            name = parts[0] if parts else raw
            capability_text = parts[1] if len(parts) > 1 else ""
            details.append(raw)
            try:
                capability = float(capability_text)
            except Exception:
                capability = 0.0
            normalized_name = name.lower()
            if capability >= 12.0 or "rtx 50" in normalized_name or "blackwell" in normalized_name:
                return True, raw

        if details:
            return False, "; ".join(details)

        try:
            fallback = run_command(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture=True,
                check=False,
            )
        except Exception as exc:
            return False, f"nvidia-smi name query failed: {exc}"
        names = [line.strip() for line in fallback.stdout.splitlines() if line.strip()]
        for name in names:
            normalized_name = name.lower()
            if "rtx 50" in normalized_name or "blackwell" in normalized_name:
                return True, name
        return False, "; ".join(names) if names else "no NVIDIA GPU details returned"

    def main_torch_install_plan(self) -> tuple[tuple[str, ...], str, str]:
        is_blackwell, detail = self.detect_blackwell_gpu()
        if is_blackwell:
            return (
                MAIN_TORCH_CU128_PACKAGES,
                MAIN_TORCH_CU128_INDEX_URL,
                f"RTX 50 / Blackwell-class GPU detected ({detail}); using PyTorch cu128 wheels.",
            )
        return (
            MAIN_TORCH_CU126_PACKAGES,
            MAIN_TORCH_CU126_INDEX_URL,
            f"Using Neural Companion default PyTorch cu126 stack ({detail}).",
        )

    def musetalk_torch_install_plan(self) -> tuple[tuple[str, ...], str, str]:
        is_blackwell, detail = self.detect_blackwell_gpu()
        if is_blackwell:
            return (
                MUSETALK_TORCH_CU128_PACKAGES,
                MUSETALK_TORCH_CU128_INDEX_URL,
                f"RTX 50 / Blackwell-class GPU detected ({detail}); using MuseTalk PyTorch cu128 wheels.",
            )
        return (
            MUSETALK_TORCH_CU118_PACKAGES,
            MUSETALK_TORCH_CU118_INDEX_URL,
            f"Using MuseTalk default PyTorch cu118 stack ({detail}).",
        )

    def detect_lm_studio(self) -> DoctorFinding:
        common_paths = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "LM Studio" / "LM Studio.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "LM-Studio" / "LM Studio.exe",
            Path("C:/Program Files/LM Studio/LM Studio.exe"),
        ]
        for candidate in common_paths:
            if candidate.exists():
                return DoctorFinding("LM Studio", "OK", f"Found at {candidate}")
        return DoctorFinding(
            "LM Studio",
            "WARN",
            "Not found in common install locations. Neural Companion can still install, but local chat provider setup will need attention.",
        )

    def ensure_venv(self, venv_path: Path, label: str) -> Path:
        venv_python = venv_path / "Scripts" / "python.exe"
        if venv_python.exists():
            version = get_python_minor_version([str(venv_python)])
            if version != "3.11":
                warn(f"Existing {label} venv uses Python {version}. Rebuilding it with Python 3.11...")
                shutil.rmtree(venv_path, ignore_errors=True)

        if not venv_path.exists():
            note(f"Creating {label} virtual environment at {venv_path}")
            venv_path.parent.mkdir(parents=True, exist_ok=True)
            self.invoke_selected_python("-m", "venv", str(venv_path))

        if not venv_python.exists():
            raise SystemExit(f"{label} virtual environment python was not created correctly.")

        return venv_python

    def pip_install(self, python_exe: Path, *args: str) -> None:
        run_command([str(python_exe), "-m", "pip", *args], cwd=REPO_ROOT)

    def pip_uninstall(self, python_exe: Path, packages: Iterable[str]) -> None:
        package_list = sorted(set(packages))
        if package_list:
            run_command([str(python_exe), "-m", "pip", "uninstall", "-y", *package_list], cwd=REPO_ROOT, check=False)

    def resolve_ffmpeg_binary(self, name: str) -> str | None:
        executable = f"{name}.exe" if os.name == "nt" else name
        bundled = FFMPEG_BIN_DIR / executable
        if bundled.exists():
            return str(bundled)
        return shutil.which(name)

    def ensure_ffmpeg(self) -> None:
        ffmpeg_path = self.resolve_ffmpeg_binary("ffmpeg")
        ffprobe_path = self.resolve_ffmpeg_binary("ffprobe")
        if ffmpeg_path and ffprobe_path:
            ok(f"FFmpeg ready: ffmpeg={ffmpeg_path}, ffprobe={ffprobe_path}")
            return
        if os.name != "nt":
            warn("FFmpeg or ffprobe is missing. Install FFmpeg through your system package manager.")
            return

        headline("Installing FFmpeg")
        FFMPEG_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="nc_ffmpeg_") as temp_dir:
            temp_root = Path(temp_dir)
            archive_path = temp_root / "ffmpeg.zip"
            extract_root = temp_root / "extract"
            note("Downloading bundled FFmpeg for Windows...")
            self.download_file(FFMPEG_WINDOWS_URL, archive_path)
            note("Extracting FFmpeg tools...")
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.infolist():
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise SystemExit(f"FFmpeg archive contains an unsafe path: {member.filename}")
                archive.extractall(extract_root)
            bin_candidates = [
                path for path in extract_root.rglob("bin")
                if (path / "ffmpeg.exe").exists() and (path / "ffprobe.exe").exists()
            ]
            if not bin_candidates:
                raise SystemExit("Downloaded FFmpeg archive did not contain ffmpeg.exe and ffprobe.exe.")
            source_bin = bin_candidates[0]
            if FFMPEG_BIN_DIR.exists():
                shutil.rmtree(FFMPEG_BIN_DIR, ignore_errors=True)
            FFMPEG_BIN_DIR.mkdir(parents=True, exist_ok=True)
            for executable in ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe"):
                source = source_bin / executable
                if source.exists():
                    shutil.copy2(source, FFMPEG_BIN_DIR / executable)
        ok(f"Bundled FFmpeg installed at {FFMPEG_BIN_DIR}")

    def filtered_requirements_file(self, source_path: Path, skip_names: set[str], temp_dir: Path) -> Path:
        filtered_path = temp_dir / source_path.name
        filtered_lines = []
        skipped = []
        for line in source_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                filtered_lines.append(line)
                continue
            package_name = re.split(r"\s*(?:==|>=|<=|~=|!=|>|<|\[)", stripped, maxsplit=1)[0].strip().lower()
            if package_name in skip_names:
                skipped.append(stripped)
                continue
            filtered_lines.append(line)
        filtered_path.write_text("\n".join(filtered_lines) + "\n", encoding="utf-8")
        if skipped:
            note(f"Skipping cu128-incompatible MuseTalk requirement(s): {', '.join(skipped)}")
        return filtered_path

    def verify_imports(self, python_exe: Path, imports: list[str], label: str) -> None:
        script = "; ".join(f"import {name}" for name in imports)
        run_command([str(python_exe), "-c", script], cwd=REPO_ROOT)
        ok(f"{label} validation passed: imported {', '.join(imports)}")

    def install_avatar_packs(self, pack_keys: list[str]) -> None:
        if not pack_keys:
            return
        headline("Installing Avatar Packs")
        AVATAR_PACKS_ROOT.mkdir(parents=True, exist_ok=True)
        for pack_key in pack_keys:
            self.install_avatar_pack(pack_key)

    def install_avatar_pack(self, pack_key: str) -> None:
        pack = DEFAULT_AVATAR_PACKS.get(pack_key)
        if not pack:
            warn(f"Unknown avatar pack target: {pack_key}")
            return

        pack_id = str(pack["id"])
        label = str(pack["label"])
        filename = str(pack["filename"])
        destination = AVATAR_PACKS_ROOT / pack_id
        if destination.exists():
            ok(f"{label} avatar pack already installed at {destination}")
            return

        url = f"{AVATAR_PACK_BASE_URL}/{filename}"
        with tempfile.TemporaryDirectory(prefix=f"nc_avatar_pack_{pack_key}_") as temp_dir:
            temp_root = Path(temp_dir)
            archive_path = temp_root / filename
            extract_root = temp_root / "extract"
            note(f"Downloading {label} avatar pack...")
            self.download_avatar_pack_file(filename, url, archive_path)
            note(f"Extracting {label} avatar pack...")
            self.extract_avatar_pack_zip(archive_path, extract_root)

            extracted_pack = extract_root / pack_id
            if not extracted_pack.is_dir():
                raise SystemExit(
                    f"{label} avatar pack archive did not contain the expected top-level folder: {pack_id}"
                )
            shutil.move(str(extracted_pack), str(destination))
            ok(f"{label} avatar pack installed at {destination}")

    def github_token(self) -> str:
        return str(os.environ.get("NC_AVATAR_PACK_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()

    def download_avatar_pack_file(self, filename: str, public_url: str, destination: Path) -> None:
        token = self.github_token()
        if token:
            try:
                self.download_github_release_asset(filename, destination, token)
                return
            except urllib.error.HTTPError as exc:
                raise SystemExit(
                    f"Could not download private avatar pack asset {filename} from {AVATAR_PACK_REPO}: "
                    f"GitHub API returned HTTP {exc.code}. Check that the token has read access to repository contents."
                ) from exc
        self.download_file(public_url, destination)

    def github_headers(self, token: str, *, octet_stream: bool = False) -> dict[str, str]:
        accept = "application/octet-stream" if octet_stream else "application/vnd.github+json"
        return {
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "User-Agent": "NeuralCompanionInstaller",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def download_github_release_asset(self, filename: str, destination: Path, token: str) -> None:
        release_request = urllib.request.Request(AVATAR_PACK_RELEASE_API_URL, headers=self.github_headers(token))
        with urllib.request.urlopen(release_request, timeout=120) as response:
            release = json.loads(response.read().decode("utf-8"))

        assets = release.get("assets") or []
        asset = next((item for item in assets if item.get("name") == filename), None)
        if not asset:
            raise SystemExit(f"Avatar pack release {AVATAR_PACK_RELEASE_TAG} does not contain asset: {filename}")

        asset_url = str(asset.get("url") or "")
        if not asset_url:
            raise SystemExit(f"Avatar pack asset {filename} did not include a GitHub API download URL.")
        note(f"Using authenticated GitHub release asset download for {filename}.")
        self.download_file(asset_url, destination, headers=self.github_headers(token, octet_stream=True))

    def download_file(self, url: str, destination: Path, headers: dict[str, str] | None = None) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        headers = headers or {"User-Agent": "NeuralCompanionInstaller"}
        request = urllib.request.Request(str(url), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                next_report = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if total and downloaded >= next_report:
                        percent = int((downloaded / total) * 100)
                        note(f"  downloaded {percent}%")
                        next_report = downloaded + max(total // 10, 1)
        except Exception as exc:
            raise SystemExit(f"Could not download {url}: {exc}") from exc

    def extract_avatar_pack_zip(self, archive_path: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise SystemExit(f"Avatar pack archive contains an unsafe path: {member.filename}")
            archive.extractall(destination)

    def install_main(self) -> None:
        headline("Installing Neural Companion")
        python_exe = self.ensure_venv(COMPANION_VENV, "main app")
        note("Upgrading pip/setuptools/wheel...")
        self.pip_install(python_exe, "install", "--upgrade", "pip", "setuptools<81", "wheel")

        torch_packages: tuple[str, ...] = ()
        torch_index_url = ""
        if not self.args.skip_main_torch:
            torch_packages, torch_index_url, torch_plan_detail = self.main_torch_install_plan()
            note(torch_plan_detail)
            if torch_index_url == MAIN_TORCH_CU128_INDEX_URL:
                warn(
                    "The cu128 torch stack can print strict Chatterbox dependency warnings; "
                    "NC avoids torchaudio file IO and uses this path for RTX 50-series GPU support."
                )
            note("Installing CUDA-enabled torch for Neural Companion...")
            self.pip_install(
                python_exe,
                "install",
                *torch_packages,
                "--force-reinstall",
                "--index-url",
                torch_index_url,
            )
        else:
            warn("Skipping main torch install because --skip-main-torch was requested.")

        note("Installing Neural Companion requirements...")
        self.pip_install(
            python_exe,
            "install",
            "-r",
            str(REPO_ROOT / "requirements.companion.txt"),
        )

        if torch_index_url == MAIN_TORCH_CU128_INDEX_URL:
            note("Re-applying PyTorch cu128 after requirements so Chatterbox metadata pins do not downgrade RTX 50 support...")
            self.pip_install(
                python_exe,
                "install",
                *torch_packages,
                "--force-reinstall",
                "--index-url",
                torch_index_url,
            )

        note("Repairing compiled scientific package ABI pins...")
        self.pip_install(
            python_exe,
            "install",
            "--force-reinstall",
            "--no-cache-dir",
            *MAIN_BINARY_COMPAT_PACKAGES,
        )

        note("Applying known-good runtime pins...")
        self.pip_install(
            python_exe,
            "install",
            *MAIN_RUNTIME_PIN_PACKAGES,
        )

        self.verify_imports(
            python_exe,
            ["torch", "numpy", "pandas", "sklearn", "PySide6", "flask", "nltk", "openai"],
            "Main app",
        )
        self.verify_torch_cuda(python_exe, "Main app")
        self.ensure_ffmpeg()

    def install_pockettts(self) -> None:
        headline("Installing PocketTTS")
        python_exe = self.ensure_venv(POCKETTTS_VENV, "PocketTTS")
        note("Upgrading PocketTTS bootstrap tools...")
        self.pip_install(python_exe, "install", "--upgrade", "pip", "setuptools<81", "wheel")
        note("Installing pocket-tts into isolated environment...")
        self.pip_install(python_exe, "install", "pocket-tts==1.1.1")
        run_command([str(python_exe), "-m", "pip", "show", "pocket-tts"], cwd=REPO_ROOT)
        ok("PocketTTS validation passed: package is installed in the isolated runtime")
        self.check_pockettts_huggingface_access(python_exe)

    def check_pockettts_huggingface_access(self, python_exe: Path) -> None:
        headline("PocketTTS Hugging Face Check")
        checker = """
import json
from huggingface_hub import HfApi
from huggingface_hub.utils import get_token

token = get_token()
status = {"has_token": bool(token), "whoami_ok": False, "identity": ""}
if token:
    try:
        who = HfApi().whoami(token=token)
        if isinstance(who, dict):
            status["identity"] = who.get("name") or who.get("fullname") or who.get("email") or ""
        else:
            status["identity"] = str(who)
        status["whoami_ok"] = True
    except Exception as exc:
        status["identity"] = f"token present but whoami failed: {exc}"
print(json.dumps(status))
"""
        try:
            result = run_command(
                [str(python_exe), "-c", checker],
                cwd=REPO_ROOT,
                capture=True,
            )
            payload = json.loads(result.stdout.strip())
        except Exception as exc:
            self.pockettts_auth_status = "unknown"
            self.pockettts_auth_detail = f"Could not verify Hugging Face login state: {exc}"
            warn(self.pockettts_auth_detail)
            warn("PocketTTS may still work for built-in voices, but cloning readiness is not verified.")
            return

        if payload.get("whoami_ok"):
            identity = payload.get("identity") or "signed-in user"
            self.pockettts_auth_status = "ready"
            self.pockettts_auth_detail = (
                f"Hugging Face login detected ({identity}). PocketTTS cloning login requirement looks satisfied."
            )
            ok(self.pockettts_auth_detail)
            warn("PocketTTS gated model terms may still need to be accepted separately on Hugging Face.")
            return

        if payload.get("has_token"):
            identity = payload.get("identity") or "token present but account verification failed"
            self.pockettts_auth_status = "partial"
            self.pockettts_auth_detail = (
                f"Hugging Face token detected, but login could not be fully verified ({identity})."
            )
            warn(self.pockettts_auth_detail)
            warn("PocketTTS built-in voices should work, but cloning readiness is uncertain.")
            return

        self.pockettts_auth_status = "missing"
        self.pockettts_auth_detail = (
            "No Hugging Face login detected. PocketTTS is installed, but voice cloning is not ready yet."
        )
        warn(self.pockettts_auth_detail)
        print("To finish PocketTTS cloning setup:")
        print("  1. Accept the terms at https://huggingface.co/kyutai/pocket-tts")
        print("  2. Create a Hugging Face Read token at https://huggingface.co/settings/tokens")
        print("     - Sign in, choose New token, select Read permission, then copy the token")
        print(f"  3. Run: {python_exe.parent / 'hf.exe'} auth login")
        print("  4. Paste the token when the Hugging Face CLI asks for it")

    def install_musetalk(self) -> None:
        headline("Installing MuseTalk")
        if not shutil.which("nvidia-smi"):
            warn("MuseTalk can be installed without nvidia-smi, but GPU-backed performance may not be available.")

        python_exe = self.ensure_venv(MUSETALK_VENV, "MuseTalk")
        note("Upgrading MuseTalk bootstrap tools...")
        self.pip_install(python_exe, "install", "--upgrade", "pip", "setuptools<81", "wheel")

        torch_packages, torch_index_url, torch_plan_detail = self.musetalk_torch_install_plan()
        note(torch_plan_detail)
        note("Installing CUDA-enabled torch for MuseTalk...")
        self.pip_install(
            python_exe,
            "install",
            *torch_packages,
            "--force-reinstall",
            "--index-url",
            torch_index_url,
        )

        use_musetalk_cu128 = torch_index_url == MUSETALK_TORCH_CU128_INDEX_URL
        if use_musetalk_cu128:
            note("Skipping OpenMMLab/mmcv install for MuseTalk cu128; MediaPipe will be used for avatar preprocessing fallback.")
            note("Removing stale OpenMMLab/TensorFlow packages from existing MuseTalk cu128 venvs...")
            self.pip_uninstall(python_exe, MUSETALK_CU128_SKIP_REQUIREMENT_NAMES)
            self.pip_install(python_exe, "install", "mediapipe")
        else:
            note("Installing OpenMMLab bootstrap tools...")
            self.pip_install(python_exe, "install", "openmim==0.3.9")

            note("Installing mmcv through OpenMIM...")
            run_command([str(python_exe), "-m", "mim", "install", "mmcv==2.0.1"], cwd=REPO_ROOT)

        note("Preinstalling chumpy without build isolation...")
        self.pip_install(python_exe, "install", "chumpy==0.70", "--no-build-isolation")

        note("Installing pinned MuseTalk runtime requirements...")
        requirements_path = REPO_ROOT / "requirements.musetalk.txt"
        if use_musetalk_cu128:
            with tempfile.TemporaryDirectory(prefix="nc_musetalk_cu128_requirements_") as temp_dir:
                filtered_requirements = self.filtered_requirements_file(
                    requirements_path,
                    MUSETALK_CU128_SKIP_REQUIREMENT_NAMES,
                    Path(temp_dir),
                )
                self.pip_install(python_exe, "install", "-r", str(filtered_requirements))
        else:
            self.pip_install(python_exe, "install", "-r", str(requirements_path))

        if use_musetalk_cu128:
            note("Re-applying MuseTalk PyTorch cu128 after requirements so runtime dependencies do not downgrade RTX 50 support...")
            self.pip_install(
                python_exe,
                "install",
                *torch_packages,
                "--force-reinstall",
                "--index-url",
                torch_index_url,
            )

        note("Applying known-good MuseTalk compatibility pins...")
        self.pip_install(
            python_exe,
            "install",
            "--force-reinstall",
            "--no-cache-dir",
            *MUSETALK_RUNTIME_COMPAT_PACKAGES,
        )

        self.ensure_musetalk_weights(python_exe)

        musetalk_imports = ["torch", "cv2", "diffusers"]
        musetalk_imports.append("mediapipe" if use_musetalk_cu128 else "mmcv")
        self.verify_imports(python_exe, musetalk_imports, "MuseTalk")
        self.verify_torch_cuda(python_exe, "MuseTalk")

    def ensure_musetalk_weights(self, python_exe: Path) -> None:
        headline("MuseTalk Weights")
        expected_files = [
            MUSETALK_MODELS / "musetalk" / "pytorch_model.bin",
            MUSETALK_MODELS / "musetalkV15" / "unet.pth",
            MUSETALK_MODELS / "syncnet" / "latentsync_syncnet.pt",
            MUSETALK_MODELS / "dwpose" / "dw-ll_ucoco_384.pth",
            MUSETALK_MODELS / "sd-vae" / "diffusion_pytorch_model.bin",
            MUSETALK_MODELS / "whisper" / "pytorch_model.bin",
            MUSETALK_MODELS / "face-parse-bisent" / "79999_iter.pth",
            MUSETALK_MODELS / "face-parse-bisent" / "resnet18-5c106cde.pth",
        ]
        if all(path.exists() for path in expected_files):
            ok("MuseTalk weights already present.")
            return

        note("Downloading MuseTalk weights. This is the largest step and can take a while...")
        for subdir in [
            "musetalk",
            "musetalkV15",
            "syncnet",
            "dwpose",
            "face-parse-bisent",
            "sd-vae",
            "sd-vae-ft-mse",
            "whisper",
        ]:
            (MUSETALK_MODELS / subdir).mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()

        download_jobs = [
            {
                "repo_id": "TMElyralab/MuseTalk",
                "local_dir": str(MUSETALK_MODELS),
                "mode": "snapshot",
            },
            {
                "repo_id": "stabilityai/sd-vae-ft-mse",
                "local_dir": str(MUSETALK_MODELS / "sd-vae"),
                "mode": "files",
                "filenames": ["config.json", "diffusion_pytorch_model.bin"],
            },
            {
                "repo_id": "openai/whisper-tiny",
                "local_dir": str(MUSETALK_MODELS / "whisper"),
                "mode": "files",
                "filenames": ["config.json", "pytorch_model.bin", "preprocessor_config.json"],
            },
            {
                "repo_id": "yzd-v/DWPose",
                "local_dir": str(MUSETALK_MODELS / "dwpose"),
                "mode": "files",
                "filenames": ["dw-ll_ucoco_384.pth"],
            },
            {
                "repo_id": "ByteDance/LatentSync",
                "local_dir": str(MUSETALK_MODELS / "syncnet"),
                "mode": "files",
                "filenames": ["latentsync_syncnet.pt"],
            },
            {
                "repo_id": "ManyOtherFunctions/face-parse-bisent",
                "local_dir": str(MUSETALK_MODELS / "face-parse-bisent"),
                "mode": "files",
                "filenames": ["79999_iter.pth", "resnet18-5c106cde.pth"],
            },
        ]

        downloader = """
import json
import os
import sys
from huggingface_hub import hf_hub_download, snapshot_download

jobs = json.loads(sys.argv[1])
endpoint = os.environ.get("HF_ENDPOINT")
extra_kwargs = {"endpoint": endpoint} if endpoint else {}

for job in jobs:
    local_dir = job["local_dir"]
    os.makedirs(local_dir, exist_ok=True)
    print(f"Downloading {job['repo_id']} -> {local_dir}", flush=True)
    if job["mode"] == "snapshot":
        snapshot_download(repo_id=job["repo_id"], local_dir=local_dir, **extra_kwargs)
    else:
        for filename in job["filenames"]:
            print(f"  {filename}", flush=True)
            hf_hub_download(
                repo_id=job["repo_id"],
                filename=filename,
                local_dir=local_dir,
                **extra_kwargs,
            )
"""
        run_command(
            [str(python_exe), "-c", downloader, json.dumps(download_jobs)],
            cwd=MUSETALK_ROOT,
            check=True,
            env=env,
        )

        missing = [str(path) for path in expected_files if not path.exists()]
        if missing:
            raise SystemExit(
                "MuseTalk weight download completed, but some expected files are still missing:\n"
                + "\n".join(missing)
            )
        ok("MuseTalk weights downloaded successfully.")


    def verify_torch_cuda(self, python_exe: Path, label: str) -> None:
        result = run_command(
            [
                str(python_exe),
                "-c",
                (
                    "import torch; "
                    "print('available=' + str(torch.cuda.is_available())); "
                    "print('cuda=' + str(torch.version.cuda)); "
                    "print('torch=' + str(torch.__version__)); "
                    "print('arch_list=' + ','.join(torch.cuda.get_arch_list()) if torch.cuda.is_available() else 'arch_list='); "
                    "print('device=' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'device='); "
                    "print('capability=' + '.'.join(map(str, torch.cuda.get_device_capability(0))) if torch.cuda.is_available() else 'capability=')"
                ),
            ],
            cwd=REPO_ROOT,
            capture=True,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        detail = ", ".join(lines) if lines else "torch reported no CUDA details"
        if any("available=True" in line for line in lines):
            ok(f"{label} torch CUDA check: {detail}")
        else:
            warn(f"{label} torch CUDA check: {detail}")

    def final_summary(self, install_main: bool, install_musetalk: bool, install_pockettts: bool, avatar_pack_keys: list[str]) -> None:
        headline("Installer Summary")
        ok("Unified installer finished.")
        note(f"Python 3.11 source: {self.selected_python_label()}")

        if install_main:
            ok(f"Main app runtime ready at {COMPANION_VENV}")
        if install_musetalk:
            ok(f"MuseTalk runtime ready at {MUSETALK_VENV}")
        if install_pockettts:
            ok(f"PocketTTS runtime ready at {POCKETTTS_VENV}")
            if self.pockettts_auth_status == "ready":
                ok(f"PocketTTS cloning login check: {self.pockettts_auth_detail}")
            elif self.pockettts_auth_status in {"partial", "missing", "unknown"}:
                warn(f"PocketTTS cloning login check: {self.pockettts_auth_detail}")
        for pack_key in avatar_pack_keys:
            pack = DEFAULT_AVATAR_PACKS.get(pack_key, {})
            pack_id = str(pack.get("id") or pack_key)
            ok(f"Avatar pack ready at {AVATAR_PACKS_ROOT / pack_id}")

        print()
        warn("Still worth checking by hand:")
        print("  - FFmpeg/ffprobe are available on PATH or bundled under tools\\ffmpeg\\bin")
        print("  - LM Studio is installed and has a model loaded if you want local chat")
        print("  - Optional MuseTalk avatar packs live in avatar_packs/<pack_id>")
        print("  - PocketTTS voice cloning still requires Hugging Face terms acceptance on kyutai/pocket-tts")
        print("  - If PocketTTS asks for login, create a Read token at https://huggingface.co/settings/tokens")
        print()
        ok("Launch the app with run_neural_companion.bat")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unified installer for the Neural Companion Git release.",
    )
    parser.add_argument("--python-exe", default="", help="Path to a Python 3.11 interpreter")
    parser.add_argument("--main", action="store_true", help="Install the main Neural Companion runtime")
    parser.add_argument("--musetalk", action="store_true", help="Install the isolated MuseTalk runtime")
    parser.add_argument("--pockettts", action="store_true", help="Install the isolated PocketTTS runtime")
    parser.add_argument("--avatar-pack-echo", action="store_true", help="Download and install the default Echo avatar pack")
    parser.add_argument("--avatar-pack-eon", action="store_true", help="Download and install the default Eon avatar pack")
    parser.add_argument("--avatar-packs", action="store_true", help="Download and install all default avatar packs")
    parser.add_argument("--all", action="store_true", help="Install main app, MuseTalk, and PocketTTS")
    parser.add_argument("--skip-main-torch", action="store_true", help="Skip the main app torch install")
    parser.add_argument("--doctor-only", action="store_true", help="Run preflight checks only")
    parser.add_argument("--non-interactive", action="store_true", help="Do not prompt; use CLI flags/defaults")
    return parser


def resolve_requested_components(args: argparse.Namespace) -> tuple[bool, bool, bool, list[str]]:
    avatar_pack_keys: list[str] = []
    if args.avatar_pack_echo:
        avatar_pack_keys.append("echo")
    if args.avatar_pack_eon:
        avatar_pack_keys.append("eon")
    if args.avatar_packs:
        avatar_pack_keys = list(DEFAULT_AVATAR_PACKS.keys())

    if args.all:
        return True, True, True, avatar_pack_keys

    requested_any = args.main or args.musetalk or args.pockettts or bool(avatar_pack_keys)
    if requested_any:
        return args.main, args.musetalk, args.pockettts, avatar_pack_keys

    if args.doctor_only:
        return False, False, False, []

    if args.non_interactive:
        return True, False, False, []

    headline("Installation Selection")
    install_main = prompt_yes_no("Install the main Neural Companion runtime?", True)
    install_musetalk = prompt_yes_no("Install the isolated MuseTalk runtime too?", True)
    install_pockettts = prompt_yes_no("Install the isolated PocketTTS runtime too?", True)
    install_echo = prompt_yes_no("Download and install the default Echo avatar pack?", False)
    install_eon = prompt_yes_no("Download and install the default Eon avatar pack?", False)
    if install_echo:
        avatar_pack_keys.append("echo")
    if install_eon:
        avatar_pack_keys.append("eon")
    return install_main, install_musetalk, install_pockettts, avatar_pack_keys


def main() -> int:
    os.chdir(REPO_ROOT)
    args = build_parser().parse_args()
    installer = Installer(args)
    installer.preflight()

    if args.doctor_only:
        return 0

    install_main, install_musetalk, install_pockettts, avatar_pack_keys = resolve_requested_components(args)
    if not any([install_main, install_musetalk, install_pockettts, bool(avatar_pack_keys)]):
        warn("Nothing was selected for installation.")
        return 0

    try:
        if install_main:
            installer.install_main()
        if install_musetalk:
            installer.install_musetalk()
        if install_pockettts:
            installer.install_pockettts()
        if avatar_pack_keys:
            installer.install_avatar_packs(avatar_pack_keys)
    except subprocess.CalledProcessError as exc:
        fail("")
        fail("Installation failed.")
        cmd = [str(item) for item in exc.cmd]
        if "-c" in cmd:
            index = cmd.index("-c")
            compact_cmd = cmd[: index + 1] + ["<inline installer helper>"] + cmd[index + 2 :]
        else:
            compact_cmd = cmd
        fail(f"Command: {' '.join(compact_cmd)}")
        fail(f"Exit code: {exc.returncode}")
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr)
        return exc.returncode or 1

    installer.final_summary(install_main, install_musetalk, install_pockettts, avatar_pack_keys)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
