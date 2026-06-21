"""
sockets/market_events.py
------------------------
Flask-SocketIO event handlers for the /market namespace.

Events:
    subscribe_symbol   {symbol: str} → join room, add to active_symbols set
    unsubscribe_symbol {symbol: str} → leave room, remove from active_symbols

The client receives 'market_data' events streamed by the market feed background
task (live_data/market_feed.py) for each subscribed symbol.

Example client usage (JavaScript):
    const socket = io('/market');
    socket.emit('subscribe_symbol', {symbol: 'EURUSD'});
    socket.on('market_data', (data) => console.log(data));
"""

from flask_socketio import join_room, leave_room
from extensions import socketio
from live_data.market_feed import active_symbols
from utils.logger import get_logger

logger = get_logger(__name__)


@socketio.on("subscribe_symbol", namespace="/market")
def on_subscribe_symbol(data: dict) -> None:
    """
    Handle a client subscribing to live market data for a symbol.

    Args:
        data: Dict containing 'symbol' key (e.g. {'symbol': 'EURUSD'}).
    """
    symbol = (data or {}).get("symbol", "").upper().strip()
    if not symbol:
        logger.warning("subscribe_symbol received with no symbol — ignored.")
        return

    join_room(symbol)
    active_symbols.add(symbol)
    logger.info("Client subscribed to symbol '%s'. Active symbols: %s", symbol, active_symbols)


@socketio.on("unsubscribe_symbol", namespace="/market")
def on_unsubscribe_symbol(data: dict) -> None:
    """
    Handle a client unsubscribing from live market data for a symbol.

    Args:
        data: Dict containing 'symbol' key (e.g. {'symbol': 'EURUSD'}).
    """
    symbol = (data or {}).get("symbol", "").upper().strip()
    if not symbol:
        return

    leave_room(symbol)
    # Remove from active set if no more subscribers
    # Note: a more robust implementation would count per-symbol subscribers
    active_symbols.discard(symbol)
    logger.info("Client unsubscribed from symbol '%s'. Active symbols: %s", symbol, active_symbols)


@socketio.on("connect", namespace="/market")
def on_connect() -> None:
    """Log new client connection to the /market namespace."""
    logger.debug("Client connected to /market namespace.")


@socketio.on("disconnect", namespace="/market")
def on_disconnect() -> None:
    """Log client disconnection from the /market namespace."""
    logger.debug("Client disconnected from /market namespace.")
