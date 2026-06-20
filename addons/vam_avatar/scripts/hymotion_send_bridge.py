from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from addons.vam_avatar.hymotion_config import resolve_settings
from addons.vam_avatar.hymotion_runner import build_vam_bridge_payload, write_vam_bridge_command


def _latest_manifest(output_dir: Path) -> Path | None:
    manifests = [path for path in output_dir.rglob("motion_manifest.json") if path.is_file()]
    if not manifests:
        return None
    return max(manifests, key=lambda path: path.stat().st_mtime)


def _load_motion_result(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"manifest": manifest, "manifest_path": str(manifest_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage a HY-Motion result and send it to the VaM bridge inbox.")
    parser.add_argument("--manifest", default="", help="Path to a HY-Motion motion_manifest.json. Defaults to the newest output manifest.")
    parser.add_argument("--vam-root", default="", help="VaM root path. Defaults to the configured NC_VAM_ROOT/default VaM path.")
    parser.add_argument("--no-stage", action="store_true", help="Do not copy motion files into VaM PluginData before sending.")
    parser.add_argument("--dry-run", action="store_true", help="Build the payload without copying assets or writing an inbox command.")
    parser.add_argument("--print-json", action="store_true", help="Print the full command result as JSON.")
    args = parser.parse_args()

    overrides = {"dry_run": bool(args.dry_run), "stage_assets": not bool(args.no_stage)}
    if args.vam_root.strip():
        overrides["vam_root"] = args.vam_root.strip()
    settings = resolve_settings(overrides=overrides)

    manifest_path = Path(args.manifest).expanduser() if args.manifest.strip() else _latest_manifest(settings.output_dir)
    if manifest_path is None or not manifest_path.exists():
        print(f"No HY-Motion manifest found under {settings.output_dir}", file=sys.stderr)
        return 2

    motion_result = _load_motion_result(manifest_path)
    payload = build_vam_bridge_payload(motion_result, overrides=overrides)
    result = write_vam_bridge_command(settings.bridge_root, "hy_motion_generated", payload, dry_run=args.dry_run)
    result["manifest"] = str(manifest_path)
    result["bridge_root"] = settings.bridge_root
    result["motion_stage_dir"] = payload.get("motion_stage_dir", "")

    if args.print_json:
        print(json.dumps(result, indent=2))
    else:
        status = "would write" if args.dry_run else "wrote"
        print(f"{status}: {result.get('path', '')}")
        print(f"manifest: {manifest_path}")
        print(f"stage: {payload.get('motion_stage_dir', '')}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
