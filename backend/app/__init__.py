import logging
from flask import Flask, jsonify
from flask_cors import CORS
from app.config import Config
from app.extensions import db, jwt, migrate

def create_app(config_override=None):
    app = Flask(__name__); app.config.from_object(Config)
    if config_override: app.config.update(config_override)
    if not app.config.get("TESTING"): Config.validate()
    db.init_app(app); migrate.init_app(app, db); jwt.init_app(app)
    CORS(app, origins=[app.config["FRONTEND_ORIGIN"]] if app.config.get("FRONTEND_ORIGIN") else [], supports_credentials=False)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from app.api.v1.routes import api; app.register_blueprint(api, url_prefix="/api/v1")
    @app.get("/health")
    def health(): return jsonify(data={"status": "ok"}, meta={})
    @app.errorhandler(ValueError)
    def value_error(err): return jsonify(error={"code": str(err), "message": "The request could not be completed.", "details": {}}), 400
    @app.errorhandler(PermissionError)
    def permission_error(err): return jsonify(error={"code": str(err), "message": "You are not authorized to perform this action.", "details": {}}), 403
    return app
