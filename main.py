"""
Kisan Dost — terminal entry point.

Run with:  python -m agent.main
This is the core deliverable the hackathon grades live: a terminal agent
built on the OpenAI Agents SDK, with sessions, structured tools, handoffs,
and guardrails all wired together.
"""

import asyncio
from datetime import date

from agents import InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered

from .models import FarmerProfile
from .kisan_agent import run_chat, make_session, build_daily_reminder


def collect_profile() -> FarmerProfile:
    print("=" * 60)
    print("  KISAN DOST — Farmer's Friend")
    print("=" * 60)
    print("Let's set up your field profile once. You won't be asked again.\n")

    name = input("Your name: ").strip() or "Farmer"
    district = input("District (e.g. Multan): ").strip() or "Multan"
    crop = input("Crop (wheat/cotton/rice/maize/sugarcane): ").strip() or "wheat"
    sowing_date = input("Sowing date (YYYY-MM-DD): ").strip() or date.today().isoformat()
    land_acres = float(input("Land size (acres): ").strip() or "5")
    soil_type = input("Soil type (clay/loamy/sandy/sandy-loam) [loamy]: ").strip() or "loamy"

    return FarmerProfile(
        name=name, district=district, crop=crop, sowing_date=sowing_date,
        land_acres=land_acres, soil_type=soil_type,  # type: ignore[arg-type]
    )


def print_daily_reminder(profile: FarmerProfile) -> None:
    reminder = build_daily_reminder(profile)
    print("\n" + "-" * 60)
    print(f"TODAY'S REMINDER — {reminder.date}")
    print("-" * 60)
    print(f"  {reminder.headline}\n")
    print(f"  Crop stage : {reminder.stage.stage_name} "
          f"(day {reminder.stage.days_since_sowing}, stage {reminder.stage.stage_number}/{reminder.stage.total_stages})")
    print(f"  Irrigation : {'YES, water today' if reminder.irrigation.needs_water_today else 'not needed today'} "
          f"[{reminder.irrigation.urgency}]")
    print(f"             -> {reminder.irrigation.reason}")
    if reminder.harvest:
        print(f"  Harvest    : {'READY NOW' if reminder.harvest.is_ready_to_harvest else f'in ~{reminder.harvest.days_to_harvest} days'}")
    for note in reminder.extra_notes:
        print(f"  Note       : {note}")
    print("-" * 60 + "\n")


async def main() -> None:
    profile = collect_profile()
    session = make_session(farmer_id=profile.name.lower().replace(" ", "_"))

    print_daily_reminder(profile)
    print("Ask me anything (irrigation, sowing time, harvest readiness). Type 'exit' to quit.\n")

    while True:
        user_input = input(f"{profile.name}> ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Khuda Hafiz! Kisan Dost is always here when you need it.")
            break
        if not user_input:
            continue
        try:
            reply = await run_chat(user_input, profile, session)
            print(f"Kisan Dost> {reply}\n")
        except InputGuardrailTripwireTriggered:
            print("Kisan Dost> Sorry, I can only help with farming questions — crops, water, sowing, "
                  "harvest, fertilizer, or market prices. Please rephrase.\n")
        except OutputGuardrailTripwireTriggered:
            print("Kisan Dost> I wasn't confident that answer was safe to give. Please contact your "
                  "nearest agriculture extension office for that specific question.\n")


if __name__ == "__main__":
    asyncio.run(main())
