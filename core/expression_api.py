"""Small local HTTP API for expression and MuseTalk preview state."""

import logging


def _load_flask_runtime():
    try:
        from flask import Flask, jsonify
        from flask_cors import CORS
    except Exception:
        return None, None, None
    return Flask, jsonify, CORS


def create_expression_api(expression_state_module, *, musetalk_state_module=None, preview_state_getter=None):
    Flask, jsonify, CORS = _load_flask_runtime()
    if Flask is None:
        return None
    if musetalk_state_module is None:
        # Backward-compatible path for older callers that passed one combined
        # module carrying both expression and MuseTalk state.
        musetalk_state_module = expression_state_module

    app = Flask(__name__)
    if callable(CORS):
        CORS(app)

    @app.route("/get-expression")
    def get_expression():
        return jsonify(getattr(expression_state_module, "current_expression_data", {}))

    @app.route("/get-musetalk-preview")
    def get_musetalk_preview():
        if callable(preview_state_getter):
            try:
                return jsonify(dict(preview_state_getter() or {}))
            except Exception:
                pass
        return jsonify(getattr(musetalk_state_module, "current_musetalk_frame_data", {}))

    return app


def start_expression_api(expression_state_module, *, musetalk_state_module=None, preview_state_getter=None, port=5005):
    app = create_expression_api(
        expression_state_module,
        musetalk_state_module=musetalk_state_module,
        preview_state_getter=preview_state_getter,
    )
    if app is None:
        print("[API] Flask is unavailable in this environment; expression API server not started.")
        return
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(port=int(port), debug=False, use_reloader=False)
