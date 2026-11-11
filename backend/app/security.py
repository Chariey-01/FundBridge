from datetime import datetime, timedelta, timezone
from functools import wraps
import jwt
from flask import current_app, g, request
from .errors import error
from .models import User
from .extensions import db


def issue_token(user):
    return jwt.encode({"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(hours=12)},
                      current_app.config["JWT_SECRET_KEY"], algorithm="HS256")


def require_auth(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "): error("AUTHENTICATION_REQUIRED", "Authentication is required.", 401)
        try:
            payload = jwt.decode(header[7:], current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])
        except jwt.PyJWTError:
            error("INVALID_TOKEN", "The access token is invalid or expired.", 401)
        g.user = db.session.get(User, payload["sub"])
        if not g.user or g.user.status != "active": error("ACCOUNT_UNAVAILABLE", "This account is unavailable.", 403)
        return fn(*args, **kwargs)
    return wrapped


def roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if g.user.role not in allowed: error("FORBIDDEN", "You are not authorized for this action.", 403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator
