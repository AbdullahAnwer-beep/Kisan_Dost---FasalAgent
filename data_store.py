"""
Tiny file-based persistence layer.

For a hackathon / demo build, a JSON file is a deliberate choice over a
real database: it needs zero setup, is easy to inspect, and is trivial
to swap for SQLite/Postgres later without touching the agent or API code.
"""

import json
import os
from pathlib import Path
from typing import Optional

from agent.models import FarmerProfile

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
FARMERS_FILE = DATA_DIR / "farmers.json"
CROPS_FILE = DATA_DIR / "crops.json"
SCHEMES_FILE = DATA_DIR / "schemes.json"

DATA_DIR.mkdir(exist_ok=True)
if not FARMERS_FILE.exists():
    FARMERS_FILE.write_text("{}")


def load_crops() -> dict:
    return json.loads(CROPS_FILE.read_text())


def load_schemes() -> list:
    return json.loads(SCHEMES_FILE.read_text())


def _read_farmers() -> dict:
    return json.loads(FARMERS_FILE.read_text())


def _write_farmers(data: dict) -> None:
    FARMERS_FILE.write_text(json.dumps(data, indent=2, default=str))


def save_farmer(profile: FarmerProfile) -> None:
    if not profile.farmer_id:
        raise ValueError("Farmer profile must have a farmer_id")
    data = _read_farmers()
    data[profile.farmer_id] = json.loads(profile.model_dump_json())
    _write_farmers(data)


def get_farmer(farmer_id: str) -> Optional[FarmerProfile]:
    data = _read_farmers()
    record = data.get(farmer_id)
    if not record:
        return None
    return FarmerProfile(**record)


def list_farmers() -> list[FarmerProfile]:
    data = _read_farmers()
    return [FarmerProfile(**record) for record in data.values()]
