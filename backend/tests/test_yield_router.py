from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_session
from app.main import app
from app.models import Measurement, MeasurementQuality
from app.repositories import measurement_repo
from tests.test_reference_repo import save_samples

client = TestClient(app)


@pytest.fixture
def api_with_db(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    yield db_session
    app.dependency_overrides.clear()


def store(session, hours_ago: int, speed: float | None, quality=MeasurementQuality.OK):
    timestamp = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours_ago)
    measurement_repo.upsert_measurements(
        session,
        [
            Measurement(
                timestamp=timestamp,
                wind_speed_ms=speed,
                wind_speed_raw=str(speed),
                unit_raw="m/s",
                wind_direction_deg=180,
                quality=quality,
                source_version=1,
                source_updated_at=timestamp,
            )
        ],
    )


def test_returns_503_before_first_sync(api_with_db):
    response = client.get("/api/yield")

    assert response.status_code == 503


def test_returns_yield_with_inputs_and_data_quality(api_with_db):
    save_samples(api_with_db)
    store(api_with_db, 1, 11.44)
    store(api_with_db, 2, 7.86)
    store(api_with_db, 3, None, MeasurementQuality.SENSOR_ERROR)

    response = client.get("/api/yield")

    assert response.status_code == 200
    body = response.json()
    assert body["hours_valid"] == 2
    assert body["p50_mwh"] == body["aep_net_mwh"]
    assert body["p90_mwh"] == pytest.approx(body["p50_mwh"] * 0.8718)
    assert body["measured_mwh"] == pytest.approx((3536.5 + 1802.5) / 1000, abs=1e-3)
    assert body["inputs"]["turbine_version"] == 43
    assert body["inputs"]["loss_wake"] == 0.05
    quality = body["data_quality"]
    assert quality["valid"] == 2
    assert quality["sensor_error"] == 1
    assert sum(quality.values()) == body["hours_total"]
    assert sum(m["hours"] for m in body["monthly"]) == body["hours_total"]
