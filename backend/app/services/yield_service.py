from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.yield_calculator import (
    HourlyWind,
    PowerCurve,
    SiteParameters,
    YieldResult,
    calculate_yield,
    mark_frozen_values,
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

    curve, site = _power_model(reference)
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


@dataclass(frozen=True)
class RecentHour:
    timestamp: datetime
    wind_speed_ms: float | None  # Messhöhe; None = keine gültige Messung
    hub_wind_ms: float | None
    power_kw: float | None
    status: str  # "valid", "frozen", "no_record" oder die Qualität aus der DB (z. B. "sensor_error")


@dataclass(frozen=True)
class RecentReport:
    hours: list[RecentHour]
    energy_mwh: float  # nur gemessene Stunden, ohne Auffüllen
    mean_wind_ms: float | None
    coverage: float


# Vorlauf, damit eine eingefrorene Folge, die vor dem Zeitraum beginnt, richtig erkannt wird
FROZEN_LOOKBACK = timedelta(hours=24)


def recent_hours(session: Session, now: datetime, days: int) -> RecentReport:
    """Stündlicher Verlauf der letzten Tage: Wind, Leistung und Grund für jede ungültige Stunde."""
    reference = reference_repo.load(session)
    if reference is None:
        raise NoDataYet("Noch keine Stammdaten – der erste Sync läuft noch")
    curve, site = _power_model(reference)

    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days) + timedelta(hours=1)
    lookback_start = start - FROZEN_LOOKBACK
    stored = measurement_repo.wind_and_quality_between(session, lookback_start, end)
    timeline = [lookback_start + timedelta(hours=i) for i in range(int((end - lookback_start) / timedelta(hours=1)) + 1)]
    cleaned, _ = mark_frozen_values([HourlyWind(h, stored.get(h, (None, ""))[0]) for h in timeline])

    hours = []
    for hour in cleaned[-days * 24 :]:
        wind, quality = stored.get(hour.timestamp, (None, "no_record"))
        if hour.wind_speed_ms is not None:
            hub = hour.wind_speed_ms * site.hub_height_factor
            hours.append(RecentHour(hour.timestamp, hour.wind_speed_ms, hub, curve.power_kw(hub), "valid"))
        else:
            status = "frozen" if wind is not None else ("no_record" if quality == "no_record" else quality)
            hours.append(RecentHour(hour.timestamp, None, None, None, status))

    valid = [h for h in hours if h.status == "valid"]
    return RecentReport(
        hours=hours,
        energy_mwh=sum(h.power_kw for h in valid) / 1000,
        mean_wind_ms=sum(h.wind_speed_ms for h in valid) / len(valid) if valid else None,
        coverage=len(valid) / len(hours),
    )


def _power_model(reference: ReferenceSet) -> tuple[PowerCurve, SiteParameters]:
    """Übersetzt die gespeicherten API-Stammdaten in die Typen des Rechenkerns."""
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
    return curve, site


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
