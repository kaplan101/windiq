from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import Measurement, MeasurementQuality
from app.repositories import measurement_repo

HOUR = datetime(2026, 10, 25, 8, tzinfo=UTC)


def measurement(timestamp=HOUR, version=1, speed=11.44, updated_at=None) -> Measurement:
    return Measurement(
        timestamp=timestamp,
        wind_speed_ms=speed,
        wind_speed_raw=str(speed),
        unit_raw="m/s",
        wind_direction_deg=311,
        quality=MeasurementQuality.OK,
        source_version=version,
        source_updated_at=updated_at or timestamp + timedelta(minutes=5),
    )


def stored(session, timestamp=HOUR) -> Measurement:
    session.expire_all()
    return session.get(Measurement, timestamp)


def test_inserts_new_hours(db_session):
    written = measurement_repo.upsert_measurements(
        db_session, [measurement(HOUR), measurement(HOUR + timedelta(hours=1), speed=10.75)]
    )

    assert written == 2
    assert db_session.scalar(select(func.count()).select_from(Measurement)) == 2
    assert stored(db_session).wind_speed_ms == 11.44


def test_higher_version_overwrites(db_session):
    measurement_repo.upsert_measurements(db_session, [measurement(version=1, speed=6.0)])

    written = measurement_repo.upsert_measurements(db_session, [measurement(version=2, speed=6.64)])

    assert written == 1
    assert stored(db_session).wind_speed_ms == 6.64
    assert stored(db_session).source_version == 2


def test_same_or_lower_version_is_ignored(db_session):
    measurement_repo.upsert_measurements(db_session, [measurement(version=2, speed=6.64)])

    written = measurement_repo.upsert_measurements(
        db_session, [measurement(version=2, speed=1.0), measurement(version=1, speed=2.0)]
    )

    assert written == 0
    assert stored(db_session).wind_speed_ms == 6.64


def test_same_hour_twice_in_one_call_keeps_highest_version(db_session):
    # z. B. "…T08:00:00Z" und "…T08:00:00+00:00" auf derselben Seite
    written = measurement_repo.upsert_measurements(
        db_session, [measurement(version=1, speed=5.75), measurement(version=3, speed=5.80)]
    )

    assert written == 1
    assert stored(db_session).wind_speed_ms == 5.80


def test_repeated_sync_is_idempotent(db_session):
    batch = [measurement(HOUR + timedelta(hours=i)) for i in range(5)]

    first = measurement_repo.upsert_measurements(db_session, batch)
    second = measurement_repo.upsert_measurements(db_session, batch)

    assert (first, second) == (5, 0)


def test_handles_more_rows_than_one_batch(db_session):
    year = [measurement(HOUR - timedelta(hours=i)) for i in range(2500)]

    written = measurement_repo.upsert_measurements(db_session, year)

    assert written == 2500


def test_latest_source_updated_at(db_session):
    assert measurement_repo.latest_source_updated_at(db_session) is None

    newest = datetime(2026, 10, 25, 12, 7, 31, tzinfo=UTC)
    measurement_repo.upsert_measurements(
        db_session,
        [measurement(HOUR, updated_at=HOUR), measurement(HOUR + timedelta(hours=4), updated_at=newest)],
    )

    assert measurement_repo.latest_source_updated_at(db_session) == newest
