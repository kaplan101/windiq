from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.yield_calculator import (
    HourlyWind,
    PowerCurve,
    SiteParameters,
    YieldResult,
    calculate_yield,
    twelve_month_window,
)
from app.repositories import measurement_repo, reference_repo
from app.repositories.reference_repo import ReferenceSet


@dataclass(frozen=True)
class YieldReport:
    window_start: datetime
    window_end: datetime
    result: YieldResult
    reference: ReferenceSet
    site: SiteParameters
    data_quality: dict[str, int]


class NoDataYet(Exception):
    """Noch keine Stammdaten oder keine gültigen Messwerte (z. B. direkt nach dem ersten Start)."""


def calculate_current_yield(session: Session, now: datetime) -> YieldReport:
    """Ertrag der letzten 12 Monate bis jetzt, gerechnet mit den gespeicherten Stammdaten und Messwerten."""
    reference = reference_repo.load(session)
    if reference is None:
        raise NoDataYet("Noch keine Stammdaten – der erste Sync läuft noch")

    window = twelve_month_window(now)
    winds = measurement_repo.wind_speeds_between(session, window[0], window[-1])
    hours = [HourlyWind(hour, winds.get(hour)) for hour in window]

    curve = PowerCurve(
        speeds_ms=tuple(p.wind_speed_ms for p in reference.turbine.power_curve),
        powers_kw=tuple(p.power_kw for p in reference.turbine.power_curve),
        cut_in_ms=reference.turbine.cut_in_wind_speed_ms,
        cut_out_ms=reference.turbine.cut_out_wind_speed_ms,
    )
    site = SiteParameters(
        measurement_height_m=reference.mast.measurement_height_m,
        hub_height_m=reference.turbine.hub_height_m,
        shear_exponent=reference.site.shear_exponent,
        loss_availability=reference.site.losses.availability,
        loss_electrical=reference.site.losses.electrical,
        loss_wake=reference.site.losses.wake,
        uncertainty=reference.site.uncertainty,
    )
    try:
        result = calculate_yield(hours, curve, site)
    except ValueError as exc:
        raise NoDataYet(str(exc)) from exc

    return YieldReport(
        window_start=window[0],
        window_end=window[-1],
        result=result,
        reference=reference,
        site=site,
        data_quality=_data_quality(session, window, result, len(winds)),
    )


def _data_quality(session: Session, window: list[datetime], result: YieldResult, records: int) -> dict[str, int]:
    """Wie viele Stunden des Zeitfensters gültig sind und warum die übrigen fehlen."""
    by_quality = measurement_repo.count_by_quality(session, window[0], window[-1])
    by_quality.pop("ok", None)  # „ok“ teilt sich auf in gültig und eingefroren
    return {
        "valid": result.hours_valid,
        "frozen": result.hours_frozen,
        **by_quality,
        "no_record": len(window) - records,
    }
