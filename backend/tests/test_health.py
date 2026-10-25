import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.db import get_session
from app.main import app

client = TestClient(app)


class FakeSession:
    """Ersetzt die echte DB-Session, damit die Tests ohne Datenbank laufen."""

    def __init__(self, db_reachable: bool):
        self.db_reachable = db_reachable

    def execute(self, statement):
        if not self.db_reachable:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_page_is_served():
    page = client.get("/")
    script = client.get("/static/app.js")

    assert page.status_code == 200
    assert "WindIQ Ertragsrechnung" in page.text
    assert script.status_code == 200


def test_ready_returns_ok_when_database_reachable():
    app.dependency_overrides[get_session] = lambda: FakeSession(db_reachable=True)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_ready_returns_503_when_database_unreachable():
    app.dependency_overrides[get_session] = lambda: FakeSession(db_reachable=False)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}
