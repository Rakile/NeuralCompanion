from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from addons.vam_avatar.hymotion_config import resolve_settings
from addons.vam_avatar.hymotion_runner import (
    build_vam_bridge_payload,
    run_prompt_to_motion,
    write_vam_bridge_command,
)


DEFAULT_TIMEOUT_SECONDS = 1800
EXPECTED_BRIDGE_VERSION = "2026-06-13-hymotion-events-timeline"


def latest_manifest(output_dir: Path) -> Path | None:
    manifests = [path for path in output_dir.rglob("motion_manifest.json") if path.is_file()]
    if not manifests:
        return None
    return max(manifests, key=lambda path: path.stat().st_mtime)


def load_motion_result(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"manifest": manifest, "manifest_path": str(manifest_path)}


def bridge_paths(vam_root: str = "") -> dict[str, Path]:
    settings = resolve_settings(overrides={"vam_root": vam_root} if vam_root.strip() else {})
    bridge_root = Path(settings.bridge_root)
    return {
        "bridge_root": bridge_root,
        "inbox": bridge_root / "inbox",
        "outbox": bridge_root / "outbox",
        "status": bridge_root / "outbox" / "status.json",
        "last_hy_motion": bridge_root / "outbox" / "last_hy_motion.json",
        "trace": bridge_root / "outbox" / "trace.log",
    }


def read_bridge_status(vam_root: str = "") -> dict[str, Any]:
    paths = bridge_paths(vam_root)
    result: dict[str, Any] = {"paths": {key: str(value) for key, value in paths.items()}}
    for key in ("status", "last_hy_motion"):
        path = paths[key]
        if path.exists():
            try:
                result[key] = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                result[key] = {"error": str(exc), "raw": path.read_text(encoding="utf-8", errors="replace")[-2000:]}
        else:
            result[key] = {"missing": str(path)}
    return result


