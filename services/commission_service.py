"""
services/commission_service.py
--------------------------------
Commission calculation engine.

Rules:
  - Rate: $5.00 per standard lot (configurable via COMMISSION_RATE_PER_LOT env var).
  - calculate_for_trade() is idempotent: calling it twice on the same trade
    returns the existing Commission without creating a duplicate.
  - After inserting a new Commission, a 'commission_created' WebSocket event
    is emitted so connected clients receive real-time updates.
"""

import os
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy import outerjoin

from extensions import db
from models.trade import Trade, TradeStatus
from models.commission import Commission, CommissionStatus
from utils.logger import get_logger

logger = get_logger(__name__)


def _get_rate() -> Decimal:
    """
    Return the configured commission rate per lot.

    Reads COMMISSION_RATE_PER_LOT from the environment (falls back to 5.00).
    Also checks the Flask app config if available.

    Returns:
        Commission rate as a Decimal.
    """
    # Try Flask app config first (populated from config.py)
    try:
        from flask import current_app
        rate = current_app.config.get("COMMISSION_RATE_PER_LOT")
        if rate is not None:
            return Decimal(str(rate))
    except RuntimeError:
        pass  # No app context (e.g. during standalone script)

    return Decimal(os.environ.get("COMMISSION_RATE_PER_LOT", "5.00"))


def calculate_for_trade(trade: Trade) -> Commission:
    """
    Idempotently calculate and persist a commission for a closed trade.

    If a commission already exists for this trade (checked via the UNIQUE
    constraint on trade_id), the existing record is returned unchanged.

    Steps:
        1. Check if a commission already exists → return it (idempotency).
        2. Calculate amount = volume * rate_per_lot.
        3. Insert the Commission record.
        4. Handle IntegrityError as a secondary idempotency guard.
        5. Emit 'commission_created' WebSocket event.

    Args:
        trade: A closed Trade instance. Must have status=closed.

    Returns:
        The Commission record (either newly created or pre-existing).
    """
    # ── Idempotency check ─────────────────────────────────────────────────────
    existing = Commission.query.filter_by(trade_id=trade.id).first()
    if existing:
        logger.debug(
            "Commission already exists for trade_id=%d (id=%d) — returning existing.",
            trade.id,
            existing.id,
        )
        return existing

    rate = _get_rate()
    volume = Decimal(str(trade.volume))
    amount = (volume * rate).quantize(Decimal("0.01"))

    commission = Commission(
        trade_id=trade.id,
        broker_account_id=trade.broker_account_id,
        volume=volume,
        rate_per_lot=rate,
        amount=amount,
        status=CommissionStatus.pending,
    )

    try:
        db.session.add(commission)
        db.session.commit()
        logger.info(
            "Created commission id=%d trade_id=%d amount=%.2f",
            commission.id,
            trade.id,
            amount,
        )
    except IntegrityError:
        # Race condition: another request inserted the commission concurrently
        db.session.rollback()
        logger.debug(
            "IntegrityError on commission for trade_id=%d — returning existing.", trade.id
        )
        existing = Commission.query.filter_by(trade_id=trade.id).first()
        return existing  # type: ignore[return-value]

    # ── Emit WebSocket event ──────────────────────────────────────────────────
    _emit_commission_created(commission)

    return commission


def process_new_trades(broker_account_id: int) -> int:
    """
    Calculate commissions for all closed trades that don't yet have one.

    Uses an outer join to find closed trades with no matching commission row,
    then calls calculate_for_trade() for each one.

    Args:
        broker_account_id: ID of the BrokerAccount to process.

    Returns:
        Number of commissions created in this call.
    """
    # Find closed trades for this account that have no commission yet
    uncalculated_trades = (
        db.session.query(Trade)
        .outerjoin(Commission, Trade.id == Commission.trade_id)
        .filter(
            Trade.broker_account_id == broker_account_id,
            Trade.status == TradeStatus.closed,
            Commission.id.is_(None),  # No matching commission
        )
        .all()
    )

    count = 0
    for trade in uncalculated_trades:
        try:
            calculate_for_trade(trade)
            count += 1
        except Exception as exc:
            logger.error(
                "Failed to calculate commission for trade_id=%d: %s", trade.id, exc
            )
    logger.info(
        "process_new_trades(account_id=%d) → %d commissions created.",
        broker_account_id,
        count,
    )
    return count


def _emit_commission_created(commission: Commission) -> None:
    """
    Emit a 'commission_created' WebSocket event to all connected clients.

    Gracefully handles the case where SocketIO is not available
    (e.g. during testing or standalone scripts).

    Args:
        commission: The newly created Commission record.
    """
    try:
        from sockets.commission_events import emit_commission_created
        emit_commission_created(commission)
    except Exception as exc:
        logger.warning("Could not emit commission_created event: %s", exc)
