import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest
from app import create_app
from app.extensions import db

@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "JWT_SECRET_KEY": "test-secret"})
    with app.app_context():
        db.create_all(); yield app; db.session.remove(); db.drop_all()

@pytest.fixture
def client(app): return app.test_client()
