"""
Specialist Subpackage - Modular specialist node components.

This package contains extracted components from the monolithic specialist_main.py:
- base.py: Constants, field handling
- guards.py: Core field guard, default adults gate, no-op gate
- templates.py: Template-first approach for required_fields, pre-core mode
- groundedness.py: Groundedness guardrail for tile-based specialists (P3)
- response_processor.py: LLM response parsing and validation (P3)

The main _specialist function is in nodes/specialist_main.py and re-exported here
for backward compatibility.
"""

# Re-export the main _specialist function for backward compatibility
from app.planner.nodes.specialist.base import (
    CORE_FIELDS,
    CORRECTION_ALLOWED_FIELDS,
    CORRECTION_SKIP_FIELDS,
    QUESTION_TARGET_FIELD_MAP,
    SPECIALIST_TYPES,
    get_skip_fields_for_specialist,
)
from app.planner.nodes.specialist.groundedness import (
    TILE_BASED_SPECIALISTS,
    check_groundedness_guardrail,
)
from app.planner.nodes.specialist.guards import (
    GUARDED_SPECIALISTS,
    NOOP_GATE_SPECIALISTS,
    apply_noop_gate_response,
    check_core_field_guard,
    check_default_adults_gate,
    check_domain_keyword_for_default_adults,
    check_noop_gate,
)
from app.planner.nodes.specialist.response_processor import (
    QUESTION_TARGET_FIELD_CHECK,
    cache_required_fields_response,
    get_skip_fields,
    process_llm_response,
    validate_question_target,
)
from app.planner.nodes.specialist.templates import (
    TOPIC_ACKNOWLEDGMENTS,
    apply_pre_core_template_response,
    apply_template_response,
    check_requires_llm,
    determine_question_target,
    handle_loop_guard,
)
from app.planner.nodes.specialist_main import (
    _invoke_missing_fields_guard,
    _select_required_fields_prompt,
    _specialist,
)

__all__ = [
    # Main functions (re-exported from specialist_main.py)
    "_specialist",
    "_invoke_missing_fields_guard",
    "_select_required_fields_prompt",
    # Base
    "CORE_FIELDS",
    "CORRECTION_ALLOWED_FIELDS",
    "CORRECTION_SKIP_FIELDS",
    "SPECIALIST_TYPES",
    "QUESTION_TARGET_FIELD_MAP",
    "get_skip_fields_for_specialist",
    # Guards
    "GUARDED_SPECIALISTS",
    "NOOP_GATE_SPECIALISTS",
    "check_core_field_guard",
    "check_default_adults_gate",
    "check_noop_gate",
    "apply_noop_gate_response",
    "check_domain_keyword_for_default_adults",
    # Templates
    "TOPIC_ACKNOWLEDGMENTS",
    "determine_question_target",
    "check_requires_llm",
    "apply_template_response",
    "apply_pre_core_template_response",
    "handle_loop_guard",
    # Groundedness (P3)
    "TILE_BASED_SPECIALISTS",
    "check_groundedness_guardrail",
    # Response Processor (P3)
    "QUESTION_TARGET_FIELD_CHECK",
    "get_skip_fields",
    "validate_question_target",
    "process_llm_response",
    "cache_required_fields_response",
]
