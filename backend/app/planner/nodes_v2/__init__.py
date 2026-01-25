"""
Nodes V2 Package - Simplified 6-Node Architecture.

This package contains the new "Core + Specialist" architecture nodes:

1. IntentRouter     - LLM (Fast): Classifies intent
2. TripArchitect    - LLM (Smart): The Core, manages TripPlan, calls tools
3. VerticalSpecialist - LLM (Expert): Domain logic for diving/skiing/hiking
4. ConstraintGuard  - Python: Deterministic validation
5. Synthesizer      - LLM (Writer): Unified response generation

Key Principles:
- "Flights/Hotels are NOT Agents" - They are data fetchers (tools)
- "Diving IS an Agent" - It requires domain logic
- "Architect sees the whole picture" - Avoids context fracture
"""

from app.planner.nodes_v2.constraint_guard import ConstraintGuard, constraint_guard
from app.planner.nodes_v2.intent_router import IntentClassification, intent_router
from app.planner.nodes_v2.synthesizer import Synthesizer, synthesizer
from app.planner.nodes_v2.trip_architect import TripArchitect, trip_architect
from app.planner.nodes_v2.vertical_specialist import VerticalSpecialist, vertical_specialist

__all__ = [
    # Node classes/schemas
    "IntentClassification",  # Schema for LLM classification output
    "TripArchitect",
    "VerticalSpecialist",
    "ConstraintGuard",
    "Synthesizer",
    # Node functions (for graph registration)
    "intent_router",
    "trip_architect",
    "vertical_specialist",
    "constraint_guard",
    "synthesizer",
]
