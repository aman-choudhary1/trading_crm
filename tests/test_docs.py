"""
tests/test_docs.py
------------------
Tests for the Swagger API documentation endpoints.
Ensures docs routes bypass the API key middleware and return correct formats.
"""

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


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_swagger_ui_html_loads(client):
    """GET /docs should return 200 and serve the customized Swagger UI HTML page."""
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    
    html_content = resp.get_data(as_text=True)
    assert "Mini Trading CRM — Developer Portal" in html_content
    assert "swagger-ui" in html_content
    assert "openapi.json" in html_content
    assert "test-api-key" in html_content  # Verifies dynamic api key injection works


def test_openapi_json_spec_loads(client):
    """GET /docs/openapi.json should return the raw valid OpenAPI 3.0 specification."""
    resp = client.get("/docs/openapi.json")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    
    data = resp.get_json()
    assert data is not None
    assert data["openapi"] == "3.0.0"
    assert "info" in data
    assert data["info"]["title"] == "Mini Trading CRM API"
    assert "paths" in data
    assert "/api/users" in data["paths"]
    assert "/api/copier-links" in data["paths"]
