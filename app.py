"""
Kisan Dost — FastAPI backend (bonus deliverable).

Wraps the terminal agent behind a small HTTP API so the frontend
dashboard can show a farmer their daily reminder and let them chat.
Run with:  uvicorn backend.app:app --reload --port 8000
"""

from __future__ import annotations
import sys, os
from typing import Literal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from agents import InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered

from agent.models import FarmerProfile, DailyReminder
from agent.kisan_agent import run_chat, fallback_chat, make_session, build_daily_reminder
from backend.data_store import get_farmer, list_farmers, save_farmer

load_dotenv()

app = FastAPI(title="Kisan Dost API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your frontend's real origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Profiles are persisted to backend/data/farmers.json. Sessions are backed by
# SQLite and are recreated here after a backend restart.
_profiles: dict[str, FarmerProfile] = {
    profile.farmer_id: profile for profile in list_farmers() if profile.farmer_id
}
_sessions: dict[str, object] = {
    farmer_id: make_session(farmer_id) for farmer_id in _profiles
}


class RegisterRequest(BaseModel):
    farmer_id: str
    name: str
    district: str
    crop: str
    sowing_date: str
    land_acres: float
    soil_type: str = "loamy"
    water_source: str = "canal"


class ChatRequest(BaseModel):
    farmer_id: str
    message: str
    language: Literal["en", "ur"] = "en"


@app.post("/farmer/register")
def register_farmer(req: RegisterRequest) -> dict:
    profile = FarmerProfile(
        farmer_id=req.farmer_id,
        name=req.name, district=req.district, crop=req.crop, sowing_date=req.sowing_date,
        land_acres=req.land_acres, soil_type=req.soil_type, water_source=req.water_source,  # type: ignore[arg-type]
    )
    save_farmer(profile)
    _profiles[req.farmer_id] = profile
    _sessions[req.farmer_id] = make_session(req.farmer_id)
    return {"status": "ok", "farmer_id": req.farmer_id}


@app.get("/reminder/today/{farmer_id}", response_model=DailyReminder)
def reminder_today(farmer_id: str) -> DailyReminder:
    profile = _profiles.get(farmer_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Farmer not registered. Call /farmer/register first.")
    return build_daily_reminder(profile)


@app.post("/chat")
async def chat(req: ChatRequest) -> dict:
    profile = _profiles.get(req.farmer_id)
    session = _sessions.get(req.farmer_id)
    if not profile or not session:
        raise HTTPException(status_code=404, detail="Farmer not registered. Call /farmer/register first.")
    try:
        reply = await run_chat(req.message, profile, session, req.language)
        return {"reply": reply}
    except InputGuardrailTripwireTriggered:
        return {"reply": "Sorry, I can only help with farming questions. Please rephrase."}
    except OutputGuardrailTripwireTriggered:
        return {"reply": "That answer wasn't safe to give — please contact your local agriculture office."}
    except Exception:
        return {"reply": fallback_chat(req.message, profile, req.language)}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
