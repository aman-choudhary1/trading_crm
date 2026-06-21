"""
routes/commission_routes.py
---------------------------
REST endpoints for commission calculation and reporting.

Endpoints:
    POST /api/trades/<id>/calculate-commission
        — Idempotently calculate (or return existing) commission for a trade
    GET  /api/broker-accounts/<id>/commissions
        — List commissions with pending/paid summary totals
    GET  /api/commissions/summary
        — Aggregate totals, filterable by broker_account_id
"""

from decimal import Decimal
from flask import Blueprint, request
from sqlalchemy import func

from extensions import db
from models.trade import Trade
from models.broker_account import BrokerAccount
from models.commission import Commission, CommissionStatus
from services.commission_service import calculate_for_trade
from utils.exceptions import NotFoundError, ValidationError
from utils.response import success_response, paginated_response
from utils.logger import get_logger

logger = get_logger(__name__)

commission_bp = Blueprint("commissions", __name__)


@commission_bp.route("/trades/<int:trade_id>/calculate-commission", methods=["POST"])
def calculate_commission(trade_id: int):
    """
    Calculate and store a commission for a trade (idempotent).

    If a commission already exists for this trade, it is returned as-is
    without creating a duplicate.

    Path params:
        trade_id (int)

    Returns:
        200 with existing commission if already calculated.
        201 with newly created commission.
        404 if the trade does not exist.
        422 if the trade is not yet closed.
    """
    trade = db.session.get(Trade, trade_id)
    if not trade:
        raise NotFoundError(f"Trade {trade_id} not found.")

    # Return existing commission if already calculated (idempotency)
    if trade.commission:
        return success_response(trade.commission.to_dict(), status=200)

    from models.trade import TradeStatus
    if trade.status != TradeStatus.closed:
        raise ValidationError("Commission can only be calculated for closed trades.")

    commission = calculate_for_trade(trade)
    return success_response(commission.to_dict(), status=201)


@commission_bp.route("/broker-accounts/<int:account_id>/commissions", methods=["GET"])
def list_commissions(account_id: int):
    """
    List all commissions for a broker account with summary totals.

    Path params:
        account_id (int)

    Query params:
        page     (int, default 1)
        per_page (int, default 20, max 100)

    Returns:
        200 with paginated commissions and a summary of pending vs paid totals.
        404 if the account does not exist.
    """
    account = db.session.get(BrokerAccount, account_id)
    if not account:
        raise NotFoundError(f"Broker account {account_id} not found.")

    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", 20, type=int)))

    query = Commission.query.filter_by(broker_account_id=account_id)
    pagination = query.order_by(Commission.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # ── Summary totals ────────────────────────────────────────────────────────
    summary_rows = (
        db.session.query(Commission.status, func.sum(Commission.amount))
        .filter(Commission.broker_account_id == account_id)
        .group_by(Commission.status)
        .all()
    )
    summary: dict[str, str] = {
        "pending_total": "0.00",
        "paid_total": "0.00",
        "grand_total": "0.00",
    }
    grand = Decimal("0.00")
    for status, total in summary_rows:
        amt = Decimal(str(total or 0))
        grand += amt
        if status == CommissionStatus.pending:
            summary["pending_total"] = str(amt.quantize(Decimal("0.01")))
        elif status == CommissionStatus.paid:
            summary["paid_total"] = str(amt.quantize(Decimal("0.01")))
    summary["grand_total"] = str(grand.quantize(Decimal("0.01")))

    return success_response(
        {
            "commissions": [c.to_dict() for c in pagination.items],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": pagination.total,
                "pages": max(1, -(-pagination.total // per_page)),
            },
            "summary": summary,
        }
    )


@commission_bp.route("/commissions/summary", methods=["GET"])
def commission_summary():
    """
    Return aggregate commission totals, optionally filtered by broker account.

    Query params:
        broker_account_id (int, optional) — filter to a single account

    Returns:
        200 with {pending_total, paid_total, grand_total, count}.
    """
    account_id = request.args.get("broker_account_id", type=int)

    query = db.session.query(Commission.status, func.sum(Commission.amount), func.count())

    if account_id is not None:
        account = db.session.get(BrokerAccount, account_id)
        if not account:
            raise NotFoundError(f"Broker account {account_id} not found.")
        query = query.filter(Commission.broker_account_id == account_id)

    rows = query.group_by(Commission.status).all()

    summary: dict = {
        "pending_total": "0.00",
        "paid_total": "0.00",
        "grand_total": "0.00",
        "count": 0,
    }
    grand = Decimal("0.00")
    total_count = 0
    for status, total, count in rows:
        amt = Decimal(str(total or 0))
        grand += amt
        total_count += count
        if status == CommissionStatus.pending:
            summary["pending_total"] = str(amt.quantize(Decimal("0.01")))
        elif status == CommissionStatus.paid:
            summary["paid_total"] = str(amt.quantize(Decimal("0.01")))
    summary["grand_total"] = str(grand.quantize(Decimal("0.01")))
    summary["count"] = total_count

    return success_response(summary)
