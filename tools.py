"""
Function tools for the Kisan Dost Field Reminder Agent.

Each tool is small, typed, single-responsibility, and returns a
Pydantic model (see models.py) instead of a loose string — this is
what the hackathon brief calls "structured outputs" and it is what
lets the frontend render a reminder card without parsing text.
"""

from datetime import date, datetime
from agents import function_tool

from data_store import load_crops, load_schemes
from models import WaterAdvice, SowingAdvice, HarvestAdvice, GovtSupportAdvice
from weather import get_rainfall_forecast_mm


def _growth_stage(days_since_sowing: int, maturity_days: int) -> str:
    fraction = days_since_sowing / maturity_days
    if fraction < 0.15:
        return "germination"
    if fraction < 0.45:
        return "vegetative"
    if fraction < 0.65:
        return "flowering"
    if fraction < 0.9:
        return "grain_fill"
    return "maturity"


@function_tool
def check_irrigation_need(
    crop: str,
    district: str,
    sowing_date: str,
    last_irrigation_date: str,
) -> WaterAdvice:
    """Decide whether a field needs watering today.

    Args:
        crop: Crop name, e.g. "wheat", "cotton", "rice", "maize", "sugarcane".
        district: Farmer's district, used to fetch a real rainfall forecast.
        sowing_date: ISO date (YYYY-MM-DD) the crop was sown.
        last_irrigation_date: ISO date (YYYY-MM-DD) of the last irrigation.
    """
    crops = load_crops()
    crop_key = crop.strip().lower()
    if crop_key not in crops:
        return WaterAdvice(
            water_needed_today=False,
            days_since_last_irrigation=0,
            recommended_interval_days=0,
            growth_stage="unknown",
            rainfall_expected_mm_next_3_days=0.0,
            reason=f"'{crop}' is not in the crop database yet, so no irrigation "
                   f"advice can be given. Supported crops: {', '.join(crops.keys())}.",
        )

    today = date.today()
    sowed = datetime.strptime(sowing_date, "%Y-%m-%d").date()
    last_irrigated = datetime.strptime(last_irrigation_date, "%Y-%m-%d").date()

    days_since_sowing = (today - sowed).days
    days_since_irrigation = (today - last_irrigated).days
    stage = _growth_stage(days_since_sowing, crops[crop_key]["maturity_days"])
    interval = crops[crop_key]["irrigation_interval_days"].get(stage, 14)

    rainfall = get_rainfall_forecast_mm(district, days=3)
    enough_rain_coming = rainfall >= 15.0

    needs_water = days_since_irrigation >= interval and not enough_rain_coming

    if enough_rain_coming:
        reason = (
            f"{rainfall}mm of rain is expected in {district} over the next 3 days, "
            f"so irrigation can wait even though it has been {days_since_irrigation} "
            f"days since the last watering."
        )
    elif needs_water:
        reason = (
            f"It has been {days_since_irrigation} days since the last irrigation, "
            f"which is past the {interval}-day limit for the {stage} stage, and no "
            f"significant rain ({rainfall}mm) is expected."
        )
    else:
        reason = (
            f"Only {days_since_irrigation} of the {interval} days between waterings "
            f"for the {stage} stage have passed. No action needed yet."
        )

    return WaterAdvice(
        water_needed_today=needs_water,
        days_since_last_irrigation=days_since_irrigation,
        recommended_interval_days=interval,
        growth_stage=stage,
        rainfall_expected_mm_next_3_days=rainfall,
        reason=reason,
    )


