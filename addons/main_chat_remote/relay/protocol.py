"""Use the actual upstream Zod validators, including transforms/refinements.

Called only on relay workers, never from Qt slots. Payloads use local pipes;
they are not process arguments or diagnostic messages.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class ProtocolError(ValueError):
    pass


def _validate(request: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    script = (
        Path(__file__).resolve().parents[3]
        / "packages/nc-relay-protocol/dist/validator.cjs"
    )
    if not node or not script.is_file():
        raise ProtocolError("NC Relay requires Node.js and the built protocol package.")
    try:
        result = subprocess.run(
            [node, str(script)],
            input=json.dumps(request),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        reply = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise ProtocolError("Relay protocol validator unavailable.") from None
    if result.returncode or not reply.get("ok"):
        raise ProtocolError("Relay protocol validation failed.")
    return reply["value"]


def validate_http(schema: str, payload: object) -> dict[str, Any]:
    return _validate({"op": "http", "schema": schema, "payload": payload})


def validate_signal(payload: dict[str, Any] | str) -> dict[str, Any]:
    return _validate({"op": "signal", "payload": payload})


def protocol_constants() -> dict[str, Any]:
    return _validate({"op": "constants"})
