"""HTTP hardening for the whole API: request IDs, access logging, sign-in rate limits, error envelopes.

- Every response carries ``X-Request-ID`` (a sane incoming value is kept, otherwise one is generated)
  and one access-log line without query strings or bodies, so no search terms, emails or phone
  numbers reach the logs.
- ``POST /auth/login``: per-IP attempt limit, plus a per-account failed-attempt limit that only
  counts 401 responses and resets on success. ``POST /auth/register`` and ``POST /donations/orders``
  have per-IP limits. Limits are in-process (see ``SlidingWindowRateLimiter``); with several workers
  each keeps its own window, so a multi-instance deployment needs a shared store.
- Payment/payout provider HTTP failures become ``PROVIDER_REQUEST_REJECTED`` (502) or
  ``PROVIDER_UNAVAILABLE`` (503) envelopes instead of Flask's HTML 500. The database session is
  rolled back, so no partial donation or payout row is written by this request. The messages never
  claim "nothing was charged": a capture that timed out may still have succeeded at the provider,
  so clients must re-read the donation status.
- Any other unhandled exception becomes a logged ``INTERNAL_ERROR`` envelope with the request ID.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
import uuid
from collections import deque

import requests
from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

from app.extensions import db
from app.services.ai.rate_limit import SlidingWindowRateLimiter

from .http_envelope import error

log = logging.getLogger("fundbridge.http")
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")

LOGIN = "/api/v1/auth/login"
REGISTER = "/api/v1/auth/register"
DONATION_ORDER = "/api/v1/donations/orders"


class FailureWindow:
    """Counts failures per key in a sliding window; ``blocked`` peeks without recording."""

    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic, max_keys: int = 50_000):
        self.limit, self.window, self._clock, self._max_keys = limit, window_seconds, clock, max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float] | None:
        bucket = self._hits.get(key)
        while bucket and bucket[0] <= now - self.window:
            bucket.popleft()
        return bucket

    def retry_after(self, key: str) -> int:
        """Seconds until another attempt is allowed; 0 when not blocked."""
        now = self._clock()
        with self._lock:
            bucket = self._trim(key, now)
            if not bucket or len(bucket) < self.limit:
                return 0
            return max(1, math.ceil(bucket[0] + self.window - now))

    def record(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            if key not in self._hits and len(self._hits) >= self._max_keys:
                for stale in [k for k, b in self._hits.items() if not b or b[-1] <= now - self.window]:
                    del self._hits[stale]
            self._hits.setdefault(key, deque()).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


def _int(app: Flask, name: str, default: int) -> int:
    import os

    raw = app.config.get(name, os.environ.get(name))
    return int(raw) if raw not in (None, "") else default


def _rate_limited(retry_after: int):
    return error("RATE_LIMITED", "Too many attempts. Please wait and try again.", 429,
                 {"retry_after_seconds": retry_after}, headers={"Retry-After": str(retry_after)})


def _login_identity() -> str:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return ""
    value = body.get("email") or body.get("phone_number") or ""
    return value.strip().lower()[:255] if isinstance(value, str) else ""


def init_hardening(app: Flask) -> None:
    enabled = str(app.config.get("RATE_LIMITS_ENABLED", "true")).lower() != "false"
    login_ip = SlidingWindowRateLimiter(_int(app, "AUTH_LOGIN_LIMIT_PER_IP_PER_MINUTE", 30), 60)
    login_failures = FailureWindow(_int(app, "AUTH_LOGIN_FAILURES_PER_ACCOUNT", 5),
                                   _int(app, "AUTH_LOGIN_FAILURE_WINDOW_SECONDS", 900))
    register_ip = SlidingWindowRateLimiter(_int(app, "AUTH_REGISTER_LIMIT_PER_IP_PER_10_MINUTES", 20), 600)
    orders_ip = SlidingWindowRateLimiter(_int(app, "DONATION_ORDER_LIMIT_PER_IP_PER_MINUTE", 30), 60)
    app.extensions["fundbridge.login_failures"] = login_failures

    @app.before_request
    def _start():
        incoming = request.headers.get("X-Request-ID", "")
        g.request_id = incoming if _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        g.request_started = time.perf_counter()
        if not enabled or request.method != "POST":
            return None
        ip = request.remote_addr or "unknown"
        if request.path == LOGIN:
            decision = login_ip.hit(f"login-ip:{ip}")
            if not decision.allowed:
                return _rate_limited(decision.retry_after_seconds)
            g.login_identity = _login_identity()
            wait = login_failures.retry_after(g.login_identity) if g.login_identity else 0
            if wait:
                return _rate_limited(wait)
        elif request.path == REGISTER:
            decision = register_ip.hit(f"register-ip:{ip}")
            if not decision.allowed:
                return _rate_limited(decision.retry_after_seconds)
        elif request.path == DONATION_ORDER:
            decision = orders_ip.hit(f"orders-ip:{ip}")
            if not decision.allowed:
                return _rate_limited(decision.retry_after_seconds)
        return None

    @app.after_request
    def _finish(response):
        identity = g.pop("login_identity", None)
        if identity:
            if response.status_code == 401:
                login_failures.record(identity)
            elif response.status_code == 200:
                login_failures.clear(identity)
        request_id = getattr(g, "request_id", None) or uuid.uuid4().hex
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        started = getattr(g, "request_started", None)
        elapsed_ms = int((time.perf_counter() - started) * 1000) if started else -1
        log.info("request method=%s path=%s status=%s duration_ms=%s request_id=%s",
                 request.method, request.path, response.status_code, elapsed_ms, request_id)
        return response

    @app.errorhandler(requests.RequestException)
    def _provider_failure(exc: requests.RequestException):
        db.session.rollback()
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        log.warning("provider call failed type=%s provider_status=%s request_id=%s",
                    type(exc).__name__, status, getattr(g, "request_id", None))
        if isinstance(exc, requests.HTTPError) and status is not None and status < 500:
            details = {"provider_status": status}
            issue = _provider_issue(response)
            if issue:
                details["provider_issue"] = issue
            return error("PROVIDER_REQUEST_REJECTED",
                         "The payment provider did not accept this request. Check the donation status before retrying.",
                         502, details)
        return error("PROVIDER_UNAVAILABLE",
                     "The payment provider is not reachable right now. Check the donation status before retrying.", 503)

    @app.errorhandler(HTTPException)
    def _http_exception(exc: HTTPException):
        code = re.sub(r"[^A-Z]+", "_", (exc.name or "HTTP_ERROR").upper()).strip("_")
        return error(code, exc.description or exc.name, exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        db.session.rollback()
        request_id = getattr(g, "request_id", None)
        log.exception("unhandled error request_id=%s", request_id)
        return error("INTERNAL_ERROR", "Something went wrong. Quote the request ID if you contact support.", 500, {"request_id": request_id})


def _provider_issue(response) -> str | None:
    """PayPal-style ``details[0].issue`` (for example ORDER_NOT_APPROVED); a short code, never a payload."""
    try:
        body = response.json()
    except Exception:
        return None
    details = body.get("details") if isinstance(body, dict) else None
    issue = details[0].get("issue") if isinstance(details, list) and details and isinstance(details[0], dict) else None
    if not issue and isinstance(body, dict):
        issue = body.get("name") or body.get("error")
    return issue if isinstance(issue, str) and re.fullmatch(r"[A-Z0-9_]{2,64}", issue) else None
