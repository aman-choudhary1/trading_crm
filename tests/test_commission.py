"""
tests/test_commission.py
--------------------------
Tests for the commission calculation engine.

Covers:
  - Successful commission calculation for a closed trade
  - Idempotency: calling calculate_for_trade twice returns same commission
  - Commission amount formula: volume * rate_per_lot
  - process_new_trades: only processes uncalculated closed trades
  - SocketIO 'commission_created' event is emitted when a commission is created
  - API endpoint idempotency (POST /api/trades/<id>/calculate-commission)
  - Cannot calculate commission for an open trade (422)
"""

import json
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app import create_app
from extensions import db as _db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    application = create_app("testing")
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(autouse=True)
def clean_db(app):
    with app.app_context():
        yield
        _db.session.rollback()
        from models.commission import Commission, CopierLink, CopierMapping
        from models.trade import Trade
        from models.broker_account import BrokerAccount
        from models.user import User
        CopierMapping.query.delete()
        CopierLink.query.delete()
        Commission.query.delete()
        Trade.query.delete()
        BrokerAccount.query.delete()
        User.query.delete()
        _db.session.commit()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def api_headers():
    return {"X-API-Key": "test-api-key", "Content-Type": "application/json"}


@pytest.fixture()
def setup_account_and_trade(app):
    """
    Create a user, broker account, and a closed trade.
    Returns (account_id, trade_id).
    """
    with app.app_context():
        from models.user import User
        from models.broker_account import BrokerAccount, AccountType
        from models.trade import Trade, TradeType, TradeStatus
        from utils.crypto import encrypt_password

        user = User(name="Commission Tester", email="comm@example.com")
        _db.session.add(user)
        _db.session.flush()

        account = BrokerAccount(
            user_id=user.id,
            mt5_login=200001,
            mt5_password=encrypt_password("pw"),
            server="Demo",
            account_type=AccountType.standalone,
        )
        _db.session.add(account)
        _db.session.flush()

        trade = Trade(
            broker_account_id=account.id,
            mt5_ticket=5001,
            symbol="EURUSD",
            volume=Decimal("2.0"),
            trade_type=TradeType.buy,
            open_price=Decimal("1.1000"),
            close_price=Decimal("1.1050"),
            profit=Decimal("100.00"),
            open_time=datetime(2024, 1, 20, tzinfo=timezone.utc),
            close_time=datetime(2024, 1, 21, tzinfo=timezone.utc),
            status=TradeStatus.closed,
        )
        _db.session.add(trade)
        _db.session.commit()
        return account.id, trade.id


# ── Tests: commission_service ─────────────────────────────────────────────────

class TestCalculateForTrade:
    @patch("services.commission_service._emit_commission_created")
    def test_calculate_commission_success(self, mock_emit, app, setup_account_and_trade):
        """
        calculate_for_trade should create a commission with amount = volume * rate.
        Default rate = $5.00/lot, volume = 2.0 → amount = $10.00.
        """
        account_id, trade_id = setup_account_and_trade

        with app.app_context():
            from services.commission_service import calculate_for_trade
            from models.trade import Trade
            from models.commission import Commission

            trade = _db.session.get(Trade, trade_id)
            commission = calculate_for_trade(trade)

            assert commission is not None
            assert commission.trade_id == trade_id
            assert commission.amount == Decimal("10.00")  # 2.0 lots * $5.00
            assert commission.status.value == "pending"
            mock_emit.assert_called_once()

    @patch("services.commission_service._emit_commission_created")
    def test_calculate_commission_idempotent(self, mock_emit, app, setup_account_and_trade):
        """
        Calling calculate_for_trade twice on the same trade must return the
        same commission without creating a duplicate or raising an error.
        """
        account_id, trade_id = setup_account_and_trade

        with app.app_context():
            from services.commission_service import calculate_for_trade
            from models.trade import Trade
            from models.commission import Commission

            trade = _db.session.get(Trade, trade_id)

            # First call
            comm1 = calculate_for_trade(trade)
            # Second call
            comm2 = calculate_for_trade(trade)

            assert comm1.id == comm2.id  # Same commission returned

            # Only one commission should exist in the DB
            count = Commission.query.filter_by(trade_id=trade_id).count()
            assert count == 1

            # Event should only be emitted once (on creation, not on repeat)
            assert mock_emit.call_count == 1

    @patch("services.commission_service._emit_commission_created")
    def test_calculate_commission_rate_from_config(self, mock_emit, app, setup_account_and_trade):
        """
        Commission rate should be read from app config (COMMISSION_RATE_PER_LOT).
        """
        account_id, trade_id = setup_account_and_trade

        with app.app_context():
            # Temporarily change the rate
            app.config["COMMISSION_RATE_PER_LOT"] = Decimal("7.50")

            from services.commission_service import calculate_for_trade
            from models.trade import Trade

            trade = _db.session.get(Trade, trade_id)
            commission = calculate_for_trade(trade)

            # 2.0 lots * $7.50 = $15.00
            assert commission.amount == Decimal("15.00")
            assert commission.rate_per_lot == Decimal("7.50")

            # Restore
            app.config["COMMISSION_RATE_PER_LOT"] = Decimal("5.00")


