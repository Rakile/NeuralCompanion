# Chatterbox Multilingual TTS

Separate local TTS backend for ResembleAI Chatterbox Multilingual.

This addon intentionally stays separate from the regular Chatterbox Turbo
backend so English/Turbo behavior remains unchanged.

Use the addon panel's **Install / Update Runtime** button if the local
`chatterbox` package does not include `chatterbox.mtl_tts`. The button installs
the official GitHub source package without changing the rest of the Python
environment dependencies.
