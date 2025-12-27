"""
Specialist Subpackage - Modular specialist node components.

This package contains extracted components from the monolithic specialist_main.py:
- base.py: Constants, prompt selection, pre-core mode handling
- guards.py: Core field guard, default adults gate, no-op gate
- templates.py: Template-first approach for required_fields

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
    handle_pre_core_mode,
    select_required_fields_prompt,
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
from app.planner.nodes.specialist.templates import (
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
    "select_required_fields_prompt",
    "get_skip_fields_for_specialist",
    "handle_pre_core_mode",
    # Guards
    "GUARDED_SPECIALISTS",
    "NOOP_GATE_SPECIALISTS",
    "check_core_field_guard",
    "check_default_adults_gate",
    "check_noop_gate",
    "apply_noop_gate_response",
    "check_domain_keyword_for_default_adults",
    # Templates
    "determine_question_target",
    "check_requires_llm",
    "apply_template_response",
    "handle_loop_guard",
]
