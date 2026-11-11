from functools import wraps
from flask import g
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from app.models.core import Role, User

def current_user():
    verify_jwt_in_request(); user = User.query.get(get_jwt_identity())
    if not user or user.status != "active": raise PermissionError("ACCOUNT_INACTIVE")
    return user

def roles_allowed(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            g.current_user = current_user()
            if g.current_user.role not in roles: raise PermissionError("FORBIDDEN")
            return fn(*args, **kwargs)
        return wrapped
    return deco