def send_manifest_to_vam(
    manifest_path: Path,
    *,
    vam_root: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {"dry_run": bool(dry_run), "stage_assets": True}
    if vam_root.strip():
        overrides["vam_root"] = vam_root.strip()
    settings = resolve_settings(overrides=overrides)
    motion_result = load_motion_result(manifest_path)
    payload = build_vam_bridge_payload(motion_result, overrides=overrides)
    command = write_vam_bridge_command(settings.bridge_root, "hy_motion_generated", payload, dry_run=dry_run)
    return {
        "ok": bool(command.get("ok")),
        "dry_run": bool(dry_run),
        "manifest": str(manifest_path),
        "command": command,
        "payload": payload,
    }


def send_bridge_action(
    action: str,
    *,
    vam_root: str = "",
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {"dry_run": bool(dry_run)}
    if vam_root.strip():
        overrides["vam_root"] = vam_root.strip()
    settings = resolve_settings(overrides=overrides)
    body = dict(payload or {})
    command = write_vam_bridge_command(settings.bridge_root, action, body, dry_run=dry_run)
    return {
        "ok": bool(command.get("ok")),
        "dry_run": bool(dry_run),
        "action": action,
        "bridge_root": settings.bridge_root,
        "command": command,
    }


def verify_bridge_actions(
    *,
    vam_root: str = "",
    dry_run: bool = False,
    wait_seconds: float = 1.5,
) -> dict[str, Any]:
    def wait_for_consumed(command_result: dict[str, Any], timeout: float) -> dict[str, Any]:
        path = Path(str(((command_result or {}).get("command") or {}).get("path") or ""))
        if not path:
            return {"ok": False, "path": "", "message": "No command path was returned."}
        deadline = time.time() + max(0.1, float(timeout))
        while time.time() < deadline:
            if not path.exists():
                return {"ok": True, "path": str(path), "message": "Command was consumed by VaM."}
            time.sleep(0.1)
        return {"ok": False, "path": str(path), "message": "Command file was not consumed by VaM."}

    self_test = send_bridge_action("bridge_self_test", vam_root=vam_root, dry_run=dry_run)
    if dry_run:
        return {"ok": bool(self_test.get("ok")), "dry_run": True, "sent": self_test, "expected_bridge_version": EXPECTED_BRIDGE_VERSION}

    self_test_consumed = wait_for_consumed(self_test, wait_seconds)
    status = read_bridge_status(vam_root)
    current = dict(status.get("status") or {})
    action = str(current.get("lastAction") or "")
    note = str(current.get("note") or "")
    version = str(current.get("bridgeVersion") or "")
    old_bridge = action == "bridge_self_test" and "Unknown bridge command" in note
    version_ok = version == EXPECTED_BRIDGE_VERSION
    self_test_ok = bool(self_test.get("ok")) and bool(self_test_consumed.get("ok")) and action == "bridge_self_test" and version_ok and not old_bridge

    play_latest = None
    play_latest_consumed = None
    if self_test_ok:
        play_latest = send_bridge_action("hy_motion_play_latest", vam_root=vam_root, dry_run=False)
        play_latest_consumed = wait_for_consumed(play_latest, wait_seconds)
        status = read_bridge_status(vam_root)
        current = dict(status.get("status") or {})

    if not self_test_consumed.get("ok"):
        message = "VaM did not consume the self-test command. VaM is closed, polling is off, or the bridge is not loaded."
    elif old_bridge or not version_ok or action != "bridge_self_test":
        message = "VaM is still running the old compiled bridge; reload/re-add NeuralCompanionBridge.cs."
    elif play_latest_consumed is not None and not play_latest_consumed.get("ok"):
        message = "VaM accepted self-test but did not consume Play Latest HY-Motion."
    else:
        message = "VaM accepted the trigger-friendly HY-Motion bridge action."

    return {
        "ok": self_test_ok and (play_latest_consumed is None or bool(play_latest_consumed.get("ok"))),
        "sent": self_test,
        "self_test_consumed": self_test_consumed,
        "play_latest": play_latest,
        "play_latest_consumed": play_latest_consumed,
        "status": current,
        "old_bridge_still_loaded": old_bridge,
        "expected_bridge_version": EXPECTED_BRIDGE_VERSION,
        "bridge_version": version,
        "message": message,
    }


def generate_motion_from_prompt(
    prompt: str,
    *,
    duration_seconds: float,
    cfg_scale: float,
    num_seeds: int,
    validation_steps: int | None,
    vam_root: str = "",
    send: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {
        "duration_seconds": float(duration_seconds),
        "cfg_scale": float(cfg_scale),
        "num_seeds": int(num_seeds),
    }
    if validation_steps:
        overrides["validation_steps"] = int(validation_steps)
    if vam_root.strip():
        overrides["vam_root"] = vam_root.strip()

    motion = run_prompt_to_motion(
        prompt,
        overrides=overrides,
        dry_run=dry_run,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )
    result: dict[str, Any] = {"motion": motion}
    if not motion.get("ok"):
        result["ok"] = False
        result["error"] = motion.get("error") or "HY-Motion generation failed."
        return result

    manifest_path = Path(str(motion.get("manifest_path") or ""))
    if send and not dry_run:
        result["send"] = send_manifest_to_vam(manifest_path, vam_root=vam_root, dry_run=False)
    elif send and dry_run:
        # Dry runs have no manifest on disk. Build/send is covered by hymotion_send_bridge.py.
        result["send"] = {"dry_run": True, "skipped": "Generation dry-run does not create a manifest."}
    result["ok"] = True
    return result


def _json_summary(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


def run_gui() -> int:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("HY-Motion VaM Test")
    root.geometry("920x680")

    events: "queue.Queue[tuple[str, Any]]" = queue.Queue()
    busy = tk.BooleanVar(value=False)
    prompt_var = tk.StringVar(value="A friendly wave, relaxed posture, subtle breathing and hand movement.")
    duration_var = tk.StringVar(value="4.0")
    cfg_var = tk.StringVar(value="5.0")
    seeds_var = tk.StringVar(value="1")
    validation_var = tk.StringVar(value="")
    motion_name_var = tk.StringVar(value="")
    vam_root_var = tk.StringVar(value=resolve_settings().vam_root)

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.columnconfigure(1, weight=1)
    frm.rowconfigure(7, weight=1)

    ttk.Label(frm, text="Prompt").grid(row=0, column=0, sticky="w")
    prompt_entry = ttk.Entry(frm, textvariable=prompt_var)
    prompt_entry.grid(row=0, column=1, columnspan=5, sticky="ew", pady=3)

    ttk.Label(frm, text="Duration").grid(row=1, column=0, sticky="w")
    ttk.Entry(frm, textvariable=duration_var, width=10).grid(row=1, column=1, sticky="w", pady=3)
    ttk.Label(frm, text="CFG").grid(row=1, column=2, sticky="w")
    ttk.Entry(frm, textvariable=cfg_var, width=10).grid(row=1, column=3, sticky="w", pady=3)
    ttk.Label(frm, text="Seeds").grid(row=1, column=4, sticky="w")
    ttk.Entry(frm, textvariable=seeds_var, width=10).grid(row=1, column=5, sticky="w", pady=3)

    ttk.Label(frm, text="Validation steps").grid(row=2, column=0, sticky="w")
    ttk.Entry(frm, textvariable=validation_var, width=10).grid(row=2, column=1, sticky="w", pady=3)
    ttk.Label(frm, text="Motion name").grid(row=2, column=2, sticky="w")
    ttk.Entry(frm, textvariable=motion_name_var, width=28).grid(row=2, column=3, columnspan=3, sticky="ew", pady=3)
    ttk.Label(frm, text="VaM root").grid(row=3, column=0, sticky="w")
    ttk.Entry(frm, textvariable=vam_root_var).grid(row=3, column=1, columnspan=5, sticky="ew", pady=3)

    log = scrolledtext.ScrolledText(frm, height=24, wrap=tk.WORD)
    log.grid(row=7, column=0, columnspan=6, sticky="nsew", pady=(10, 0))

    def append(text: str) -> None:
        log.insert(tk.END, text.rstrip() + "\n")
        log.see(tk.END)

    def parse_float(raw: str, default: float) -> float:
        try:
            return float(raw)
        except ValueError:
            return default

    def parse_int(raw: str, default: int | None) -> int | None:
        text = raw.strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            return default

    def worker(action: str, send: bool = True) -> None:
        try:
            if action == "generate":
                events.put(("log", "Starting HY-Motion generation. This can take a few minutes..."))
                result = generate_motion_from_prompt(
                    prompt_var.get(),
                    duration_seconds=parse_float(duration_var.get(), 4.0),
                    cfg_scale=parse_float(cfg_var.get(), 5.0),
                    num_seeds=int(parse_int(seeds_var.get(), 1) or 1),
                    validation_steps=parse_int(validation_var.get(), None),
                    vam_root=vam_root_var.get(),
                    send=send,
                    dry_run=False,
                )
                events.put(("result", result))
            elif action == "send_latest":
                settings = resolve_settings(overrides={"vam_root": vam_root_var.get()} if vam_root_var.get().strip() else {})
                manifest = latest_manifest(settings.output_dir)
                if manifest is None:
                    raise RuntimeError(f"No motion_manifest.json found under {settings.output_dir}")
                events.put(("result", send_manifest_to_vam(manifest, vam_root=vam_root_var.get(), dry_run=False)))
            elif action == "status":
                events.put(("result", read_bridge_status(vam_root_var.get())))
            elif action == "play_latest":
                events.put(("result", send_bridge_action("hy_motion_play_latest", vam_root=vam_root_var.get())))
            elif action == "stop":
                events.put(("result", send_bridge_action("hy_motion_stop", vam_root=vam_root_var.get())))
            elif action == "reset_pose":
                events.put(("result", send_bridge_action("hy_motion_reset_pose", vam_root=vam_root_var.get())))
            elif action == "load_name":
                name = motion_name_var.get().strip()
                if not name:
                    raise RuntimeError("Motion name is required for Load By Name.")
                events.put(("result", send_bridge_action("hy_motion_load_by_name", vam_root=vam_root_var.get(), payload={"motion_stage_dir": name})))
            elif action == "verify_actions":
                events.put(("result", verify_bridge_actions(vam_root=vam_root_var.get())))
        except Exception:
            events.put(("error", traceback.format_exc()))
        finally:
            events.put(("busy", False))

    def start(action: str, send: bool = True) -> None:
        if busy.get():
            messagebox.showinfo("HY-Motion", "A task is already running.")
            return
        busy.set(True)
        events.put(("busy", True))
        threading.Thread(target=worker, args=(action, send), daemon=True).start()

    def pump() -> None:
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == "busy":
                    busy.set(bool(payload))
                elif kind == "log":
                    append(str(payload))
                elif kind == "result":
                    append(_json_summary(payload))
                elif kind == "error":
                    append(str(payload))
                    messagebox.showerror("HY-Motion", "Task failed. See log for details.")
        except queue.Empty:
            pass
        root.after(200, pump)

    ttk.Button(frm, text="Generate and Send", command=lambda: start("generate", True)).grid(row=4, column=0, pady=8, sticky="ew")
    ttk.Button(frm, text="Generate Only", command=lambda: start("generate", False)).grid(row=4, column=1, pady=8, sticky="ew")
    ttk.Button(frm, text="Send Latest", command=lambda: start("send_latest", True)).grid(row=4, column=2, pady=8, sticky="ew")
    ttk.Button(frm, text="Bridge Status", command=lambda: start("status", True)).grid(row=4, column=3, pady=8, sticky="ew")
    ttk.Button(frm, text="Clear Log", command=lambda: log.delete("1.0", tk.END)).grid(row=4, column=4, pady=8, sticky="ew")
    ttk.Button(frm, text="Play Latest", command=lambda: start("play_latest", True)).grid(row=5, column=0, pady=4, sticky="ew")
    ttk.Button(frm, text="Stop", command=lambda: start("stop", True)).grid(row=5, column=1, pady=4, sticky="ew")
    ttk.Button(frm, text="Reset Pose", command=lambda: start("reset_pose", True)).grid(row=5, column=2, pady=4, sticky="ew")
    ttk.Button(frm, text="Load Name", command=lambda: start("load_name", True)).grid(row=5, column=3, pady=4, sticky="ew")
    ttk.Button(frm, text="Verify Actions", command=lambda: start("verify_actions", True)).grid(row=5, column=4, pady=4, sticky="ew")

    append("Ready. Start VaM, load NeuralCompanionBridge.cs on Person, then Generate and Send.")
    pump()
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Small HY-Motion text-to-motion test app for VaM.")
    parser.add_argument("--prompt", default="", help="Generate from this prompt without opening the GUI.")
    parser.add_argument("--duration", type=float, default=4.0)
    parser.add_argument("--cfg-scale", type=float, default=5.0)
    parser.add_argument("--num-seeds", type=int, default=1)
    parser.add_argument("--validation-steps", type=int, default=0)
    parser.add_argument("--vam-root", default="")
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--send-latest", action="store_true")
    parser.add_argument("--play-latest", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--reset-pose", action="store_true")
    parser.add_argument("--load-name", default="")
    parser.add_argument("--verify-actions", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.status:
        print(_json_summary(read_bridge_status(args.vam_root)))
        return 0

    if args.send_latest:
        settings = resolve_settings(overrides={"vam_root": args.vam_root} if args.vam_root.strip() else {})
        manifest = latest_manifest(settings.output_dir)
        if manifest is None:
            print(f"No motion_manifest.json found under {settings.output_dir}", file=sys.stderr)
            return 2
        print(_json_summary(send_manifest_to_vam(manifest, vam_root=args.vam_root, dry_run=args.dry_run)))
        return 0

    if args.play_latest:
        print(_json_summary(send_bridge_action("hy_motion_play_latest", vam_root=args.vam_root, dry_run=args.dry_run)))
        return 0

    if args.stop:
        print(_json_summary(send_bridge_action("hy_motion_stop", vam_root=args.vam_root, dry_run=args.dry_run)))
        return 0

    if args.reset_pose:
        print(_json_summary(send_bridge_action("hy_motion_reset_pose", vam_root=args.vam_root, dry_run=args.dry_run)))
        return 0

    if args.load_name.strip():
        print(
            _json_summary(
                send_bridge_action(
                    "hy_motion_load_by_name",
                    vam_root=args.vam_root,
                    payload={"motion_stage_dir": args.load_name.strip()},
                    dry_run=args.dry_run,
                )
            )
        )
        return 0

    if args.verify_actions:
        result = verify_bridge_actions(vam_root=args.vam_root, dry_run=args.dry_run)
        print(_json_summary(result))
        return 0 if result.get("ok") else 1

    if args.prompt.strip():
        print(
            _json_summary(
                generate_motion_from_prompt(
                    args.prompt,
                    duration_seconds=args.duration,
                    cfg_scale=args.cfg_scale,
                    num_seeds=args.num_seeds,
                    validation_steps=args.validation_steps or None,
                    vam_root=args.vam_root,
                    send=not args.generate_only,
                    dry_run=args.dry_run,
                )
            )
        )
        return 0

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
