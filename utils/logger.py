"""
utils/logger.py
---------------
Centralised logging configuration for the Mini Trading CRM.

Features:
  - Console handler (stdout) with coloured level names in development.
  - Rotating file handler writing to logs/trading_crm.log.
  - Consistent format: timestamp | level | module:lineno | message.

Usage:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Hello from %s", __name__)
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "trading_crm.log"
MAX_BYTES = 10 * 1024 * 1024   # 10 MB per file
BACKUP_COUNT = 5               # Keep last 5 rotated files


def _configure_root_logger() -> None:
    """
    Set up handlers on the root logger.

    Called once at module import time. Subsequent ``get_logger()`` calls
    just return child loggers that propagate to the root.
    """
    root = logging.getLogger()

    # Avoid adding duplicate handlers when this module is re-imported
    if root.handlers:
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root.setLevel(level)

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)

    # ── Console handler ───────────────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # ── Rotating file handler ─────────────────────────────────────────────────
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        # If we cannot write logs to disk, at least warn on the console
        root.warning("Could not create rotating file handler: %s", exc)


# Configure once at import time
_configure_root_logger()


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger that inherits the root configuration.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    return logging.getLogger(name)
