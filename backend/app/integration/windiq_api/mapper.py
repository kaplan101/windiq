"""Übersetzt Rohdaten der API in bereinigte Messwerte (Begründungen: siehe README, Abschnitt Datenqualität)."""

import math
from datetime import UTC

from app.integration.windiq_api.schemas import MeasurementDto
from app.models import Measurement, MeasurementQuality

SENSOR_ERROR_VALUE = -999.0
MAX_PLAUSIBLE_WIND_SPEED_MS = 40.0
UNIT_TO_MS = {"m/s": 1.0, "km/h": 1 / 3.6}


def to_measurement(dto: MeasurementDto) -> Measurement:
    wind_speed_ms, quality = clean_wind_speed(dto.wind_speed, dto.unit)
    return Measurement(
        timestamp=dto.timestamp.astimezone(UTC),
        wind_speed_ms=wind_speed_ms,
        wind_speed_raw=None if dto.wind_speed is None else str(dto.wind_speed),
        unit_raw=dto.unit,
        wind_direction_deg=dto.wind_direction_deg,
        quality=quality,
        source_version=dto.version,
        source_updated_at=dto.updated_at.astimezone(UTC),
    )


def clean_wind_speed(raw: float | str | None, unit: str) -> tuple[float | None, MeasurementQuality]:
    """Liefert die Windgeschwindigkeit in m/s und die Qualität; bei ungültigen Werten (None, Grund)."""
    if raw is None:
        return None, MeasurementQuality.MISSING

    try:
        value = float(raw)
    except ValueError:
        return None, MeasurementQuality.INVALID
    if not math.isfinite(value):
        return None, MeasurementQuality.INVALID

    # Fehlercode vor der Umrechnung prüfen, sonst würde aus -999 km/h ein anderer Wert
    if value == SENSOR_ERROR_VALUE:
        return None, MeasurementQuality.SENSOR_ERROR

    factor = UNIT_TO_MS.get(unit)
    if factor is None:
        return None, MeasurementQuality.UNKNOWN_UNIT
    speed_ms = value * factor

    if speed_ms < 0 or speed_ms > MAX_PLAUSIBLE_WIND_SPEED_MS:
        return None, MeasurementQuality.OUTLIER

    return speed_ms, MeasurementQuality.OK
