from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))

from install_neural_companion import Installer  # noqa: E402


class AvatarPackDownloadProbe(Installer):
    def __init__(self, *, token: str = "", public_fails: bool = False) -> None:
        self.token = token
        self.public_fails = public_fails
        self.calls: list[tuple[str, str]] = []

    def github_token(self) -> str:
        return self.token

    def download_file(self, url: str, destination: Path, headers: dict[str, str] | None = None) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if headers:
            self.calls.append(("api_download", url))
            destination.write_bytes(b"api")
            return
        self.calls.append(("public_download", url))
        if self.public_fails:
            raise SystemExit("public download failed")
        destination.write_bytes(b"public")

    def download_github_release_asset(self, filename: str, destination: Path, token: str) -> None:
        self.calls.append(("api_lookup", filename))
        self.download_file(f"https://api.example.test/{filename}", destination, headers={"Authorization": f"Bearer {token}"})


def test_avatar_pack_download_uses_public_release_url_even_when_token_exists(tmp_path: Path) -> None:
    probe = AvatarPackDownloadProbe(token="stale-token")
    destination = tmp_path / "pack.zip"

    probe.download_avatar_pack_file("pack.zip", "https://public.example.test/pack.zip", destination)

    assert destination.read_bytes() == b"public"
    assert probe.calls == [("public_download", "https://public.example.test/pack.zip")]


def test_avatar_pack_download_can_fallback_to_authenticated_asset(tmp_path: Path) -> None:
    probe = AvatarPackDownloadProbe(token="valid-token", public_fails=True)
    destination = tmp_path / "pack.zip"

    probe.download_avatar_pack_file("pack.zip", "https://public.example.test/pack.zip", destination)

    assert destination.read_bytes() == b"api"
    assert probe.calls == [
        ("public_download", "https://public.example.test/pack.zip"),
        ("api_lookup", "pack.zip"),
        ("api_download", "https://api.example.test/pack.zip"),
    ]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory(prefix="nc_avatar_pack_download_smoke_") as tmp:
        root = Path(tmp)
        test_avatar_pack_download_uses_public_release_url_even_when_token_exists(root / "public")
        test_avatar_pack_download_can_fallback_to_authenticated_asset(root / "fallback")
    print("smoke_installer_avatar_pack_download: ok")
