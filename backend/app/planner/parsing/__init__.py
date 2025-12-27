"""
Parsing Package - Tier 4 Module Extraction.

This package consolidates parsing-related functions from plan_graph.py
for better organization and testability.

Modules:
    provenance: Parse provenance tracking with precedence enforcement
    lqa_parsers: LQA field-specific answer parsers
    deterministic: Zero-LLM deterministic parsing (pending extraction)

Usage:
    from app.planner.parsing import (
        # Provenance tracking
        set_parse_provenance_once,
        finalize_parse_provenance,
        get_parse_provenance,
        set_parse_provenance,  # deprecated
        PARSE_PROVENANCE_PRECEDENCE,

        # LQA parsers
        LQA_FIELD_PARSERS,
        _parse_destination_answer,
        _parse_origin_answer,
        _parse_date_answer,
        _parse_travelers_answer,
        _parse_budget_answer,
        _parse_duration_answer,
    )
"""

from app.planner.parsing.lqa_parsers import (
    _ACTIVITY_MODIFIER_WORDS,
    # Constants
    _ARTICLE_PREFIX,
    _LQA_FIELD_PARSERS,
    _MONTH_NAMES,
    _RELATIVE_DATE_WORDS,
    _STRATEGY_KEYWORDS,
    # Registry
    LQA_FIELD_PARSERS,
    LQAParserFunc,
    _is_activity_preference_text,
    # Detection helpers
    _is_date_like_text,
    _is_place_like_text,
    _parse_budget_answer,
    _parse_date_answer,
    # Parsers
    _parse_destination_answer,
    _parse_duration_answer,
    _parse_origin_answer,
    _parse_travelers_answer,
)
from app.planner.parsing.provenance import (
    PARSE_PROVENANCE_PRECEDENCE,
    finalize_parse_provenance,
    get_parse_provenance,
    set_parse_provenance,
    set_parse_provenance_once,
)

__all__ = [
    # Provenance tracking
    "PARSE_PROVENANCE_PRECEDENCE",
    "set_parse_provenance_once",
    "finalize_parse_provenance",
    "get_parse_provenance",
    "set_parse_provenance",
    # LQA constants
    "_ARTICLE_PREFIX",
    "_MONTH_NAMES",
    "_RELATIVE_DATE_WORDS",
    "_ACTIVITY_MODIFIER_WORDS",
    "_STRATEGY_KEYWORDS",
    # LQA detection helpers
    "_is_date_like_text",
    "_is_place_like_text",
    "_is_activity_preference_text",
    # LQA parsers
    "_parse_destination_answer",
    "_parse_origin_answer",
    "_parse_date_answer",
    "_parse_travelers_answer",
    "_parse_budget_answer",
    "_parse_duration_answer",
    # LQA registry
    "LQA_FIELD_PARSERS",
    "_LQA_FIELD_PARSERS",
    "LQAParserFunc",
]
