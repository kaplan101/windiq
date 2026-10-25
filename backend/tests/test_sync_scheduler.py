from datetime import UTC, datetime, timedelta

import pytest

from app.services.ingestion_service import SyncResult
from app.services.sync_scheduler import SyncScheduler

RESULT = SyncResult(since=datetime(2026, 10, 25, tzinfo=UTC), fetched=3, written=2)


def test_successful_run_is_remembered():
    scheduler = SyncScheduler(lambda: RESULT, timedelta(minutes=15))

    run = scheduler.run_once()

    assert run.ok
    assert run.result == RESULT
    assert scheduler.last_run is run
    assert scheduler.last_success is run


def test_failed_run_does_not_raise_and_keeps_last_success():
    calls = iter([RESULT, RuntimeError("API weg")])

    def flaky_sync():
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    scheduler = SyncScheduler(flaky_sync, timedelta(minutes=15))
    first = scheduler.run_once()
    second = scheduler.run_once()

    assert not second.ok
    assert "API weg" in second.error
    assert scheduler.last_run is second
    assert scheduler.last_success is first


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 25, 19, 8, 0, tzinfo=UTC), datetime(2026, 10, 25, 19, 15, tzinfo=UTC)),
        (datetime(2026, 10, 25, 19, 14, 59, tzinfo=UTC), datetime(2026, 10, 25, 19, 15, tzinfo=UTC)),
        (datetime(2026, 10, 25, 19, 45, 1, tzinfo=UTC), datetime(2026, 10, 25, 20, 0, tzinfo=UTC)),
        (datetime(2026, 10, 25, 19, 15, 0, tzinfo=UTC), datetime(2026, 10, 25, 19, 30, tzinfo=UTC)),
    ],
)
def test_next_run_is_on_the_quarter_hour(now, expected):
    scheduler = SyncScheduler(lambda: RESULT, timedelta(minutes=15), clock=lambda: now)

    assert scheduler.next_slot() == expected


def test_background_loop_runs_immediately_and_stops():
    runs = []
    scheduler = SyncScheduler(lambda: runs.append(1) or RESULT, timedelta(hours=1))

    scheduler.start()
    scheduler.stop()

    assert len(runs) == 1
