"""Flask app exposing ShopStream DWH metrics. Deployed to Lambda via Zappa."""
from __future__ import annotations

import logging
import os
import traceback

from flask import Flask, jsonify

from api.endpoints import anomalies, pages, sessions

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(pages.bp)
    app.register_blueprint(sessions.bp)
    app.register_blueprint(anomalies.bp)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "shopstream-api"})

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @app.errorhandler(404)
    def not_found(_err):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        logger.error("unhandled: %s\n%s", err, traceback.format_exc())
        return jsonify({"error": "internal server error"}), 500

    return app


app = create_app()
