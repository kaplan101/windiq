from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.repositories import measurement_repo
from app.services.sync_scheduler import SyncRun

router = APIRouter(tags=["status"])

# Neue Werte kommen stündlich; ist der neueste älter, hängt der Sync oder die Quelle
MAX_DATA_AGE = timedelta(hours=2)


class DataFreshness(BaseModel):
    status: str
    latest_measurement_at: datetime | None
    age_minutes: int | None
    max_age_minutes: int


class SyncRunInfo(BaseModel):
    started_at: datetime
    finished_at: datetime
    ok: bool
    fetched: int | None
    written: int | None
    error: str | None


class StatusResponse(BaseModel):
    measurements_total: int
    measurements_by_quality: dict[str, int]
    oldest_measurement_at: datetime | None
    latest_measurement_at: datetime | None
    sync_interval_minutes: int | None
    next_sync_at: datetime | None
    last_sync: SyncRunInfo | None
    last_successful_sync: SyncRunInfo | None


@router.get("/health/data")
def data_freshness(session: SessionDep, response: Response) -> DataFreshness:
    """Datenfrische: 503, wenn der neueste Messwert älter als 2 Stunden ist."""
    latest = measurement_repo.latest_timestamp(session)
    age = None if latest is None else datetime.now(UTC) - latest
    fresh = age is not None and age <= MAX_DATA_AGE
    if not fresh:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DataFreshness(
        status="ok" if fresh else "stale",
        latest_measurement_at=latest,
        age_minutes=None if age is None else int(age.total_seconds() // 60),
        max_age_minutes=int(MAX_DATA_AGE.total_seconds() // 60),
    )


@router.get("/api/status")
def sync_status(session: SessionDep, request: Request) -> StatusResponse:
    """Überblick für den Betrieb: Datenbestand, Datenqualität und letzte Sync-Läufe."""
    by_quality = measurement_repo.count_by_quality(session)
    scheduler = request.app.state.scheduler
    return StatusResponse(
        measurements_total=sum(by_quality.values()),
        measurements_by_quality=by_quality,
        oldest_measurement_at=measurement_repo.oldest_timestamp(session),
        latest_measurement_at=measurement_repo.latest_timestamp(session),
        sync_interval_minutes=None if scheduler is None else int(scheduler.interval.total_seconds() // 60),
        next_sync_at=None if scheduler is None else scheduler.next_run_at,
        last_sync=_to_info(scheduler.last_run if scheduler else None),
        last_successful_sync=_to_info(scheduler.last_success if scheduler else None),
    )


def _to_info(run: SyncRun | None) -> SyncRunInfo | None:
    if run is None:
        return None
    return SyncRunInfo(
        started_at=run.started_at,
        finished_at=run.finished_at,
        ok=run.ok,
        fetched=run.result.fetched if run.result else None,
        written=run.result.written if run.result else None,
        error=run.error,
    )
