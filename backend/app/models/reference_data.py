from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReferenceData(Base):
    """Stammdaten aus der API (Mast, Turbine, Standort) – je Art der zuletzt abgeholte Stand."""

    __tablename__ = "reference_data"

    kind: Mapped[str] = mapped_column(String(20), primary_key=True)  # "mast", "turbine" oder "site"
    version: Mapped[int | None]
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB)  # die API-Antwort, wie geprüft empfangen
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
