import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///fundbridge.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN")
    PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID")
    PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET")
    PAYPAL_BASE_URL = os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
    PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID")
    PAYOUT_PROVIDER = os.environ.get("PAYOUT_PROVIDER", "simulator")
    DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"

    @classmethod
    def validate(cls):
        if not cls.SECRET_KEY or not cls.JWT_SECRET_KEY:
            # Development/testing may set explicit overrides; production must not start insecurely.
            if os.environ.get("FLASK_ENV") == "production":
                raise RuntimeError("SECRET_KEY and JWT_SECRET_KEY are required in production")
