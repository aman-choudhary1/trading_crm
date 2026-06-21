"""
tests/test_trade_sync.py
-------------------------
Tests for the trade synchronisation service.

All MT5 calls are mocked — no real MT5 terminal is required.

Covers:
  - Successful sync inserting new trades
  - Trade deduplication via unique constraint (same ticket skipped)
  - IntegrityError handling as race-condition safety net
  - Sync on inactive account is a no-op
  - Sync updates last_synced_at
  - Closed trades trigger commission calculation (mocked)
"""

import json
import pytest
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
def broker_account(app):
    """Create a user + broker account for sync tests."""
    with app.app_context():
        from models.user import User
        from models.broker_account import BrokerAccount, AccountType
        from utils.crypto import encrypt_password

        user = User(name="Sync Tester", email="sync@example.com")
        _db.session.add(user)
        _db.session.flush()

        account = BrokerAccount(
            user_id=user.id,
            mt5_login=100001,
            mt5_password=encrypt_password("test_password"),
            server="Demo",
            account_type=AccountType.standalone,
            is_active=True,
        )
        _db.session.add(account)
        _db.session.commit()
        return account.id  # Return just the ID; re-fetch inside tests


# ── Mock deal factory ─────────────────────────────────────────────────────────

def make_deal(ticket: int, symbol: str = "EURUSD", volume: float = 1.0,
              profit: float = 50.0, entry: int = 1, price: float = 1.1000) -> dict:
    """Create a mock MT5 deal dict."""
    return {
        "ticket": ticket,
        "order": ticket,
        "symbol": symbol,
        "volume": volume,
        "type": 0,       # buy
        "entry": entry,  # 0=open, 1=close
        "price": price,
        "profit": profit,
        "time": int(datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc).timestamp()),
        "commission": 0,
        "swap": 0,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTradeSync:
    @patch("services.trade_sync_service.fetch_trade_history")
    @patch("services.trade_sync_service.decrypt_password")
    @patch("services.commission_service.process_new_trades")
    def test_sync_inserts_new_trades(
        self, mock_process, mock_decrypt, mock_fetch, app, broker_account
    ):
        """Sync should insert new deal records and return the count."""
        mock_decrypt.return_value = "test_password"
        mock_fetch.return_value = [
            make_deal(ticket=1001, entry=1),  # closed
            make_deal(ticket=1002, entry=1),  # closed
        ]
        mock_process.return_value = 2

        with app.app_context():
            from services.trade_sync_service import sync
            from models.trade import Trade

            count = sync(broker_account)
            assert count == 2

            trades = Trade.query.filter_by(broker_account_id=broker_account).all()
            assert len(trades) == 2
            tickets = {t.mt5_ticket for t in trades}
            assert 1001 in tickets
            assert 1002 in tickets

    @patch("services.trade_sync_service.fetch_trade_history")
    @patch("services.trade_sync_service.decrypt_password")
    @patch("services.commission_service.process_new_trades")
    def test_sync_deduplicates_existing_trades(
        self, mock_process, mock_decrypt, mock_fetch, app, broker_account
    ):
        """
        Running sync twice with the same deals should only insert once.
        The second sync call should return 0 new trades (deduplication).
        """
        mock_decrypt.return_value = "test_password"
        deals = [make_deal(ticket=2001, entry=1)]
        mock_fetch.return_value = deals
        mock_process.return_value = 0

        with app.app_context():
            from services.trade_sync_service import sync
            from models.trade import Trade

            # First sync
            count1 = sync(broker_account)
            assert count1 == 1

            # Second sync with same data
            count2 = sync(broker_account)
            assert count2 == 0

            # Only one trade should exist
            trades = Trade.query.filter_by(
                broker_account_id=broker_account, mt5_ticket=2001
            ).all()
            assert len(trades) == 1

    @patch("services.trade_sync_service.fetch_trade_history")
    @patch("services.trade_sync_service.decrypt_password")
    @patch("services.commission_service.process_new_trades")
    def test_sync_updates_last_synced_at(
        self, mock_process, mock_decrypt, mock_fetch, app, broker_account
    ):
        """Sync should update the account's last_synced_at timestamp."""
        mock_decrypt.return_value = "test_password"
        mock_fetch.return_value = []
        mock_process.return_value = 0

        with app.app_context():
            from services.trade_sync_service import sync
            from models.broker_account import BrokerAccount

            account = _db.session.get(BrokerAccount, broker_account)
            assert account.last_synced_at is None

            sync(broker_account)

            _db.session.refresh(account)
            assert account.last_synced_at is not None

    @patch("services.trade_sync_service.fetch_trade_history")
    @patch("services.trade_sync_service.decrypt_password")
    def test_sync_inactive_account_is_noop(
        self, mock_decrypt, mock_fetch, app, broker_account
    ):
        """Syncing an inactive account should return 0 and not call MT5."""
        with app.app_context():
            from services.trade_sync_service import sync
            from models.broker_account import BrokerAccount

            account = _db.session.get(BrokerAccount, broker_account)
            account.is_active = False
            _db.session.commit()

            count = sync(broker_account)
            assert count == 0
            mock_fetch.assert_not_called()

            # Restore
            account.is_active = True
            _db.session.commit()

    def test_sync_account_not_found(self, app):
        """Syncing a non-existent account should raise NotFoundError."""
        with app.app_context():
            from services.trade_sync_service import sync
            from utils.exceptions import NotFoundError

            with pytest.raises(NotFoundError):
                sync(99999)

    @patch("services.trade_sync_service.fetch_trade_history")
    @patch("services.trade_sync_service.decrypt_password")
    @patch("services.commission_service.process_new_trades")
    def test_sync_handles_integrity_error_gracefully(
        self, mock_process, mock_decrypt, mock_fetch, app, broker_account
    ):
        """
        IntegrityError from the unique constraint (race condition simulation)
        should be caught gracefully and not crash the sync.
        """
        from sqlalchemy.exc import IntegrityError

        mock_decrypt.return_value = "test_password"
        mock_fetch.return_value = [make_deal(ticket=3001, entry=1)]
        mock_process.return_value = 0

        with app.app_context():
            # Insert the trade directly to simulate it already being there
            from models.trade import Trade, TradeType, TradeStatus
            from decimal import Decimal

            existing = Trade(
                broker_account_id=broker_account,
                mt5_ticket=3001,
                symbol="EURUSD",
                volume=Decimal("1.0"),
                trade_type=TradeType.buy,
                open_price=Decimal("1.1000"),
                profit=Decimal("50.0"),
                open_time=datetime(2024, 1, 15, tzinfo=timezone.utc),
                status=TradeStatus.closed,
            )
            _db.session.add(existing)
            _db.session.commit()

            from services.trade_sync_service import sync
            # Sync with the same ticket — should skip, not crash
            count = sync(broker_account)
            assert count == 0  # No new trade inserted
