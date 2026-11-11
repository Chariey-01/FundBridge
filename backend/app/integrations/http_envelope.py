"""Response envelope helpers matching the shared contract (section 5).

Success: {"data": ..., "meta": {...}}
Error:   {"error": {"code": ..., "message": ..., "details": {...}}}

If the core backend ships its own helpers, these should delegate to them.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify
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


def validation_details(exc: ValidationError) -> dict[str, list[str]]:
    details: dict[str, list[str]] = {}
    for err in exc.errors(include_url=False, include_input=False):
        field = ".".join(str(part) for part in err.get("loc", ())) or "body"
        details.setdefault(field, []).append(err.get("msg", "Invalid value."))
    return details
