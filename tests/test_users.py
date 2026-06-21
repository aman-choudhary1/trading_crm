"""
tests/test_users.py
--------------------
Tests for the User CRUD API endpoints.

Covers:
  - Successful user creation
  - Missing required fields (name, email)
  - Invalid email format
  - Duplicate email rejection
  - Paginated user list
  - User detail with nested broker accounts

MT5 is not involved in user tests.
"""

import json
import pytest
from app import create_app
from extensions import db as _db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    """Create a test Flask application with SQLite in-memory database."""
    application = create_app("testing")
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    """Return a test client for the Flask app."""
    return app.test_client()


@pytest.fixture()
def api_headers():
    """Return request headers with the test API key."""
    return {"X-API-Key": "test-api-key", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def clean_db(app):
    """Roll back all DB changes after each test to keep tests isolated."""
    with app.app_context():
        yield
        _db.session.rollback()
        # Delete in dependency order
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


# ── Helper ────────────────────────────────────────────────────────────────────

def post_user(client, headers, name="Alice", email="alice@example.com", phone=None):
    """Helper: POST /api/users and return the response."""
    payload = {"name": name, "email": email}
    if phone:
        payload["phone"] = phone
    return client.post(
        "/api/users",
        data=json.dumps(payload),
        headers=headers,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCreateUser:
    def test_create_user_success(self, client, api_headers):
        """A valid user creation should return 201 with the user data."""
        resp = post_user(client, api_headers, name="Alice", email="alice@example.com")
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["email"] == "alice@example.com"
        assert data["data"]["name"] == "Alice"
        assert data["data"]["id"] is not None

    def test_create_user_with_phone(self, client, api_headers):
        """User creation with optional phone should store the phone."""
        resp = post_user(client, api_headers, email="bob@example.com", name="Bob", phone="+1234567890")
        assert resp.status_code == 201
        assert resp.get_json()["data"]["phone"] == "+1234567890"

    def test_create_user_missing_name(self, client, api_headers):
        """Missing 'name' field should return 422."""
        resp = client.post(
            "/api/users",
            data=json.dumps({"email": "noname@example.com"}),
            headers=api_headers,
        )
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["success"] is False
        assert "name" in data["error"].lower() or "missing" in data["error"].lower()

    def test_create_user_missing_email(self, client, api_headers):
        """Missing 'email' field should return 422."""
        resp = client.post(
            "/api/users",
            data=json.dumps({"name": "NoEmail"}),
            headers=api_headers,
        )
        assert resp.status_code == 422

    def test_create_user_invalid_email(self, client, api_headers):
        """An invalid email format should return 422."""
        resp = post_user(client, api_headers, email="not-an-email")
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["success"] is False

    def test_create_user_duplicate_email(self, client, api_headers):
        """Creating two users with the same email should return 422 on the second."""
        post_user(client, api_headers, email="dup@example.com", name="First")
        resp = post_user(client, api_headers, email="dup@example.com", name="Second")
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["success"] is False
        assert "dup@example.com" in data["error"] or "registered" in data["error"]

    def test_create_user_email_normalised_lowercase(self, client, api_headers):
        """Email should be lowercased before saving."""
        resp = post_user(client, api_headers, email="UPPER@EXAMPLE.COM", name="Upper")
        assert resp.status_code == 201
        assert resp.get_json()["data"]["email"] == "upper@example.com"

    def test_api_key_required(self, client):
        """Requests without X-API-Key should return 401."""
        resp = client.post(
            "/api/users",
            data=json.dumps({"name": "Test", "email": "test@example.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 401


class TestListUsers:
    def test_list_users_empty(self, client, api_headers):
        """List endpoint should return 200 with empty items when no users exist."""
        resp = client.get("/api/users", headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["items"] == []
        assert data["data"]["pagination"]["total"] == 0

    def test_list_users_pagination(self, client, api_headers):
        """List should support page/per_page query params."""
        for i in range(5):
            post_user(client, api_headers, name=f"User{i}", email=f"user{i}@example.com")

        resp = client.get("/api/users?page=1&per_page=3", headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert len(data["items"]) == 3
        assert data["pagination"]["total"] == 5
        assert data["pagination"]["pages"] == 2


class TestGetUser:
    def test_get_user_success(self, client, api_headers):
        """GET /api/users/<id> should return user with broker_accounts key."""
        create_resp = post_user(client, api_headers)
        user_id = create_resp.get_json()["data"]["id"]

        resp = client.get(f"/api/users/{user_id}", headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["id"] == user_id
        assert "broker_accounts" in data

    def test_get_user_not_found(self, client, api_headers):
        """GET /api/users/99999 should return 404."""
        resp = client.get("/api/users/99999", headers=api_headers)
        assert resp.status_code == 404
        assert resp.get_json()["success"] is False
