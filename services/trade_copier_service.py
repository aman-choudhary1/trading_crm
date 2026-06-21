"""
services/trade_copier_service.py
---------------------------------
Bonus: Master-slave trade copier service.

Overview
--------
This service mirrors open positions from a "master" MT5 account to one or
more "slave" MT5 accounts according to the CopierLink records in the database.

Workflow (runs every COPIER_POLL_SECONDS, default 2s):
  1. Load all active CopierLinks.
  2. For each link, fetch open positions on the master account.
  3. For each master position not yet in copier_mappings for this slave,
     place a scaled order on the slave account (scaled by lot_multiplier,
     rounded to the broker's minimum lot step).
  4. Tag the slave order with magic=master_ticket and comment="copy:<ticket>".
  5. When a master position disappears (i.e. was closed), find the slave
     ticket in copier_mappings and send a closing market order, then mark
     the mapping as closed.

Error handling:
  - Symbol mismatches logged and skipped.
  - Lot rounding errors logged and skipped.
  - order_send failures (requotes, slippage) logged and skipped.
  - Exceptions per-link do NOT crash the whole loop.

PLATFORM CONSTRAINT: MT5 is Windows-only. See services/mt5_service.py.
"""

import math
import time
import threading
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger(__name__)

# Module-level flag so the copier loop can be stopped cleanly
_stop_event = threading.Event()


def start_copier_loop(app) -> threading.Thread:
    """
    Start the trade copier background loop in a daemon thread.

    Args:
        app: The Flask application instance (for app context).

    Returns:
        The started daemon thread.
    """
    thread = threading.Thread(
        target=_copier_loop,
        args=(app,),
        name="trade-copier",
        daemon=True,
    )
    thread.start()
    logger.info("Trade copier loop started (thread=%s).", thread.name)
    return thread


def stop_copier_loop() -> None:
    """Signal the copier loop to stop on next iteration."""
    _stop_event.set()


def _copier_loop(app) -> None:
    """
    The main copier polling loop.

    Runs inside the Flask app context so that DB access works correctly.
    Polls every COPIER_POLL_SECONDS seconds.
    """
    import os
    poll_interval = int(os.environ.get("COPIER_POLL_SECONDS", "2"))

    while not _stop_event.is_set():
        try:
            with app.app_context():
                _run_copier_cycle()
        except Exception as exc:
            logger.error("Unhandled exception in copier loop: %s", exc, exc_info=True)

        _stop_event.wait(timeout=poll_interval)


def _run_copier_cycle() -> None:
    """
    Execute one full iteration of the copier for all active links.

    Loads all active CopierLinks from the DB, fetches master positions,
    and mirrors / closes positions on slave accounts as needed.
    """
    from extensions import db
    from models.commission import CopierLink, CopierMapping
    from services.mt5_service import fetch_open_positions, mt5_session
    from utils.crypto import decrypt_password

    links = CopierLink.query.filter_by(is_active=True).all()
    if not links:
        return

    for link in links:
        try:
            _process_link(link, db, CopierMapping, fetch_open_positions, mt5_session, decrypt_password)
        except Exception as exc:
            logger.error(
                "Error processing CopierLink id=%d (master=%d → slave=%d): %s",
                link.id,
                link.master_account_id,
                link.slave_account_id,
                exc,
                exc_info=True,
            )


def _process_link(link, db, CopierMapping, fetch_open_positions, mt5_session, decrypt_password) -> None:
    """
    Mirror positions from a single master account to its slave.

    Args:
        link:                 Active CopierLink record.
        db:                   SQLAlchemy db instance.
        CopierMapping:        CopierMapping model class.
        fetch_open_positions: Callable from mt5_service.
        mt5_session:          Context manager from mt5_service.
        decrypt_password:     Callable from utils.crypto.
    """
    master = link.master_account
    slave = link.slave_account

    master_password = decrypt_password(master.mt5_password)
    slave_password = decrypt_password(slave.mt5_password)

    # ── Fetch current master positions ────────────────────────────────────────
    master_positions = fetch_open_positions(
        login=master.mt5_login,
        password=master_password,
        server=master.server,
    )
    master_tickets = {pos["ticket"] for pos in master_positions}

    # ── Open new positions on slave for any new master positions ──────────────
    for pos in master_positions:
        master_ticket = pos["ticket"]

        # Check if this position is already copied
        existing_mapping = CopierMapping.query.filter_by(
            copier_link_id=link.id,
            master_ticket=master_ticket,
            is_closed=False,
        ).first()

        if existing_mapping:
            continue  # Already copied, skip

        # ── Calculate scaled lot size ─────────────────────────────────────────
        try:
            slave_volume = _scale_lots(
                master_volume=float(pos["volume"]),
                multiplier=float(link.lot_multiplier),
                min_lot=0.01,  # default; ideally fetch from symbol_info
            )
        except ValueError as exc:
            logger.warning(
                "Lot rounding error for CopierLink id=%d master_ticket=%d: %s — skipping.",
                link.id,
                master_ticket,
                exc,
            )
            continue

        # ── Place order on slave ──────────────────────────────────────────────
        symbol = pos.get("symbol", "")
        order_type = pos.get("type", 0)  # 0=buy, 1=sell

        try:
            slave_ticket = _place_slave_order(
                slave=slave,
                slave_password=slave_password,
                symbol=symbol,
                volume=slave_volume,
                order_type=order_type,
                master_ticket=master_ticket,
                mt5_session=mt5_session,
            )
        except Exception as exc:
            logger.error(
                "Failed to place slave order for master_ticket=%d on slave=%d: %s",
                master_ticket,
                slave.id,
                exc,
            )
            continue

        if slave_ticket is None:
            logger.warning(
                "order_send returned no ticket for master_ticket=%d slave_id=%d — "
                "possibly requote/slippage. Skipping.",
                master_ticket,
                slave.id,
            )
            continue

        # ── Record the mapping ────────────────────────────────────────────────
        mapping = CopierMapping(
            copier_link_id=link.id,
            master_ticket=master_ticket,
            slave_account_id=slave.id,
            slave_ticket=slave_ticket,
        )
        db.session.add(mapping)
        db.session.commit()
        logger.info(
            "Copied master_ticket=%d → slave_ticket=%d (link_id=%d).",
            master_ticket,
            slave_ticket,
            link.id,
        )

    # ── Close slave positions whose master position has closed ─────────────────
    open_mappings = CopierMapping.query.filter_by(
        copier_link_id=link.id,
        is_closed=False,
    ).all()

    for mapping in open_mappings:
        if mapping.master_ticket not in master_tickets:
            # Master position is gone — close the slave position
            try:
                _close_slave_position(
                    slave=slave,
                    slave_password=slave_password,
                    slave_ticket=mapping.slave_ticket,
                    mt5_session=mt5_session,
                )
                mapping.is_closed = True
                db.session.commit()
                logger.info(
                    "Closed slave_ticket=%d (master_ticket=%d closed, link_id=%d).",
                    mapping.slave_ticket,
                    mapping.master_ticket,
                    link.id,
                )
            except Exception as exc:
                logger.error(
                    "Failed to close slave_ticket=%d for mapping_id=%d: %s",
                    mapping.slave_ticket,
                    mapping.id,
                    exc,
                )


