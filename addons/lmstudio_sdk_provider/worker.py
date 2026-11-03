"""One SDK operation per child; stdout is reserved for NC's JSON protocol."""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    # Avoid the Windows console code page corrupting non-ASCII model text.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    wire = sys.stdout
    def send(frame):
        wire.write(json.dumps(frame, ensure_ascii=False, allow_nan=False) + '\n')
        wire.flush()
    sdk = None
    try:
        request = json.loads(sys.stdin.buffer.read().decode('utf-8'))
        if not isinstance(request, dict):
            raise ValueError('SDK helper request must be an object.')
        with contextlib.redirect_stdout(sys.stderr):
            sdk = None
            if request.get('action') not in {'models','lifecycle'}:
                import lmstudio as sdk
                # Applies in this child only. The caller owns deadlines/cancellation.
                sdk.set_sync_api_timeout(None)
            from addons.lmstudio_sdk_provider.backend import handle_request
            value = handle_request(request, lambda chunk: send({'chunk': chunk}), sdk=sdk)
        send({'ok': True, 'value': value})
        return 0
    except Exception as exc:
        from core.chat_providers import _classify_frozen_provider_failure, chat_provider_error_message
        category, status = _classify_frozen_provider_failure(exc)
        if (sdk is not None and isinstance(exc, getattr(sdk, 'LMStudioClientError', ()))
                and str(exc).startswith('LM Studio is not reachable at ')):
            # SDK 1.5 collapses connection failures into this local client error
            # without a cause. Retain its category, never its endpoint/text.
            category, status = 'connection', None
        send({'diagnostic': {'phase': 'provider_error', 'category': category, 'http_status': status}})
        send({'ok': False, 'error': chat_provider_error_message('lmstudio_sdk', category, status)})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
