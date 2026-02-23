from __future__ import annotations

# This file is generated from JSON Schema. Do not edit manually.

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Agent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    organization: Optional[str] = None
    email: Optional[EmailStr] = None
    orcid: Optional[str] = None


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[str] = Field(default=None, description="ISO 8601 date-time")
    created_by: Optional[Agent] = None
    source: Optional[str] = None


class Quantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str
    unit_uri: Optional[str] = None


class Battery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["cell", "module", "pack", "system"]
    chemistry: Optional[str] = None
    manufacturer: Optional[Agent] = None
    nominal_capacity: Optional[Quantity] = None
    nominal_voltage: Optional[Quantity] = None
    mass: Optional[Quantity] = None


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    property: Optional[str] = None
    quantity: Quantity
    method: Optional[str] = None
    timestamp: Optional[str] = None


class BattinfoDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    battinfo_version: str
    profile: Optional[str] = None
    record: Record
    battery: Battery
    measurements: Optional[list[Measurement]] = None
