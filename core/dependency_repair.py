from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_STATE_PATH = APP_ROOT / "runtime" / "dependency_state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def current_python() -> str:
    return str(Path(sys.executable).resolve())


def requirements_hash_from_lines(lines: list[str]) -> str:
    normalized = "\n".join(str(line).strip() for line in lines if str(line).strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def requirements_file_hash(path: str | Path) -> str:
    target = Path(path)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def load_dependency_state(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else DEPENDENCY_STATE_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def save_dependency_state(payload: dict[str, Any], path: str | Path | None = None) -> None:
    target = Path(path) if path is not None else DEPENDENCY_STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload or {}), indent=2, sort_keys=True), encoding="utf-8")


def _record_for(target_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = state if state is not None else load_dependency_state()
    record = (payload.get("targets") or {}).get(str(target_id or "").strip())
    return dict(record) if isinstance(record, dict) else {}


def _record_matches(record: dict[str, Any], requirements_hash: str, python: str | None = None) -> bool:
    return (
        str(record.get("status") or "") == "ok"
        and str(record.get("requirements_hash") or "") == str(requirements_hash or "")
        and str(record.get("python") or "") == str(python or current_python())
    )


def install_args_for_packages(packages: list[str]) -> list[str]:
    return ["-m", "pip", "install", *[str(item).strip() for item in packages if str(item).strip()]]


def install_args_for_requirements(requirements_path: str | Path) -> list[str]:
    return ["-m", "pip", "install", "-r", str(Path(requirements_path))]


def core_feature_status(
    *,
    feature_id: str,
    label: str,
    requirements: list[str],
    available: bool,
    message: str = "",
    installable: bool = True,
) -> dict[str, Any]:
    target_id = str(feature_id or "").strip()
    reqs = [str(item).strip() for item in list(requirements or []) if str(item).strip()]
    req_hash = requirements_hash_from_lines(reqs)
    record = _record_for(target_id)
    status = {
        "id": target_id,
        "kind": "core_feature",
        "label": str(label or target_id).strip() or target_id,
        "requirements": reqs,
        "requirements_hash": req_hash,
        "python": current_python(),
        "available": bool(available),
        "installable": bool(installable),
        "state_record": record,
    }
    if available:
        status.update({"status": "ok", "needs_install": False, "message": message or "Dependency is available."})
    else:
        status.update({"status": "missing", "needs_install": bool(installable), "message": message or "Dependency is missing."})
    return status


def addon_requirements_status(
    *,
    addon_id: str,
    label: str,
    requirements_path: str | Path,
) -> dict[str, Any]:
    target_id = str(addon_id or "").strip()
    target = Path(requirements_path)
    if not target.exists():
        return {
            "id": target_id,
            "kind": "addon",
            "label": str(label or target_id).strip() or target_id,
            "requirements_path": str(target),
            "status": "none",
            "needs_install": False,
            "installable": False,
            "message": "No addon requirements file.",
        }
    req_hash = requirements_file_hash(target)
    record = _record_for(target_id)
    ok = _record_matches(record, req_hash)
    return {
        "id": target_id,
        "kind": "addon",
        "label": str(label or target_id).strip() or target_id,
        "requirements_path": str(target),
        "requirements_hash": req_hash,
        "python": current_python(),
        "status": "ok" if ok else "needs_check",
        "needs_install": not ok,
        "installable": True,
        "message": "Addon requirements verified for this environment." if ok else "Addon requirements need user-approved install/check.",
        "state_record": record,
    }


def record_install_result(
    *,
    target_id: str,
    kind: str,
    requirements_hash: str,
    success: bool,
    requirements_path: str = "",
    error: str = "",
) -> None:
    payload = load_dependency_state()
    targets = payload.setdefault("targets", {})
    targets[str(target_id or "").strip()] = {
        "kind": str(kind or "").strip(),
        "requirements_hash": str(requirements_hash or ""),
        "requirements_path": str(requirements_path or ""),
        "python": current_python(),
        "status": "ok" if success else "failed",
        "last_error": "" if success else str(error or ""),
        "updated_at": _now_iso(),
    }
    save_dependency_state(payload)
