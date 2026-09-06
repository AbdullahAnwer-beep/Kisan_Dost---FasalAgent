"""
Kisan Dost function tools.

Each tool is a single-responsibility, typed @function_tool per the
hackathon's technical checklist. Real weather comes from Open-Meteo
(free, no API key) — everything else uses the hardcoded agronomy tables
in data/crop_calendar.py, which is explicitly allowed by the rules.
"""

from datetime import datetime, date
import httpx
from agents import function_tool, RunContextWrapper

from .models import CropStage, IrrigationAdvice, SowingAdvice, HarvestAdvice, FarmerProfile
from .data.crop_calendar import (
    CROP_STAGES, HARVEST_DAYS, SOWING_WINDOWS, IRRIGATION_INTERVAL_DAYS,
    CRITICAL_STAGES, normalize_crop,
)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _days_since(sowing_date: str, today: date | None = None) -> int:
    sowed = datetime.strptime(sowing_date, "%Y-%m-%d").date()
    today = today or date.today()
    return max((today - sowed).days, 0)


@function_tool
def get_crop_stage(crop: str, sowing_date: str) -> CropStage:
    """Work out what growth stage a crop is in today.

    Args:
        crop: Crop name, e.g. 'wheat', 'cotton', 'rice', 'maize', 'sugarcane'.
        sowing_date: The date the crop was sown, in YYYY-MM-DD format.
    """
    crop_key = normalize_crop(crop)
    stages = CROP_STAGES.get(crop_key)
    if not stages:
        return CropStage(
            crop=crop, days_since_sowing=0, stage_name="unknown",
            stage_number=0, total_stages=0, days_remaining_in_stage=0,
            notes=f"No stage data for '{crop}' yet. Supported crops: {', '.join(CROP_STAGES)}.",
        )

    dso = _days_since(sowing_date)
    running = 0
    for i, (name, length) in enumerate(stages, start=1):
        if dso <= running + length:
            return CropStage(
                crop=crop_key, days_since_sowing=dso, stage_name=name,
                stage_number=i, total_stages=len(stages),
                days_remaining_in_stage=running + length - dso,
                notes=f"{crop_key.title()} is {dso} days old, in the '{name}' stage.",
            )
        running += length

    return CropStage(
        crop=crop_key, days_since_sowing=dso, stage_name="Past maturity",
        stage_number=len(stages), total_stages=len(stages),
        days_remaining_in_stage=0,
        notes=f"{crop_key.title()} has passed its normal growth cycle ({dso} days). Check harvest readiness.",
    )


@function_tool
def get_weather_forecast(district: str, latitude: float | None = None, longitude: float | None = None) -> str:
    """Fetch today's real weather (temperature, humidity, rain chance) for a
    Pakistani district using the free Open-Meteo API. Falls back to a plain
    text note if the network call fails so the agent never crashes.

    Args:
        district: District or city name, e.g. 'Multan', 'Faisalabad'.
        latitude: Optional latitude if already known (skips geocoding).
        longitude: Optional longitude if already known (skips geocoding).
    """
    try:
        with httpx.Client(timeout=6.0) as client:
            if latitude is None or longitude is None:
                geo = client.get(GEOCODE_URL, params={"name": district, "count": 1, "country": "PK"})
                geo.raise_for_status()
                results = geo.json().get("results")
                if not results:
                    return f"Could not geocode '{district}'. Assume normal weather, no extreme heat or frost."
                latitude, longitude = results[0]["latitude"], results[0]["longitude"]

            fc = client.get(FORECAST_URL, params={
                "latitude": latitude, "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m",
                "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min",
                "timezone": "auto", "forecast_days": 3,
            })
            fc.raise_for_status()
            data = fc.json()
            cur = data.get("current", {})
            daily = data.get("daily", {})
            rain_today = (daily.get("precipitation_sum") or [0])[0]
            tmax = (daily.get("temperature_2m_max") or [None])[0]
            tmin = (daily.get("temperature_2m_min") or [None])[0]
            return (
                f"District: {district}. Current temp: {cur.get('temperature_2m')}°C, "
                f"humidity: {cur.get('relative_humidity_2m')}%. Today's forecast: "
                f"max {tmax}°C / min {tmin}°C, expected rain {rain_today}mm."
            )
    except Exception as e:
        return f"Weather service unavailable ({e}). Assume normal weather, no extreme heat, no rain expected."


