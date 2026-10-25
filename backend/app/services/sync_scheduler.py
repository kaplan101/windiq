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
    """Führt den Sync im Hintergrund aus: einmal beim Start, danach im festen Uhrzeit-Raster.

    Bei 15 Minuten also um :00, :15, :30 und :45 – unabhängig davon, wann die App gestartet wurde.
    """

    def __init__(
        self,
        run_sync: Callable[[], SyncResult],
        interval: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._run_sync = run_sync
        self._interval = interval
        self._clock = clock
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="sync-scheduler", daemon=True)
        self.last_run: SyncRun | None = None
        self.last_success: SyncRun | None = None
        self.next_run_at: datetime | None = None

    @property
    def interval(self) -> timedelta:
        return self._interval

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def next_slot(self) -> datetime:
        """Nächster Zeitpunkt im Raster, z. B. 19:15:00 bei 19:08 und 15-Minuten-Intervall."""
        now = self._clock()
        interval_s = self._interval.total_seconds()
        seconds_into_slot = now.timestamp() % interval_s
        return now + timedelta(seconds=interval_s - seconds_into_slot)

    def run_once(self) -> SyncRun:
        started_at = self._clock()
        try:
            result = self._run_sync()
        except Exception as exc:  # ein fehlgeschlagener Lauf darf die App nie stoppen
            logger.exception("Sync fehlgeschlagen")
            run = SyncRun(started_at, self._clock(), None, f"{type(exc).__name__}: {exc}")
        else:
            logger.info(
                "Sync ok: %d Werte abgerufen, %d gespeichert (geändert seit %s), Turbine v%s, Standort v%s",
                result.fetched, result.written, result.since.isoformat(), result.turbine_version, result.site_version,
            )
            run = SyncRun(started_at, self._clock(), result, None)
            self.last_success = run
        self.last_run = run
        return run

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self.next_run_at = self.next_slot()
            # wartet bis zum nächsten Rasterzeitpunkt, wacht aber sofort auf, wenn stop() aufgerufen wird
            self._stop.wait((self.next_run_at - self._clock()).total_seconds())
