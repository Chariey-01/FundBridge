from flask import jsonify
from werkzeug.exceptions import HTTPException


class APIError(Exception):
    def __init__(self, code, message, status=400, details=None):
        self.code, self.message, self.status, self.details = code, message, status, details or {}


def error(code, message, status=400, details=None):
    raise APIError(code, message, status, details)


def register_error_handlers(app):
    @app.errorhandler(APIError)
    def api_error(exc):
        return jsonify(error={"code": exc.code, "message": exc.message, "details": exc.details}), exc.status

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error={"code": exc.name.upper().replace(" ", "_"), "message": exc.description, "details": {}}), exc.code

    @app.errorhandler(Exception)
    def unexpected(exc):
        app.logger.exception("Unhandled request error")
        return jsonify(error={"code": "INTERNAL_ERROR", "message": "An unexpected error occurred.", "details": {}}), 500
