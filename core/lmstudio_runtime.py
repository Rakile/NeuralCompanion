"""LM Studio model lifecycle helpers.

Provider-specific model load/unload behavior lives here so the engine can stay
focused on orchestration instead of embedding LM Studio mechanics directly.
"""

from __future__ import annotations

import importlib
import re
import subprocess


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _clean_cli_output(text: str) -> str:
    cleaned = _ANSI_RE.sub("", str(text or ""))
    cleaned = cleaned.replace("\r", "\n")
    lines = []
    for line in cleaned.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("loading ") and "model loaded successfully" not in line.lower():
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def get_sdk():
    try:
        return importlib.import_module("lmstudio")
    except Exception:
        return None


def sdk_host(base_url: str) -> str:
    try:
        api_host = str(base_url or "").strip()
        api_host = re.sub(r"^https?://", "", api_host, flags=re.IGNORECASE)
        api_host = api_host.rstrip("/")
        if api_host.endswith("/v1"):
            api_host = api_host[:-3]
        return api_host.strip("/")
    except Exception:
        return "127.0.0.1:1234"


def sdk_client(sdk, base_url: str):
    if sdk is None:
        return None
    try:
        return sdk.Client(api_host=sdk_host(base_url))
    except Exception:
        return None


def run_lms_cli(args, timeout=300):
    try:
        completed = subprocess.run(
            ["lms", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        output = "\n".join(
            part.strip() for part in [completed.stdout or "", completed.stderr or ""] if part and part.strip()
        ).strip()
        output = _clean_cli_output(output)
        return completed.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def unload_models(*, base_url: str, logger=print) -> bool:
    logger("🧠 [LM Studio] Unloading loaded models before MuseTalk warmup...")
    sdk = get_sdk()
    if sdk is not None:
        try:
            client = sdk_client(sdk, base_url)
            if client is None:
                raise RuntimeError("Could not create LM Studio SDK client")
            loaded_models = list(client.list_loaded_models())
            if not loaded_models:
                logger("✓ [LM Studio] No loaded models to unload.")
                return True
            unloaded = []
            for model in loaded_models:
                identifier = getattr(model, "identifier", None) or "<unknown>"
                model.unload()
                unloaded.append(str(identifier))
            logger(f"✓ [LM Studio] Unloaded via SDK: {', '.join(unloaded)}")
            return True
        except Exception as exc:
            logger(f"⚠️ [LM Studio] SDK unload failed, falling back to CLI: {exc}")
    ok, output = run_lms_cli(["unload", "--all"], timeout=180)
    if ok:
        if output:
            logger(f"✓ [LM Studio] Unload complete: {output}")
        else:
            logger("✓ [LM Studio] Unload complete.")
        return True
    logger(f"⚠️ [LM Studio] Could not unload models: {output}")
    return False


def load_model(model_name: str, *, base_url: str, is_placeholder=None, logger=print) -> bool:
    clean_model_name = str(model_name or "").strip()
    if callable(is_placeholder) and is_placeholder(clean_model_name):
        return False
    logger(f"🧠 [LM Studio] Reloading selected model: {clean_model_name}")
    sdk = get_sdk()
    if sdk is not None:
        try:
            client = sdk_client(sdk, base_url)
            if client is None:
                raise RuntimeError("Could not create LM Studio SDK client")
            model = client.llm.model(clean_model_name)
            identifier = getattr(model, "identifier", None) or clean_model_name
            logger(f"✓ [LM Studio] Model ready via SDK: {identifier}")
            return True
        except Exception as exc:
            logger(f"⚠️ [LM Studio] SDK reload failed, falling back to CLI: {exc}")
    ok, output = run_lms_cli(["load", clean_model_name, "--yes"], timeout=600)
    if ok:
        logger(f"✓ [LM Studio] Model ready: {clean_model_name}")
        return True
    logger(f"⚠️ [LM Studio] Could not reload '{clean_model_name}': {output}")
    return False
