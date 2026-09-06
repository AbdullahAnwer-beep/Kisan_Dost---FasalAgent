"""
Kisan Dost — agent graph.

    Triage Agent
        |-- Irrigation & Field-Status Agent  (water today? seed time? harvest ready?)
        |-- Sowing Agent
        |-- Harvest Agent

This is intentionally focused on the reminder use case (water / seed /
harvest) rather than the full 7-tool hackathon scope, per what was asked.
Each specialist is a small agent with its own tools and a structured
output type, wired together with handoffs and shared guardrails.
"""

from __future__ import annotations
from datetime import date, datetime

from dotenv import load_dotenv
from agents import Agent, Runner, SQLiteSession

from .models import FarmerProfile, DailyReminder, CropStage, IrrigationAdvice, HarvestAdvice
from .tools import (
    get_crop_stage, get_weather_forecast, check_irrigation_need,
    check_sowing_time, check_harvest_readiness,
)
from .guardrails import farming_topic_guardrail, safety_output_guardrail
from .data.crop_calendar import (
    CROP_STAGES, HARVEST_DAYS, IRRIGATION_INTERVAL_DAYS, CRITICAL_STAGES,
    normalize_crop,
)

load_dotenv()

MODEL = "gpt-4o-mini"

irrigation_agent = Agent[FarmerProfile](
    name="Irrigation Agent",
    handoff_description="Decides if the farmer's field needs water today, using weather + crop stage + soil type.",
    instructions=(
        "You are Kisan Dost's irrigation specialist. Use get_weather_forecast to check today's real "
        "weather for the farmer's district, then use get_crop_stage and check_irrigation_need to decide "
        "if the field needs water today. Always state the reason in one clear sentence a farmer can act on. "
        "Be direct: say clearly whether to irrigate today or not."
    ),
    tools=[get_weather_forecast, get_crop_stage, check_irrigation_need],
    model=MODEL,
)

sowing_agent = Agent[FarmerProfile](
    name="Sowing Agent",
    handoff_description="Tells the farmer if now is the right time to sow a given crop.",
    instructions=(
        "You are Kisan Dost's sowing-calendar specialist. Use check_sowing_time to tell the farmer whether "
        "today is inside the ideal sowing window for their crop and season, and what the ideal window is."
    ),
    tools=[check_sowing_time],
    model=MODEL,
)

harvest_agent = Agent[FarmerProfile](
    name="Harvest Agent",
    handoff_description="Tells the farmer if their crop is ready to harvest, or how many days remain.",
    instructions=(
        "You are Kisan Dost's harvest-readiness specialist. Use check_harvest_readiness and get_crop_stage "
        "to tell the farmer clearly whether to harvest now or wait, and for how long."
    ),
    tools=[check_harvest_readiness, get_crop_stage],
    model=MODEL,
)

triage_agent = Agent[FarmerProfile](
    name="Kisan Dost Triage Agent",
    instructions=(
        "You are Kisan Dost ('Farmer's Friend'), a warm, practical AI agronomy assistant for Pakistani "
        "farmers. Farmers may write in English, Urdu, or Roman Urdu (Urdu written in English letters) — "
        "reply in whichever style they used, in short, plain, actionable sentences. No jargon. "
        "Route irrigation/water questions to the Irrigation Agent, sowing/seed-timing questions to the "
        "Sowing Agent, and harvest-readiness questions to the Harvest Agent. If the farmer just says "
        "hello or asks for today's summary, greet them briefly and check all three yourself. Never give "
        "advice about human health, and never invent numbers you are not confident about — say so plainly "
        "if you are unsure and suggest contacting the nearest agriculture extension office."
    ),
    handoffs=[irrigation_agent, sowing_agent, harvest_agent],
    input_guardrails=[farming_topic_guardrail],
    output_guardrails=[safety_output_guardrail],
    model=MODEL,
)


def make_session(farmer_id: str) -> SQLiteSession:
    """One persistent SQLite-backed session per farmer, so their district,
    crop, and land size are remembered across turns without re-asking."""
    return SQLiteSession(session_id=f"kisan_dost_{farmer_id}", db_path="kisan_dost_sessions.db")


async def run_chat(message: str, profile: FarmerProfile, session: SQLiteSession, language: str = "en") -> str:
    language_instruction = (
        " Reply entirely in Urdu script. Use simple words suitable for a farmer."
        if language == "ur" else " Reply in English."
    )
    result = await Runner.run(
        triage_agent, message + language_instruction, context=profile, session=session,
    )
    return result.final_output if isinstance(result.final_output, str) else str(result.final_output)


