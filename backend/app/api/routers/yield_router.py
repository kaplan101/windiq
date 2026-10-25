from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.services.yield_service import NoDataYet, YieldReport, calculate_current_yield, recent_hours

router = APIRouter(tags=["yield"])


class MonthlyEnergyOut(BaseModel):
    month: str
    hours: int
    valid_hours: int
    measured_mwh: float
    filled_mwh: float


class DailyOut(BaseModel):
    day: date
    hours: int
    valid_hours: int
    mean_wind_ms: float | None
    mean_power_kw: float | None
    measured_mwh: float
    filled_mwh: float


class InputsOut(BaseModel):
    mast_name: str
    turbine_name: str
    site_name: str
    measurement_height_m: float
    hub_height_m: float
    shear_exponent: float
    hub_height_factor: float
    rated_power_kw: float
    cut_in_wind_speed_ms: float
    cut_out_wind_speed_ms: float
    loss_availability: float
    loss_electrical: float
    loss_wake: float
    net_factor: float
    uncertainty: float
    p90_factor: float
    turbine_version: int
    turbine_updated_at: datetime
    site_version: int
    site_updated_at: datetime


class YieldResponse(BaseModel):
    calculated_at: datetime
    window_start: datetime
    window_end: datetime
    aep_gross_mwh: float
    aep_net_mwh: float
    p50_mwh: float
    p90_mwh: float
    measured_mwh: float
    hours_total: int
    hours_valid: int
    coverage: float
    data_quality: dict[str, int]
    monthly: list[MonthlyEnergyOut]
    daily: list[DailyOut]  # Kalendertage in deutscher Zeit
    inputs: InputsOut


class RecentHourOut(BaseModel):
    timestamp: datetime
    wind_speed_ms: float | None
    hub_wind_ms: float | None
    power_kw: float | None
    status: str


class RecentResponse(BaseModel):
    energy_mwh: float
    mean_wind_ms: float | None
    coverage: float
    hours: list[RecentHourOut]


@router.get("/api/recent")
def get_recent(session: SessionDep, days: int = Query(7, ge=1, le=31)) -> RecentResponse:
    """Stündlicher Verlauf der letzten Tage: Wind, Leistung und Grund für jede ungültige Stunde."""
    try:
        report = recent_hours(session, datetime.now(UTC), days)
    except NoDataYet as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return RecentResponse(
        energy_mwh=report.energy_mwh,
        mean_wind_ms=report.mean_wind_ms,
        coverage=report.coverage,
        hours=[RecentHourOut(**vars(h)) for h in report.hours],
    )


@router.get("/api/yield")
def get_yield(session: SessionDep) -> YieldResponse:
    """Jahresenergieertrag (AEP brutto/netto), P50 und P90 der letzten 12 Monate."""
    now = datetime.now(UTC)
    try:
        report = calculate_current_yield(session, now)
    except NoDataYet as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return _to_response(report, now)


def _to_response(report: YieldReport, now: datetime) -> YieldResponse:
    r, site, turbine, site_data = report.result, report.site, report.reference.turbine, report.reference.site
    return YieldResponse(
        calculated_at=now,
        window_start=report.window_start,
        window_end=report.window_end,
        aep_gross_mwh=r.aep_gross_mwh,
        aep_net_mwh=r.aep_net_mwh,
        p50_mwh=r.p50_mwh,
        p90_mwh=r.p90_mwh,
        measured_mwh=r.measured_mwh,
        hours_total=r.hours_total,
        hours_valid=r.hours_valid,
        coverage=r.coverage,
        data_quality=report.data_quality,
        monthly=[MonthlyEnergyOut(**vars(m)) for m in r.monthly],
        daily=[DailyOut(**vars(d)) for d in r.daily],
        inputs=InputsOut(
            mast_name=report.reference.mast.name,
            turbine_name=turbine.name,
            site_name=site_data.name,
            measurement_height_m=site.measurement_height_m,
            hub_height_m=site.hub_height_m,
            shear_exponent=site.shear_exponent,
            hub_height_factor=site.hub_height_factor,
            rated_power_kw=turbine.rated_power_kw,
            cut_in_wind_speed_ms=turbine.cut_in_wind_speed_ms,
            cut_out_wind_speed_ms=turbine.cut_out_wind_speed_ms,
            loss_availability=site.loss_availability,
            loss_electrical=site.loss_electrical,
            loss_wake=site.loss_wake,
            net_factor=site.net_factor,
            uncertainty=site.uncertainty,
            p90_factor=site.p90_factor,
            turbine_version=turbine.version,
            turbine_updated_at=turbine.updated_at,
            site_version=site_data.version,
            site_updated_at=site_data.updated_at,
        ),
    )
