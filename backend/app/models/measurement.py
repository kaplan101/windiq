import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MeasurementQuality(enum.StrEnum):
    """Warum ein Messwert verwendet wird oder nicht."""

    OK = "ok"
    MISSING = "missing"  # API lieferte null
    INVALID = "invalid"  # Text, der keine Zahl ist
    SENSOR_ERROR = "sensor_error"  # Fehlercode -999
    OUTLIER = "outlier"  # physikalisch unmöglich: negativ oder über 40 m/s
    UNKNOWN_UNIT = "unknown_unit"  # Einheit nicht umrechenbar


class Measurement(Base):
    """Ein stündlicher Messwert des Mastes, bereinigt und mit Originalwert."""

    __tablename__ = "measurement"

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    wind_speed_ms: Mapped[float | None]
    wind_speed_raw: Mapped[str | None]
    unit_raw: Mapped[str]
    wind_direction_deg: Mapped[int | None]
    quality: Mapped[MeasurementQuality] = mapped_column(
        Enum(
            MeasurementQuality,
            native_enum=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    source_version: Mapped[int]
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
