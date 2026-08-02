from __future__ import annotations

import hashlib
import hmac
import io
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from addons.main_chat_remote.internet_settings import InternetRemoteSettings


PUBLIC_IP_ENDPOINTS = (
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
)
PUBLIC_IP_TIMEOUT_SECONDS = 3.0
PUBLIC_IP_RESPONSE_LIMIT = 64
CERTIFICATE_CHECK_INTERVAL_SECONDS = 12 * 60 * 60
CERTIFICATE_RENEWAL_WINDOW_SECONDS = 72 * 60 * 60
RETRY_DELAYS_SECONDS = (5 * 60, 15 * 60, 60 * 60, 3 * 60 * 60, 6 * 60 * 60)


@dataclass(frozen=True)
class LegoRelease:
    version: str
    asset_name: str
    url: str
    sha256: str


LEGO_RELEASE = LegoRelease(
    version="5.2.1",
    asset_name="lego_v5.2.1_windows_amd64.zip",
    url="https://github.com/go-acme/lego/releases/download/v5.2.1/lego_v5.2.1_windows_amd64.zip",
    sha256="3e87c133bcb0a6fd4236d11e0583967ecd2f04f454d2ff48286f1ab1183d699e",
)


@dataclass(frozen=True)
class HelperInstallResult:
    accepted: bool
    message: str
    executable: str = ""


@dataclass(frozen=True)
class PublicIpResult:
    accepted: bool
    message: str
    public_ip: str = ""
    observations: tuple[str, ...] = ()


@dataclass(frozen=True)
class DdnsResult:
    accepted: bool
    message: str
    hostname: str = ""
    addresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class CertificateOperationResult:
    accepted: bool
    message: str
    changed: bool = False
    expires_at: float = 0.0
    next_check_at: float = 0.0


class LegoInstaller:
    def __init__(
        self,
        *,
        runtime_dir: str | Path,
        downloader: Callable[[str], bytes] | None = None,
        runner: Callable[[list[str]], Any] | None = None,
        release: LegoRelease = LEGO_RELEASE,
    ):
        self.runtime_dir = Path(runtime_dir)
        self.release = release
        self._downloader = downloader or self._download
        self._runner = runner or self._run_version

    @property
    def tool_dir(self) -> Path:
        return self.runtime_dir / "tools" / "lego" / self.release.version

    @property
    def executable(self) -> Path:
        return self.tool_dir / ("lego.exe" if os.name == "nt" else "lego")

    def install(self) -> HelperInstallResult:
        if self.executable.is_file() and self._version_matches(self.executable):
            return HelperInstallResult(True, "Pinned ACME helper is already installed.", str(self.executable))
        try:
            archive_bytes = self._downloader(self.release.url)
        except Exception:
            return HelperInstallResult(False, "Could not download the pinned ACME helper.")
        digest = hashlib.sha256(archive_bytes).hexdigest()
        if not hmac.compare_digest(digest, self.release.sha256.lower()):
            return HelperInstallResult(False, "ACME helper checksum verification failed.")
        try:
            executable_bytes = self._validated_executable_bytes(archive_bytes)
        except (OSError, ValueError, zipfile.BadZipFile):
            return HelperInstallResult(False, "ACME helper archive validation failed.")

        parent = self.tool_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging_dir: Path | None = Path(
            tempfile.mkdtemp(prefix=f".{self.release.version}.", dir=parent)
        )
        backup_dir: Path | None = None
        try:
            staging_executable = staging_dir / self.executable.name
            staging_executable.write_bytes(executable_bytes)
            try:
                os.chmod(staging_executable, 0o700)
            except OSError:
                pass
            if not self._version_matches(staging_executable):
                return HelperInstallResult(False, "ACME helper version verification failed.")
            if self.tool_dir.exists():
                backup_dir = parent / f".{self.release.version}.backup-{os.getpid()}-{time.time_ns()}"
                os.replace(self.tool_dir, backup_dir)
            os.replace(staging_dir, self.tool_dir)
            staging_dir = None
            if backup_dir is not None:
                shutil.rmtree(backup_dir, ignore_errors=True)
                backup_dir = None
            return HelperInstallResult(True, "Pinned ACME helper installed.", str(self.executable))
        except OSError:
            if backup_dir is not None and backup_dir.exists() and not self.tool_dir.exists():
                os.replace(backup_dir, self.tool_dir)
                backup_dir = None
            return HelperInstallResult(False, "Could not activate the pinned ACME helper.")
        finally:
            if staging_dir is not None and staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            if backup_dir is not None and backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)

    def _validated_executable_bytes(self, archive_bytes: bytes) -> bytes:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            candidates = []
            for member in archive.infolist():
                path = PurePosixPath(member.filename.replace("\\", "/"))
                if member.is_dir() or path.name.lower() != "lego.exe":
                    continue
                if path.is_absolute() or ".." in path.parts or member.file_size > 64 * 1024 * 1024:
                    raise ValueError("Unsafe archive member.")
                candidates.append(member)
            if len(candidates) != 1:
                raise ValueError("Expected exactly one lego executable.")
            return archive.read(candidates[0])

    def _version_matches(self, executable: Path) -> bool:
        try:
            completed = self._runner([str(executable), "--version"])
            output = f"{getattr(completed, 'stdout', '')}\n{getattr(completed, 'stderr', '')}".strip()
            return int(getattr(completed, "returncode", 1)) == 0 and output.startswith(
                f"lego version {self.release.version}"
            )
        except Exception:
            return False

    @staticmethod
    def _download(url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "NeuralCompanion-ACME-Installer/1"})
        with urllib.request.urlopen(request, timeout=30.0) as response:
            payload = response.read(64 * 1024 * 1024 + 1)
        if len(payload) > 64 * 1024 * 1024:
            raise ValueError("ACME helper archive is too large.")
        return payload

    @staticmethod
    def _run_version(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )


