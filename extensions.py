"""
extensions.py
-------------
Centralised extension instances to avoid circular imports.

Import these objects in other modules rather than creating new instances.
The actual initialisation (binding to the Flask app) happens inside
``create_app()`` in app.py.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO

# SQLAlchemy ORM instance
db: SQLAlchemy = SQLAlchemy()

# Flask-Migrate for Alembic-based schema migrations
migrate: Migrate = Migrate()

# Flask-SocketIO — eventlet async mode is set via config / create_app
socketio: SocketIO = SocketIO()
