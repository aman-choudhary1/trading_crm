"""
tests/test_broker_accounts.py
------------------------------
Tests for broker account creation and listing.

MT5 calls are fully mocked — no real MT5 terminal is required.

Covers:
  - Successful broker account creation (with mocked encryption)
  - Missing required fields
  - Invalid account_type
  - test_connect=true path (mocked MT5 session)
  - test_connect=true path when MT5 fails → 502
  - Listing broker accounts for a user
"""

import json
import pytest
from unittest.mock import patch, MagicMock
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


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def api_headers():
    return {"X-API-Key": "test-api-key", "Content-Type": "application/json"}


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
def existing_user(client, api_headers):
    """Create and return a test user."""
    resp = client.post(
        "/api/users",
        data=json.dumps({"name": "Trader Joe", "email": "trader@example.com"}),
        headers=api_headers,
    )
    return resp.get_json()["data"]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCreateBrokerAccount:
    def test_create_account_success(self, client, api_headers, existing_user, app):
        """
        Broker account creation should encrypt the password and return 201.
        MT5 connection is NOT tested (test_connect omitted / false).
        """
        user_id = existing_user["id"]
        payload = {
            "mt5_login": 123456,
            "mt5_password": "secret123",
            "server": "MetaQuotes-Demo",
            "account_type": "standalone",
        }
        with app.app_context():
            resp = client.post(
                f"/api/users/{user_id}/broker-accounts",
                data=json.dumps(payload),
                headers=api_headers,
            )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        account = data["data"]
        assert account["mt5_login"] == 123456
        assert account["server"] == "MetaQuotes-Demo"
        assert account["account_type"] == "standalone"
        assert "mt5_password" not in account  # Password must NOT be returned

    def test_create_account_missing_fields(self, client, api_headers, existing_user):
        """Missing required fields should return 422."""
        user_id = existing_user["id"]
        resp = client.post(
            f"/api/users/{user_id}/broker-accounts",
            data=json.dumps({"mt5_login": 123456}),  # missing password/server/type
            headers=api_headers,
        )
        assert resp.status_code == 422

    def test_create_account_invalid_type(self, client, api_headers, existing_user):
        """An unrecognised account_type should return 422."""
        user_id = existing_user["id"]
        payload = {
            "mt5_login": 999,
            "mt5_password": "pw",
            "server": "Demo",
            "account_type": "invalid_type",
        }
        resp = client.post(
            f"/api/users/{user_id}/broker-accounts",
            data=json.dumps(payload),
            headers=api_headers,
        )
        assert resp.status_code == 422

    def test_create_account_user_not_found(self, client, api_headers):
        """Creating an account for a non-existent user should return 404."""
        payload = {
            "mt5_login": 111,
            "mt5_password": "pw",
            "server": "Demo",
            "account_type": "standalone",
        }
        resp = client.post(
            "/api/users/99999/broker-accounts",
            data=json.dumps(payload),
            headers=api_headers,
        )
        assert resp.status_code == 404

    @patch("routes.broker_routes._test_mt5_connection")
    def test_create_account_with_successful_test_connect(
        self, mock_test_connect, client, api_headers, existing_user
    ):
        """
        When test_connect=true and MT5 succeeds, account should be created.
        The _test_mt5_connection function is mocked to avoid real MT5 calls.
        """
        mock_test_connect.return_value = None  # success, no exception

        user_id = existing_user["id"]
        payload = {
            "mt5_login": 555555,
            "mt5_password": "pw",
            "server": "Demo",
            "account_type": "master",
            "test_connect": True,
        }
        resp = client.post(
            f"/api/users/{user_id}/broker-accounts",
            data=json.dumps(payload),
            headers=api_headers,
        )
        assert resp.status_code == 201
        mock_test_connect.assert_called_once_with(555555, "pw", "Demo")

    @patch("routes.broker_routes._test_mt5_connection")
    def test_create_account_with_failed_test_connect(
        self, mock_test_connect, client, api_headers, existing_user
    ):
        """
        When test_connect=true and MT5 fails, should return 502.
        """
        from utils.exceptions import MT5ConnectionError
        mock_test_connect.side_effect = MT5ConnectionError("Login rejected")

        user_id = existing_user["id"]
        payload = {
            "mt5_login": 666666,
            "mt5_password": "wrong_pw",
            "server": "Demo",
            "account_type": "standalone",
            "test_connect": True,
        }
        resp = client.post(
            f"/api/users/{user_id}/broker-accounts",
            data=json.dumps(payload),
            headers=api_headers,
        )
        assert resp.status_code == 502
        data = resp.get_json()
        assert data["success"] is False


class TestListBrokerAccounts:
    def test_list_accounts_empty(self, client, api_headers, existing_user):
        """User with no accounts should return empty list."""
        user_id = existing_user["id"]
        resp = client.get(
            f"/api/users/{user_id}/broker-accounts", headers=api_headers
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []

    def test_list_accounts_multiple(self, client, api_headers, existing_user):
        """List should return all accounts for the user."""
        user_id = existing_user["id"]
        for i in range(3):
            client.post(
                f"/api/users/{user_id}/broker-accounts",
                data=json.dumps({
                    "mt5_login": 10000 + i,
                    "mt5_password": "pw",
                    "server": "Demo",
                    "account_type": "standalone",
                }),
                headers=api_headers,
            )
        resp = client.get(
            f"/api/users/{user_id}/broker-accounts", headers=api_headers
        )
        assert resp.status_code == 200
        assert len(resp.get_json()["data"]) == 3
