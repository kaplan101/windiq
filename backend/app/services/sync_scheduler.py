import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.services.ingestion_service import SyncResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncRun:
    started_at: datetime
    finished_at: datetime
    result: SyncResult | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


class SyncScheduler:
    """Führt den Sync im Hintergrund regelmäßig aus und merkt sich den letzten Lauf."""

    def __init__(self, run_sync: Callable[[], SyncResult], interval: timedelta):
        self._run_sync = run_sync
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="sync-scheduler", daemon=True)
        self.last_run: SyncRun | None = None
        self.last_success: SyncRun | None = None

    @property
    def interval(self) -> timedelta:
        return self._interval

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def run_once(self) -> SyncRun:
        started_at = datetime.now(UTC)
        try:
            result = self._run_sync()
        except Exception as exc:  # ein fehlgeschlagener Lauf darf die App nie stoppen
            logger.exception("Sync fehlgeschlagen")
            run = SyncRun(started_at, datetime.now(UTC), None, f"{type(exc).__name__}: {exc}")
        else:
            logger.info(
                "Sync ok: %d Werte abgerufen, %d gespeichert (geändert seit %s)",
                result.fetched, result.written, result.since.isoformat(),
            )
            run = SyncRun(started_at, datetime.now(UTC), result, None)
            self.last_success = run
        self.last_run = run
        return run

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            # wartet bis zum nächsten Lauf, wacht aber sofort auf, wenn stop() aufgerufen wird
            self._stop.wait(self._interval.total_seconds())
