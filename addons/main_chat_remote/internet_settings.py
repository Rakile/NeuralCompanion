from __future__ import annotations

import ipaddress
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _normalize_hostname(value: object) -> str:
    candidate = str(value or "").strip().lower().rstrip(".")
    if not candidate or len(candidate) > 253:
        return ""
    if any(character in candidate for character in (":", "/", "\\", "@")):
        return ""
    try:
        candidate = candidate.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    labels = candidate.split(".")
    if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        return ""
    return candidate


def _normalize_public_ip(value: object) -> str:
    candidate = str(value or "").strip()
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return ""
    return address.compressed if address.is_global else ""


def _normalize_port(value: object, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65_535 else default


def _origin(host: str, port: int) -> str:
    if not host:
        return ""
    display_host = f"[{host}]" if ":" in host else host
    suffix = "" if port == 443 else f":{port}"
    return f"https://{display_host}{suffix}"


@dataclass(frozen=True)
class InternetRemoteSettings:
    enabled: bool = False
    ddns_hostname: str = ""
    public_ip: str = ""
    external_port: int = 443
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8788
    acme_port: int = 8780
    account_email: str = ""
    terms_accepted: bool = False
    confirm_ip_changes: bool = True

    def normalized(self) -> "InternetRemoteSettings":
        gateway_host = str(self.gateway_host or "0.0.0.0").strip()
        try:
            gateway_host = ipaddress.ip_address(gateway_host).compressed
        except ValueError:
            gateway_host = "0.0.0.0"
        return InternetRemoteSettings(
            enabled=bool(self.enabled),
            ddns_hostname=_normalize_hostname(self.ddns_hostname),
            public_ip=_normalize_public_ip(self.public_ip),
            external_port=_normalize_port(self.external_port, 443),
            gateway_host=gateway_host,
            gateway_port=_normalize_port(self.gateway_port, 8788),
            acme_port=_normalize_port(self.acme_port, 8780),
            account_email=str(self.account_email or "").strip(),
            terms_accepted=bool(self.terms_accepted),
            confirm_ip_changes=bool(self.confirm_ip_changes),
        )

    @property
    def primary_origin(self) -> str:
        normalized = self.normalized()
        return _origin(normalized.ddns_hostname, normalized.external_port)

    @property
    def fallback_origin(self) -> str:
        normalized = self.normalized()
        return _origin(normalized.public_ip, normalized.external_port)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "InternetRemoteSettings":
        source = payload if isinstance(payload, Mapping) else {}
        field_names = cls.__dataclass_fields__
        return cls(**{name: source[name] for name in field_names if name in source}).normalized()


class InternetSettingsStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> InternetRemoteSettings:
        if not self.path.exists():
            return InternetRemoteSettings()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return InternetRemoteSettings()
        settings_payload = payload.get("settings", payload) if isinstance(payload, dict) else {}
        return InternetRemoteSettings.from_payload(settings_payload)

    def save(self, settings: InternetRemoteSettings) -> InternetRemoteSettings:
        normalized = settings.normalized()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "settings": normalized.to_dict()}
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return normalized
