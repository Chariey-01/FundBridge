from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# Keeping attributes usable after a successful transaction avoids accidental
# refreshes outside request context; financial writes still use explicit commits.
db = SQLAlchemy(session_options={"expire_on_commit": False})
migrate = Migrate()
