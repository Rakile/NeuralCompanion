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

        ffmpeg_ok = shutil.which("ffmpeg") is not None
        self.findings.append(
            DoctorFinding(
                "FFmpeg",
                "OK" if ffmpeg_ok else "WARN",
                "Found on PATH" if ffmpeg_ok else "Missing from PATH",
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
            self.download_file(url, archive_path)
            note(f"Extracting {label} avatar pack...")
            self.extract_avatar_pack_zip(archive_path, extract_root)

            extracted_pack = extract_root / pack_id
            if not extracted_pack.is_dir():
                raise SystemExit(
                    f"{label} avatar pack archive did not contain the expected top-level folder: {pack_id}"
                )
            shutil.move(str(extracted_pack), str(destination))
            ok(f"{label} avatar pack installed at {destination}")

    def download_file(self, url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        headers = {"User-Agent": "NeuralCompanionInstaller"}
        token = str(os.environ.get("NC_AVATAR_PACK_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
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

        if not self.args.skip_main_torch:
            note("Installing CUDA-enabled torch for Neural Companion...")
            self.pip_install(
                python_exe,
                "install",
                "torch==2.6.0",
                "torchaudio==2.6.0",
                "torchvision==0.21.0",
                "--force-reinstall",
                "--index-url",
                "https://download.pytorch.org/whl/cu126",
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

        note("Applying known-good compatibility pins...")
        self.pip_install(
            python_exe,
            "install",
            "numpy==1.24.4",
            "pillow==11.2.1",
            "PyAudio==0.2.14",
        )

        self.verify_imports(
            python_exe,
            ["torch", "PySide6", "flask", "nltk", "openai"],
            "Main app",
        )
        self.verify_torch_cuda(python_exe, "Main app")

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
        print(f"  2. Run: {python_exe.parent / 'hf.exe'} auth login")

    def install_musetalk(self) -> None:
        headline("Installing MuseTalk")
        if not shutil.which("nvidia-smi"):
            warn("MuseTalk can be installed without nvidia-smi, but GPU-backed performance may not be available.")

        python_exe = self.ensure_venv(MUSETALK_VENV, "MuseTalk")
        note("Upgrading MuseTalk bootstrap tools...")
        self.pip_install(python_exe, "install", "--upgrade", "pip", "setuptools<81", "wheel")

        note("Installing CUDA-enabled torch for MuseTalk...")
        self.pip_install(
            python_exe,
            "install",
            "torch==2.0.1+cu118",
            "torchaudio==2.0.2+cu118",
            "torchvision==0.15.2+cu118",
            "--force-reinstall",
            "--index-url",
            "https://download.pytorch.org/whl/cu118",
        )

        note("Installing OpenMMLab bootstrap tools...")
        self.pip_install(python_exe, "install", "openmim==0.3.9")

        note("Installing mmcv through OpenMIM...")
        run_command([str(python_exe), "-m", "mim", "install", "mmcv==2.0.1"], cwd=REPO_ROOT)

        note("Preinstalling chumpy without build isolation...")
        self.pip_install(python_exe, "install", "chumpy==0.70", "--no-build-isolation")

        note("Installing pinned MuseTalk runtime requirements...")
        self.pip_install(
            python_exe,
            "install",
            "-r",
            str(REPO_ROOT / "requirements.musetalk.txt"),
        )

        note("Applying known-good MuseTalk compatibility pins...")
        self.pip_install(
            python_exe,
            "install",
            "numpy==1.26.4",
            "pillow==11.2.1",
        )

        self.ensure_musetalk_weights(python_exe)

        self.verify_imports(
            python_exe,
            ["torch", "cv2", "diffusers", "mmcv"],
            "MuseTalk",
        )
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
                "import torch; print('available=' + str(torch.cuda.is_available())); print('cuda=' + str(torch.version.cuda))",
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
        print("  - FFmpeg is on PATH")
        print("  - LM Studio is installed and has a model loaded if you want local chat")
        print("  - Optional MuseTalk avatar packs live in avatar_packs/<pack_id>")
        print("  - PocketTTS voice cloning still requires Hugging Face terms acceptance on kyutai/pocket-tts")
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
