"""Response envelope helpers matching the shared contract (section 5).

Success: {"data": ..., "meta": {...}}
Error:   {"error": {"code": ..., "message": ..., "details": {...}}}

If the core backend ships its own helpers, these should delegate to them.
"""

from __future__ import annotations

from typing import Any

from flask import current_app, jsonify
from pydantic import ValidationError


def ok(data: Any, meta: dict[str, Any] | None = None, status: int = 200):
    return jsonify({"data": data, "meta": meta or {}}), status


def error(code: str, message: str, status: int, details: dict[str, Any] | None = None, headers=None):
    body = {"error": {"code": code, "message": message, "details": details or {}}}
    response = jsonify(body)
    response.status_code = status
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


AUTH_FAILURE_EXTENSION = "fundbridge.auth_failure"


def unauthenticated():
    """Error response when a protected AI/messaging route has no usable caller.

    The host app may register a classifier under ``AUTH_FAILURE_EXTENSION`` returning
    ``(code, message, status)`` so these routes use the same codes as the core JWT
    loaders (AUTH_REQUIRED, INVALID_TOKEN, TOKEN_EXPIRED, ACCOUNT_INACTIVE). Without one,
    every failure is reported as AUTH_REQUIRED.
    """
    classify = current_app.extensions.get(AUTH_FAILURE_EXTENSION)
    code, message, status = classify() if classify else ("AUTH_REQUIRED", "Authentication is required.", 401)
    return error(code, message, status)


def validation_details(exc: ValidationError) -> dict[str, list[str]]:
    details: dict[str, list[str]] = {}
    for err in exc.errors(include_url=False, include_input=False):
        field = ".".join(str(part) for part in err.get("loc", ())) or "body"
        details.setdefault(field, []).append(err.get("msg", "Invalid value."))
    return details