class CertificateManager:
    def __init__(
        self,
        settings: InternetRemoteSettings,
        *,
        runtime_dir: str | Path,
        installer: LegoInstaller | None = None,
        ip_fetcher: Callable[[str, float, int], bytes] | None = None,
        resolver: Callable[[str], Iterable[str]] | None = None,
        runner: Callable[[list[str]], Any] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.settings = settings.normalized()
        self.runtime_dir = Path(runtime_dir)
        self.installer = installer or LegoInstaller(runtime_dir=self.runtime_dir)
        self._ip_fetcher = ip_fetcher or self._fetch_public_ip
        self._resolver = resolver or self._resolve_addresses
        self._runner = runner or self._run_lego
        self._clock = clock
        self.acme_data_dir = self.runtime_dir / "acme"
        self.active_dir = self.runtime_dir / "active"
        self.status_file = self.runtime_dir / "certificate-status.json"

    @property
    def certificate_file(self) -> Path:
        return self.active_dir / "fullchain.pem"

    @property
    def private_key_file(self) -> Path:
        return self.active_dir / "private-key.pem"

    def detect_public_ip(self, *, explicit: bool = False) -> PublicIpResult:
        if not self.settings.enabled and not explicit:
            return PublicIpResult(False, "Internet Remote is disabled.")
        observations: list[str] = []
        for endpoint in PUBLIC_IP_ENDPOINTS:
            try:
                raw = self._ip_fetcher(endpoint, PUBLIC_IP_TIMEOUT_SECONDS, PUBLIC_IP_RESPONSE_LIMIT)
                if len(raw) > PUBLIC_IP_RESPONSE_LIMIT:
                    raise ValueError("response too large")
                value = raw.decode("ascii").strip()
                address = ipaddress.ip_address(value)
                observations.append(address.compressed if address.is_global else "")
            except Exception:
                observations.append("")
        if len(observations) != 2 or not observations[0] or observations[0] != observations[1]:
            return PublicIpResult(False, "Public IP sources did not agree.", observations=tuple(observations))
        return PublicIpResult(True, "Public IP confirmed by two HTTPS sources.", observations[0], tuple(observations))

    def resolve_ddns(self) -> DdnsResult:
        hostname = self.settings.ddns_hostname
        if not hostname:
            return DdnsResult(False, "A Dynamic DNS hostname is required.")
        try:
            addresses = tuple(sorted({ipaddress.ip_address(item).compressed for item in self._resolver(hostname)}))
        except Exception:
            return DdnsResult(False, "Dynamic DNS lookup failed.", hostname)
        accepted = bool(self.settings.public_ip and self.settings.public_ip in addresses)
        message = "Dynamic DNS resolves to the configured public IP." if accepted else "Dynamic DNS does not resolve to the configured public IP."
        return DdnsResult(accepted, message, hostname, addresses)

    def issue_command(self, *, staging: bool) -> list[str]:
        settings = self.settings
        acme_data_dir = self.runtime_dir / ("acme-staging" if staging else "acme")
        certificates_dir = acme_data_dir / "certificates"
        action = "renew" if any(certificates_dir.glob("*.crt")) and any(certificates_dir.glob("*.key")) else "run"
        return [
            str(self.installer.executable),
            f"--email={settings.account_email}",
            "--accept-tos",
            f"--path={acme_data_dir}",
            f"--server={'letsencrypt-staging' if staging else 'letsencrypt'}",
            "--profile=shortlived",
            "--key-type=ec256",
            "--domains",
            settings.ddns_hostname,
            "--domains",
            settings.public_ip,
            action,
            f"--http.port=:{settings.acme_port}",
            "--http",
        ]

    def issue(self, *, staging: bool = False) -> CertificateOperationResult:
        validation_error = self._settings_error()
        if validation_error:
            return CertificateOperationResult(False, validation_error)
        if not self.installer.executable.is_file():
            return CertificateOperationResult(False, "The pinned ACME helper is not installed.")
        acme_data_dir = self.runtime_dir / ("acme-staging" if staging else "acme")
        acme_data_dir.mkdir(parents=True, exist_ok=True)
        try:
            completed = self._runner(self.issue_command(staging=staging))
        except Exception:
            return CertificateOperationResult(False, "Certificate operation could not start.")
        if int(getattr(completed, "returncode", 1)) != 0:
            return CertificateOperationResult(False, "Certificate authority operation failed.")
        try:
            destination_dir = self.runtime_dir / "staging-active" if staging else self.active_dir
            expires_at = self._activate_lego_certificate(acme_data_dir, destination_dir)
        except (OSError, ValueError, ssl.SSLError):
            return CertificateOperationResult(False, "Issued certificate validation failed.")
        next_check = self._clock() + CERTIFICATE_CHECK_INTERVAL_SECONDS
        if not staging:
            self._write_status({"next_check_at": next_check, "failure_count": 0, "expires_at": expires_at})
        message = "Staging certificate test passed." if staging else "Certificate is active."
        return CertificateOperationResult(True, message, not staging, expires_at, next_check)

    def renew_if_due(self) -> CertificateOperationResult:
        now = self._clock()
        status = self._read_status()
        next_check = float(status.get("next_check_at", 0.0))
        if next_check > now:
            return CertificateOperationResult(True, "Certificate check is not due.", False, float(status.get("expires_at", 0.0)), next_check)
        result = self.issue(staging=False)
        if result.accepted:
            return result
        failures = int(status.get("failure_count", 0)) + 1
        delay = RETRY_DELAYS_SECONDS[min(failures - 1, len(RETRY_DELAYS_SECONDS) - 1)]
        retry_at = now + delay
        self._write_status({"next_check_at": retry_at, "failure_count": failures, "expires_at": float(status.get("expires_at", 0.0))})
        return CertificateOperationResult(False, result.message, False, float(status.get("expires_at", 0.0)), retry_at)

    def status_snapshot(self) -> dict[str, Any]:
        status = self._read_status()
        return {
            "helper_installed": self.installer.executable.is_file(),
            "certificate_exists": self.certificate_file.is_file(),
            "private_key_exists": self.private_key_file.is_file(),
            "certificate_file": str(self.certificate_file),
            "private_key_file": str(self.private_key_file),
            "expires_at": float(status.get("expires_at", 0.0)),
            "next_check_at": float(status.get("next_check_at", 0.0)),
            "failure_count": int(status.get("failure_count", 0)),
        }

    def _settings_error(self) -> str:
        if not self.settings.enabled:
            return "Internet Remote is disabled."
        if not self.settings.terms_accepted or not self.settings.account_email:
            return "ACME terms and an account email are required."
        if not self.settings.ddns_hostname or not self.settings.public_ip:
            return "Both a Dynamic DNS hostname and public IP are required."
        return ""

    def _activate_lego_certificate(self, acme_data_dir: Path, destination_dir: Path) -> float:
        certificates_dir = (acme_data_dir / "certificates").resolve()
        candidates: list[tuple[Path, Path]] = []
        if not certificates_dir.is_dir():
            raise ValueError("Certificate metadata directory is missing.")
        for metadata_path in certificates_dir.glob("*.json"):
            if metadata_path.stat().st_size > 1024 * 1024:
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            domain = metadata.get("domain") if isinstance(metadata, dict) else None
            if isinstance(domain, dict):
                names = {str(domain.get("main") or ""), *(str(item) for item in domain.get("sans", ()))}
            else:
                names = {str(domain or "")}
            if self.settings.ddns_hostname not in names and self.settings.public_ip not in names:
                continue
            certificate_path = metadata_path.with_suffix(".crt").resolve()
            key_path = metadata_path.with_suffix(".key").resolve()
            if certificates_dir not in certificate_path.parents or certificates_dir not in key_path.parents:
                continue
            if certificate_path.is_file() and key_path.is_file():
                candidates.append((certificate_path, key_path))
        if len(candidates) != 1:
            raise ValueError("Could not identify one certificate from lego metadata.")
        certificate_bytes = candidates[0][0].read_bytes()
        key_bytes = candidates[0][1].read_bytes()
        expires_at = self._validate_pem_pair(certificate_bytes, key_bytes)
        destination_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(destination_dir / "fullchain.pem", certificate_bytes, 0o600)
        self._atomic_write(destination_dir / "private-key.pem", key_bytes, 0o600)
        return expires_at

    def _validate_pem_pair(self, certificate_bytes: bytes, key_bytes: bytes) -> float:
        if b"-----BEGIN CERTIFICATE-----" not in certificate_bytes or b"PRIVATE KEY-----" not in key_bytes:
            raise ValueError("Certificate files are not PEM encoded.")
        with tempfile.TemporaryDirectory(prefix="nc-certificate-validate-") as temp_dir:
            certificate_path = Path(temp_dir) / "certificate.pem"
            key_path = Path(temp_dir) / "private-key.pem"
            certificate_path.write_bytes(certificate_bytes)
            key_path.write_bytes(key_bytes)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(certificate_path), str(key_path))
            decoded = ssl._ssl._test_decode_cert(str(certificate_path))
        sans = {(str(kind), str(value)) for kind, value in decoded.get("subjectAltName", ())}
        hostname_present = ("DNS", self.settings.ddns_hostname) in sans
        ip_present = any(
            kind in {"IP Address", "IP"}
            and ipaddress.ip_address(value).compressed == self.settings.public_ip
            for kind, value in sans
        )
        if not hostname_present or not ip_present:
            raise ValueError("Certificate SANs do not match the configured identifiers.")
        expires_at = ssl.cert_time_to_seconds(str(decoded.get("notAfter") or ""))
        if expires_at <= self._clock():
            raise ValueError("Certificate has expired.")
        return float(expires_at)

    @staticmethod
    def _atomic_write(path: Path, payload: bytes, mode: int) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, mode)
            except OSError:
                pass
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _read_status(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.status_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_status(self, payload: dict[str, Any]) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(
            self.status_file,
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            0o600,
        )

    @staticmethod
    def _fetch_public_ip(url: str, timeout: float, limit: int) -> bytes:
        request = urllib.request.Request(url, headers={"Accept": "text/plain"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(limit + 1)

    @staticmethod
    def _resolve_addresses(hostname: str) -> tuple[str, ...]:
        return tuple(info[4][0] for info in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM))

    @staticmethod
    def _run_lego(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
