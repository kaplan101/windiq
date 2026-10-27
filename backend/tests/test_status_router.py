from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_session
from app.main import app
from app.models import Measurement, MeasurementQuality
from app.repositories import measurement_repo

client = TestClient(app)


@pytest.fixture
def api_with_db(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    yield db_session
    app.dependency_overrides.clear()


def store(session, timestamp: datetime, quality=MeasurementQuality.OK):
    measurement_repo.upsert_measurements(
        session,
        [
            Measurement(
                timestamp=timestamp,
                wind_speed_ms=5.0 if quality == MeasurementQuality.OK else None,
                wind_speed_raw="5.0",
                unit_raw="m/s",
                wind_direction_deg=180,
                quality=quality,
                source_version=1,
                source_updated_at=timestamp,
            )
        ],
    )


def test_data_is_stale_without_measurements(api_with_db):
    response = client.get("/health/data")

    assert response.status_code == 503
    assert response.json()["status"] == "stale"


def test_data_is_fresh_with_recent_measurement(api_with_db):
    store(api_with_db, datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1))

    response = client.get("/health/data")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_single_late_hour_at_windiq_is_tolerated(api_with_db):
    # 19:14, der Wert für 18 Uhr kommt bei WindIQ verspätet → neuester ist 17 Uhr, 2 h 14 min alt
    store(api_with_db, datetime.now(UTC) - timedelta(hours=2, minutes=14))

    response = client.get("/health/data")

    assert response.status_code == 200
    assert response.json()["max_age_minutes"] == 150


def test_data_is_stale_when_newest_measurement_is_old(api_with_db):
    store(api_with_db, datetime.now(UTC) - timedelta(hours=3))

    response = client.get("/health/data")

    assert response.status_code == 503
    assert response.json()["age_minutes"] >= 180


def test_status_counts_measurements_by_quality(api_with_db):
    base = datetime(2026, 10, 25, tzinfo=UTC)
    store(api_with_db, base)
    store(api_with_db, base + timedelta(hours=1))
    store(api_with_db, base + timedelta(hours=2), MeasurementQuality.SENSOR_ERROR)

    body = client.get("/api/status").json()

    assert body["measurements_total"] == 3
    assert body["measurements_by_quality"] == {"ok": 2, "sensor_error": 1}
    assert body["last_sync"] is None  # im Test läuft kein Hintergrund-Sync