def _scale_lots(master_volume: float, multiplier: float, min_lot: float = 0.01) -> float:
    """
    Scale master lot size by multiplier and round down to min_lot step.

    Args:
        master_volume: Master position volume in lots.
        multiplier:    lot_multiplier from the CopierLink.
        min_lot:       Minimum lot step for the broker (default 0.01).

    Returns:
        Scaled and rounded lot size.

    Raises:
        ValueError: If the resulting volume is below min_lot.
    """
    raw = master_volume * multiplier
    # Round down to nearest min_lot step
    steps = math.floor(raw / min_lot)
    rounded = steps * min_lot
    # Avoid floating-point noise
    rounded = round(rounded, 2)
    if rounded < min_lot:
        raise ValueError(
            f"Scaled volume {raw:.4f} rounds to {rounded}, below min_lot={min_lot}."
        )
    return rounded


def _place_slave_order(
    slave,
    slave_password: str,
    symbol: str,
    volume: float,
    order_type: int,
    master_ticket: int,
    mt5_session,
) -> int | None:
    """
    Send a market order on the slave account using mt5.order_send().

    Args:
        slave:         BrokerAccount (slave).
        slave_password: Plain-text slave MT5 password.
        symbol:        Trading symbol.
        volume:        Lot size (already scaled and rounded).
        order_type:    0=buy, 1=sell.
        master_ticket: Used for magic number and comment tagging.
        mt5_session:   MT5 session context manager.

    Returns:
        The slave ticket number on success, or None on failure.
    """
    # MT5 order type constants
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_FILLING_IOC = 1  # Immediate or Cancel

    with mt5_session(slave.mt5_login, slave_password, slave.server) as mt5:
        # Check symbol is available on slave broker
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            logger.warning(
                "Symbol '%s' not found on slave server '%s' — skipping copy.",
                symbol,
                slave.server,
            )
            return None

        # Get current price
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.warning("No tick data for symbol '%s' on slave — skipping.", symbol)
            return None

        price = tick.ask if order_type == ORDER_TYPE_BUY else tick.bid

        request_dict = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,  # max price deviation in points
            "magic": master_ticket,
            "comment": f"copy:{master_ticket}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request_dict)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else "None"
            logger.warning(
                "order_send failed for symbol=%s volume=%.2f slave=%d retcode=%s",
                symbol,
                volume,
                slave.id,
                retcode,
            )
            return None

        return result.order


def _close_slave_position(slave, slave_password: str, slave_ticket: int, mt5_session) -> None:
    """
    Close an open position on the slave account by ticket.

    Args:
        slave:          BrokerAccount (slave).
        slave_password: Plain-text slave MT5 password.
        slave_ticket:   The ticket of the slave position to close.
        mt5_session:    MT5 session context manager.
    """
    ORDER_FILLING_IOC = 1

    with mt5_session(slave.mt5_login, slave_password, slave.server) as mt5:
        # Find the position to get current details
        positions = mt5.positions_get(ticket=slave_ticket)
        if not positions:
            logger.warning(
                "Slave position ticket=%d not found — may already be closed.", slave_ticket
            )
            return

        pos = positions[0]
        symbol = pos.symbol
        volume = pos.volume
        # Reverse direction to close
        close_type = 1 if pos.type == 0 else 0  # sell to close buy, buy to close sell

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise Exception(f"No tick data to close position ticket={slave_ticket}")

        price = tick.ask if close_type == 0 else tick.bid

        close_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": close_type,
            "position": slave_ticket,
            "price": price,
            "deviation": 20,
            "magic": slave_ticket,
            "comment": f"close:copy:{slave_ticket}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": ORDER_FILLING_IOC,
        }

        result = mt5.order_send(close_request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else "None"
            raise Exception(
                f"Failed to close slave_ticket={slave_ticket}: retcode={retcode}"
            )
