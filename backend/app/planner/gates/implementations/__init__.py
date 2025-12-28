"""Gate Implementations Package.

Contains individual gate classes extracted from GateEvaluator.evaluate().
Each gate is a separate class implementing the Gate interface.

Gates are listed in precedence order (13 active gates):
- 10: StrategyExpansionGate
- 20: GenerateRequestedGate
- 30: ShortCircuitGate, InfeasibilityGate
- 35: StrategyPostCoreGate
- 40: ReadyNoFieldsGate
- 50: FastPathGate
- 60: SpecialistPreCoreGate
- 70: StrategyTopicSwitchGate
- 80: StrategyPreCoreValueGate
- 90: CoreCollectionGate
- 110: QuestionKeywordGate
- 999: RouterLLMGate

Usage:
    from app.planner.gates.implementations import (
        StrategyExpansionGate,
        GenerateRequestedGate,
        ShortCircuitGate,
        ...
    )
"""

from app.planner.gates.implementations.core_collection import CoreCollectionGate
from app.planner.gates.implementations.fast_path import FastPathGate
from app.planner.gates.implementations.generate_requested import GenerateRequestedGate
from app.planner.gates.implementations.heuristic_gates import QuestionKeywordGate
from app.planner.gates.implementations.ready_no_fields import ReadyNoFieldsGate
from app.planner.gates.implementations.router_llm import RouterLLMGate
from app.planner.gates.implementations.short_circuit import InfeasibilityGate, ShortCircuitGate
from app.planner.gates.implementations.specialist_pre_core import SpecialistPreCoreGate
from app.planner.gates.implementations.strategy_expansion import StrategyExpansionGate
from app.planner.gates.implementations.strategy_post_core import StrategyPostCoreGate
from app.planner.gates.implementations.strategy_pre_core import StrategyPreCoreValueGate
from app.planner.gates.implementations.strategy_topic_switch import StrategyTopicSwitchGate

__all__ = [
    # Precedence 10
    "StrategyExpansionGate",
    # Precedence 20
    "GenerateRequestedGate",
    # Precedence 30
    "ShortCircuitGate",
    "InfeasibilityGate",
    # Precedence 35
    "StrategyPostCoreGate",
    # Precedence 40
    "ReadyNoFieldsGate",
    # Precedence 50
    "FastPathGate",
    # Precedence 60
    "SpecialistPreCoreGate",
    # Precedence 70
    "StrategyTopicSwitchGate",
    # Precedence 80
    "StrategyPreCoreValueGate",
    # Precedence 90
    "CoreCollectionGate",
    # Precedence 110
    "QuestionKeywordGate",
    # Precedence 999
    "RouterLLMGate",
]
