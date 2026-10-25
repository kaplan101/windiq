from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.integration.windiq_api.client import WindiqApiClient
from app.integration.windiq_api.mapper import to_measurement
from app.repositories import measurement_repo

# Leere Datenbank: alles holen, was die API hat (das letzte Jahr)
INITIAL_SINCE = datetime(1970, 1, 1, tzinfo=UTC)
# Etwas früher fragen als nötig, damit Werte, die sich während eines Abrufs ändern, nicht durchrutschen
WATERMARK_OVERLAP = timedelta(hours=2)


@dataclass(frozen=True)
class SyncResult:
    since: datetime
    fetched: int
    written: int


def sync_measurements(session: Session, client: WindiqApiClient) -> SyncResult:
    """Holt alle Messwerte, die sich seit dem letzten Sync geändert haben, und speichert sie."""
    latest = measurement_repo.latest_source_updated_at(session)
    since = INITIAL_SINCE if latest is None else latest - WATERMARK_OVERLAP

    fetched = written = 0
    for page in client.iter_measurement_pages(updated_since=since):
        written += measurement_repo.upsert_measurements(session, [to_measurement(dto) for dto in page])
        # Seite für Seite festschreiben: bricht der Sync ab, bleibt das Bisherige gespeichert
        session.commit()
        fetched += len(page)
    return SyncResult(since=since, fetched=fetched, written=written)


def run_sync() -> SyncResult:
    """Ein kompletter Sync-Lauf mit eigener Verbindung zur API und zur Datenbank."""
    settings = get_settings()
    with (
        httpx.Client(base_url=settings.windiq_api_base_url, timeout=30) as http,
        get_session_factory()() as session,
    ):
        client = WindiqApiClient(http, settings.windiq_client_id, settings.windiq_client_secret.get_secret_value())
        return sync_measurements(session, client)