def fallback_chat(message: str, profile: FarmerProfile, language: str = "en") -> str:
    """Give useful calendar-based answers when the model service is unavailable."""
    text = message.lower()
    reminder = build_daily_reminder(profile)

    if language == "ur":
        if any(word in text for word in ("irrigat", "water", "paani", "پانی")):
            advice = reminder.irrigation
            action = "آج آبپاشی کریں۔" if advice.needs_water_today else "آج آبپاشی کی ضرورت نہیں۔"
            return f"{action} اگلی بار تقریباً {advice.next_check_in_days} دن بعد دوبارہ جائزہ لیں۔"
        if any(word in text for word in ("harvest", "ready", "cut", "برداشت")):
            return "فصل برداشت کے لیے تیار ہے۔ کھیت کا معائنہ کریں اور کٹائی کی تیاری کریں۔" if reminder.harvest.is_ready_to_harvest else f"فصل ابھی تیار نہیں ہے۔ تقریباً {reminder.harvest.days_to_harvest} دن باقی ہیں۔"
        if any(word in text for word in ("sow", "sowing", "seed", "plant", "بوائی")):
            return "آپ کی فصل اس وقت بڑھنے کے مرحلے میں ہے۔ نئی فصل کی بوائی کے لیے فصل کا نام بتائیں۔"
        if any(word in text for word in ("today", "summary", "status", "update", "آج", "حالت")):
            water = "آج آبپاشی کریں۔" if reminder.irrigation.needs_water_today else "آج آبپاشی کی ضرورت نہیں۔"
            harvest = "فصل برداشت کے لیے تیار ہے۔" if reminder.harvest.is_ready_to_harvest else "فصل ابھی برداشت کے لیے تیار نہیں۔"
            return f"آج کی صورت حال: {water} {harvest}"
        if any(word in text for word in ("hello", "hi", "salam", "assalam", "سلام")):
            return f"السلام علیکم {profile.name}۔ آپ کی فصل بڑھنے کے مرحلے میں ہے۔ پانی، بوائی یا برداشت کے بارے میں سوال کریں۔"
        return "میں آبپاشی، بوائی، فصل کے مرحلے، برداشت اور کھیتی کے موسم کے بارے میں مدد کر سکتا ہوں۔"

    if any(word in text for word in ("irrigat", "water", "paani", "پانی")):
        advice = reminder.irrigation
        return f"{advice.recommended_action} {advice.reason} Check again in about {advice.next_check_in_days} days."
    if any(word in text for word in ("harvest", "ready", "cut", "برداشت")):
        advice = reminder.harvest
        return f"{advice.recommended_action} {advice.reason}"
    if any(word in text for word in ("sow", "sowing", "seed", "plant", "بوائی")):
        return (
            f"Your field currently has {profile.crop} planted, at the {reminder.stage.stage_name} stage. "
            "For a new crop, tell me the crop name and I will check its sowing window."
        )
    if any(word in text for word in ("today", "summary", "status", "update")):
        return f"{reminder.headline} {reminder.irrigation.recommended_action} {reminder.harvest.recommended_action}"
    if any(word in text for word in ("hello", "hi", "salam", "assalam")):
        return f"Hello {profile.name}. Your {profile.crop} is in the {reminder.stage.stage_name} stage. Ask me about water, sowing, or harvest."
    return (
        "I can help with irrigation, sowing time, crop stage, harvest readiness, and farm weather. "
        "Please ask one of those questions."
    )


def build_daily_reminder(profile: FarmerProfile) -> DailyReminder:
    """Deterministic (non-LLM) daily reminder assembled directly from the
    tool functions — used by the /reminder/today API endpoint and the
    frontend dashboard so it's instant and doesn't need a model call.
    Assumes the field was last irrigated `last_irrigation_days_ago` days
    ago; the frontend/CLI collects that one number from the farmer.
    """
    crop_key = normalize_crop(profile.crop)
    days_since_sowing = max((date.today() - datetime.strptime(profile.sowing_date, "%Y-%m-%d").date()).days, 0)
    stages = CROP_STAGES.get(crop_key, [])
    running_days = 0
    stage_name = "unknown"
    stage_number = 0
    days_remaining = 0
    for number, (name, length) in enumerate(stages, start=1):
        if days_since_sowing <= running_days + length:
            stage_name, stage_number = name, number
            days_remaining = running_days + length - days_since_sowing
            break
        running_days += length
    if stages and stage_name == "unknown":
        stage_name, stage_number = "Past maturity", len(stages)
    stage = CropStage(
        crop=crop_key, days_since_sowing=days_since_sowing, stage_name=stage_name,
        stage_number=stage_number, total_stages=len(stages),
        days_remaining_in_stage=days_remaining, notes=f"{crop_key.title()} is {days_since_sowing} days old.",
    )
    interval = IRRIGATION_INTERVAL_DAYS.get(crop_key, IRRIGATION_INTERVAL_DAYS["wheat"]).get(profile.soil_type, 14)
    needs_water = 7 >= interval
    urgency = "medium" if needs_water else "low"
    irrigation = IrrigationAdvice(
        needs_water_today=needs_water, urgency=urgency,
        reason=f"The field was last assumed irrigated 7 days ago; the usual gap is about {interval} days.",
        recommended_action="Irrigate today." if needs_water else "No irrigation needed today.",
        next_check_in_days=max(interval - 7, 1),
    )
    harvest_days = HARVEST_DAYS.get(crop_key, 0)
    harvest = HarvestAdvice(
        is_ready_to_harvest=bool(harvest_days and days_since_sowing >= harvest_days),
        days_to_harvest=max(harvest_days - days_since_sowing, 0) if harvest_days else -1,
        reason=f"{crop_key.title()} is {days_since_sowing} days into its {harvest_days}-day cycle.",
        recommended_action="Inspect the field and plan harvest." if harvest_days and days_since_sowing >= harvest_days else "Continue monitoring the crop.",
    )

    notes = []
    if harvest.is_ready_to_harvest:
        headline = f"Your {crop_key} is ready — plan the harvest."
    elif irrigation.needs_water_today:
        headline = f"Your field needs water today ({irrigation.urgency} urgency)."
    else:
        headline = f"No action needed today — {crop_key} is in the {stage.stage_name} stage."
        notes.append(f"Next irrigation check suggested in about {irrigation.next_check_in_days} days.")

    return DailyReminder(
        farmer_name=profile.name, district=profile.district, crop=crop_key,
        date=date.today().isoformat(), headline=headline,
        irrigation=irrigation, stage=stage, harvest=harvest, extra_notes=notes,
    )