@function_tool
def check_irrigation_need(
    crop: str, sowing_date: str, soil_type: str, last_irrigation_days_ago: int, weather_summary: str,
) -> IrrigationAdvice:
    """Decide whether the field needs water TODAY.

    Args:
        crop: Crop name.
        sowing_date: YYYY-MM-DD sowing date, used to find the current growth stage.
        soil_type: One of 'clay', 'loamy', 'sandy', 'sandy-loam', or 'unknown'.
        last_irrigation_days_ago: How many days ago the field was last irrigated.
        weather_summary: Short text weather summary (from get_weather_forecast), used
            to check for rain that would delay irrigation, or heat that speeds it up.
    """
    crop_key = normalize_crop(crop)
    interval_table = IRRIGATION_INTERVAL_DAYS.get(crop_key, IRRIGATION_INTERVAL_DAYS["wheat"])
    interval = interval_table.get(soil_type, interval_table["unknown"])

    stage_info = get_crop_stage(crop_key, sowing_date)
    is_critical_stage = stage_info.stage_name in CRITICAL_STAGES.get(crop_key, [])
    if is_critical_stage:
        interval = max(interval - 2, 2)  # tighter gap during flowering/tillering/etc.

    rain_expected = any(tok in weather_summary.lower() for tok in ["rain", "mm"]) and \
        any(c.isdigit() and int(c) > 3 for c in weather_summary if c.isdigit())
    heatwave = "40" in weather_summary or "42" in weather_summary or "45" in weather_summary

    overdue_by = last_irrigation_days_ago - interval

    if rain_expected and overdue_by < 2:
        return IrrigationAdvice(
            needs_water_today=False, urgency="none",
            reason="Meaningful rain is expected soon and the field is not badly overdue.",
            recommended_action="Skip irrigation today. Recheck after the rain to see if it was enough.",
            next_check_in_days=2,
        )

    if overdue_by >= 3 or (overdue_by >= 0 and is_critical_stage) or heatwave:
        urgency = "critical" if overdue_by >= 5 else ("high" if is_critical_stage or heatwave else "medium")
        return IrrigationAdvice(
            needs_water_today=True, urgency=urgency,
            reason=(
                f"It has been {last_irrigation_days_ago} days since last irrigation; the normal gap for "
                f"{crop_key} on {soil_type} soil is about {interval} days"
                + (", and the crop is in a water-critical stage right now" if is_critical_stage else "")
                + (". Hot weather is increasing water demand" if heatwave else "") + "."
            ),
            recommended_action="Irrigate the field today — do not delay further.",
            next_check_in_days=interval,
        )

    return IrrigationAdvice(
        needs_water_today=False, urgency="low" if overdue_by > -2 else "none",
        reason=f"Only {last_irrigation_days_ago} of the usual {interval}-day gap has passed for {crop_key} on {soil_type} soil.",
        recommended_action="No irrigation needed today. Check again in a few days.",
        next_check_in_days=max(interval - last_irrigation_days_ago, 1),
    )


@function_tool
def check_sowing_time(crop: str, district: str, season: str) -> SowingAdvice:
    """Check whether NOW is a good time to sow a given crop.

    Args:
        crop: Crop name to sow.
        district: District, used only for the response text (no location logic yet).
        season: 'Rabi' or 'Kharif'.
    """
    crop_key = normalize_crop(crop)
    windows = SOWING_WINDOWS.get(crop_key, {})
    window = windows.get(season)
    if not window:
        return SowingAdvice(
            is_good_time_to_sow=False, crop=crop_key, season=season,  # type: ignore[arg-type]
            reason=f"No {season} sowing window is defined for {crop_key} in {district}.",
            ideal_window="Not applicable",
        )
    start_month, end_month = window
    current_month = date.today().month
    in_window = start_month <= current_month <= end_month
    month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    window_text = f"{month_names[start_month]}-{month_names[end_month]}"
    return SowingAdvice(
        is_good_time_to_sow=in_window, crop=crop_key, season=season,  # type: ignore[arg-type]
        reason=(
            f"The ideal sowing window for {crop_key} ({season}) in Punjab-type conditions is {window_text}."
            + (" You are inside that window now." if in_window else " You are currently outside that window.")
        ),
        ideal_window=window_text,
    )


@function_tool
def check_harvest_readiness(crop: str, sowing_date: str) -> HarvestAdvice:
    """Check if a crop is ready to harvest, or how many days remain.

    Args:
        crop: Crop name.
        sowing_date: YYYY-MM-DD sowing date.
    """
    crop_key = normalize_crop(crop)
    total_days = HARVEST_DAYS.get(crop_key)
    if not total_days:
        return HarvestAdvice(
            is_ready_to_harvest=False, days_to_harvest=-1,
            reason=f"No harvest timeline available for '{crop}'.",
            recommended_action="Consult your local agriculture extension office.",
        )
    dso = _days_since(sowing_date)
    remaining = total_days - dso
    if remaining <= 0:
        return HarvestAdvice(
            is_ready_to_harvest=True, days_to_harvest=0,
            reason=f"{crop_key.title()} is {dso} days old; normal maturity is {total_days} days.",
            recommended_action="Inspect the field and begin harvest — grain/boll moisture check recommended before cutting.",
        )
    return HarvestAdvice(
        is_ready_to_harvest=False, days_to_harvest=remaining,
        reason=f"{crop_key.title()} is {dso} of {total_days} days into its cycle.",
        recommended_action=f"Not ready yet — check back in about {remaining} days.",
    )
