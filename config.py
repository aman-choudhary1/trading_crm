"""
config.py
---------
Flask application configuration classes.

Reads settings from environment variables (via .env loaded by python-dotenv).
Three configs are provided:
  - DevelopmentConfig  (default, MySQL, debug on)
  - ProductionConfig   (MySQL, debug off, strict settings)
  - TestingConfig      (SQLite in-memory, no real MT5 calls)
"""

import os
from decimal import Decimal
from dotenv import load_dotenv

# Load .env from the project root before reading env vars
load_dotenv()


class BaseConfig:
    """Shared settings across all environments."""

    # ── Flask ────────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    JSON_SORT_KEYS: bool = False

    # ── SQLAlchemy ───────────────────────────────────────────────────────────
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # ── API Auth ─────────────────────────────────────────────────────────────
    API_KEY: str = os.environ.get("API_KEY", "dev-api-key")

    # ── Fernet Encryption ────────────────────────────────────────────────────
    FERNET_KEY: str = os.environ.get("FERNET_KEY", "")

    # ── Commission ───────────────────────────────────────────────────────────
    COMMISSION_RATE_PER_LOT: Decimal = Decimal(
        os.environ.get("COMMISSION_RATE_PER_LOT", "5.00")
    )

    # ── Scheduler ────────────────────────────────────────────────────────────
    SYNC_INTERVAL_SECONDS: int = int(os.environ.get("SYNC_INTERVAL_SECONDS", "60"))

    # ── Copier ───────────────────────────────────────────────────────────────
    COPIER_POLL_SECONDS: int = int(os.environ.get("COPIER_POLL_SECONDS", "2"))

    # ── MetaTrader5 ──────────────────────────────────────────────────────────
    MT5_TIMEOUT_MS: int = int(os.environ.get("MT5_TIMEOUT_MS", "10000"))

    # ── SocketIO ─────────────────────────────────────────────────────────────
    SOCKETIO_ASYNC_MODE: str = "eventlet"

    # ── Testing ──────────────────────────────────────────────────────────────
    TESTING: bool = False


class DevelopmentConfig(BaseConfig):
    """Development configuration — MySQL, debug on."""

    DEBUG: bool = True
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "SQLALCHEMY_DATABASE_URI",
        "mysql+pymysql://root:password@localhost:3306/trading_crm",
    )
    SQLALCHEMY_ECHO: bool = False  # Set True to log all SQL


class ProductionConfig(BaseConfig):
    """Production configuration — MySQL, debug off."""

    DEBUG: bool = False
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "SQLALCHEMY_DATABASE_URI",
        "mysql+pymysql://root:password@localhost:3306/trading_crm_prod",
    )


class TestingConfig(BaseConfig):
    """
    Testing configuration — SQLite in-memory for fast isolated tests.

    MySQL is the real driver for dev/prod; SQLite is only used here to
    avoid needing a live database server during CI.
    """

    TESTING: bool = True
    DEBUG: bool = True
    # SQLite in-memory — fast, no teardown needed
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    # Disable CSRF / other protections for easier test requests
    WTF_CSRF_ENABLED: bool = False
    # Use a deterministic API key in tests
    API_KEY: str = "test-api-key"
    # Use a fixed Fernet key for tests (valid Fernet key)
    FERNET_KEY: str = "q-moE78rUoDTaVc6KJDq8GJ_ZS_OlqyiRHjqV4Wm8Yw="


# ── Config registry ──────────────────────────────────────────────────────────
config_map: dict[str, type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(name: str | None = None) -> type[BaseConfig]:
    """
    Return the config class for the given environment name.

    Falls back to FLASK_ENV env var, then 'development'.
    """
    env = name or os.environ.get("FLASK_ENV", "development")
    return config_map.get(env, DevelopmentConfig)
