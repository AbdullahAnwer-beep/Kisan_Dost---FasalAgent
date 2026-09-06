"""
Structured output models for Kisan Dost.

Every tool and every agent returns one of these typed objects instead of
loose text. This is what the hackathon brief calls out as the difference
between a "Pass" build and a "Good" build.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class FarmerProfile(BaseModel):
    """Carried as typed context across the whole session so the farmer
    never has to repeat district / land size / crop again."""
    farmer_id: str = ""
    name: str = "Farmer"
    district: str
    province: Literal["Punjab", "Sindh", "KPK", "Balochistan", "Other"] = "Punjab"
    crop: str
    sowing_date: str  # ISO format YYYY-MM-DD
    land_acres: float
    soil_type: Literal["clay", "loamy", "sandy", "sandy-loam", "unknown"] = "unknown"
    water_source: Literal["canal", "tube-well", "rain-fed", "unknown"] = "unknown"


class CropStage(BaseModel):
    crop: str
    days_since_sowing: int
    stage_name: str
    stage_number: int
    total_stages: int
    days_remaining_in_stage: int
    notes: str


class IrrigationAdvice(BaseModel):
    needs_water_today: bool
    urgency: Literal["none", "low", "medium", "high", "critical"]
    reason: str
    recommended_action: str
    next_check_in_days: int


class SowingAdvice(BaseModel):
    is_good_time_to_sow: bool
    crop: str
    season: Literal["Rabi", "Kharif"]
    reason: str
    ideal_window: str


class HarvestAdvice(BaseModel):
    is_ready_to_harvest: bool
    days_to_harvest: int
    reason: str
    recommended_action: str


class DailyReminder(BaseModel):
    """The single message shown to the farmer each day — the whole point
    of the product."""
    farmer_name: str
    district: str
    crop: str
    date: str
    headline: str
    irrigation: IrrigationAdvice
    stage: CropStage
    harvest: Optional[HarvestAdvice] = None
    extra_notes: list[str] = Field(default_factory=list)


class GuardrailCheck(BaseModel):
    is_allowed: bool
    reason: str
