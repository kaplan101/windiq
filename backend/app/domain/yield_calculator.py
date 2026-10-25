"""Ertragsrechnung als reine Funktionen: keine Datenbank, kein HTTP – Zahlen rein, Zahlen raus.

Fachliche Begründungen der einzelnen Regeln: README, Abschnitt „Ertragsrechnung“.
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo

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
class DailyStats:
    day: date  # Kalendertag in der übergebenen Zeitzone
    hours: int
    valid_hours: int
    mean_wind_ms: float | None  # Messhöhe, nur gültige Stunden
    mean_power_kw: float | None
    measured_mwh: float
    filled_mwh: float  # fehlende Stunden mit dem Mittel ihres Monats, wie in der Jahresrechnung


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
    daily: list[DailyStats]

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


def calculate_yield(
    hours: list[HourlyWind], curve: PowerCurve, site: SiteParameters, tz: tzinfo = UTC
) -> YieldResult:
    """AEP brutto/netto, P50 und P90 für die übergebenen Stunden (lückenlos, ungültige als None).

    Fehlende Stunden werden je Kalendermonat mit der mittleren Leistung dieses Monats aufgefüllt,
    ein Monat ganz ohne gültige Werte mit der mittleren Leistung des ganzen Zeitraums.
    Zusätzlich gibt es Tageswerte, gruppiert nach Kalendertagen in der Zeitzone `tz`.
    """
    hours, frozen = mark_frozen_values(hours)
    factor = site.hub_height_factor
    powers = [None if h.wind_speed_ms is None else curve.power_kw(h.wind_speed_ms * factor) for h in hours]

    by_month: dict[str, list[float | None]] = defaultdict(list)
    for hour, power in zip(hours, powers):
        by_month[_month_of(hour)].append(power)

    valid_powers = [p for p in powers if p is not None]
    if not valid_powers:
        raise ValueError("Keine gültigen Messwerte im Zeitraum")
    overall_mean_kw = sum(valid_powers) / len(valid_powers)

    monthly = []
    month_mean_kw: dict[str, float] = {}
    for month, month_powers in sorted(by_month.items()):
        valid = [p for p in month_powers if p is not None]
        month_mean_kw[month] = sum(valid) / len(valid) if valid else overall_mean_kw
        missing_hours = len(month_powers) - len(valid)
        monthly.append(
            MonthlyEnergy(
                month=month,
                hours=len(month_powers),
                valid_hours=len(valid),
                measured_mwh=sum(valid) / 1000,
                filled_mwh=missing_hours * month_mean_kw[month] / 1000,
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
        daily=_daily_stats(hours, powers, month_mean_kw, tz),
    )


def _month_of(hour: HourlyWind) -> str:
    return hour.timestamp.strftime("%Y-%m")


def _daily_stats(
    hours: list[HourlyWind], powers: list[float | None], month_mean_kw: dict[str, float], tz: tzinfo
) -> list[DailyStats]:
    by_day: dict[date, list[tuple[HourlyWind, float | None]]] = defaultdict(list)
    for hour, power in zip(hours, powers):
        by_day[hour.timestamp.astimezone(tz).date()].append((hour, power))

    daily = []
    for day, entries in sorted(by_day.items()):
        valid = [(h.wind_speed_ms, p) for h, p in entries if p is not None]
        filled_kwh = sum(month_mean_kw[_month_of(h)] for h, p in entries if p is None)
        daily.append(
            DailyStats(
                day=day,
                hours=len(entries),
                valid_hours=len(valid),
                mean_wind_ms=sum(w for w, _ in valid) / len(valid) if valid else None,
                mean_power_kw=sum(p for _, p in valid) / len(valid) if valid else None,
                measured_mwh=sum(p for _, p in valid) / 1000,
                filled_mwh=filled_kwh / 1000,
            )
        )
    return daily
