"""
services/trade_sync_service.py
-------------------------------
Trade synchronisation service.

Fetches deal history from MT5 for a broker account since its last sync
timestamp, inserts new trade records, and triggers commission calculation
for newly closed trades.

Deduplication strategy:
  Primary:   Skip insertion if Trade with same (broker_account_id, mt5_ticket)
             already exists (pre-check in Python).
  Secondary: Catch IntegrityError from the DB unique constraint as a race-
             condition safety net (e.g. concurrent scheduler runs).
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from extensions import db
from models.broker_account import BrokerAccount
from models.trade import Trade, TradeType, TradeStatus
from services.mt5_service import fetch_trade_history
from utils.crypto import decrypt_password
from utils.exceptions import MT5ConnectionError, NotFoundError
from utils.logger import get_logger

logger = get_logger(__name__)

# MT5 deal entry types
_ENTRY_IN = 0   # Opening deal
_ENTRY_OUT = 1  # Closing deal

# Fallback "epoch" start when account has never been synced
_EPOCH_START = datetime(2000, 1, 1, tzinfo=timezone.utc)


def sync(broker_account_id: int) -> int:
    """
    Synchronise MT5 deals for the given broker account.

    Steps:
        1. Load account + decrypt password.
        2. Determine sync range (last_synced_at → now).
        3. Fetch deals from MT5.
        4. For each deal, skip if already present; otherwise insert.
        5. Catch IntegrityError on unique violation (race-condition safety net).
        6. Call commission_service.process_new_trades() for closed trades.
        7. Update last_synced_at.

    Args:
        broker_account_id: Primary key of the BrokerAccount to sync.

    Returns:
        Number of new trade records inserted.

    Raises:
        NotFoundError:    If the account doesn't exist or is inactive.
        MT5ConnectionError: If the MT5 session cannot be established.
    """
    account: BrokerAccount | None = db.session.get(BrokerAccount, broker_account_id)
    if not account:
        raise NotFoundError(f"Broker account {broker_account_id} not found.")
    if not account.is_active:
        logger.info("Skipping inactive broker account id=%d", broker_account_id)
        return 0

    # ── Date range for this sync ──────────────────────────────────────────────
    from_date = account.last_synced_at or _EPOCH_START
    to_date = datetime.now(timezone.utc)

    # Ensure from_date is timezone-aware
    if from_date.tzinfo is None:
        from_date = from_date.replace(tzinfo=timezone.utc)

    logger.info(
        "Syncing account id=%d login=%d from=%s to=%s",
        account.id,
        account.mt5_login,
        from_date.isoformat(),
        to_date.isoformat(),
    )

    # ── Decrypt password ──────────────────────────────────────────────────────
    plain_password = decrypt_password(account.mt5_password)

    # ── Fetch deal history from MT5 ───────────────────────────────────────────
    deals = fetch_trade_history(
        login=account.mt5_login,
        password=plain_password,
        server=account.server,
        from_date=from_date,
        to_date=to_date,
    )
    logger.info("Fetched %d deals for account_id=%d", len(deals), account.id)

    new_count = 0
    for deal in deals:
        try:
            inserted = _process_deal(deal, account)
            if inserted:
                new_count += 1
        except Exception as exc:
            logger.error(
                "Error processing deal ticket=%s for account_id=%d: %s",
                deal.get("ticket"),
                account.id,
                exc,
            )
            db.session.rollback()
            continue

    # ── Trigger commission calculation for newly closed trades ────────────────
    if new_count > 0:
        from services.commission_service import process_new_trades
        process_new_trades(broker_account_id)

    # ── Update last_synced_at ─────────────────────────────────────────────────
    account.last_synced_at = to_date
    db.session.commit()
    logger.info(
        "Sync complete for account_id=%d — %d new trades inserted.", account.id, new_count
    )
    return new_count


def _process_deal(deal: dict, account: BrokerAccount) -> bool:
    """
    Insert a single MT5 deal as a Trade record if it doesn't already exist.

    Args:
        deal:    Dict from mt5.history_deals_get() (or mock equivalent).
        account: The BrokerAccount this deal belongs to.

    Returns:
        True if a new Trade was inserted, False if skipped as duplicate.
    """
    ticket = deal.get("ticket") or deal.get("order")
    if ticket is None:
        logger.warning("Deal has no ticket, skipping: %s", deal)
        return False

    # ── Primary dedup check ───────────────────────────────────────────────────
    existing = Trade.query.filter_by(
        broker_account_id=account.id,
        mt5_ticket=ticket,
    ).first()
    if existing:
        logger.debug("Duplicate deal ticket=%d for account_id=%d — skipped.", ticket, account.id)
        return False

    # ── Map MT5 deal type to our enum ─────────────────────────────────────────
    # MT5 deal type: 0=buy, 1=sell (for DEAL_TYPE_BUY / DEAL_TYPE_SELL)
    deal_type_raw = deal.get("type", 0)
    trade_type = TradeType.buy if deal_type_raw == 0 else TradeType.sell

    # ── Determine open/close times ────────────────────────────────────────────
    deal_time = deal.get("time")
    if deal_time:
        if isinstance(deal_time, (int, float)):
            open_time = datetime.fromtimestamp(deal_time, tz=timezone.utc)
        else:
            open_time = deal_time
    else:
        open_time = datetime.now(timezone.utc)

    # MT5 entry types: 0=DEAL_ENTRY_IN (open), 1=DEAL_ENTRY_OUT (close)
    entry_type = deal.get("entry", _ENTRY_IN)
    is_closed = entry_type == _ENTRY_OUT
    status = TradeStatus.closed if is_closed else TradeStatus.open

    trade = Trade(
        broker_account_id=account.id,
        mt5_ticket=ticket,
        symbol=deal.get("symbol", "UNKNOWN"),
        volume=Decimal(str(deal.get("volume", 0))),
        trade_type=trade_type,
        open_price=Decimal(str(deal.get("price", 0))),
        close_price=Decimal(str(deal.get("price", 0))) if is_closed else None,
        profit=Decimal(str(deal.get("profit", 0))),
        open_time=open_time,
        close_time=open_time if is_closed else None,
        status=status,
    )

    try:
        db.session.add(trade)
        db.session.commit()
        logger.debug(
            "Inserted trade ticket=%d symbol=%s account_id=%d",
            ticket,
            trade.symbol,
            account.id,
        )
        return True
    except IntegrityError:
        # Secondary dedup: race condition safety net
        db.session.rollback()
        logger.debug(
            "IntegrityError (race condition) for ticket=%d account_id=%d — skipped.",
            ticket,
            account.id,
        )
        return False
