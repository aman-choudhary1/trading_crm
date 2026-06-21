"""
services/mt5_service.py
-----------------------
MetaTrader 5 integration service.

PLATFORM CONSTRAINT
-------------------
The ``MetaTrader5`` Python package (``import MetaTrader5 as mt5``) is
**Windows-only**. It communicates with a locally-installed MT5 terminal
via shared memory / named pipes and will NOT work on Linux or macOS.

To run this project on Linux/macOS:
  - Use a Windows VM or Docker with Wine.
  - Mock all MT5 calls in tests (see tests/).
  - Set TESTING=true to skip real MT5 calls.

MT5 SESSION MODEL
-----------------
MT5 only supports **one active session per process**. Never hold a global
persistent mt5 handle across multiple accounts. Always use the
``mt5_session()`` context manager which calls ``mt5.shutdown()`` in
the finally block, guaranteeing the session is released even on errors.
"""

import time
import contextlib
from datetime import datetime, timezone
from typing import Generator

from utils.exceptions import MT5ConnectionError
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Retry configuration ───────────────────────────────────────────────────────
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 1.0  # doubles on each retry: 1s, 2s, 4s

# Lazy import so the module doesn't crash on Linux during unit-test collection
try:
    import MetaTrader5 as _mt5_module  # type: ignore[import]
    _MT5_AVAILABLE = True
except ImportError:
    _mt5_module = None
    _MT5_AVAILABLE = False
    logger.warning(
        "MetaTrader5 package is not installed or not available on this platform. "
        "All MT5 operations will raise MT5ConnectionError. "
        "See README for Windows-only platform constraint."
    )


def _require_mt5():
    """
    Return the mt5 module or raise MT5ConnectionError if unavailable.

    Raises:
        MT5ConnectionError: If the MetaTrader5 package is not installed.
    """
    if not _MT5_AVAILABLE or _mt5_module is None:
        raise MT5ConnectionError(
            "MetaTrader5 package is not available. "
            "This feature requires Windows with MT5 terminal installed."
        )
    return _mt5_module


def _retry(fn, *args, description: str = "MT5 operation", **kwargs):
    """
    Call ``fn(*args, **kwargs)`` with exponential-backoff retry.

    Args:
        fn:          Callable to retry.
        *args:       Positional arguments forwarded to fn.
        description: Human-readable label for log messages.
        **kwargs:    Keyword arguments forwarded to fn.

    Returns:
        The return value of a successful fn call.

    Raises:
        MT5ConnectionError: After all retries are exhausted.
    """
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except MT5ConnectionError as exc:
            last_error = exc
            if attempt < _MAX_RETRIES:
                wait = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                    description,
                    attempt,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "%s failed after %d attempts: %s", description, _MAX_RETRIES, exc
                )
    raise MT5ConnectionError(
        f"{description} failed after {_MAX_RETRIES} attempts: {last_error}"
    )


@contextlib.contextmanager
def mt5_session(
    login: int,
    password: str,
    server: str,
) -> Generator:
    """
    Context manager that opens an MT5 session and ensures it is always closed.

    Usage:
        with mt5_session(login, password, server) as mt5:
            positions = mt5.positions_get()

    Args:
        login:    MT5 account login number (integer).
        password: Plain-text MT5 account password.
        server:   MT5 broker server name (e.g. 'MetaQuotes-Demo').

    Yields:
        The ``MetaTrader5`` module with an active authenticated session.

    Raises:
        MT5ConnectionError: If initialisation or login fails.
    """
    mt5 = _require_mt5()

    # Initialise the MT5 terminal connection
    if not mt5.initialize():
        err = mt5.last_error()
        raise MT5ConnectionError(
            f"mt5.initialize() failed — last_error={err}"
        )

    try:
        # Authenticate with the broker server
        authorized = mt5.login(login, password=password, server=server)
        if not authorized:
            err = mt5.last_error()
            raise MT5ConnectionError(
                f"mt5.login() failed for login={login} server={server!r} — "
                f"last_error={err}"
            )
        logger.debug("MT5 session opened for login=%d server=%s", login, server)
        yield mt5
    finally:
        mt5.shutdown()
        logger.debug("MT5 session closed for login=%d", login)


def fetch_trade_history(
    login: int,
    password: str,
    server: str,
    from_date: datetime,
    to_date: datetime,
) -> list[dict]:
    """
    Retrieve closed deal history from MT5 for a date range.

    Uses ``mt5.history_deals_get(from_date, to_date)`` to fetch all
    closed deals, then converts each TradeDeal named-tuple to a plain dict.

    Args:
        login:     MT5 account login.
        password:  Plain-text MT5 password.
        server:    MT5 broker server name.
        from_date: Start of the date range (UTC).
        to_date:   End of the date range (UTC).

    Returns:
        List of deal dicts with keys matching the TradeDeal fields:
        ticket, order, time, time_msc, type, entry, magic, position_id,
        reason, volume, price, commission, swap, profit, fee, symbol,
        comment, external_id.

    Raises:
        MT5ConnectionError: If the MT5 connection or query fails.
    """
    def _fetch():
        with mt5_session(login, password, server) as mt5:
            deals = mt5.history_deals_get(from_date, to_date)
            if deals is None:
                err = mt5.last_error()
                raise MT5ConnectionError(
                    f"history_deals_get() returned None — last_error={err}"
                )
            return [deal._asdict() for deal in deals]

    return _retry(_fetch, description=f"fetch_trade_history(login={login})")


def fetch_open_positions(
    login: int,
    password: str,
    server: str,
) -> list[dict]:
    """
    Retrieve all currently open positions for an MT5 account.

    Uses ``mt5.positions_get()`` to fetch live open positions.

    Args:
        login:    MT5 account login.
        password: Plain-text MT5 password.
        server:   MT5 broker server name.

    Returns:
        List of position dicts with keys matching the TradePosition fields:
        ticket, time, time_msc, time_update, time_update_msc, type, magic,
        identifier, reason, volume, price_open, sl, tp, price_current,
        swap, profit, symbol, comment, external_id.

    Raises:
        MT5ConnectionError: If the MT5 connection or query fails.
    """
    def _fetch():
        with mt5_session(login, password, server) as mt5:
            positions = mt5.positions_get()
            if positions is None:
                err = mt5.last_error()
                raise MT5ConnectionError(
                    f"positions_get() returned None — last_error={err}"
                )
            return [pos._asdict() for pos in positions]

    return _retry(_fetch, description=f"fetch_open_positions(login={login})")


def fetch_symbol_tick(symbol: str) -> dict | None:
    """
    Get the latest bid/ask tick for a symbol without a full session.

    NOTE: This function assumes MT5 is already initialised by the
    market feed background task. It is NOT wrapped in mt5_session()
    because the market feed holds a single long-running session.

    Args:
        symbol: MT5 symbol name (e.g. 'EURUSD').

    Returns:
        Dict with keys {symbol, bid, ask, time} or None if unavailable.
    """
    if not _MT5_AVAILABLE:
        return None
    mt5 = _mt5_module
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return {
        "symbol": symbol,
        "bid": tick.bid,
        "ask": tick.ask,
        "time": tick.time,
    }
