from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VENV_DIR = REPO_ROOT / ".venvs" / "nc_phone_remote"
DEFAULT_BRIDGE_INFO = REPO_ROOT / "runtime" / "main_chat_remote" / "bridge_info.json"
REMOTE_BACKEND = REPO_ROOT / "addons" / "main_chat_remote" / "remote_backend.py"
PAIRING_CODE_MIN_DIGITS = 4
PAIRING_CODE_MAX_DIGITS = 9


def venv_python(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run(command: list[str], *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"command": command, "returncode": 0, "dry_run": True}
    completed = subprocess.run(command, check=False)
    return {"command": command, "returncode": int(completed.returncode), "dry_run": False}


def validate_bridge_info(bridge_info: Path) -> dict[str, Any]:
    if not bridge_info.exists():
        return {"ok": False, "error": f"Bridge info not found. Enable the addon bridge first: {bridge_info}"}
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from addons.main_chat_remote.remote_backend import load_bridge_info

        info = load_bridge_info(bridge_info)
        return {
            "ok": True,
            "url": str(info.get("url") or ""),
            "updated_at": info.get("updated_at"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc) or "Bridge info is not usable."}


def check_status(venv_dir: Path, bridge_info: Path) -> dict[str, Any]:
    python_exe = venv_python(venv_dir)
    bridge_validation = validate_bridge_info(bridge_info)
    return {
        "repo_root": str(REPO_ROOT),
        "venv_dir": str(venv_dir),
        "venv_exists": venv_dir.exists(),
        "python": str(python_exe),
        "python_exists": python_exe.exists(),
        "bridge_info": str(bridge_info),
        "bridge_info_exists": bridge_info.exists(),
        "bridge_info_usable": bool(bridge_validation.get("ok")),
        "bridge_info_error": str(bridge_validation.get("error") or ""),
        "remote_backend": str(REMOTE_BACKEND),
        "remote_backend_exists": REMOTE_BACKEND.exists(),
    }


def create_venv(venv_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    python_exe = venv_python(venv_dir)
    if python_exe.exists():
        return {"skipped": True, "reason": "venv python already exists", "python": str(python_exe)}
    return run([sys.executable, "-m", "venv", str(venv_dir)], dry_run=dry_run)


def backend_command(args: argparse.Namespace, python_exe: Path) -> list[str]:
    return [
        str(python_exe),
        str(REMOTE_BACKEND),
        "--bridge-info",
        str(Path(args.bridge_info)),
        "--host",
        str(args.host),
        "--port",
        str(int(args.port)),
    ]


def normalize_pairing_code(value: str, *, max_digits: int = PAIRING_CODE_MAX_DIGITS) -> str:
    digits = "".join(ch for ch in str(value or "") if "0" <= ch <= "9")[: max(1, int(max_digits or PAIRING_CODE_MAX_DIGITS))]
    if len(digits) < PAIRING_CODE_MIN_DIGITS:
        return ""
    return digits


def backend_environment(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    code = normalize_pairing_code(str(args.pairing_code or ""))
    if not code:
        env.pop("NC_MAIN_CHAT_REMOTE_CODE", None)
        env.pop("NC_MAIN_CHAT_REMOTE_HIDE_CODE_OUTPUT", None)
        return env
    env["NC_MAIN_CHAT_REMOTE_CODE"] = code
    env["NC_MAIN_CHAT_REMOTE_HIDE_CODE_OUTPUT"] = "1"
    return env


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create/check/start the Main Chat Remote backend venv.")
    parser.add_argument("--venv-dir", default=str(DEFAULT_VENV_DIR))
    parser.add_argument("--bridge-info", default=str(DEFAULT_BRIDGE_INFO))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--pairing-code", default="")
    parser.add_argument("--create", action="store_true", help="Create the backend venv if it is missing.")
    parser.add_argument("--start", action="store_true", help="Start the LAN backend using the venv Python.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without creating or starting anything.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    venv_dir = Path(args.venv_dir)
    if not venv_dir.is_absolute():
        venv_dir = REPO_ROOT / venv_dir
    bridge_info = Path(args.bridge_info)
    if not bridge_info.is_absolute():
        bridge_info = REPO_ROOT / bridge_info
    args.bridge_info = str(bridge_info)
    result: dict[str, Any] = {"status_before": check_status(venv_dir, bridge_info), "actions": []}

    if args.create:
        result["actions"].append({"create_venv": create_venv(venv_dir, dry_run=bool(args.dry_run))})

    status_after_create = check_status(venv_dir, bridge_info)
    result["status_after_create"] = status_after_create

    if args.start:
        python_exe = Path(status_after_create["python"])
        command = backend_command(args, python_exe)
        result["actions"].append(
            {
                "start_backend": {
                    "command": command,
                    "dry_run": bool(args.dry_run),
                    "pairing_code_source": (
                        "env" if normalize_pairing_code(str(args.pairing_code or "")) else "backend_generated"
                    ),
                }
            }
        )
        print(json.dumps(result, indent=2), flush=True)
        if args.dry_run:
            return 0
        if not python_exe.exists():
            print(f"Backend venv Python not found: {python_exe}", file=sys.stderr)
            return 2
        bridge_validation = validate_bridge_info(bridge_info)
        if not bool(bridge_validation.get("ok")):
            print(f"Bridge info is not usable. Start the local bridge first: {bridge_validation.get('error')}", file=sys.stderr)
            return 3
        return int(subprocess.call(command, env=backend_environment(args)))

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
