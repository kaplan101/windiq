"""Datenformate der WindIQ-API, so wie sie geliefert werden (noch unbereinigt)."""

from datetime import datetime

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class MeasurementDto(BaseModel):
    timestamp: datetime
    wind_speed: float | str | None  # die API liefert Zahl, Text oder null
    unit: str
    wind_direction_deg: int | None = None
    version: int
    updated_at: datetime


class MeasurementPage(BaseModel):
    data: list[MeasurementDto]
    next_cursor: str | None
