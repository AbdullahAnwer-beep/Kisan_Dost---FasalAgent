"""
Real weather data via Open-Meteo — free, no API key required.

Two calls:
1. Geocoding API turns a district/city name into latitude & longitude.
2. Forecast API returns daily rainfall so the irrigation tool can skip
   a watering reminder if rain is already on the way.

If the network call fails for any reason (offline demo, blocked
network, unknown place name) we fall back to a neutral "no rain
expected" estimate so the rest of the agent keeps working — a farmer
should never see a crash, only a slightly less precise reminder.
"""

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _geocode(place_name: str) -> tuple[float, float] | None:
    try:
        resp = httpx.get(
            GEOCODE_URL,
            params={"name": place_name, "count": 1, "country": "PK"},
            timeout=5.0,
        )
        resp.raise_for_status()
        results = resp.json().get("results")
        if not results:
            return None
        return results[0]["latitude"], results[0]["longitude"]
    except Exception:
        return None


def get_rainfall_forecast_mm(district: str, days: int = 3) -> float:
    """Total expected rainfall (mm) over the next `days` days for a district."""
    coords = _geocode(f"{district}, Pakistan")
    if coords is None:
        return 0.0
    lat, lon = coords
    try:
        resp = httpx.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "precipitation_sum",
                "forecast_days": days,
                "timezone": "auto",
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        daily = resp.json().get("daily", {})
        values = daily.get("precipitation_sum", [])
        return round(sum(v for v in values if v is not None), 1)
    except Exception:
        return 0.0
