"""Datenformate der WindIQ-API, so wie sie geliefert werden (noch unbereinigt)."""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class MastDto(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    measurement_height_m: float = Field(gt=0)


class PowerCurvePoint(BaseModel):
    wind_speed_ms: float = Field(ge=0)
    power_kw: float = Field(ge=0)


class TurbineDto(BaseModel):
    id: str
    name: str
    rated_power_kw: float = Field(gt=0)
    hub_height_m: float = Field(gt=0)
    cut_in_wind_speed_ms: float = Field(ge=0)
    cut_out_wind_speed_ms: float = Field(gt=0)
    power_curve: list[PowerCurvePoint] = Field(min_length=2)
    version: int
    updated_at: datetime

    @model_validator(mode="after")
    def curve_is_sorted(self) -> "TurbineDto":
        speeds = [p.wind_speed_ms for p in self.power_curve]
        if speeds != sorted(set(speeds)):
            raise ValueError("power_curve muss nach Windgeschwindigkeit aufsteigend sortiert sein")
        return self


class LossesDto(BaseModel):
    # Anteile, z. B. 0.03 = 3 %
    availability: float = Field(ge=0, lt=1)
    electrical: float = Field(ge=0, lt=1)
    wake: float = Field(ge=0, lt=1)


class SiteDto(BaseModel):
    id: str
    name: str
    shear_exponent: float
    losses: LossesDto
    uncertainty: float = Field(ge=0, lt=1)
    version: int
    updated_at: datetime


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
