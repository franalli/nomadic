"""
Nodes Package - Planner Agent Architecture.

This package contains the planner execution nodes:

- VerticalSpecialist - LLM (Expert): Domain logic for diving/skiing/hiking
- LocalExpert        - LLM/Static: City logistics and tips
- LogisticsNode      - Data Fetcher: Flight/hotel fetching with safety logic
- ConstraintGuard    - Python: Deterministic validation
- RouterExtraction   - LLM: Intent classification and field extraction

Deleted nodes (replaced by create_agent + tools architecture):
- IntentRouter (replaced by extract_trip_fields tool)
- TripArchitect (replaced by planner agent)
- Synthesizer (replaced by planner agent direct responses)
"""

from app.planner.nodes.constraint_guard import ConstraintGuard, constraint_guard
from app.planner.nodes.local_expert import local_expert
from app.planner.nodes.logistics_node import logistics_node
from app.planner.nodes.vertical_specialist import VerticalSpecialist, vertical_specialist

__all__ = [
    # Node classes/schemas
    "VerticalSpecialist",
    "ConstraintGuard",
    # Node functions (used by tools)
    "vertical_specialist",
    "local_expert",
    "logistics_node",
    "constraint_guard",
]
