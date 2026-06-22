from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    from core import crash_diagnostics

    with tempfile.TemporaryDirectory(prefix="nc_crash_diag_smoke_") as temp_name:
        app_root = Path(temp_name)
        runtime_dir = app_root / "runtime"
        (runtime_dir / "crash_dumps").mkdir(parents=True)
        (runtime_dir / "logs").mkdir(parents=True)
        (runtime_dir / "companion_orb" / "debug").mkdir(parents=True)
        (app_root / "addons" / "sample_addon").mkdir(parents=True)

        crash_log = runtime_dir / "crash_dumps" / "nc_crash_smoke.log"
        crash_log.write_text("traceback line\nsecret should not matter here\n", encoding="utf-8")
        (runtime_dir / "logs" / "sample.log").write_text("line one\nline two\n", encoding="utf-8")
        (runtime_dir / "companion_orb" / "debug" / "companion_orb_debug.log").write_text(
            '{"event":"hidden_ping_attempt","accepted":true}\n',
            encoding="utf-8",
        )
        (app_root / "addons" / "sample_addon" / "addon.json").write_text(
            json.dumps({"id": "nc.sample", "name": "Sample Addon"}),
            encoding="utf-8",
        )
        (app_root / "qt_session.json").write_text(
            json.dumps(
                {
                    "chat_provider_settings": {"openai": {"api_key": "sk-live-secret"}},
                    "main_chat_remote_bridge_token": "keep-this-private",
                    "normal_value": "visible",
                }
            ),
            encoding="utf-8",
        )

        crash_diagnostics.record_console_text("console before crash\n")
        bundle_zip = crash_diagnostics.create_debug_bundle(
            app_root=app_root,
            reason="smoke-test",
            crash_log_path=crash_log,
            runtime_config={"api_key": "secret-token", "chat_provider": "lmstudio"},
            extra_context={"unit": "smoke"},
        )

        if not bundle_zip.exists() or bundle_zip.suffix.lower() != ".zip":
            raise AssertionError(f"Expected debug bundle zip, got {bundle_zip}")

        with zipfile.ZipFile(bundle_zip, "r") as archive:
            names = set(archive.namelist())
            required = {
                "README_FOR_CODEX.txt",
                "manifest.json",
                "environment.json",
                "runtime_config_redacted.json",
                "qt_session_redacted.json",
                "console_tail.txt",
                "addons.json",
                "files/latest_crash.log",
                "files/runtime_logs/sample.log",
            }
            missing = sorted(required - names)
            if missing:
                raise AssertionError(f"Debug bundle missing files: {missing}")
            runtime_config = json.loads(archive.read("runtime_config_redacted.json").decode("utf-8"))
            qt_session = json.loads(archive.read("qt_session_redacted.json").decode("utf-8"))
            readme = archive.read("README_FOR_CODEX.txt").decode("utf-8")
            console_tail = archive.read("console_tail.txt").decode("utf-8")

        if runtime_config.get("api_key") != "[REDACTED]":
            raise AssertionError(f"Runtime API key was not redacted: {runtime_config!r}")
        if qt_session.get("main_chat_remote_bridge_token") != "[REDACTED]":
            raise AssertionError(f"Session token was not redacted: {qt_session!r}")
        provider_key = qt_session.get("chat_provider_settings", {}).get("openai", {}).get("api_key")
        if provider_key != "[REDACTED]":
            raise AssertionError(f"Nested provider key was not redacted: {provider_key!r}")
        if "normal_value" not in qt_session or qt_session["normal_value"] != "visible":
            raise AssertionError(f"Non-secret session value was unexpectedly changed: {qt_session!r}")
        if "Codex" not in readme or "smoke-test" not in readme:
            raise AssertionError("README_FOR_CODEX.txt should explain the bundle reason")
        if "console before crash" not in console_tail:
            raise AssertionError("Console tail was not captured")

    print("Crash diagnostics debug bundle smoke passed.")

    app_entry_source = (ROOT_DIR / "ui" / "app_entry.py").read_text(encoding="utf-8")
    console_redirect_source = (ROOT_DIR / "ui" / "runtime" / "console_redirect.py").read_text(encoding="utf-8")
    qt_app_source = (ROOT_DIR / "qt_app.py").read_text(encoding="utf-8")
    if "crash_diagnostics.create_debug_bundle" not in app_entry_source:
        raise AssertionError("ui/app_entry.py should create a Codex debug bundle from crash hooks")
    if "crash_diagnostics.record_console_text" not in console_redirect_source:
        raise AssertionError("console redirect should feed the diagnostic console tail")
    if "--codex-debug-bundle" not in qt_app_source:
        raise AssertionError("qt_app.py should expose a manual Codex debug bundle command")


if __name__ == "__main__":
    main()
