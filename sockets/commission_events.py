"""
sockets/commission_events.py
-----------------------------
WebSocket event emission helpers for commission updates.

When a new commission is created (by commission_service.calculate_for_trade),
``emit_commission_created()`` is called to notify all connected clients
in real-time.

Clients can listen on the default namespace for 'commission_created' events.

Example client usage (JavaScript):
    const socket = io('/');
    socket.on('commission_created', (data) => {
        console.log('New commission:', data);
    });
"""

from extensions import socketio
from utils.logger import get_logger

logger = get_logger(__name__)


def emit_commission_created(commission) -> None:
    """
    Emit a 'commission_created' WebSocket event to all connected clients.

    Broadcasts to the default namespace (all connected clients).
    Clients subscribed to commission events will receive:

        {
            "commission_id":     int,
            "trade_id":          int,
            "amount":            str,   # Decimal as string e.g. "10.00"
            "broker_account_id": int,
            "status":            str    # "pending" | "paid"
        }

    Args:
        commission: A Commission model instance with a valid id.
    """
    payload = {
        "commission_id": commission.id,
        "trade_id": commission.trade_id,
        "amount": str(commission.amount),
        "broker_account_id": commission.broker_account_id,
        "status": commission.status.value if commission.status else "pending",
    }
    socketio.emit("commission_created", payload, namespace="/")
    logger.debug(
        "Emitted commission_created: commission_id=%d trade_id=%d amount=%s",
        commission.id,
        commission.trade_id,
        payload["amount"],
    )
