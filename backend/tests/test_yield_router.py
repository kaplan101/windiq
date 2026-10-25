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


def test_recent_hours_show_power_and_reason_for_invalid_hours(api_with_db):
    save_samples(api_with_db)
    store(api_with_db, 1, 11.44)
    store(api_with_db, 2, None, MeasurementQuality.SENSOR_ERROR)
    for hours_ago in (5, 4, 3):  # dreimal exakt gleicher Wert → Wiederholungen eingefroren
        store(api_with_db, hours_ago, 6.49)

    body = client.get("/api/recent?days=2").json()  # gestern 0 Uhr (deutsche Zeit) bis jetzt

    hours = body["hours"]
    by_age = {len(hours) - 1 - i: h for i, h in enumerate(hours)}  # letzte Stunde = vor 0 h
    assert 25 <= len(hours) <= 49
    assert by_age[1]["power_kw"] == pytest.approx(3536.5, abs=0.1)
    assert by_age[2]["status"] == "sensor_error"
    assert [by_age[a]["status"] for a in (5, 4, 3)] == ["valid", "frozen", "frozen"]
    assert by_age[10]["status"] == "no_record"
    assert body["energy_mwh"] == pytest.approx((3536.5 + by_age[5]["power_kw"]) / 1000, abs=1e-3)


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
    assert sum(d["hours"] for d in body["daily"]) == body["hours_total"]
    assert body["daily"][-1]["measured_mwh"] >= 0
