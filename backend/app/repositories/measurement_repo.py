from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Measurement

# Postgres erlaubt höchstens 65.535 Parameter pro Statement; 1000 Zeilen × 8 Spalten bleiben weit darunter
BATCH_SIZE = 1000
UPDATABLE_COLUMNS = (
    "wind_speed_ms",
    "wind_speed_raw",
    "unit_raw",
    "wind_direction_deg",
    "quality",
    "source_version",
    "source_updated_at",
)


def upsert_measurements(session: Session, measurements: list[Measurement]) -> int:
    """Speichert Messwerte. Eine vorhandene Stunde wird nur durch eine höhere Version überschrieben.

    Gibt zurück, wie viele Stunden neu angelegt oder aktualisiert wurden.
    """
    newest = _keep_highest_version(measurements)
    written = 0
    for start in range(0, len(newest), BATCH_SIZE):
        rows = [_to_row(m) for m in newest[start : start + BATCH_SIZE]]
        stmt = insert(Measurement).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Measurement.timestamp],
            set_={**{column: stmt.excluded[column] for column in UPDATABLE_COLUMNS}, "ingested_at": func.now()},
            where=Measurement.source_version < stmt.excluded.source_version,
        ).returning(Measurement.timestamp)
        # RETURNING liefert nur Zeilen, die wirklich angelegt oder überschrieben wurden
        written += len(session.execute(stmt).all())
    return written


def latest_source_updated_at(session: Session) -> datetime | None:
    """Jüngste Änderungszeit aller gespeicherten Werte – Ausgangspunkt für den nächsten Sync."""
    return session.scalar(select(func.max(Measurement.source_updated_at)))


def _keep_highest_version(measurements: list[Measurement]) -> list[Measurement]:
    # Dieselbe Stunde darf in einem Statement nur einmal vorkommen (z. B. "…Z" und "…+00:00")
    newest: dict[datetime, Measurement] = {}
    for m in measurements:
        current = newest.get(m.timestamp)
        if current is None or m.source_version > current.source_version:
            newest[m.timestamp] = m
    return list(newest.values())


def _to_row(m: Measurement) -> dict:
    return {column: getattr(m, column) for column in ("timestamp", *UPDATABLE_COLUMNS)}
