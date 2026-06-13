from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from addons.vam_avatar.hymotion_config import resolve_settings, validate_model_path
from addons.vam_avatar.hymotion_runner import run_prompt_to_motion


def _run(command, *, cwd=None, dry_run=False, check=False):
    record = {"command": [str(part) for part in command], "cwd": str(cwd or ""), "dry_run": bool(dry_run)}
    if dry_run:
        record.update({"returncode": 0, "stdout": "", "stderr": ""})
        return record
    proc = subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)
    record.update({"returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]})
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(record['command'])}\n{record['stderr']}")
    return record


def _which(name: str) -> str:
    return shutil.which(name) or ""


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def check_environment(settings) -> dict:
    disk_root = settings.output_dir.anchor or str(settings.output_dir.drive) or str(settings.output_dir.parent)
    usage = shutil.disk_usage(disk_root)
    venv_python = _venv_python(settings.venv_dir)
    checks = {
        "repo_root": str(REPO_ROOT),
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "python_recommended": sys.version_info[:2] in {(3, 10), (3, 11)},
        "python_note": "HY-Motion/PyTorch wheels are usually safest on Python 3.10 or 3.11.",
        "git": _which("git"),
        "git_lfs": _which("git-lfs"),
        "nvidia_smi": _which("nvidia-smi"),
        "huggingface_cli": _which("huggingface-cli"),
        "hf_token_present": bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")),
        "disk_free_gib": round(usage.free / (1024 ** 3), 2),
        "settings": settings.as_payload(),
        "model_check": validate_model_path(settings.model_path),
        "source_check": {
            "repo_dir_exists": settings.repo_dir.exists(),
            "local_infer_exists": (settings.repo_dir / "local_infer.py").exists(),
        },
        "venv_check": {
            "venv_dir_exists": settings.venv_dir.exists(),
            "python_exists": venv_python.exists(),
        },
    }
    if checks["nvidia_smi"]:
        checks["nvidia_smi_query"] = _run(
            [
                checks["nvidia_smi"],
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            dry_run=False,
        )
    if venv_python.exists():
        checks["torch_query"] = _run(
            [
                str(venv_python),
                "-c",
                "import torch; print({'torch': torch.__version__, 'cuda_available': torch.cuda.is_available(), 'cuda': torch.version.cuda})",
            ],
            dry_run=False,
        )
    return checks


def create_venv(settings, *, dry_run=False) -> dict:
    return _run([sys.executable, "-m", "venv", str(settings.venv_dir)], dry_run=dry_run, check=not dry_run)


def clone_or_update(settings, *, dry_run=False) -> list[dict]:
    commands = []
    if settings.repo_dir.exists():
        commands.append(_run(["git", "-C", str(settings.repo_dir), "pull", "--ff-only"], dry_run=dry_run))
    else:
        settings.repo_dir.parent.mkdir(parents=True, exist_ok=True)
        commands.append(_run(["git", "clone", settings.repo_url, str(settings.repo_dir)], dry_run=dry_run))
    commands.append(_run(["git", "-C", str(settings.repo_dir), "lfs", "pull"], dry_run=dry_run))
    return commands


def install_requirements(settings, *, torch_index_url="", dry_run=False) -> list[dict]:
    python_exe = _venv_python(settings.venv_dir)
    requirements = settings.repo_dir / "requirements.txt"
    commands = [
        _run([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"], dry_run=dry_run),
    ]
    if torch_index_url:
        commands.append(
            _run(
                [str(python_exe), "-m", "pip", "install", "torch==2.5.1", "torchvision==0.20.1", "--index-url", torch_index_url],
                dry_run=dry_run,
            )
        )
    commands.append(_run([str(python_exe), "-m", "pip", "install", "-r", str(requirements)], dry_run=dry_run))
    return commands


def download_model(settings, *, dry_run=False) -> dict:
    target = Path(settings.model_path)
    if target.name == "HY-Motion-1.0-Lite":
        local_dir = target.parent
    else:
        local_dir = target
    if not dry_run:
        local_dir.mkdir(parents=True, exist_ok=True)
    include_pattern = f"{settings.model_name}/*"
    return _run(
        [
            "huggingface-cli",
            "download",
            "tencent/HY-Motion-1.0",
            "--include",
            include_pattern,
            "--local-dir",
            str(local_dir),
        ],
        dry_run=dry_run,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Setup/check HY-Motion for the VaM avatar addon.")
    parser.add_argument("--check", action="store_true", help="Print environment and path checks.")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without installing or generating.")
    parser.add_argument("--create-venv", action="store_true", help="Create the addon-local HY-Motion venv.")
    parser.add_argument("--clone", action="store_true", help="Clone or fast-forward update HY-Motion source.")
    parser.add_argument("--install", action="store_true", help="Install HY-Motion requirements inside the addon venv.")
    parser.add_argument("--download-model", action="store_true", help="Download HY-Motion Lite into the configured model folder.")
    parser.add_argument("--validate-inference", action="store_true", help="Run a short real inference. Requires GPU and installed weights.")
    parser.add_argument("--all", action="store_true", help="Run create-venv, clone, install, download-model, and check.")
    parser.add_argument("--model-path", default="", help="Override the configured model folder.")
    parser.add_argument("--repo-dir", default="", help="Override HY-Motion source checkout folder.")
    parser.add_argument("--torch-index-url", default="", help="Optional PyTorch index URL for CUDA-specific wheels.")
    args = parser.parse_args(argv)

    overrides = {}
    if args.model_path:
        overrides["model_path"] = args.model_path
    if args.repo_dir:
        overrides["repo_dir"] = args.repo_dir
    settings = resolve_settings(overrides=overrides)
    result = {"settings": settings.as_payload(), "actions": []}

    run_all = bool(args.all)
    if args.check or run_all or not any((args.create_venv, args.clone, args.install, args.download_model, args.validate_inference)):
        result["check"] = check_environment(settings)
    if args.create_venv or run_all:
        result["actions"].append({"create_venv": create_venv(settings, dry_run=args.dry_run)})
    if args.clone or run_all:
        result["actions"].append({"clone_or_update": clone_or_update(settings, dry_run=args.dry_run)})
    if args.install or run_all:
        result["actions"].append({"install_requirements": install_requirements(settings, torch_index_url=args.torch_index_url, dry_run=args.dry_run)})
    if args.download_model or run_all:
        result["actions"].append({"download_model": download_model(settings, dry_run=args.dry_run)})
    if args.validate_inference:
        result["actions"].append(
            {
                "validate_inference": run_prompt_to_motion(
                    "A calm standing idle gesture, subtle breathing and hand movement.",
                    overrides={"duration_seconds": 2.0, "num_seeds": 1},
                    dry_run=args.dry_run,
                    timeout_seconds=900,
                )
            }
        )

    print(json.dumps(result, indent=2))
    failed = False
    for action in result.get("actions", []):
        for value in action.values():
            records = value if isinstance(value, list) else [value]
            for record in records:
                if isinstance(record, dict) and int(record.get("returncode", 0) or 0) != 0:
                    failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
