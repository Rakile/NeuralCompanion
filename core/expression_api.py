"""Small local HTTP API for expression and MuseTalk preview state."""

import logging


def _load_flask_runtime():
    try:
        from flask import Flask, jsonify
        from flask_cors import CORS
    except Exception:
        return None, None, None
    return Flask, jsonify, CORS


def create_expression_api(shared_state_module):
    Flask, jsonify, CORS = _load_flask_runtime()
    if Flask is None:
        return None

    app = Flask(__name__)
    if callable(CORS):
        CORS(app)

    @app.route("/get-expression")
    def get_expression():
        return jsonify(getattr(shared_state_module, "current_expression_data", {}))

    @app.route("/get-musetalk-preview")
    def get_musetalk_preview():
        return jsonify(getattr(shared_state_module, "current_musetalk_frame_data", {}))

    return app


def start_expression_api(shared_state_module, *, port=5005):
    app = create_expression_api(shared_state_module)
    if app is None:
        print("[API] Flask is unavailable in this environment; expression API server not started.")
        return
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(port=int(port), debug=False, use_reloader=False)
