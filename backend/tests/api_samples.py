"""Echte Antworten der WindIQ-API vom 25.10.2026 – als Testdaten."""

MAST = {
    "id": "WIQ-MM-01",
    "name": "Messmast Spreewald",
    "latitude": 51.8732,
    "longitude": 14.0412,
    "measurement_height_m": 100.0,
    "operator": "WindIQ",
    "commissioned_at": "2023-04-01",
}

_CURVE_KW = [0, 0, 0, 55, 180, 385, 680, 1064, 1566, 2147, 2780, 3250, 3520, 3590] + [3600] * 12

TURBINE = {
    "id": "WIQ-T36",
    "name": "Referenzanlage 3,6 MW",
    "rated_power_kw": 3600.0,
    "hub_height_m": 140.0,
    "rotor_diameter_m": 136.0,
    "cut_in_wind_speed_ms": 3.0,
    "cut_out_wind_speed_ms": 25.0,
    "power_curve": [{"wind_speed_ms": float(v), "power_kw": float(p)} for v, p in enumerate(_CURVE_KW)],
    "version": 43,
    "updated_at": "2026-10-20T15:00:00Z",
}

SITE = {
    "id": "WIQ-SITE-01",
    "name": "Windpark Spreewald",
    "mast_id": "WIQ-MM-01",
    "shear_exponent": 0.2,
    "losses": {"availability": 0.03, "electrical": 0.02, "wake": 0.05},
    "uncertainty": 0.1,
    "version": 44,
    "updated_at": "2026-10-25T10:00:00Z",
}
