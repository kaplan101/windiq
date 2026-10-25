"""Ertragsrechnung als reine Funktionen: keine Datenbank, kein HTTP – Zahlen rein, Zahlen raus.

Fachliche Begründungen der einzelnen Regeln: README, Abschnitt „Ertragsrechnung“.
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

# 90-%-Quantil der Standardnormalverteilung (aus der Aufgabe)
P90_Z = 1.282
# Ab so vielen exakt gleichen Werten am Stück gilt der Windmesser als hängend
FROZEN_RUN_MIN_LENGTH = 3


@dataclass(frozen=True)
class PowerCurve:
    speeds_ms: tuple[float, ...]  # Wind auf Nabenhöhe, aufsteigend
    powers_kw: tuple[float, ...]
    cut_in_ms: float
    cut_out_ms: float

    def power_kw(self, hub_wind_ms: float) -> float:
        """Leistung bei gegebenem Wind auf Nabenhöhe, linear zwischen den Stützpunkten."""
        if hub_wind_ms < self.cut_in_ms or hub_wind_ms > self.cut_out_ms:
            return 0.0
        if hub_wind_ms >= self.speeds_ms[-1]:
            return self.powers_kw[-1]
        i = bisect_right(self.speeds_ms, hub_wind_ms) - 1
        v0, v1 = self.speeds_ms[i], self.speeds_ms[i + 1]
        p0, p1 = self.powers_kw[i], self.powers_kw[i + 1]
        return p0 + (hub_wind_ms - v0) / (v1 - v0) * (p1 - p0)


@dataclass(frozen=True)
class SiteParameters:
    measurement_height_m: float
    hub_height_m: float
    shear_exponent: float
    loss_availability: float
    loss_electrical: float
    loss_wake: float
    uncertainty: float

    @property
    def hub_height_factor(self) -> float:
        """v_Nabe = v_Mess × (h_Nabe / h_Mess) ^ α"""
        return (self.hub_height_m / self.measurement_height_m) ** self.shear_exponent

    @property
    def net_factor(self) -> float:
        return (1 - self.loss_availability) * (1 - self.loss_electrical) * (1 - self.loss_wake)

    @property
    def p90_factor(self) -> float:
        return 1 - P90_Z * self.uncertainty


@dataclass(frozen=True)
class HourlyWind:
    timestamp: datetime
    wind_speed_ms: float | None  # gemessen auf Messhöhe; None = fehlt oder ungültig


@dataclass(frozen=True)
class MonthlyEnergy:
    month: str  # "2026-04"
    hours: int
    valid_hours: int
    measured_mwh: float
    filled_mwh: float


@dataclass(frozen=True)
class YieldResult:
    hours_total: int
    hours_valid: int
    hours_frozen: int
    measured_mwh: float
    aep_gross_mwh: float
    aep_net_mwh: float
    p50_mwh: float
    p90_mwh: float
    monthly: list[MonthlyEnergy]

    @property
    def coverage(self) -> float:
        return self.hours_valid / self.hours_total


def twelve_month_window(now: datetime) -> list[datetime]:
    """Alle Stunden der letzten 12 Monate bis zur aktuellen Stunde (einschließlich)."""
    end = now.replace(minute=0, second=0, microsecond=0)
    try:
        year_ago = end.replace(year=end.year - 1)
    except ValueError:  # 29. Februar
        year_ago = end.replace(year=end.year - 1, day=28)
    hours = int((end - year_ago) / timedelta(hours=1))
    return [year_ago + timedelta(hours=i + 1) for i in range(hours)]


def mark_frozen_values(hours: list[HourlyWind]) -> tuple[list[HourlyWind], int]:
    """Hängender Windmesser: Ab 3 exakt gleichen Werten am Stück gilt nur der erste, die Wiederholungen werden ungültig.

    Erwartet lückenlos aufeinanderfolgende Stunden; eine ungültige Stunde unterbricht eine Folge.
    """
    result = list(hours)
    frozen = 0
    run_start = 0
    for i in range(1, len(hours) + 1):
        continues = (
            i < len(hours)
            and hours[i].wind_speed_ms is not None
            and hours[i].wind_speed_ms == hours[i - 1].wind_speed_ms
        )
        if continues:
            continue
        run_length = i - run_start
        if run_length >= FROZEN_RUN_MIN_LENGTH and hours[run_start].wind_speed_ms is not None:
            for j in range(run_start + 1, i):
                result[j] = HourlyWind(hours[j].timestamp, None)
            frozen += run_length - 1
        run_start = i
    return result, frozen


def calculate_yield(hours: list[HourlyWind], curve: PowerCurve, site: SiteParameters) -> YieldResult:
    """AEP brutto/netto, P50 und P90 für die übergebenen Stunden (lückenlos, ungültige als None).

    Fehlende Stunden werden je Kalendermonat mit der mittleren Leistung dieses Monats aufgefüllt,
    ein Monat ganz ohne gültige Werte mit der mittleren Leistung des ganzen Zeitraums.
    """
    hours, frozen = mark_frozen_values(hours)
    factor = site.hub_height_factor

    by_month: dict[str, list[float | None]] = defaultdict(list)
    for hour in hours:
        power = None if hour.wind_speed_ms is None else curve.power_kw(hour.wind_speed_ms * factor)
        by_month[hour.timestamp.strftime("%Y-%m")].append(power)

    valid_powers = [p for powers in by_month.values() for p in powers if p is not None]
    if not valid_powers:
        raise ValueError("Keine gültigen Messwerte im Zeitraum")
    overall_mean_kw = sum(valid_powers) / len(valid_powers)

    monthly = []
    for month, powers in sorted(by_month.items()):
        valid = [p for p in powers if p is not None]
        mean_kw = sum(valid) / len(valid) if valid else overall_mean_kw
        missing_hours = len(powers) - len(valid)
        monthly.append(
            MonthlyEnergy(
                month=month,
                hours=len(powers),
                valid_hours=len(valid),
                measured_mwh=sum(valid) / 1000,
                filled_mwh=missing_hours * mean_kw / 1000,
            )
        )

    measured = sum(m.measured_mwh for m in monthly)
    gross = measured + sum(m.filled_mwh for m in monthly)
    net = gross * site.net_factor
    return YieldResult(
        hours_total=len(hours),
        hours_valid=len(valid_powers),
        hours_frozen=frozen,
        measured_mwh=measured,
        aep_gross_mwh=gross,
        aep_net_mwh=net,
        p50_mwh=net,
        p90_mwh=net * site.p90_factor,
        monthly=monthly,
    )
