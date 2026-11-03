"""Production WSGI server; configure HOST and PORT via environment."""
import os
from waitress import serve
from app import app

if __name__ == "__main__":
    serve(app, host=os.environ.get("HOST", "0.0.0.0"),
          port=int(os.environ.get("PORT", "8050")), threads=4,
          max_request_body_size=app.config["MAX_CONTENT_LENGTH"])
