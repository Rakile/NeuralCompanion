from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def main():
    builder = _read("ui/runtime/backend_system_shaping_builders.py")
    frontend = _read("ui/runtime/real_ui_surfaces.py")
    runtime = _read("ui/runtime/backend_chat_session_runtime.py")
    session = _read("ui/runtime/main_window_session.py")
    schema = _read("core/chat_runtime_session_schema.py")

    object_name = "long_term_memory_image_context_max_output_tokens_spin"
    setting_name = "long_term_memory_image_context_max_output_tokens"
    assert object_name in builder
    assert object_name in frontend
    assert "Image-context judge max output tokens (advanced)" in builder
    assert "Image-context judge max output tokens (advanced)" in frontend
    assert setting_name in runtime
    assert setting_name in session
    assert setting_name in schema
    print("smoke_long_term_memory_image_context_output_limit: ok")


if __name__ == "__main__":
    raise SystemExit(main())
