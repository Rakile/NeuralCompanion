from musetalk_bridge import _parse_torch_cuda_compatibility_output


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


if __name__ == "__main__":
    test_torch_compatibility_parser_ignores_trailing_ansi_reset()
    test_torch_compatibility_parser_uses_last_json_payload()
    print("smoke_musetalk_bridge: ok")
