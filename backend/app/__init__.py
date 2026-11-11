from flask import Flask
from .config import Config
from .extensions import db, migrate
from .api import api


def create_app(config_override=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_override:
        app.config.update(config_override)
    db.init_app(app)
    migrate.init_app(app, db)
    app.register_blueprint(api)
    from .errors import register_error_handlers
    register_error_handlers(app)
    return app
