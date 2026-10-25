from datetime import UTC, datetime

import pytest

from app.integration.windiq_api.mapper import clean_wind_speed, to_measurement
from app.integration.windiq_api.schemas import MeasurementDto
from app.models import MeasurementQuality as Q


@pytest.mark.parametrize(
    ("raw", "unit", "expected_ms", "expected_quality"),
    [
        # Beispiele aus den echten API-Daten
        (11.44, "m/s", 11.44, Q.OK),
        ("7.47", "m/s", 7.47, Q.OK),  # Zahl als Text
        (18.43, "km/h", 18.43 / 3.6, Q.OK),  # km/h → m/s
        (None, "m/s", None, Q.MISSING),
        (-999.0, "m/s", None, Q.SENSOR_ERROR),
        (-999.0, "km/h", None, Q.SENSOR_ERROR),  # Fehlercode vor Umrechnung erkannt
        (-0.53, "m/s", None, Q.OUTLIER),  # negativ
        (82.06, "m/s", None, Q.OUTLIER),  # über 40 m/s
        (23.69, "m/s", 23.69, Q.OK),  # echter Sturm, über Cut-out, aber gültig
        # Grenzfälle
        (0.0, "m/s", 0.0, Q.OK),
        (40.0, "m/s", 40.0, Q.OK),
        (40.01, "m/s", None, Q.OUTLIER),
        ("n/a", "m/s", None, Q.INVALID),
        ("7,3", "m/s", None, Q.INVALID),  # Komma: lieber markieren als raten
        ("nan", "m/s", None, Q.INVALID),
        (5.0, "kn", None, Q.UNKNOWN_UNIT),
    ],
)
def test_clean_wind_speed(raw, unit, expected_ms, expected_quality):
    speed_ms, quality = clean_wind_speed(raw, unit)

    assert quality == expected_quality
    assert speed_ms == pytest.approx(expected_ms)


def test_to_measurement_normalizes_timestamps_to_utc():
    dto = MeasurementDto(
        timestamp="2026-07-19T02:00:00+02:00",
        wind_speed="6.49",
        unit="m/s",
        wind_direction_deg=260,
        version=2,
        updated_at="2026-07-19T00:05:00Z",
    )

    m = to_measurement(dto)

    assert m.timestamp == datetime(2026, 7, 19, 0, 0, tzinfo=UTC)
    assert m.timestamp.utcoffset().total_seconds() == 0
    assert m.wind_speed_ms == pytest.approx(6.49)
    assert m.wind_speed_raw == "6.49"
    assert m.quality == Q.OK
    assert m.source_version == 2


def test_z_and_offset_notation_give_same_timestamp():
    common = {"wind_speed": 5.75, "unit": "m/s", "wind_direction_deg": 233, "version": 1, "updated_at": "2025-11-10T03:04:19Z"}

    a = to_measurement(MeasurementDto(timestamp="2025-11-10T03:00:00Z", **common))
    b = to_measurement(MeasurementDto(timestamp="2025-11-10T03:00:00+00:00", **common))

    assert a.timestamp == b.timestamp
