from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.integration.windiq_api.schemas import MeasurementDto
from app.models import Measurement, MeasurementQuality
from app.services.ingestion_service import INITIAL_SINCE, WATERMARK_OVERLAP, sync_measurements


def dto(hour: int, speed: float | str | None = 5.0, version: int = 1, unit: str = "m/s") -> MeasurementDto:
    timestamp = datetime(2026, 10, 25, hour, tzinfo=UTC)
    return MeasurementDto(
        timestamp=timestamp,
        wind_speed=speed,
        unit=unit,
        wind_direction_deg=180,
        version=version,
        updated_at=timestamp + timedelta(minutes=5 + version),
    )


class FakeClient:
    """Liefert vorgegebene Seiten und merkt sich, ab wann gefragt wurde."""

    def __init__(self, pages: list[list[MeasurementDto]]):
        self.pages = pages
        self.asked_since: list[datetime] = []

    def iter_measurement_pages(self, updated_since: datetime):
        self.asked_since.append(updated_since)
        yield from self.pages


def test_first_sync_fetches_everything_and_stores_cleaned_values(db_session):
    client = FakeClient([[dto(0, 11.44), dto(1, "7.47")], [dto(2, -999.0), dto(3, 18.0, unit="km/h")]])

    result = sync_measurements(db_session, client)

    assert client.asked_since == [INITIAL_SINCE]
    assert (result.fetched, result.written) == (4, 4)
    rows = {m.timestamp.hour: m for m in db_session.scalars(select(Measurement))}
    assert rows[1].wind_speed_ms == 7.47
    assert rows[2].quality == MeasurementQuality.SENSOR_ERROR
    assert rows[3].wind_speed_ms == 5.0  # 18 km/h


def test_next_sync_asks_for_changes_since_last_update_minus_overlap(db_session):
    sync_measurements(db_session, FakeClient([[dto(0), dto(1)]]))
    newest_update = datetime(2026, 10, 25, 1, 6, tzinfo=UTC)

    client = FakeClient([])
    sync_measurements(db_session, client)

    assert client.asked_since == [newest_update - WATERMARK_OVERLAP]


def test_correction_overwrites_and_repeated_data_changes_nothing(db_session):
    sync_measurements(db_session, FakeClient([[dto(8, 6.0, version=1)]]))

    corrected = sync_measurements(db_session, FakeClient([[dto(8, 6.64, version=2)]]))
    repeated = sync_measurements(db_session, FakeClient([[dto(8, 6.64, version=2)]]))

    assert (corrected.written, repeated.written) == (1, 0)
    assert db_session.scalar(select(Measurement.wind_speed_ms)) == 6.64


def test_failed_page_keeps_earlier_pages(db_session):
    class BrokenClient(FakeClient):
        def iter_measurement_pages(self, updated_since):
            yield [dto(0), dto(1)]
            raise RuntimeError("API weg")

    try:
        sync_measurements(db_session, BrokenClient([]))
    except RuntimeError:
        pass

    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(Measurement)) == 2
