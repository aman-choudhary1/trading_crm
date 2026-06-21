"""
app.py
------
Flask application factory.

Usage:
    from app import create_app
    app = create_app("development")

The factory pattern allows multiple app instances (e.g., for testing) and
avoids circular imports by deferring extension initialisation.
"""

import os
from flask import Flask, request, g
from config import get_config
from extensions import db, migrate, socketio
from utils.error_handlers import register_error_handlers
from utils.logger import get_logger

logger = get_logger(__name__)


def create_app(config_name: str | None = None) -> Flask:
    """
    Create and configure a Flask application instance.

    Args:
        config_name: One of 'development', 'production', 'testing'.
                     Defaults to the FLASK_ENV env var or 'development'.

    Returns:
        A fully configured Flask app with:
          - SQLAlchemy + Migrate + SocketIO initialised
          - All blueprints registered under /api
          - Error handlers registered
          - API key middleware applied
          - Market feed background task started (non-testing)
          - APScheduler started (non-testing)
    """
    app = Flask(__name__)

    # ── Load configuration ────────────────────────────────────────────────────
    config_class = get_config(config_name)
    app.config.from_object(config_class)
    logger.info("Starting app with config: %s", config_class.__name__)

    # ── Initialise extensions ─────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(
        app,
        async_mode=app.config.get("SOCKETIO_ASYNC_MODE", "eventlet"),
        cors_allowed_origins="*",
        logger=False,
        engineio_logger=False,
    )

    # ── Register blueprints ───────────────────────────────────────────────────
    _register_blueprints(app)

    # ── Register error handlers ───────────────────────────────────────────────
    register_error_handlers(app)

    # ── API key middleware ────────────────────────────────────────────────────
    _register_api_key_middleware(app)

    # ── Import models so Alembic can discover them ────────────────────────────
    with app.app_context():
        import models  # noqa: F401 — side-effect import for metadata registration

    # ── Start background tasks (skip in testing) ──────────────────────────────
    if not app.config.get("TESTING", False):
        _start_background_tasks(app)

    return app


def _register_blueprints(app: Flask) -> None:
    """Register all route blueprints under the /api prefix."""
    from routes.user_routes import users_bp
    from routes.broker_routes import broker_bp
    from routes.trade_routes import trade_bp
    from routes.commission_routes import commission_bp
    from routes.docs_routes import docs_bp

    app.register_blueprint(users_bp, url_prefix="/api")
    app.register_blueprint(broker_bp, url_prefix="/api")
    app.register_blueprint(trade_bp, url_prefix="/api")
    app.register_blueprint(commission_bp, url_prefix="/api")
    app.register_blueprint(docs_bp)

    # ── Register SocketIO event handlers ─────────────────────────────────────
    import sockets.market_events   # noqa: F401
    import sockets.commission_events  # noqa: F401

    logger.info("All blueprints and SocketIO events registered.")


def _register_api_key_middleware(app: Flask) -> None:
    """
    Add a before_request hook that validates the X-API-Key header on
    all /api routes.

    NOTE: This is a simple shared-secret approach suitable for development
          and internal tooling. Replace with proper JWT / OAuth2 in production.
    """
    expected_key = app.config.get("API_KEY", "")

    @app.before_request
    def check_api_key():
        """Reject /api requests that lack a valid X-API-Key header."""
        if not request.path.startswith("/api"):
            return  # Only protect /api routes

        provided = request.headers.get("X-API-Key", "")
        if not expected_key:
            # If no key is configured, skip the check (warn loudly)
            logger.warning(
                "API_KEY is not set — all /api requests are unauthenticated!"
            )
            return

        if provided != expected_key:
            from utils.response import error_response
            return error_response("Invalid or missing X-API-Key header", 401)


def _start_background_tasks(app: Flask) -> None:
    """
    Start the market feed WebSocket background loop and the APScheduler.

    The WERKZEUG_RUN_MAIN guard prevents the scheduler from starting twice
    when Flask's debug reloader forks a child process.
    """
    # Market feed — ticks every 1 second via SocketIO background task
    from live_data.market_feed import start_market_feed
    start_market_feed(socketio)
    logger.info("Market feed background task started.")

    # APScheduler — trade sync job
    werkzeug_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    in_debug = app.config.get("DEBUG", False)

    if not in_debug or werkzeug_reloader_child:
        from workers.scheduler import start_scheduler
        start_scheduler(app)
        logger.info("APScheduler started.")
    else:
        logger.info(
            "Skipping scheduler start in debug mode main process "
            "(will start in reloader child)."
        )
