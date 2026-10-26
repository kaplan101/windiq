import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pydantic import SecretStr
from sqlalchemy import func, select

from app.integration.windiq_api.client import MeasurementBatch
from app.integration.windiq_api.schemas import MastDto, MeasurementDto, SiteDto, TurbineDto
from app.models import Measurement, MeasurementQuality
from app.repositories import reference_repo
from app.services import ingestion_service
from app.services.ingestion_service import (
    INITIAL_SINCE,
    WATERMARK_OVERLAP,
    sync_measurements,
    sync_reference_data,
)
from tests.api_samples import MAST, SITE, TURBINE
from tests.test_reference_repo import save_samples


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

    def __init__(self, pages: list[list[MeasurementDto]], skipped_per_page: int = 0):
        self.pages = pages
        self.skipped_per_page = skipped_per_page
        self.asked_since: list[datetime] = []

    def iter_measurement_pages(self, updated_since: datetime):
        self.asked_since.append(updated_since)
        for page in self.pages:
            yield MeasurementBatch(page, self.skipped_per_page)


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


def test_reference_data_is_fetched_and_stored(db_session):
    class ReferenceClient:
        def get_mast(self):
            return MastDto.model_validate(MAST)

        def get_turbine(self):
            return TurbineDto.model_validate(TURBINE)

        def get_site(self):
            return SiteDto.model_validate(SITE)

    versions = sync_reference_data(db_session, ReferenceClient())

    assert versions == (43, 44)
    assert reference_repo.load(db_session).turbine.hub_height_m == 140.0


def test_failed_page_keeps_earlier_pages(db_session):
    class BrokenClient(FakeClient):
        def iter_measurement_pages(self, updated_since):
            yield MeasurementBatch([dto(0), dto(1)], 0)
            raise RuntimeError("API weg")

    with contextlib.suppress(RuntimeError):
        sync_measurements(db_session, BrokenClient([]))

    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(Measurement)) == 2


def test_skipped_records_are_counted_and_the_rest_is_stored(db_session):
    result = sync_measurements(db_session, FakeClient([[dto(12), dto(13)]], skipped_per_page=1))

    assert (result.fetched, result.written, result.skipped) == (3, 2, 1)


def test_reference_error_does_not_stop_measurement_sync(db_session, monkeypatch):
    class ClientWithBadSite(FakeClient):
        def get_mast(self):
            return MastDto.model_validate(MAST)

        def get_turbine(self):
            return TurbineDto.model_validate(TURBINE)

        def get_site(self):
            # Verluste in Prozent statt als Anteil → wird zu Recht abgelehnt
            return SiteDto.model_validate({**SITE, "losses": {"availability": 3, "electrical": 2, "wake": 5}})

    class TestSessionFactory:
        def __call__(self):
            return contextlib.nullcontext(db_session)

    settings = SimpleNamespace(
        windiq_api_base_url="https://api.test", windiq_client_id="id", windiq_client_secret=SecretStr("secret")
    )
    monkeypatch.setattr(ingestion_service, "get_settings", lambda: settings)
    monkeypatch.setattr(ingestion_service, "WindiqApiClient", lambda *args, **kwargs: ClientWithBadSite([[dto(12)]]))
    monkeypatch.setattr(ingestion_service, "get_session_factory", lambda: TestSessionFactory())
    save_samples(db_session)  # letzter gültiger Stand aus einem früheren Sync: Standort v44
    db_session.commit()

    result = ingestion_service.run_sync()

    assert result.written == 1  # Messwerte trotzdem gespeichert
    assert result.reference_error.startswith("losses.availability")
    site = reference_repo.load(db_session).site
    assert (site.version, site.losses.availability) == (44, 0.03)  # gültiger Stand bleibt, nichts Ungültiges übernommen