@function_tool
def check_sowing_window(crop: str, season: str) -> SowingAdvice:
    """Check whether today falls inside the recommended sowing window for a crop.

    Args:
        crop: Crop name, e.g. "wheat", "cotton", "rice", "maize", "sugarcane".
        season: "Rabi" or "Kharif".
    """
    crops = load_crops()
    crop_key = crop.strip().lower()
    if crop_key not in crops:
        return SowingAdvice(
            sowing_window_open=False,
            window_start="-",
            window_end="-",
            days_remaining_in_window=None,
            reason=f"'{crop}' is not in the crop database yet.",
        )

    window = crops[crop_key]["sowing_window"]
    today = date.today()
    year = today.year
    start = datetime.strptime(f"{year}-{window['start']}", "%Y-%m-%d").date()
    end = datetime.strptime(f"{year}-{window['end']}", "%Y-%m-%d").date()

    # Sowing windows that cross the new year (rare, but handle it safely).
    if end < start:
        end = end.replace(year=year + 1)
        if today < start:
            start = start.replace(year=year - 1)

    is_open = start <= today <= end
    days_remaining = (end - today).days if is_open else None

    if is_open:
        reason = (
            f"Today falls inside the recommended {crop} sowing window "
            f"({window['start']} to {window['end']}). {days_remaining} days left in the window."
        )
    elif today < start:
        reason = f"The {crop} sowing window opens on {window['start']}. It is too early to sow yet."
    else:
        reason = f"The {crop} sowing window for this cycle closed on {window['end']}. It is too late for this season."

    return SowingAdvice(
        sowing_window_open=is_open,
        window_start=window["start"],
        window_end=window["end"],
        days_remaining_in_window=days_remaining,
        reason=reason,
    )


@function_tool
def check_harvest_readiness(crop: str, sowing_date: str) -> HarvestAdvice:
    """Check whether a field is ready, or close to ready, for harvest.

    Args:
        crop: Crop name, e.g. "wheat", "cotton", "rice", "maize", "sugarcane".
        sowing_date: ISO date (YYYY-MM-DD) the crop was sown.
    """
    crops = load_crops()
    crop_key = crop.strip().lower()
    if crop_key not in crops:
        return HarvestAdvice(
            harvest_ready=False,
            days_since_sowing=0,
            maturity_days=0,
            days_remaining=0,
            reason=f"'{crop}' is not in the crop database yet.",
        )

    maturity_days = crops[crop_key]["maturity_days"]
    sowed = datetime.strptime(sowing_date, "%Y-%m-%d").date()
    days_since_sowing = (date.today() - sowed).days
    days_remaining = maturity_days - days_since_sowing
    ready = days_remaining <= 0

    if ready:
        reason = (
            f"{days_since_sowing} days have passed since sowing, past the "
            f"{maturity_days}-day maturity period for {crop}. The field should "
            f"be checked for harvest."
        )
    elif days_remaining <= 10:
        reason = f"Only {days_remaining} days remain until the typical {maturity_days}-day maturity for {crop}. Start preparing labour and storage."
    else:
        reason = f"{days_remaining} days remain until the typical maturity point for {crop}."

    return HarvestAdvice(
        harvest_ready=ready,
        days_since_sowing=days_since_sowing,
        maturity_days=maturity_days,
        days_remaining=max(days_remaining, 0),
        reason=reason,
    )


@function_tool
def find_govt_support(crop: str, province: str) -> GovtSupportAdvice:
    """Find government support schemes relevant to a crop and province.

    Args:
        crop: Crop name.
        province: Farmer's province, e.g. "Punjab", "Sindh".
    """
    schemes = load_schemes()
    crop_key = crop.strip().lower()
    matches = [
        s["name"]
        for s in schemes
        if (s["province"] in (province, "Federal"))
        and ("all" in s["applies_to"] or crop_key in s["applies_to"])
    ]
    if matches:
        reason = f"Found {len(matches)} scheme(s) relevant to {crop} growers in {province}."
    else:
        reason = f"No specific scheme found for {crop} in {province}; the federal ZTBL loan is generally available."
        matches = ["Zarai Taraqiati Bank (ZTBL) Agri Loan"]

    return GovtSupportAdvice(matching_schemes=matches, reason=reason)
