"""
live_data/market_feed.py
------------------------
Real-time market data feed via WebSocket.

A SocketIO background task runs continuously (every 1 second), fetching
the latest bid/ask tick for each actively subscribed symbol and emitting
a 'market_data' event only to that symbol's room.

Subscriptions are managed by the market_events.py SocketIO event handlers.

PLATFORM CONSTRAINT: Actual MT5 tick data is Windows-only. On other
platforms the tick fetch returns None and no event is emitted.
"""

import time
from utils.logger import get_logger

logger = get_logger(__name__)

# Shared set of symbols that have active WebSocket subscribers.
# Access is not thread-safe for high-concurrency, but is adequate for
# a single-process eventlet server with cooperative multitasking.
active_symbols: set[str] = set()

# Flag to stop the background task
_running = False


def start_market_feed(socketio) -> None:
    """
    Start the market data background task using SocketIO's background task runner.

    This must be called after SocketIO is initialised (i.e. inside create_app).
    The task is idempotent — calling it twice has no effect.

    Args:
        socketio: The Flask-SocketIO instance.
    """
    global _running
    if _running:
        logger.debug("Market feed already running — skipping duplicate start.")
        return
    _running = True
    socketio.start_background_task(target=_market_feed_task, socketio=socketio)
    logger.info("Market feed background task started.")


def _market_feed_task(socketio) -> None:
    """
    Background task that ticks every 1 second.

    For each actively subscribed symbol, fetches the latest tick from MT5
    (or a mock stub when MT5 is unavailable) and emits 'market_data' to
    that symbol's SocketIO room.

    Args:
        socketio: The Flask-SocketIO instance.
    """
    from services.mt5_service import fetch_symbol_tick

    logger.info("Market feed task loop running.")
    while _running:
        symbols_snapshot = set(active_symbols)  # snapshot to avoid mutation during iteration

        for symbol in symbols_snapshot:
            try:
                tick_data = fetch_symbol_tick(symbol)
                if tick_data:
                    socketio.emit(
                        "market_data",
                        tick_data,
                        room=symbol,
                        namespace="/market",
                    )
            except Exception as exc:
                logger.warning("Error fetching tick for symbol '%s': %s", symbol, exc)

        socketio.sleep(1)  # eventlet-compatible sleep


def stop_market_feed() -> None:
    """Signal the market feed loop to stop on its next iteration."""
    global _running
    _running = False
    logger.info("Market feed background task stop requested.")
