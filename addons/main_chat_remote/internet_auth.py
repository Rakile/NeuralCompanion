from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator


def _token(length: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(length)).rstrip(b"=").decode("ascii")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_device_value(value: object, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > 128 or any(ord(character) < 32 for character in cleaned):
        raise ValueError(f"Invalid {label}.")
    return cleaned


def _clean_media_path(value: object) -> str:
    target = str(value or "").strip()
    parsed = urllib.parse.urlsplit(target)
    path = parsed.path
    if (
        not path.startswith("/api/")
        or "\\" in path
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or any(part == ".." for part in path.split("/"))
    ):
        raise ValueError("Invalid media path.")
    query = []
    for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in {"code", "token", "ticket", "secret", "signature", "sig"}:
            continue
        if len(key) > 80 or len(item) > 512:
            raise ValueError("Invalid media query.")
        query.append((key, item))
    return f"{path}?{urllib.parse.urlencode(query)}" if query else path


@dataclass(frozen=True)
class EnrollmentSecret:
    enrollment_id: str
    secret: str
    expires_at: float


@dataclass(frozen=True)
class PendingEnrollment:
    enrollment_id: str
    device_id: str
    device_name: str
    status: str
    expires_at: float


@dataclass(frozen=True)
class IssuedDeviceCredential:
    device_id: str
    token: str


@dataclass(frozen=True)
class InternetDevice:
    device_id: str
    device_name: str
    created_at: float
    last_seen_at: float
    revoked: bool


@dataclass(frozen=True)
class SignedMediaGrant:
    device_id: str
    path: str
    method: str
    expires_at: float
    nonce: str
    signature: str


class InternetCredentialStore:
    def __init__(
        self,
        path: str | Path,
        *,
        signing_key_path: str | Path,
        clock: Callable[[], float] = time.time,
    ):
        self.path = Path(path)
        self.signing_key_path = Path(signing_key_path)
        self.lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.signing_key_path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            self._ensure_signing_key()
            if not self.path.exists():
                self._save_unlocked(self._new_payload())
            else:
                self._load_unlocked()

    @property
    def gateway_id(self) -> str:
        with self._locked():
            return str(self._load_unlocked()["gateway_id"])

    def create_enrollment(self, *, ttl_seconds: float = 600.0) -> EnrollmentSecret:
        ttl = max(1.0, float(ttl_seconds))
        now = self._clock()
        enrollment_id = _token(18)
        secret = _token()
        expires_at = now + ttl
        with self._locked():
            payload = self._load_unlocked()
            self._prune_unlocked(payload, now)
            payload["enrollments"][enrollment_id] = {
                "secret_sha256": _digest(secret),
                "status": "created",
                "device_id": "",
                "device_name": "",
                "created_at": now,
                "expires_at": expires_at,
            }
            self._save_unlocked(payload)
        return EnrollmentSecret(enrollment_id, secret, expires_at)

    def submit_enrollment(
        self,
        enrollment_id: str,
        secret: str,
        *,
        device_id: object,
        device_name: object,
    ) -> PendingEnrollment:
        clean_id = _clean_device_value(device_id, "device id")
        clean_name = _clean_device_value(device_name, "device name")
        now = self._clock()
        with self._locked():
            payload = self._load_unlocked()
            enrollment = payload["enrollments"].get(str(enrollment_id))
            self._validate_enrollment(enrollment, secret, now)
            if enrollment["status"] not in {"created", "pending"}:
                raise ValueError("Enrollment cannot be submitted in its current state.")
            enrollment.update(
                status="pending",
                device_id=clean_id,
                device_name=clean_name,
            )
            self._save_unlocked(payload)
            return self._pending(str(enrollment_id), enrollment)

    def approve_enrollment(self, enrollment_id: str) -> bool:
        now = self._clock()
        with self._locked():
            payload = self._load_unlocked()
            enrollment = payload["enrollments"].get(str(enrollment_id))
            if (
                not isinstance(enrollment, dict)
                or float(enrollment.get("expires_at", 0.0)) <= now
                or enrollment.get("status") != "pending"
            ):
                return False
            enrollment["status"] = "approved"
            self._save_unlocked(payload)
            return True

    def get_enrollment(self, enrollment_id: str, secret: str) -> PendingEnrollment:
        now = self._clock()
        with self._locked():
            payload = self._load_unlocked()
            enrollment = payload["enrollments"].get(str(enrollment_id))
            self._validate_enrollment(enrollment, secret, now)
            return self._pending(str(enrollment_id), enrollment)

    def pending_enrollments(self) -> tuple[PendingEnrollment, ...]:
        now = self._clock()
        with self._locked():
            payload = self._load_unlocked()
            pending = tuple(
                self._pending(enrollment_id, enrollment)
                for enrollment_id, enrollment in payload["enrollments"].items()
                if enrollment.get("status") == "pending"
                and float(enrollment.get("expires_at", 0.0)) > now
            )
        return tuple(sorted(pending, key=lambda item: item.expires_at))

    def reject_enrollment(self, enrollment_id: str) -> bool:
        with self._locked():
            payload = self._load_unlocked()
            enrollment = payload["enrollments"].get(str(enrollment_id))
            if not isinstance(enrollment, dict):
                return False
            del payload["enrollments"][str(enrollment_id)]
            self._save_unlocked(payload)
            return True

    def complete_enrollment(self, enrollment_id: str, secret: str) -> IssuedDeviceCredential:
        now = self._clock()
        with self._locked():
            payload = self._load_unlocked()
            enrollment = payload["enrollments"].get(str(enrollment_id))
            self._validate_enrollment(enrollment, secret, now)
            if enrollment["status"] != "approved":
                raise ValueError("Enrollment has not been approved.")
            device_id = _clean_device_value(enrollment.get("device_id"), "device id")
            device_name = _clean_device_value(enrollment.get("device_name"), "device name")
            token = _token()
            payload["devices"][device_id] = {
                "device_id": device_id,
                "device_name": device_name,
                "token_sha256": _digest(token),
                "created_at": now,
                "last_seen_at": now,
                "revoked": False,
            }
            del payload["enrollments"][str(enrollment_id)]
            self._save_unlocked(payload)
            return IssuedDeviceCredential(device_id, token)

    def authenticate(self, token: str) -> InternetDevice | None:
        token_hash = _digest(str(token or ""))
        now = self._clock()
        with self._locked():
            payload = self._load_unlocked()
            for raw_device in payload["devices"].values():
                if raw_device.get("revoked"):
                    continue
                if hmac.compare_digest(str(raw_device.get("token_sha256", "")), token_hash):
                    if now - float(raw_device.get("last_seen_at", 0.0)) >= 30.0:
                        raw_device["last_seen_at"] = now
                        self._save_unlocked(payload)
                    return self._device(raw_device)
        return None

    def revoke_device(self, device_id: str) -> bool:
        with self._locked():
            payload = self._load_unlocked()
            raw_device = payload["devices"].get(str(device_id).strip())
            if not isinstance(raw_device, dict) or raw_device.get("revoked"):
                return False
            raw_device["revoked"] = True
            self._save_unlocked(payload)
            return True

    def devices(self) -> tuple[InternetDevice, ...]:
        with self._locked():
            payload = self._load_unlocked()
            devices = tuple(self._device(raw) for raw in payload["devices"].values())
        return tuple(sorted(devices, key=lambda item: (item.revoked, item.device_name.lower(), item.device_id)))

    def issue_ws_ticket(self, device_id: str, *, ttl_seconds: float = 30.0) -> str:
        now = self._clock()
        ticket = _token()
        with self._locked():
            payload = self._load_unlocked()
            raw_device = payload["devices"].get(str(device_id).strip())
            if not isinstance(raw_device, dict) or raw_device.get("revoked"):
                raise ValueError("Unknown or revoked device.")
            self._prune_unlocked(payload, now)
            payload["ws_tickets"][_digest(ticket)] = {
                "device_id": raw_device["device_id"],
                "expires_at": now + max(1.0, float(ttl_seconds)),
            }
            self._save_unlocked(payload)
        return ticket

    def consume_ws_ticket(self, ticket: str) -> InternetDevice | None:
        now = self._clock()
        with self._locked():
            payload = self._load_unlocked()
            raw_ticket = payload["ws_tickets"].pop(_digest(str(ticket or "")), None)
            self._save_unlocked(payload)
            if not isinstance(raw_ticket, dict) or float(raw_ticket.get("expires_at", 0.0)) <= now:
                return None
            raw_device = payload["devices"].get(str(raw_ticket.get("device_id", "")))
            if not isinstance(raw_device, dict) or raw_device.get("revoked"):
                return None
            return self._device(raw_device)

    def sign_media(
        self,
        device_id: str,
        path: object,
        method: str,
        *,
        ttl_seconds: float = 120.0,
    ) -> SignedMediaGrant:
        clean_path = _clean_media_path(path)
        clean_method = str(method or "GET").strip().upper()
        if clean_method != "GET":
            raise ValueError("Only GET media grants are supported.")
        now = self._clock()
        with self._locked():
            payload = self._load_unlocked()
            raw_device = payload["devices"].get(str(device_id).strip())
            if not isinstance(raw_device, dict) or raw_device.get("revoked"):
                raise ValueError("Unknown or revoked device.")
        expires_at = now + max(1.0, float(ttl_seconds))
        nonce = _token(12)
        signature = self._media_signature(
            str(raw_device["device_id"]), clean_path, clean_method, expires_at, nonce
        )
        return SignedMediaGrant(
            str(raw_device["device_id"]),
            clean_path,
            clean_method,
            expires_at,
            nonce,
            signature,
        )

    def verify_media(self, grant: SignedMediaGrant, method: str) -> InternetDevice | None:
        now = self._clock()
        clean_method = str(method or "").strip().upper()
        try:
            clean_path = _clean_media_path(grant.path)
        except ValueError:
            return None
        if clean_method != grant.method or grant.expires_at <= now:
            return None
        expected = self._media_signature(
            grant.device_id, clean_path, grant.method, grant.expires_at, grant.nonce
        )
        if not hmac.compare_digest(expected, grant.signature):
            return None
        with self._locked():
            raw_device = self._load_unlocked()["devices"].get(grant.device_id)
            if not isinstance(raw_device, dict) or raw_device.get("revoked"):
                return None
            return self._device(raw_device)

    def _media_signature(
        self,
        device_id: str,
        path: str,
        method: str,
        expires_at: float,
        nonce: str,
    ) -> str:
        canonical = "\n".join(
            (device_id, method, path, f"{float(expires_at):.6f}", nonce)
        ).encode("utf-8")
        signature = hmac.new(self.signing_key_path.read_bytes(), canonical, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")

    @staticmethod
    def _pending(enrollment_id: str, raw: dict[str, Any]) -> PendingEnrollment:
        return PendingEnrollment(
            enrollment_id=enrollment_id,
            device_id=str(raw.get("device_id", "")),
            device_name=str(raw.get("device_name", "")),
            status=str(raw.get("status", "")),
            expires_at=float(raw.get("expires_at", 0.0)),
        )

    @staticmethod
    def _device(raw: dict[str, Any]) -> InternetDevice:
        return InternetDevice(
            device_id=str(raw.get("device_id", "")),
            device_name=str(raw.get("device_name", "")),
            created_at=float(raw.get("created_at", 0.0)),
            last_seen_at=float(raw.get("last_seen_at", 0.0)),
            revoked=bool(raw.get("revoked", False)),
        )

    @staticmethod
    def _validate_enrollment(raw: object, secret: str, now: float) -> None:
        if not isinstance(raw, dict):
            raise ValueError("Unknown enrollment.")
        if float(raw.get("expires_at", 0.0)) <= now:
            raise ValueError("Enrollment expired.")
        if not hmac.compare_digest(str(raw.get("secret_sha256", "")), _digest(str(secret or ""))):
            raise ValueError("Invalid enrollment secret.")

    def _ensure_signing_key(self) -> None:
        if self.signing_key_path.exists():
            if len(self.signing_key_path.read_bytes()) < 32:
                raise ValueError("Internet Remote signing key is invalid.")
            return
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(self.signing_key_path, flags, 0o600)
        try:
            os.write(descriptor, secrets.token_bytes(32))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.chmod(self.signing_key_path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _new_payload() -> dict[str, Any]:
        return {
            "version": 1,
            "gateway_id": _token(18),
            "devices": {},
            "enrollments": {},
            "ws_tickets": {},
        }

    def _load_unlocked(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Internet Remote credential registry is unreadable.") from exc
        if not isinstance(payload, dict) or not payload.get("gateway_id"):
            raise ValueError("Internet Remote credential registry is invalid.")
        for key in ("devices", "enrollments", "ws_tickets"):
            if not isinstance(payload.get(key), dict):
                raise ValueError("Internet Remote credential registry is invalid.")
        return payload

    def _save_unlocked(self, payload: dict[str, Any]) -> None:
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
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _prune_unlocked(payload: dict[str, Any], now: float) -> None:
        payload["enrollments"] = {
            key: value
            for key, value in payload["enrollments"].items()
            if float(value.get("expires_at", 0.0)) > now
        }
        payload["ws_tickets"] = {
            key: value
            for key, value in payload["ws_tickets"].items()
            if float(value.get("expires_at", 0.0)) > now
        }

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
