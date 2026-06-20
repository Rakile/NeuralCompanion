from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.lmstudio_provider.main import Addon


class _Settings:
    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url

    def get_provider_setting(self, provider_id: str, field_id: str) -> str:
        if provider_id == "lmstudio" and field_id == "base_url":
            return self.base_url
        return ""


def _addon_with_base_url(base_url: str) -> Addon:
    addon = Addon()
    addon._chat_service = _Settings(base_url)  # type: ignore[attr-defined]
    return addon


def test_lmstudio_base_url_defaults_to_openai_v1_path() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")

    assert addon._base_url() == "http://127.0.0.1:1234/v1"
    assert addon._openai_chat_url() == "http://127.0.0.1:1234/v1/chat/completions"
    assert addon._native_api_base_url() == "http://127.0.0.1:1234"


def test_lmstudio_worker_flattens_openai_compatible_extra_body() -> None:
    addon = _addon_with_base_url("http://127.0.0.1:1234")
    config = addon._worker_request_config(
        {
            "model": "local-model",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.8,
            "top_p": 0.88,
            "max_tokens": 18000,
        },
        {"top_k": 40, "repeat_penalty": 1.11, "min_p": 0.05},
        emit_chunks=True,
    )

    payload = config["payload"]

    assert config["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert payload["stream"] is True
    assert "extra_body" not in payload
    assert payload["top_k"] == 40
    assert payload["repeat_penalty"] == 1.11
    assert payload["min_p"] == 0.05


def main() -> int:
    test_lmstudio_base_url_defaults_to_openai_v1_path()
    test_lmstudio_worker_flattens_openai_compatible_extra_body()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
