"""
Pydantic schemas for LLM output validation in planner nodes.

These schemas provide type-safe parsing of LLM responses for:
- ExtractorOutput: Structured trip data extraction
- RouterOutput: Intent classification

Design decisions:
- extra="ignore": LLMs sometimes add unexpected fields; we ignore them
- Optional fields with defaults: Graceful handling of missing data
- Literal for enums: Simpler than Enum classes, good IDE support
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Extractor Output Schema
# =============================================================================


class BudgetDelta(BaseModel):
    """Budget information from user input."""

    budget: int = Field(ge=0)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")

    model_config = ConfigDict(extra="ignore")


class ExtractorOutput(BaseModel):
    """
    Structured output from the extractor LLM.

    All fields are optional since the LLM only extracts what's present
    in the user's message. Fields use _delta suffix to indicate they
    represent changes to apply, not absolute values.
    """

    destinations_delta: Optional[list[str]] = None
    origin_delta: Optional[str] = None
    start_date_hint: Optional[str] = None
    end_date_hint: Optional[str] = None
    duration_days: Optional[int] = Field(default=None, ge=1)
    adults_delta: Optional[int] = Field(default=None, ge=1)
    children_delta: Optional[int] = Field(default=None, ge=0)
    requires_assistance_delta: Optional[bool] = None
    budget_delta: Optional[BudgetDelta] = None
    multi_city_intent_delta: Optional[Literal["multi_city", "separate"]] = None
    # Accepts both formats: ["flights", "hotels"] or {"flights": true, "hotels": true}
    category_activation: Optional[Union[list[str], dict[str, bool]]] = None
    flight_settings_delta: Optional[dict] = None
    hotel_settings_delta: Optional[dict] = None
    transport_settings_delta: Optional[dict] = None
    activity_categories_delta: Optional[list[str]] = None
    strategy_hint: Optional[str] = None
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    confidence_reasons: Optional[list[str]] = None

    model_config = ConfigDict(extra="ignore")


# =============================================================================
# Router Output Schema
# =============================================================================

# Intent types that the router can classify
IntentType = Literal[
    "required_fields",
    "flights",
    "hotels",
    "transport",
    "activities",
    "correction_needed",
    "strategy",
    "general",
    "off_topic",
]

# Strategy topics
TopicType = Literal["boating", "hiking", "diving", "skiing", "cycling"]

# User intent archetypes for conversational style adaptation
UserIntentType = Literal[
    "quick_booking",
    "short_trip",
    "adventurous",
    "undecided",
    "detailed_planner",
]


class RouterOutput(BaseModel):
    """
    Structured output from the router LLM.

    Determines user intent and routes to the appropriate next node.
    """

    intent: IntentType = "required_fields"
    topic: Optional[TopicType] = None
    user_intent: Optional[UserIntentType] = None
    notes: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    model_config = ConfigDict(extra="ignore")
