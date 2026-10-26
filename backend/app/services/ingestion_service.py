import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.integration.windiq_api.client import WindiqApiClient, describe_error
from app.integration.windiq_api.mapper import to_measurement
from app.repositories import measurement_repo, reference_repo

logger = logging.getLogger(__name__)

# Leere Datenbank: alles holen, was die API hat (das letzte Jahr)
INITIAL_SINCE = datetime(1970, 1, 1, tzinfo=UTC)
# Etwas früher fragen als nötig, damit Werte, die sich während eines Abrufs ändern, nicht durchrutschen
WATERMARK_OVERLAP = timedelta(hours=2)


@dataclass(frozen=True)
class SyncResult:
    since: datetime
    fetched: int
    written: int
    skipped: int = 0  # unlesbare Datensätze, übersprungen
    turbine_version: int | None = None
    site_version: int | None = None
    reference_error: str | None = None  # Stammdaten abgelehnt → es wird mit dem letzten gültigen Stand gerechnet


def sync_reference_data(session: Session, client: WindiqApiClient) -> tuple[int, int]:
    """Holt Mast, Turbine und Standort und speichert sie; liefert die Versionen von Turbine und Standort."""
    mast, turbine, site = client.get_mast(), client.get_turbine(), client.get_site()
    reference_repo.save(session, mast, turbine, site)
    session.commit()
    return turbine.version, site.version


def sync_measurements(session: Session, client: WindiqApiClient) -> SyncResult:
    """Holt alle Messwerte, die sich seit dem letzten Sync geändert haben, und speichert sie."""
    latest = measurement_repo.latest_source_updated_at(session)
    since = INITIAL_SINCE if latest is None else latest - WATERMARK_OVERLAP

    fetched = written = skipped = 0
    for batch in client.iter_measurement_pages(updated_since=since):
        written += measurement_repo.upsert_measurements(session, [to_measurement(dto) for dto in batch.valid])
        # Seite für Seite festschreiben: bricht der Sync ab, bleibt das Bisherige gespeichert
        session.commit()
        fetched += len(batch.valid) + batch.skipped
        skipped += batch.skipped
    return SyncResult(since=since, fetched=fetched, written=written, skipped=skipped)


def run_sync() -> SyncResult:
    """Ein kompletter Sync-Lauf mit eigener Verbindung zur API und zur Datenbank."""
    settings = get_settings()
    with (
        httpx.Client(base_url=settings.windiq_api_base_url, timeout=30) as http,
        get_session_factory()() as session,
    ):
        client = WindiqApiClient(http, settings.windiq_client_id, settings.windiq_client_secret.get_secret_value())
        turbine_version = site_version = reference_error = None
        try:
            turbine_version, site_version = sync_reference_data(session, client)
        except Exception as exc:  # ein Stammdaten-Problem darf den Messwert-Abruf nicht stoppen
            session.rollback()
            reference_error = describe_error(exc)
            logger.warning("Stammdaten nicht übernommen, letzter gültiger Stand bleibt: %s", reference_error)
        result = sync_measurements(session, client)
        return SyncResult(
            since=result.since,
            fetched=result.fetched,
            written=result.written,
            skipped=result.skipped,
            turbine_version=turbine_version,
            site_version=site_version,
            reference_error=reference_error,
        )