class TestProcessNewTrades:
    @patch("services.commission_service._emit_commission_created")
    def test_process_new_trades_skips_already_calculated(
        self, mock_emit, app, setup_account_and_trade
    ):
        """process_new_trades should not create duplicate commissions."""
        account_id, trade_id = setup_account_and_trade

        with app.app_context():
            from services.commission_service import process_new_trades, calculate_for_trade
            from models.trade import Trade

            trade = _db.session.get(Trade, trade_id)
            # Pre-calculate
            calculate_for_trade(trade)
            assert mock_emit.call_count == 1

            # Now process_new_trades should find nothing new
            count = process_new_trades(account_id)
            assert count == 0
            assert mock_emit.call_count == 1  # No new emission


# ── Tests: commission API endpoint ────────────────────────────────────────────

class TestCommissionEndpoints:
    @patch("services.commission_service._emit_commission_created")
    def test_api_calculate_commission_success(
        self, mock_emit, client, api_headers, app, setup_account_and_trade
    ):
        """POST /api/trades/<id>/calculate-commission should return 201."""
        account_id, trade_id = setup_account_and_trade

        resp = client.post(
            f"/api/trades/{trade_id}/calculate-commission",
            headers=api_headers,
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["amount"] == "10.00"
        assert data["data"]["trade_id"] == trade_id

    @patch("services.commission_service._emit_commission_created")
    def test_api_calculate_commission_idempotent(
        self, mock_emit, client, api_headers, app, setup_account_and_trade
    ):
        """
        Calling POST /api/trades/<id>/calculate-commission twice should
        return 200 on the second call (existing commission) — not 201.
        """
        account_id, trade_id = setup_account_and_trade

        resp1 = client.post(
            f"/api/trades/{trade_id}/calculate-commission",
            headers=api_headers,
        )
        assert resp1.status_code == 201

        resp2 = client.post(
            f"/api/trades/{trade_id}/calculate-commission",
            headers=api_headers,
        )
        # Second call returns the existing one (200 OK, not 201 Created)
        assert resp2.status_code == 200
        data1 = resp1.get_json()["data"]
        data2 = resp2.get_json()["data"]
        assert data1["id"] == data2["id"]

    def test_api_calculate_commission_open_trade(
        self, client, api_headers, app, setup_account_and_trade
    ):
        """Calculating commission for an open trade should return 422."""
        account_id, trade_id = setup_account_and_trade

        with app.app_context():
            from models.trade import Trade, TradeStatus
            trade = _db.session.get(Trade, trade_id)
            trade.status = TradeStatus.open
            _db.session.commit()

        resp = client.post(
            f"/api/trades/{trade_id}/calculate-commission",
            headers=api_headers,
        )
        assert resp.status_code == 422

    def test_api_calculate_commission_not_found(self, client, api_headers):
        """POST to a non-existent trade should return 404."""
        resp = client.post(
            "/api/trades/99999/calculate-commission",
            headers=api_headers,
        )
        assert resp.status_code == 404


class TestCommissionSocketIOEvent:
    @patch("services.commission_service._emit_commission_created")
    def test_commission_created_event_emitted(self, mock_emit, app, setup_account_and_trade):
        """
        When a commission is created, the 'commission_created' WebSocket
        event should be emitted with the correct payload.
        """
        account_id, trade_id = setup_account_and_trade

        with app.app_context():
            from services.commission_service import calculate_for_trade
            from models.trade import Trade

            trade = _db.session.get(Trade, trade_id)
            commission = calculate_for_trade(trade)

            # Verify the emit was called with the commission object
            mock_emit.assert_called_once()
            called_commission = mock_emit.call_args[0][0]
            assert called_commission.id == commission.id
            assert called_commission.trade_id == trade_id
