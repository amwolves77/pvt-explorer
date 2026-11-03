"""Browser-driven PVT explorer. Production WSGI entry point: app:app."""
import argparse
from functools import lru_cache
import os
from flask import Flask, Response, jsonify, render_template, request
from browser_inputs import InputError, calculate_explorer, parse_lab_data
from fit_engine import calibrate_curves

@lru_cache(maxsize=1)
def plotly_source():
    from plotly.offline import get_plotlyjs
    return get_plotlyjs()

def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    @app.get("/assets/plotly.min.js")
    def plotly_bundle():
        return Response(plotly_source(), mimetype="text/javascript")

    def json_payload():
        if not request.is_json:
            raise InputError("Send a JSON request containing browser inputs.")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise InputError("The request must contain a JSON object.")
        return payload

    @app.post("/api/lab/validate")
    def validate_lab():
        lab = parse_lab_data(json_payload().get("lab_text", ""))
        return jsonify(rows=len(lab), missing=sum(value is None for row in lab for value in row.values()))

    @app.post("/api/calculate")
    def calculate():
        payload = json_payload()
        enabled = payload.get("calibrate", False)
        if not isinstance(enabled, bool):
            raise InputError("Calibration must be enabled or disabled with a boolean value.")
        data = calculate_explorer(payload)
        data["calibration_enabled"] = enabled
        data["calibration"] = calibrate_curves(data["curves"], data["lab"]) if enabled else []
        return jsonify(data)

    @app.errorhandler(InputError)
    def invalid_input(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(413)
    def too_large(exc):
        return jsonify(error="The pasted table is too large. Keep the request under 2 MB and 20,000 lab rows."), 413

    @app.errorhandler(500)
    def internal_error(exc):
        return jsonify(error="Unable to calculate results. Please retry or contact the server administrator."), 500

    @app.after_request
    def response_headers(response):
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return app

app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the PVT Explorer development server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8050")))
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False)
