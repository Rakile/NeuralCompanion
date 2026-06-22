import subprocess

from musetalk_bridge import MuseTalkBridge, _format_image_read_error_message, _parse_torch_cuda_compatibility_output


def test_torch_compatibility_parser_ignores_trailing_ansi_reset():
    output = (
        '{"ok": true, "cuda_available": true, "torch": "2.0.1+cu118", '
        '"torch_cuda": "11.8", "device_name": "NVIDIA GeForce RTX 4090"}\n'
        "\x1b[0m\n"
    )

    payload = _parse_torch_cuda_compatibility_output(output)

    assert payload["ok"] is True
    assert payload["cuda_available"] is True
    assert payload["device_name"] == "NVIDIA GeForce RTX 4090"


def test_torch_compatibility_parser_uses_last_json_payload():
    output = (
        "warning: noisy runtime banner\n"
        '{"ok": false, "error": "old"}\n'
        '\x1b[0m{"ok": true, "cuda_available": false}\n'
    )

    payload = _parse_torch_cuda_compatibility_output(output)

    assert payload == {"ok": True, "cuda_available": False}


def test_image_read_error_message_includes_path_and_context():
    message = _format_image_read_error_message(
        {
            "worker_info": "image_read_error",
            "context": "render_audio.mask",
            "path": r"Q:\NC\MuseTalk\runtime\bad.png",
            "exists": True,
            "size_bytes": 12,
            "chunk_id": "bsData_test",
        }
    )

    assert "[MuseTalkImage]" in message
    assert "render_audio.mask" in message
    assert "bad.png" in message
    assert "size=12" in message
    assert "chunk=bsData_test" in message


def test_torch_compatibility_timeout_warns_without_blocking_startup():
    bridge = MuseTalkBridge(root_dir="MuseTalk")
    original_run = subprocess.run
    messages = []

    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["python", "-c", "import torch"], timeout=30)

    try:
        subprocess.run = fake_run
        bridge._validate_torch_cuda_compatibility(logger=messages.append)
    finally:
        subprocess.run = original_run

    assert bridge._torch_compat_checked is True
    assert any("timed out" in message.lower() for message in messages)


if __name__ == "__main__":
    test_torch_compatibility_parser_ignores_trailing_ansi_reset()
    test_torch_compatibility_parser_uses_last_json_payload()
    test_image_read_error_message_includes_path_and_context()
    test_torch_compatibility_timeout_warns_without_blocking_startup()
    print("smoke_musetalk_bridge: ok")
