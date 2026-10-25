from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.integration.windiq_api.schemas import MastDto, SiteDto, TurbineDto
from app.models import ReferenceData


@dataclass(frozen=True)
class ReferenceSet:
    mast: MastDto
    turbine: TurbineDto
    site: SiteDto


def save(session: Session, mast: MastDto, turbine: TurbineDto, site: SiteDto) -> None:
    """Speichert den aktuellen Stand der Stammdaten; ältere Stände werden überschrieben."""
    rows = [
        {"kind": "mast", "version": None, "source_updated_at": None, "payload": mast.model_dump(mode="json")},
        {"kind": "turbine", "version": turbine.version, "source_updated_at": turbine.updated_at,
         "payload": turbine.model_dump(mode="json")},
        {"kind": "site", "version": site.version, "source_updated_at": site.updated_at,
         "payload": site.model_dump(mode="json")},
    ]
    stmt = insert(ReferenceData).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ReferenceData.kind],
        set_={
            "version": stmt.excluded.version,
            "source_updated_at": stmt.excluded.source_updated_at,
            "payload": stmt.excluded.payload,
            "fetched_at": func.now(),
        },
    )
    session.execute(stmt)


def load(session: Session) -> ReferenceSet | None:
    """Liefert die gespeicherten Stammdaten, oder None, solange noch kein Sync gelaufen ist."""
    stored = {row.kind: row.payload for row in session.scalars(select(ReferenceData))}
    if not {"mast", "turbine", "site"} <= stored.keys():
        return None
    return ReferenceSet(
        mast=MastDto.model_validate(stored["mast"]),
        turbine=TurbineDto.model_validate(stored["turbine"]),
        site=SiteDto.model_validate(stored["site"]),
    )
