"""Relay-only HTTP and single-use token rotation. No NC-content endpoints."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Any

from .protocol import validate_http

API = "https://nc-relay.online"
SIGNAL = "wss://signal.nc-relay.online/v1/signaling"
_REQUESTS = {
    "/v1/auth/register": "RegisterRequestSchema",
    "/v1/auth/login": "LoginRequestSchema",
    "/v1/auth/mfa/enroll": "MfaEnrollRequestSchema",
    "/v1/auth/mfa/confirm": "MfaConfirmRequestSchema",
    "/v1/auth/mfa/verify": "MfaVerifyRequestSchema",
    "/v1/auth/refresh": "RefreshRequestSchema",
    "/v1/auth/logout": "LogoutRequestSchema",
    "/v1/auth/verify-email": "VerifyEmailRequestSchema",
    "/v1/auth/forgot-password": "ForgotPasswordRequestSchema",
    "/v1/auth/reset-password": "ResetPasswordRequestSchema",
    "/v1/desktops/register": "DesktopRegisterRequestSchema",
    "/v1/desktops/replace": "DesktopReplaceRequestSchema",
}
_OTHER = {
    "/v1/account",
    "/v1/desktops/current",
    "/v1/ice-servers",
    "/v1/auth/resend-verification",
    "/health/live",
    "/health/ready",
    "/v1/chess/mcp",
}


class RelayError(RuntimeError):
    def __init__(self, code: str, status: int = 0, retry_after: float = 0):
        self.code, self.status, self.retry_after = code, status, retry_after
        super().__init__(code)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def _request(path: str, body=None, token=None, method=None) -> dict[str, Any]:
    if path not in _REQUESTS and path not in _OTHER:
        raise RelayError("FORBIDDEN")
    if (
        path not in _REQUESTS
        and body is not None
        and not (path == "/v1/auth/resend-verification" and body == {})
        and path != "/v1/chess/mcp"
    ):
        raise RelayError("VALIDATION_FAILED")
    if path in _REQUESTS:
        body = validate_http(_REQUESTS[path], body)
    if path == "/v1/chess/mcp":
        from .chess_rpc import validate_chess_rpc
        body = validate_chess_rpc(body)
    encoded = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        API + path,
        data=encoded,
        headers=headers,
        method=method or ("POST" if body is not None else "GET"),
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(
            request, timeout=20
        ) as response:
            raw = response.read(131073)
            if len(raw) > 131072:
                raise RelayError("PAYLOAD_TOO_LARGE")
            result = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            code = validate_http("ErrorResponseSchema", json.loads(exc.read(65536)))[
                "error"
            ]["code"]
        except Exception:
            code = "INVALID_RESPONSE"
        try:
            delay = min(3600, max(0, float(exc.headers.get("Retry-After", "0"))))
        except ValueError:
            delay = 60
        raise RelayError(code, exc.code, delay) from None
    except (OSError, ValueError):
        raise RelayError("NETWORK_ERROR") from None
    if not isinstance(result, dict):
        raise RelayError("INVALID_RESPONSE")
    if path == "/v1/auth/login":
        return validate_http("LoginResponseSchema", result)
    if path == "/v1/auth/mfa/enroll":
        return validate_http("MfaEnrollmentResponseSchema", result)
    if path == "/v1/auth/mfa/confirm":
        return validate_http("MfaConfirmResponseSchema", result)
    if path in {
        "/v1/auth/login",
        "/v1/auth/mfa/verify",
        "/v1/auth/refresh",
        "/v1/desktops/register",
        "/v1/desktops/replace",
    }:
        validated = validate_http("AuthResponseSchema", result)
        if "desktop" in result:
            validated["desktop"] = validate_http(
                "DesktopRegistrationSchema", result["desktop"]
            )
        validated["resumed"] = bool(result.get("resumed", False))
        return validated
    if path == "/v1/ice-servers":
        return validate_http("IceServersResponseSchema", result)
    if "account" in result:
        result["account"] = validate_http("AccountSchema", result["account"])
    if "desktop" in result:
        result["desktop"] = validate_http(
            "DesktopRegistrationSchema", result["desktop"]
        )
    return result


async def http_request(path: str, body=None, token=None, method=None) -> dict[str, Any]:
    return await asyncio.to_thread(_request, path, body, token, method)


class RelayAuth:
    def __init__(self, store, *, role="desktop", request=http_request):
        self.store, self.role, self.request = store, role, request
        self.token = ""
        self.expires = 0.0
        self.account: dict[str, Any] = {}
        self.lock = asyncio.Lock()
        self.retry_at = 0.0
        self._clear_mfa()

    def _clear_mfa(self) -> None:
        self.mfa_status = ""
        self._pending_token = ""
        self._pending_expires = 0.0
        self.enrollment_secret = ""
        self.enrollment_uri = ""
        self.recovery_codes: list[str] = []
        self._enrolled_result: dict[str, Any] | None = None

    @property
    def mfa_pending(self) -> bool:
        if self.mfa_status == "recovery_codes":
            if time.monotonic() >= self._pending_expires:
                self._enrolled_result = None
            # Saving one-time codes has no deadline; expired session authority does.
            return True
        if self.mfa_status and time.monotonic() >= self._pending_expires:
            self._clear_mfa()
        return bool(self.mfa_status)

    def _require_mfa(self, expected: str) -> str:
        if not self.mfa_pending or self.mfa_status != expected:
            raise RelayError("MFA_INVALID", 401)
        return self._pending_token

    def _save(self, payload):
        self.store.set(payload["refreshToken"])
        self.token = payload["accessToken"]
        self.expires = time.monotonic() + payload["expiresIn"]
        self.account = payload["account"]

    def clear(self):
        self._clear_mfa()
        self.token = ""
        self.expires = 0
        self.account = {}
        self.store.delete()

    async def access(self) -> str:
        async with self.lock:
            if self.mfa_pending:
                raise RelayError("MFA_REQUIRED", 401)
            if self.token and self.expires - time.monotonic() > 180:
                return self.token
            if time.monotonic() < self.retry_at:
                if self.token and self.expires > time.monotonic():
                    return self.token
                raise RelayError("RATE_LIMITED", 429, self.retry_at - time.monotonic())
            refresh = self.store.get()
            if not refresh:
                if self.token and self.expires > time.monotonic():
                    return self.token
                self.clear()
                raise RelayError("LOGIN_REQUIRED", 401)
            # A lost response must not leave a consumed token available for replay.
            self.store.delete()
            try:
                self._save(
                    await self.request("/v1/auth/refresh", {"refreshToken": refresh})
                )
            except Exception as exc:
                temporary = isinstance(exc, (OSError, TimeoutError)) or (
                    isinstance(exc, RelayError)
                    and (exc.code == "NETWORK_ERROR" or exc.status == 429 or exc.status >= 500)
                )
                if isinstance(exc, RelayError):
                    self.retry_at = time.monotonic() + exc.retry_after
                # Retain only existing access authority, never the consumed
                # refresh token or a new expiry inferred from a failed request.
                if temporary and self.token and self.expires > time.monotonic():
                    return self.token
                self.clear()
                if isinstance(exc, RelayError):
                    raise
                raise RelayError("LOGIN_REQUIRED", 401) from None
            return self.token

    async def login(
        self, identifier: str, password: str, device_label="NeuralCompanion"
    ):
        async with self.lock:
            if time.monotonic() < self.retry_at:
                raise RelayError("RATE_LIMITED", 429, self.retry_at - time.monotonic())
            self.clear()
            try:
                result = await self.request(
                        "/v1/auth/login",
                        {
                            "identifier": identifier,
                            "password": password,
                            "role": self.role,
                            "deviceLabel": device_label,
                        },
                )
                status = result.get("status", "")
                if status in {"mfa_required", "mfa_enrollment_required"}:
                    key = "challengeToken" if status == "mfa_required" else "enrollmentToken"
                    pending = result.get(key)
                    ttl = result.get("expiresIn")
                    if not isinstance(pending, str) or not pending or not isinstance(ttl, (int, float)) or not 0 < ttl <= 600:
                        raise RelayError("INVALID_RESPONSE")
                    self.mfa_status = status
                    self._pending_token = pending
                    self._pending_expires = time.monotonic() + ttl
                    return status
                self._save(result)
                return ""
            except RelayError as exc:
                self.retry_at = time.monotonic() + exc.retry_after
                raise

    async def begin_enrollment(self) -> None:
        async with self.lock:
            pending = self._require_mfa("mfa_enrollment_required")
            result = await self.request("/v1/auth/mfa/enroll", {"enrollmentToken": pending})
            self.enrollment_secret = result["secret"]
            self.enrollment_uri = result["otpauthUri"]

    async def confirm_enrollment(self, code: str) -> None:
        async with self.lock:
            pending = self._require_mfa("mfa_enrollment_required")
            result = await self.request("/v1/auth/mfa/confirm", {"enrollmentToken": pending, "code": code})
            codes = result.get("recoveryCodes")
            if not isinstance(codes, list) or not codes or not all(isinstance(code, str) for code in codes):
                raise RelayError("INVALID_RESPONSE")
            self._pending_token = ""
            self.enrollment_secret = ""
            self.enrollment_uri = ""
            self.recovery_codes = list(codes)
            self.mfa_status = "recovery_codes"
            self._pending_expires = time.monotonic() + result["expiresIn"]
            self._enrolled_result = {key: value for key, value in result.items() if key != "recoveryCodes"}

    def acknowledge_recovery(self) -> None:
        self._require_mfa("recovery_codes")
        result = self._enrolled_result
        if result is None:
            self._clear_mfa()
            raise RelayError("LOGIN_REQUIRED", 401)
        # Time spent saving codes must not extend the server-issued JWT lifetime.
        result = {**result, "expiresIn": max(0, self._pending_expires - time.monotonic())}
        self._save(result)
        self._clear_mfa()

    async def verify_mfa(self, *, code: str = "", recovery_code: str = "") -> None:
        async with self.lock:
            pending = self._require_mfa("mfa_required")
            if bool(code) == bool(recovery_code):
                raise RelayError("VALIDATION_FAILED")
            body = {"challengeToken": pending, **({"code": code} if code else {"recoveryCode": recovery_code})}
            result = await self.request("/v1/auth/mfa/verify", body)
            self._save(result)
            self._clear_mfa()

    async def authorized(self, path, body=None, method=None):
        token = await self.access()
        try:
            return await self.request(path, body, token, method)
        except RelayError as exc:
            if exc.code == "TOKEN_REUSED":
                async with self.lock:
                    self.clear()
            if exc.status == 401 and exc.code in {"TOKEN_EXPIRED", "INVALID_TOKEN"}:
                async with self.lock:
                    if self.token == token:
                        self.expires = 0
                token = await self.access()
                try:
                    return await self.request(path, body, token, method)
                except RelayError as retry_error:
                    if retry_error.code == "TOKEN_REUSED":
                        async with self.lock:
                            self.clear()
                    raise
            raise

    async def register_desktop(self, body, replace=False):
        # Serialize replacement token issuance with refresh and logout.
        await self.access()
        async with self.lock:
            result = await self.request(
                "/v1/desktops/replace" if replace else "/v1/desktops/register",
                body,
                self.token,
            )
            try:
                self._save(result)
            except Exception:
                self.clear()
                raise
            return result

    async def logout(self):
        async with self.lock:
            token = self.store.get()
            self.clear()
            if token:
                await self.request(
                    "/v1/auth/logout", {"refreshToken": token, "allSessions": False}
                )
