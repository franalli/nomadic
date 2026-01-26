"""
Nodes V2 Package - 7-Node Architecture.

This package contains the new "Core + Specialist" architecture nodes:

1. IntentRouter       - LLM (Fast): Classifies intent, detects specialist hints
2. TripArchitect      - LLM (Smart): The Core, manages TripPlan, calls tools
3. VerticalSpecialist - LLM (Expert): Domain logic for diving/skiing/hiking
4. LocalExpert        - LLM/Static: City logistics and tips (default fallback)
5. LogisticsNode      - Data Fetcher: Flight fetching with safety logic
6. ConstraintGuard    - Python: Deterministic validation
7. Synthesizer        - LLM (Writer): Unified response generation

Key Principles:
- "Flights/Hotels are NOT Agents" - They are data fetchers (LogisticsNode + TileService)
- "Diving IS an Agent" - It requires domain logic (VerticalSpecialist)
- "Architect sees the whole picture" - Avoids context fracture
- "Local Expert Fallback" - Generic trips always have content via LocalExpert
"""

from app.planner.nodes_v2.constraint_guard import ConstraintGuard, constraint_guard
from app.planner.nodes_v2.intent_router import IntentClassification, intent_router
from app.planner.nodes_v2.local_expert import local_expert
from app.planner.nodes_v2.logistics_node import logistics_node
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
    "local_expert",
    "logistics_node",
    "constraint_guard",
    "synthesizer",
]
