from datetime import UTC, datetime, timedelta

import pytest

from app.domain.yield_calculator import (
    HourlyWind,
    PowerCurve,
    SiteParameters,
    calculate_yield,
    mark_frozen_values,
    twelve_month_window,
)
from tests.api_samples import SITE, TURBINE

CURVE = PowerCurve(
    speeds_ms=tuple(p["wind_speed_ms"] for p in TURBINE["power_curve"]),
    powers_kw=tuple(p["power_kw"] for p in TURBINE["power_curve"]),
    cut_in_ms=TURBINE["cut_in_wind_speed_ms"],
    cut_out_ms=TURBINE["cut_out_wind_speed_ms"],
)
PARAMS = SiteParameters(
    measurement_height_m=100.0,
    hub_height_m=TURBINE["hub_height_m"],
    shear_exponent=SITE["shear_exponent"],
    loss_availability=SITE["losses"]["availability"],
    loss_electrical=SITE["losses"]["electrical"],
    loss_wake=SITE["losses"]["wake"],
    uncertainty=SITE["uncertainty"],
)


def hours_from(start: datetime, speeds: list[float | None]) -> list[HourlyWind]:
    return [HourlyWind(start + timedelta(hours=i), v) for i, v in enumerate(speeds)]


# --- Handrechnung mit echten Daten vom 25.10.2026 (siehe README) ---

def test_hub_height_factor():
    assert PARAMS.hub_height_factor == pytest.approx(1.069610, abs=1e-6)


def test_hour_0800_matches_hand_calculation():
    # gemessen 11,44 m/s → Nabe 12,2363 m/s → 3520 + 0,2363 × 70 = 3536,5 kW
    hub_wind = 11.44 * PARAMS.hub_height_factor

    assert hub_wind == pytest.approx(12.2363, abs=1e-4)
    assert CURVE.power_kw(hub_wind) == pytest.approx(3536.5, abs=0.1)


def test_hour_1200_matches_hand_calculation():
    # gemessen 7,86 m/s → Nabe 8,4071 m/s → 1566 + 0,4071 × 581 = 1802,5 kW
    assert CURVE.power_kw(7.86 * PARAMS.hub_height_factor) == pytest.approx(1802.5, abs=0.1)


@pytest.mark.parametrize(
    ("hub_wind", "expected_kw"),
    [
        (2.5, 0.0),  # unter Cut-in: aus, obwohl die Kennlinie 2→3 m/s linear 27,5 kW hergäbe
        (3.0, 55.0),  # genau Cut-in
        (14.0, 3600.0),  # Nennleistung
        (25.0, 3600.0),  # genau Cut-out: läuft noch
        (25.34, 0.0),  # Sturm 18.02.2026 19:00: abgeschaltet
    ],
)
def test_cut_in_and_cut_out(hub_wind, expected_kw):
    assert CURVE.power_kw(hub_wind) == pytest.approx(expected_kw)


def test_net_and_p90_factors():
    # 0,97 × 0,98 × 0,95 = 0,90307 · 1 − 1,282 × 0,1 = 0,8718
    assert PARAMS.net_factor == pytest.approx(0.90307, abs=1e-5)
    assert PARAMS.p90_factor == pytest.approx(0.8718)


# --- Eingefrorene Werte ---

def test_frozen_run_keeps_first_value_and_drops_repeats():
    # echtes Beispiel 13.11.2025: 11 Uhr 6,74, dann 12–19 Uhr fest auf 6,49, danach 4,06
    hours = hours_from(datetime(2025, 11, 13, 11, tzinfo=UTC), [6.74] + [6.49] * 8 + [4.06])

    cleaned, frozen = mark_frozen_values(hours)

    assert frozen == 7
    assert [h.wind_speed_ms for h in cleaned] == [6.74, 6.49] + [None] * 7 + [4.06]


def test_two_equal_values_are_normal():
    hours = hours_from(datetime(2026, 1, 1, tzinfo=UTC), [5.0, 5.2, 5.2, 5.4])

    cleaned, frozen = mark_frozen_values(hours)

    assert frozen == 0
    assert cleaned == hours


def test_missing_hour_interrupts_a_run():
    hours = hours_from(datetime(2026, 1, 1, tzinfo=UTC), [5.2, 5.2, None, 5.2, 5.2])

    _, frozen = mark_frozen_values(hours)

    assert frozen == 0


# --- Hochrechnung (Methode C) ---

def test_gaps_are_filled_with_monthly_mean():
    # Januar: 3 Stunden, eine fehlt → mit dem Januar-Mittel aufgefüllt
    # Februar: 2 Stunden, beide fehlen → mit dem Mittel des ganzen Zeitraums aufgefüllt
    jan = hours_from(datetime(2026, 1, 31, 21, tzinfo=UTC), [11.44, 7.86, None])
    feb = hours_from(datetime(2026, 2, 1, tzinfo=UTC), [None, None])

    result = calculate_yield(jan + feb, CURVE, PARAMS)

    jan_mean_kw = (3536.5 + 1802.5) / 2
    assert result.hours_total == 5
    assert result.hours_valid == 2
    assert result.measured_mwh == pytest.approx((3536.5 + 1802.5) / 1000, abs=1e-3)
    assert result.monthly[0].filled_mwh == pytest.approx(jan_mean_kw / 1000, abs=1e-3)
    assert result.monthly[1].filled_mwh == pytest.approx(2 * jan_mean_kw / 1000, abs=1e-3)
    assert result.aep_gross_mwh == pytest.approx(5 * jan_mean_kw / 1000, abs=1e-3)


def test_net_p50_and_p90():
    hours = hours_from(datetime(2026, 1, 1, tzinfo=UTC), [11.44, 7.86])

    result = calculate_yield(hours, CURVE, PARAMS)

    assert result.p50_mwh == result.aep_net_mwh
    assert result.aep_net_mwh == pytest.approx(result.aep_gross_mwh * 0.90307, rel=1e-5)
    assert result.p90_mwh == pytest.approx(result.p50_mwh * 0.8718)


def test_no_valid_values_is_an_error():
    with pytest.raises(ValueError):
        calculate_yield(hours_from(datetime(2026, 1, 1, tzinfo=UTC), [None, None]), CURVE, PARAMS)


# --- Zeitfenster ---

def test_window_is_last_twelve_months_up_to_current_hour():
    window = twelve_month_window(datetime(2026, 10, 25, 16, 51, tzinfo=UTC))

    assert len(window) == 8760
    assert window[0] == datetime(2025, 10, 25, 17, tzinfo=UTC)
    assert window[-1] == datetime(2026, 10, 25, 16, tzinfo=UTC)


def test_window_contains_leap_day():
    assert len(twelve_month_window(datetime(2028, 6, 1, tzinfo=UTC))) == 8784
