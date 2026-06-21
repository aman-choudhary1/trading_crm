"""
routes/trade_routes.py
----------------------
REST endpoints for trade synchronisation and retrieval.

Endpoints:
    POST /api/broker-accounts/<id>/sync-trades
        — Trigger a manual MT5 sync for one broker account
    GET  /api/broker-accounts/<id>/trades
        — Paginated, filtered list of trades for a broker account
"""

from flask import Blueprint, request
from datetime import datetime

from extensions import db
from models.broker_account import BrokerAccount
from models.trade import Trade, TradeStatus
from services.trade_sync_service import sync
from utils.exceptions import NotFoundError
from utils.response import success_response, paginated_response
from utils.logger import get_logger

logger = get_logger(__name__)

trade_bp = Blueprint("trades", __name__)


@trade_bp.route("/broker-accounts/<int:account_id>/sync-trades", methods=["POST"])
def sync_trades(account_id: int):
    """
    Trigger a manual synchronisation of MT5 deals for a broker account.

    Fetches new deals from MT5 since the account's last_synced_at timestamp,
    inserts new trades, and triggers commission calculation for closed trades.

    Path params:
        account_id (int)

    Returns:
        200 with {new_trades_count: int}.
        404 if the account does not exist.
        502 if the MT5 connection fails.
    """
    account = db.session.get(BrokerAccount, account_id)
    if not account:
        raise NotFoundError(f"Broker account {account_id} not found.")

    new_count = sync(account_id)
    logger.info("Manual sync triggered for account_id=%d — new trades: %d", account_id, new_count)
    return success_response({"new_trades_count": new_count})


@trade_bp.route("/broker-accounts/<int:account_id>/trades", methods=["GET"])
def list_trades(account_id: int):
    """
    Return a paginated, filtered list of trades for a broker account.

    Path params:
        account_id (int)

    Query params:
        status   (str,  optional) — 'open' | 'closed'
        from     (str,  optional) — ISO 8601 datetime lower bound on open_time
        to       (str,  optional) — ISO 8601 datetime upper bound on open_time
        page     (int,  default 1)
        per_page (int,  default 20, max 100)

    Returns:
        200 with paginated items and pagination metadata.
        404 if the account does not exist.
        422 if 'status' is invalid or date format is wrong.
    """
    account = db.session.get(BrokerAccount, account_id)
    if not account:
        raise NotFoundError(f"Broker account {account_id} not found.")

    from utils.exceptions import ValidationError

    query = Trade.query.filter_by(broker_account_id=account_id)

    # ── Filter by status ──────────────────────────────────────────────────────
    status_param = request.args.get("status")
    if status_param:
        try:
            status_enum = TradeStatus(status_param)
        except ValueError:
            raise ValidationError(f"Invalid status '{status_param}'. Must be 'open' or 'closed'.")
        query = query.filter(Trade.status == status_enum)

    # ── Filter by date range ──────────────────────────────────────────────────
    from_str = request.args.get("from")
    to_str = request.args.get("to")

    if from_str:
        try:
            from_dt = datetime.fromisoformat(from_str)
            query = query.filter(Trade.open_time >= from_dt)
        except ValueError:
            raise ValidationError(f"Invalid 'from' date format: '{from_str}'. Use ISO 8601.")

    if to_str:
        try:
            to_dt = datetime.fromisoformat(to_str)
            query = query.filter(Trade.open_time <= to_dt)
        except ValueError:
            raise ValidationError(f"Invalid 'to' date format: '{to_str}'. Use ISO 8601.")

    # ── Pagination ────────────────────────────────────────────────────────────
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", 20, type=int)))

    pagination = query.order_by(Trade.open_time.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return paginated_response(
        items=[t.to_dict() for t in pagination.items],
        page=page,
        per_page=per_page,
        total=pagination.total,
    )
