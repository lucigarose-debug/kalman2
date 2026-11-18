"""Fábrica de la aplicación Flask."""
from __future__ import annotations

import logging
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge


def create_app() -> Flask:
    app = Flask(__name__)
    max_mb = float(os.environ.get("MAX_UPLOAD_MB", "20"))
    app.config.update(
        MAX_CONTENT_LENGTH=int(max_mb * 1024 * 1024),
        MAX_UPLOAD_MB=max_mb,
        MAX_POINTS=int(os.environ.get("MAX_POINTS", "200000")),
        GOOGLE_MAPS_API_KEY=os.environ.get("GOOGLE_MAPS_API_KEY", "").strip(),
        GOOGLE_MAPS_MAP_ID=os.environ.get("GOOGLE_MAPS_MAP_ID", "DEMO_MAP_ID").strip(),
        JSON_SORT_KEYS=False,
    )
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

    from .routes import bp
    app.register_blueprint(bp)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_e):
        return jsonify(error=f"Archivo demasiado grande (máximo {max_mb:g} MB)."), 413

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        return jsonify(error=e.description), e.code

    @app.errorhandler(Exception)
    def unhandled(e: Exception):
        app.logger.exception("Error no controlado")
        return jsonify(error="Error interno del servidor."), 500

    return app
