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
    def auth_error(code, message): return jsonify(error={"code":code,"message":message,"details":{}}),401
    jwt.unauthorized_loader(lambda _: auth_error("AUTH_REQUIRED","Authentication is required."))
    jwt.invalid_token_loader(lambda _: auth_error("INVALID_TOKEN","Authentication is invalid."))
    jwt.expired_token_loader(lambda *_: auth_error("TOKEN_EXPIRED","Authentication has expired."))
    CORS(app, origins=[app.config["FRONTEND_ORIGIN"]] if app.config.get("FRONTEND_ORIGIN") else [], supports_credentials=False)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from app.api.v1.routes import api; app.register_blueprint(api, url_prefix="/api/v1")
    # AI + SMS/USSD integration (Claude scope): /api/v1/ai/*, /api/v1/messaging/*, /api/v1/integrations/status
    from app.integrations.bootstrap import init_integrations; init_integrations(app)
    @app.get("/health")
    def health(): return jsonify(data={"status": "ok"}, meta={})
    @app.errorhandler(ValueError)
    def value_error(err): return jsonify(error={"code": str(err), "message": "The request could not be completed.", "details": {}}), 400
    @app.errorhandler(PermissionError)
    def permission_error(err):
        code=str(err); status=401 if code == "INVALID_CREDENTIALS" else 403
        return jsonify(error={"code": code, "message": "Authentication failed." if status == 401 else "You are not authorized to perform this action.", "details": {}}), status
    @app.errorhandler(404)
    def not_found(_): return jsonify(error={"code":"NOT_FOUND","message":"Resource not found.","details":{}}),404
    return app
