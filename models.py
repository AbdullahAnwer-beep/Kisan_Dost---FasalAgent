"""
Structured data models for Kisan Dost — Field Reminder Agent.

Every tool returns one of these typed models instead of loose text,
so the agent's output is predictable and the frontend can render it
without parsing free-form strings.
"""

from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field


class FarmerProfile(BaseModel):
    """The context object carried across a farmer's whole session."""
    farmer_id: str
    name: str
    district: str
    province: str
    crop: str
    season: Literal["Rabi", "Kharif"]
    land_acres: float
    sowing_date: date
    last_irrigation_date: date


class WaterAdvice(BaseModel):
    water_needed_today: bool
    days_since_last_irrigation: int
    recommended_interval_days: int
    growth_stage: str
    rainfall_expected_mm_next_3_days: float
    reason: str


class SowingAdvice(BaseModel):
    sowing_window_open: bool
    window_start: str
    window_end: str
    days_remaining_in_window: Optional[int]
    reason: str


class HarvestAdvice(BaseModel):
    harvest_ready: bool
    days_since_sowing: int
    maturity_days: int
    days_remaining: int
    reason: str


class GovtSupportAdvice(BaseModel):
    matching_schemes: list[str]
    reason: str


class FieldAdvisory(BaseModel):
    """The combined 'today's advisory slip' shown on the dashboard."""
    farmer_id: str
    generated_on: date
    water: WaterAdvice
    sowing: SowingAdvice
    harvest: HarvestAdvice
    govt_support: GovtSupportAdvice
