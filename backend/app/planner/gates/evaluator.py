"""
GateEvaluator - Centralized gate evaluation for routing decisions.

This module contains the GateEvaluator class extracted from plan_graph.py.
All routing gates are evaluated here in priority order.

Usage:
    from app.planner.gates import GateEvaluator
    result = GateEvaluator.evaluate(state)
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.config import settings
from app.debug_utils import _debug
from app.known_places import is_known_place
from app.pattern_matching import (
    DOMAIN_KEYWORDS,
    ENTITY_DETECTION_PATTERN,
    INTENT_ONLY_KEYWORDS,
    QUESTION_WORDS,
    QUESTIONS_ONLY_PHRASES,
    TOPIC_SWITCH_INTENT_VERBS,
    TOPIC_SWITCH_OVERRIDE_PHRASES,
    is_text_date_compatible,
)
from app.planner.gates.checks import is_strategy_expansion_request
from app.planner.gates.constants import DATE_BLOCKING_ERROR_CODES
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.readiness import TripReadiness, compute_trip_readiness
from app.planner.gates.result import GateResult
from app.planner.gates.suppression import SuppressionPredicates
from app.planner.gates.topic_detection import (
    ALL_STRATEGY_KEYWORDS,
    detect_strategy_topic,
    detect_strategy_topic_from_text,
)
from app.schemas import ErrorRecord

# Late imports from plan_graph.py are done inside methods to avoid circular dependencies

if TYPE_CHECKING:
    from app.plan_graph import GraphState, TripInputs

# =============================================================================
# CONSTANTS (duplicated from plan_graph.py for module self-containment)
# =============================================================================

# Confidence threshold for router bypass
CONFIDENCE_THRESHOLD_SKIP_ROUTER = settings.confidence_threshold_skip_router

# Strategy topic to node mapping
STRATEGY_TOPIC_TO_NODE: Dict[str, str] = {
    "hiking": "strategy_node",
    "diving": "strategy_node",
    "skiing": "strategy_node",
    "cycling": "strategy_node",
    "boating": "strategy_node",
}


class GateEvaluator:
    """
    Centralized gate evaluator for routing decisions.

    All routing gates are evaluated here in priority order.
    Nodes should read the GateResult from state rather than re-deriving conditions.
    """

    # Phase 6: Question words that, combined with domain keywords, indicate clear intent
    # NOTE: These are now imported from pattern_matching.py at module level.
    # Class-level aliases are kept for backward compatibility with tests.
    QUESTION_WORDS = QUESTION_WORDS  # Alias to module-level import
    INTENT_ONLY_KEYWORDS = INTENT_ONLY_KEYWORDS  # Alias to module-level import

    # NOTE: QUESTION_WORDS, DOMAIN_KEYWORDS, INTENT_ONLY_KEYWORDS
    # are now imported from pattern_matching.py
    # The class uses module-level imports, but class-level aliases
    # are kept for test compatibility.

    @classmethod
    def evaluate(cls, state: "GraphState") -> GateResult:
        """
        Evaluate all gates and return the result.

        This is the ONLY place where routing decisions should be made.

        Args:
            state: Current graph state

        Returns:
            GateResult with gate_fired, destination, and metadata
        """
        # Late imports to avoid circular dependencies
        from app.plan_graph import (
            NormalizationError,
            _date_stats,
            _detect_intent_from_keywords,
            _has_infeasibility_signals,
            _try_deterministic_router,
        )

        start_time = time.perf_counter()
        skipped_gates = []

        # P0: Gate trace for debugging - records each gate checked with result
        gate_trace: List[Dict[str, Any]] = []

        def record_gate(
            gate_name: str,
            fired: bool,
            reason: str,
            suppressed: bool = False,
            suppression_reason: Optional[str] = None,
        ) -> None:
            """Record a gate evaluation in the trace."""
            gate_trace.append(
                {
                    "gate": gate_name,
                    "fired": fired,
                    "reason": reason,
                    "suppressed": suppressed,
                    "suppression_reason": suppression_reason,
                    "elapsed_ms": (time.perf_counter() - start_time) * 1000,
                }
            )

        # Extract commonly used values
        user_text = state.user_text or ""
        user_text_lower = user_text.lower()
        ti = state.trip_inputs
        flags = state.flags
        extraction_conf = state.metadata.get("extraction_confidence", {})

        # Determine if we should prefer dates over destinations for question ordering
        # This applies when: strategy topic detected but no destinations extracted
        prefer_date_first = cls._should_prefer_date_first(user_text_lower, ti)

        # Use TripReadiness for consistent missing-fields computation
        # Pass metadata to respect budget_answered flag
        readiness = compute_trip_readiness(
            ti, prefer_date_first=prefer_date_first, metadata=state.metadata
        )

        # =====================================================================
        # Gate 0: STRATEGY_EXPANSION (Precedence 10)
        # =====================================================================
        # When user requests expansion on existing strategy content (e.g., "Show more details")
        # This takes highest priority to avoid the READY_NO_FIELDS gate consuming these requests.
        # Triggers when:
        # 1. pending_strategy_expansion is True (stage 1 was completed)
        # 2. User text matches expansion triggers ("show more details", "expand", etc.)
        # =====================================================================
        if state.pending_strategy_expansion:
            expansion_result = is_strategy_expansion_request(user_text)
            if expansion_result.is_expansion:
                # Get the last strategy topic for routing
                last_topic = state.metadata.get("last_strategy_topic", "hiking")
                record_gate("STRATEGY_EXPANSION", True, f"expansion_request:{last_topic}")
                _debug(
                    "STRATEGY_EXPANSION gate triggered",
                    topic=last_topic,
                    expansion_target=expansion_result.target,
                    expansion_tier=expansion_result.tier,
                    matched_phrase=expansion_result.matched_phrase,
                )
                return cls._build_result(
                    gate=GatePrecedence.STRATEGY_EXPANSION,
                    destination="strategy_node",
                    reason=f"strategy_expansion:{last_topic}:{expansion_result.matched_phrase}",
                    start_time=start_time,
                    skipped=skipped_gates,
                    state=state,
                    intent="strategy",
                    strategy_topic=last_topic,
                    metadata_updates={
                        "router_path": f"strategy_expansion:{last_topic}",
                        "router_bypassed": True,
                        "strategy_stage": 2,
                        "expansion_target": (
                            expansion_result.target.value if expansion_result.target else None
                        ),
                        "expansion_tier": (
                            expansion_result.tier.value if expansion_result.tier else None
                        ),
                        "user_request_type": "expand",
                    },
                    gate_trace=gate_trace,
                )
            record_gate("STRATEGY_EXPANSION", False, "no_expansion_request")
        else:
            record_gate("STRATEGY_EXPANSION", False, "no_pending_expansion")
        skipped_gates.append("STRATEGY_EXPANSION")

        # Gate 1: GENERATE_REQUESTED (Precedence 20)
        # When user triggers plan generation (e.g., "GENERATE_PLAN_NOW"), route
        # directly to generate handling. This takes priority over everything else.
        # EXCEPTION: Block if blocking date errors exist (DATE_AMBIGUOUS_YEAR, DATE_RANGE_INVALID)
        if flags.get("generate_requested"):
            # Check for blocking date errors
            has_blocking_date_errors = False
            if state.errors:
                for err in state.errors:
                    if isinstance(err, ErrorRecord):
                        # New structured error format
                        if err.severity == "blocking" or err.code in DATE_BLOCKING_ERROR_CODES:
                            has_blocking_date_errors = True
                            break
                    elif (
                        isinstance(err, NormalizationError)
                        and err.code in DATE_BLOCKING_ERROR_CODES
                    ):
                        has_blocking_date_errors = True
                        break
                    # Also check string errors for backwards compatibility
                    elif isinstance(err, str) and any(
                        code in err for code in DATE_BLOCKING_ERROR_CODES
                    ):
                        has_blocking_date_errors = True
                        break

            # Also check metadata for date_clarify_mode
            if state.metadata.get("date_clarify_mode"):
                has_blocking_date_errors = True

            if has_blocking_date_errors:
                # Block generation and redirect to dates clarification
                record_gate(
                    "GENERATE_REQUESTED",
                    True,
                    "blocked_by_date_errors",
                    suppressed=True,
                    suppression_reason="date_clarify_mode",
                )
                _debug(
                    "GENERATE_REQUESTED blocked due to date errors",
                    errors_count=len(state.errors),
                    date_clarify_mode=state.metadata.get("date_clarify_mode"),
                )
                _date_stats["dates_clarify_shown_count"] += 1
                return cls._build_result(
                    gate=GatePrecedence.CORE_COLLECTION,
                    destination="required_fields",
                    reason="generate_blocked:date_errors",
                    start_time=start_time,
                    skipped=skipped_gates,
                    state=state,
                    metadata_updates={
                        "router_path": "generate_blocked:date_errors",
                        "router_bypassed": True,
                        "date_clarify_mode": True,
                    },
                    gate_trace=gate_trace,
                )

            record_gate("GENERATE_REQUESTED", True, "generate_requested")
            return cls._build_result(
                gate=GatePrecedence.GENERATE_REQUESTED,  # Precedence 20
                destination="generate_responder",
                reason="generate_requested",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                metadata_updates={
                    "router_path": "generate_requested",
                    "router_bypassed": True,
                },
                gate_trace=gate_trace,
            )
        record_gate("GENERATE_REQUESTED", False, "no_generate_flag")
        skipped_gates.append("GENERATE_REQUESTED")

        # Gate 2: SHORT_CIRCUIT (Precedence 30)
        if flags.get("short_circuit"):
            sc_type = flags.get("short_circuit")
            record_gate("SHORT_CIRCUIT", True, f"short_circuit:{sc_type}")
            return cls._build_result(
                gate=GatePrecedence.SHORT_CIRCUIT,
                destination="short_circuit_responder",
                reason=f"short_circuit:{sc_type}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                metadata_updates={"router_path": f"short_circuit:{sc_type}"},
                gate_trace=gate_trace,
            )
        skipped_gates.append("SHORT_CIRCUIT")

        # Gate 1b: INFEASIBILITY_DETECTION
        # Import here to avoid circular dependency (function defined later)
        has_infeasibility, infeasibility_type = _has_infeasibility_signals(user_text, state)
        if has_infeasibility:
            return cls._build_result(
                gate=GatePrecedence.SHORT_CIRCUIT,  # Same priority as short_circuit
                destination="correction_node",
                reason=f"infeasibility:{infeasibility_type}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="correction_needed",
                metadata_updates={
                    "router_path": f"infeasibility_detection:{infeasibility_type}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"infeasibility:{infeasibility_type}",
                },
            )
        skipped_gates.append("INFEASIBILITY_DETECTION")

        # Gate 2: FAST_PATH
        # IMPORTANT: Only fire for strategy bootstrap when strategy_bootstrap_active is True
        # This prevents bootstrap from suppressing STRATEGY_TOPIC_SWITCH on subsequent turns
        if flags.get("fast_path"):
            fp_field = flags.get("fast_path_field", "unknown")
            # Strategy bootstrap fast path only fires when bootstrap is active (turn 1)
            if fp_field == "strategy_bootstrap":
                if not flags.get("strategy_bootstrap_active", False):
                    _debug(
                        "FAST_PATH skipped: strategy_bootstrap expired",
                        fast_path_field=fp_field,
                        strategy_bootstrap_active=flags.get("strategy_bootstrap_active"),
                    )
                    skipped_gates.append("FAST_PATH:bootstrap_expired")
                else:
                    return cls._build_result(
                        gate=GatePrecedence.FAST_PATH,
                        destination="required_fields_node",
                        reason=f"fast_path:{fp_field}",
                        start_time=start_time,
                        skipped=skipped_gates,
                        state=state,
                        intent="required_fields",
                        metadata_updates={"router_path": f"fast_path:{fp_field}"},
                    )
            else:
                # Non-bootstrap fast paths can fire normally
                return cls._build_result(
                    gate=GatePrecedence.FAST_PATH,
                    destination="required_fields_node",
                    reason=f"fast_path:{fp_field}",
                    start_time=start_time,
                    skipped=skipped_gates,
                    state=state,
                    intent="required_fields",
                    metadata_updates={"router_path": f"fast_path:{fp_field}"},
                )
        skipped_gates.append("FAST_PATH")

        # Gate 2.3: INTENT_ONLY_FAST_PATH (MVP Hardening)
        # When user provides only topic/intent keywords (e.g., "adventure hiking outdoors")
        # with no extractable entities, skip extractor LLM and route directly to
        # required_fields asking for destinations.
        # NOTE: Strategy topics (hiking, skiing, etc.) are handled by STRATEGY_PRE_CORE_VALUE
        # gate instead, which provides value-first responses.
        if not readiness.core_complete:
            intent_only_result = cls._check_intent_only_input(user_text_lower, ti)
            if intent_only_result:
                detected_topic = intent_only_result
                # If it's a strategy topic, let STRATEGY_PRE_CORE_VALUE handle it
                is_strategy_topic = detected_topic in {
                    "hiking",
                    "skiing",
                    "diving",
                    "cycling",
                    "boating",
                }
                if is_strategy_topic:
                    # Skip this gate, let STRATEGY_PRE_CORE_VALUE provide value-first response
                    _debug(
                        "INTENT_ONLY_FAST_PATH: deferring to STRATEGY_PRE_CORE_VALUE",
                        topic=detected_topic,
                    )
                else:
                    return cls._build_result(
                        gate=GatePrecedence.FAST_PATH,  # Same priority as fast_path
                        destination="required_fields_node",
                        reason=f"intent_only:{detected_topic}",
                        start_time=start_time,
                        skipped=skipped_gates,
                        state=state,
                        intent="required_fields",
                        question_target="destinations",
                        strategy_topic=None,
                        metadata_updates={
                            "router_path": f"intent_only_fast_path:{detected_topic}",
                            "router_bypassed": True,
                            "router_bypass_reason": f"intent_only:{detected_topic}",
                            "intent_only_detected": True,
                            "intent_only_topic": detected_topic,
                        },
                    )
        skipped_gates.append("INTENT_ONLY_FAST_PATH")

        # Gate 2.5: SPECIALIST_PRE_CORE
        # When specialist_pre_core_enabled, route to specialist nodes even before core
        # fields are complete if user clearly asks about hotels/flights/activities.
        # The specialist will acknowledge intent and ask for minimal missing fields inline.
        # IMPORTANT: Skip this gate entirely if strategy_pre_core is eligible, to avoid
        # shadowing the value-first strategy path for open-ended planning prompts.
        strategy_pre_core_eligible = cls._is_strategy_pre_core_eligible(
            user_text_lower, ti, readiness
        )
        if settings.specialist_pre_core_enabled and not readiness.core_complete:
            if strategy_pre_core_eligible:
                _debug(
                    "SPECIALIST_PRE_CORE skipped: strategy_pre_core_eligible",
                    missing_core=readiness.missing_core,
                )
            else:
                pre_core_result = cls._check_specialist_pre_core(user_text_lower, readiness, ti)
                if pre_core_result:
                    intent_name, destination = pre_core_result
                    return cls._build_result(
                        gate=GatePrecedence.SPECIALIST_PRE_CORE,
                        destination=destination,
                        reason=f"specialist_pre_core:{intent_name}",
                        start_time=start_time,
                        skipped=skipped_gates,
                        state=state,
                        intent=intent_name,
                        metadata_updates={
                            "router_path": f"specialist_pre_core:{intent_name}",
                            "router_bypassed": True,
                            "router_bypass_reason": f"specialist_pre_core:{intent_name}",
                            "pre_core_mode": True,
                            "missing_core_fields": readiness.missing_core,
                        },
                    )
        skipped_gates.append("SPECIALIST_PRE_CORE")

        # =====================================================================
        # Gate 3.5: STRATEGY_TOPIC_SWITCH
        # =====================================================================
        # Mid-session strategy topic change detection (e.g., user adds "diving")
        #
        # Triggers when:
        # 1. New strategy keyword detected in user text
        # 2. User expresses intent via verb patterns ("wanna", "go", "plan", "try")
        # 3. Topic differs from last_strategy_topic OR explicitly re-requested
        # 4. Cooldown has passed OR override phrase used ("actually", "instead")
        #
        # Behavior:
        # - If blocking_errors exist: store pending_strategy_topic, route to date clarify
        # - If core complete + no blocking errors: route to strategy stage 1
        # - If destinations missing: route to strategy stage 0
        # =====================================================================
        topic_switch_result = cls._check_strategy_topic_switch(
            user_text_lower, ti, readiness, state.metadata, state.turn_number
        )
        if topic_switch_result:
            new_topic, switch_reason = topic_switch_result

            # Check for blocking errors - must handle dates first
            if readiness.has_blocking_errors:
                _debug(
                    "STRATEGY_TOPIC_SWITCH: deferred due to blocking errors",
                    new_topic=new_topic,
                    blocking_errors=readiness.blocking_errors,
                )
                # Store pending topic for auto-fire after errors clear
                return cls._build_result(
                    gate=GatePrecedence.STRATEGY_TOPIC_SWITCH,
                    destination="required_fields_node",
                    reason=f"topic_switch_deferred:{new_topic}:blocking_errors",
                    start_time=start_time,
                    skipped=skipped_gates,
                    state=state,
                    intent="required_fields",
                    question_target="dates",
                    strategy_topic=new_topic,
                    metadata_updates={
                        "router_path": f"topic_switch_deferred:{new_topic}",
                        "router_bypassed": True,
                        "pending_strategy_topic": new_topic,
                        "date_clarify_mode": True,
                        "topic_switch_reason": switch_reason,
                    },
                )

            # Determine stage based on readiness
            # Also set strategy_dest_known when destinations are present
            has_destinations = bool(ti.destinations)
            if readiness.core_complete:
                # Core complete - route to strategy stage 1
                strategy_stage = 1
            elif not ti.destinations:
                # No destinations - route to strategy stage 0 (value-first)
                strategy_stage = 0
            else:
                # Has destinations but missing other core - stage 1
                strategy_stage = 1

            destination = STRATEGY_TOPIC_TO_NODE.get(new_topic, "strategy_node")
            record_gate("STRATEGY_TOPIC_SWITCH", True, f"topic_switch:{new_topic}")
            return cls._build_result(
                gate=GatePrecedence.STRATEGY_TOPIC_SWITCH,
                destination=destination,
                reason=f"topic_switch:{new_topic}:{switch_reason}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="strategy",
                strategy_topic=new_topic,
                metadata_updates={
                    "router_path": f"strategy_topic_switch:{new_topic}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"topic_switch:{new_topic}",
                    "strategy_stage": strategy_stage,
                    "strategy_dest_known": has_destinations,  # Enable dest-specific advice
                    "last_strategy_topic": new_topic,
                    "last_strategy_topic_turn": state.turn_number,
                    "topic_switch_cooldown_until_turn": state.turn_number + 1,
                    "topic_switch_reason": switch_reason,
                },
                gate_trace=gate_trace,
            )
        skipped_gates.append("STRATEGY_TOPIC_SWITCH")

        # Gate 4: STRATEGY_PRE_CORE_VALUE
        # Route to strategy_node (stage 0) when:
        # 1. Strategy topic detected (hiking, skiing, diving, cycling, boating)
        # 2. Core fields are missing (not readiness.core_complete)
        # 3. No destination entities extracted
        # 4. User did NOT explicitly ask for "questions only"
        strategy_pre_core_result = cls._check_strategy_pre_core_value(
            user_text_lower, ti, readiness, extraction_conf, state.metadata
        )
        if strategy_pre_core_result:
            topic, question_target = strategy_pre_core_result
            record_gate("STRATEGY_PRE_CORE_VALUE", True, f"strategy:{topic}")
            return cls._build_result(
                gate=GatePrecedence.STRATEGY_PRE_CORE_VALUE,
                destination="strategy_node",
                reason=f"strategy_pre_core_value:{topic}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="strategy",
                strategy_topic=topic,
                question_target=question_target,
                metadata_updates={
                    "router_path": f"strategy_pre_core_value:{topic}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"strategy_pre_core_value:{topic}",
                    "pre_core_mode": True,
                    "strategy_stage": 0,
                    "missing_core_fields": readiness.missing_core,
                },
                gate_trace=gate_trace,
            )
        record_gate("STRATEGY_PRE_CORE_VALUE", False, "no_strategy_topic")
        skipped_gates.append("STRATEGY_PRE_CORE_VALUE")

        # =====================================================================
        # Gate 4.5: STRATEGY_PRE_CORE_VALUE_WITH_DEST
        # =====================================================================
        # Route to strategy_node (stage 0, destination-known mode) when:
        # 1. Strategy topic detected (hiking, skiing, diving, cycling, boating)
        # 2. Core fields are missing (not readiness.core_complete)
        # 3. Destinations ARE present (e.g., "diving in Maldives")
        # 4. Turn 1 or last_strategy_topic is None (fresh strategy request)
        # 5. No blocking date errors exist
        # 6. User did NOT explicitly ask for "questions only"
        # 7. NOT (question_target set AND input is compatible with target) [OWNERSHIP]
        # 8. NOT (stage0 already completed for this topic+destination) [LIFECYCLE]
        #
        # This gate provides value-first response with destination-specific
        # guidance and then asks for the next missing field.
        # =====================================================================
        strategy_pre_core_dest_result = cls._check_strategy_pre_core_value_with_dest(
            user_text_lower,
            ti,
            readiness,
            state.metadata,
            state.turn_number,
            user_text=user_text,
            question_target=state.question_target,
        )
        if strategy_pre_core_dest_result:
            topic = strategy_pre_core_dest_result
            # Determine next question target based on what's actually missing
            # Priority: dates > origin > travelers
            next_question = "dates"  # Default
            if ti.start_date:
                # Dates already set, ask for next missing field
                if "origin" in readiness.missing_core:
                    next_question = "origin"
                elif "travelers" in readiness.missing_core or "adults" in readiness.missing_core:
                    next_question = "travelers"
            return cls._build_result(
                gate=GatePrecedence.STRATEGY_PRE_CORE_VALUE_WITH_DEST,
                destination="strategy_node",
                reason=f"strategy_pre_core_value_with_dest:{topic}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="strategy",
                strategy_topic=topic,
                question_target=next_question,
                metadata_updates={
                    "router_path": f"strategy_pre_core_value_with_dest:{topic}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"strategy_pre_core_value_with_dest:{topic}",
                    "pre_core_mode": True,
                    "strategy_stage": 0,
                    "strategy_dest_known": True,
                    "prefer_dates_first": not ti.start_date,  # Only if dates not set
                    "missing_core_fields": readiness.missing_core,
                },
            )
        skipped_gates.append("STRATEGY_PRE_CORE_VALUE_WITH_DEST")

        # =====================================================================
        # Gate 5: CORE_COLLECTION
        # =====================================================================
        # v6 HARD INVARIANT: Never route to required_fields when missing_all == []
        # This prevents question churn and stale response cascades.
        #
        # Gate fires when:
        # 1. has_blocking_errors (date clarification needed), OR
        # 2. core_complete == False (core fields missing)
        #
        # Gate is BLOCKED when:
        # - missing_all == [] (no fields to ask about)
        # - ready_to_generate == True
        # =====================================================================

        # Store readiness in metadata for downstream use (compute once, reuse)
        state.metadata["readiness_pre"] = {
            "core_complete": readiness.core_complete,
            "ready_to_generate": readiness.ready_to_generate,
            "missing_core": readiness.missing_core,
            "missing_all": readiness.missing_all,
            "has_blocking_errors": readiness.has_blocking_errors,
            "blocking_errors": readiness.blocking_errors,
            "question_target": readiness.question_target,
        }

        # =====================================================================
        # Gate 5a: ADD_MORE_DETAILS
        # =====================================================================
        # When user explicitly says they want to add more details (e.g., clicking
        # "I want to add more details first"), route to required_fields to ask
        # about optional fields like budget, end_date, or travelers.
        # This gate fires BEFORE READY_NO_FIELDS to prevent the "ready to generate"
        # loop when user wants to provide additional information.
        # =====================================================================
        add_details_phrases = (
            "add more details",
            "add details",
            "more details first",
            "add more info",
            "provide more details",
            "give more details",
        )
        wants_more_details = any(phrase in user_text_lower for phrase in add_details_phrases)

        if wants_more_details and readiness.ready_to_generate and readiness.missing_all:
            # Determine which optional field to ask about next
            # Priority: budget > travelers > end_date
            optional_field_priority = ["budget", "travelers (adults)", "end_date"]
            question_target = None
            for field in optional_field_priority:
                if field in readiness.missing_all:
                    # Normalize field name for user-facing question
                    if field == "travelers (adults)":
                        question_target = "travelers"
                    else:
                        question_target = field
                    break

            if question_target:
                record_gate("ADD_MORE_DETAILS", True, f"user_wants_details:{question_target}")
                _debug(
                    "ADD_MORE_DETAILS gate triggered",
                    question_target=question_target,
                    missing_optional=readiness.missing_all,
                )
                return cls._build_result(
                    gate=GatePrecedence.READY_NO_FIELDS,  # Use same precedence
                    destination="required_fields_node",
                    reason=f"add_more_details:{question_target}",
                    start_time=start_time,
                    skipped=skipped_gates,
                    state=state,
                    intent="required_fields",
                    question_target=question_target,
                    metadata_updates={
                        "router_path": "add_more_details",
                        "router_bypassed": True,
                        "user_wants_optional_fields": True,
                    },
                    gate_trace=gate_trace,
                )
        if wants_more_details:
            record_gate("ADD_MORE_DETAILS", False, "no_optional_fields_to_ask")
        else:
            record_gate("ADD_MORE_DETAILS", False, "no_add_details_intent")
        skipped_gates.append("ADD_MORE_DETAILS")

        # =====================================================================
        # Gate 5b: SPECIALIST_REQUEST
        # =====================================================================
        # When user explicitly requests a specialist domain (hotels, flights, etc.)
        # route to that specialist BEFORE READY_NO_FIELDS fires.
        # Examples: "Show me hotel options", "What flights are available?"
        # This ensures domain-specific requests are honored even when core is complete.
        # =====================================================================
        specialist_keywords = {
            "hotels": {
                "hotel",
                "hotels",
                "accommodation",
                "stay",
                "lodging",
                "where to stay",
                "boutique",
                "hostel",
                "airbnb",
                "room",
                "rooms",
            },
            "flights": {
                "flight",
                "flights",
                "fly",
                "flying",
                "plane",
                "airline",
                "airport",
                "book a flight",
                "find flights",
            },
            "activities": {
                "activity",
                "activities",
                "things to do",
                "attractions",
                "tour",
                "tours",
                "sightseeing",
                "museum",
                "restaurant",
                "what to do",
            },
            "transport": {
                "transport",
                "transportation",
                "train",
                "trains",
                "bus",
                "taxi",
                "uber",
                "rental car",
                "car rental",
                "rent a car",
                "getting around",
            },
        }

        def _has_keyword_match(text: str, keywords: set) -> bool:
            """Check if any keyword appears as a whole word in text."""
            import re

            for kw in keywords:
                # Multi-word keywords need exact substring match
                if " " in kw:
                    if kw in text:
                        return True
                else:
                    # Single word keywords need word boundary match
                    # to avoid "bus" matching in "business"
                    if re.search(rf"\b{re.escape(kw)}\b", text):
                        return True
            return False

        detected_specialist = None
        for specialist, keywords in specialist_keywords.items():
            if _has_keyword_match(user_text_lower, keywords):
                detected_specialist = specialist
                break

        if detected_specialist and readiness.ready_to_generate:
            specialist_node_map = {
                "hotels": "hotels_node",
                "flights": "flights_node",
                "activities": "activities_node",
                "transport": "transport_node",
            }
            destination = specialist_node_map.get(detected_specialist, "hotels_node")
            record_gate("SPECIALIST_REQUEST", True, f"explicit_request:{detected_specialist}")
            _debug(
                "SPECIALIST_REQUEST gate triggered",
                specialist=detected_specialist,
                destination=destination,
            )
            return cls._build_result(
                gate=GatePrecedence.READY_NO_FIELDS,  # Use same precedence
                destination=destination,
                reason=f"specialist_request:{detected_specialist}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent=detected_specialist,
                metadata_updates={
                    "router_path": f"specialist_request:{detected_specialist}",
                    "router_bypassed": True,
                    "explicit_specialist_request": detected_specialist,
                },
                gate_trace=gate_trace,
            )
        if detected_specialist:
            record_gate("SPECIALIST_REQUEST", False, "not_ready_to_generate")
        else:
            record_gate("SPECIALIST_REQUEST", False, "no_specialist_intent")
        skipped_gates.append("SPECIALIST_REQUEST")

        # =====================================================================
        # READY_NO_FIELDS INVARIANT (v7 Final v5)
        # =====================================================================
        # HARD EARLY RETURN: When plan is ready with no fields to ask,
        # route directly to summarize. This blocks ALL lower-precedence gates
        # (HIGH_CONFIDENCE, CORE_COLLECTION, etc.) from routing to required_fields.
        #
        # Uses ready_to_generate (core_complete AND no blocking errors) instead
        # of checking missing_all, because missing_all includes optional fields
        # like end_date and budget that shouldn't block plan progression.
        # =====================================================================
        date_clarify_mode = state.metadata.get("date_clarify_mode", False)
        if readiness.ready_to_generate and not date_clarify_mode:
            record_gate("READY_NO_FIELDS", True, "plan_ready_to_generate")
            _debug(
                "GATE READY_NO_FIELDS: plan ready, routing to summarize",
                core_complete=readiness.core_complete,
                ready_to_generate=readiness.ready_to_generate,
                missing_all=readiness.missing_all,
            )
            return cls._build_result(
                gate=GatePrecedence.READY_NO_FIELDS,
                destination="summarize",
                reason="ready_no_required_fields",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                question_target=None,  # Clear stale question_target
                metadata_updates={
                    "router_path": "ready_no_required_fields",
                    "router_bypassed": True,
                    "plan_just_became_ready": True,  # Signal to clear stale state
                    "question_target": None,  # Clear in metadata SSoT too
                },
                gate_trace=gate_trace,
            )
        record_gate(
            "READY_NO_FIELDS",
            False,
            f"ready_to_generate={readiness.ready_to_generate},clarify={date_clarify_mode}",
        )

        # CORE_COLLECTION gate continues if we have blocking errors or missing fields
        if readiness.has_blocking_errors:
            record_gate(
                "CORE_COLLECTION", True, f"blocking_errors:{','.join(readiness.blocking_errors)}"
            )
            # Blocking date errors - force date clarification
            return cls._build_result(
                gate=GatePrecedence.CORE_COLLECTION,
                destination="required_fields_node",
                reason=f"blocking_errors:{','.join(readiness.blocking_errors)}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="required_fields",
                question_target="dates",
                metadata_updates={
                    "router_path": "blocking_errors_gate",
                    "router_bypassed": True,
                    "date_clarify_mode": True,
                },
                gate_trace=gate_trace,
            )
        elif not readiness.core_complete and len(readiness.missing_all) > 0:
            # Determine question_target from readiness
            question_target = readiness.question_target

            # Infer strategy_topic from activity_settings if present
            activity_categories = ti.activity_settings.get("categories", [])
            strategy_topics = {"hiking", "skiing", "diving", "cycling", "boating"}
            inferred_topic = None
            for cat in activity_categories:
                if cat.lower() in strategy_topics:
                    inferred_topic = cat.lower()
                    break

            record_gate("CORE_COLLECTION", True, f"missing:{','.join(readiness.missing_core)}")
            return cls._build_result(
                gate=GatePrecedence.CORE_COLLECTION,
                destination="required_fields_node",
                reason=f"missing:{','.join(readiness.missing_core)}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="required_fields",
                question_target=question_target,
                strategy_topic=inferred_topic,
                metadata_updates={
                    "router_path": "core_fields_gate",
                    "router_bypassed": True,
                    "router_bypass_reason": f"missing:{','.join(readiness.missing_core)}",
                },
                gate_trace=gate_trace,
            )
        record_gate("CORE_COLLECTION", False, "core_complete_or_no_missing")
        skipped_gates.append("CORE_COLLECTION")

        # Gate 4: HIGH_CONFIDENCE
        conf_level = extraction_conf.get("level", "medium")
        conf_overall = extraction_conf.get("overall", 0.5)
        no_typos = not extraction_conf.get("typo_suggestions", {})
        is_short_input = len(user_text.strip()) <= 30

        # Check for intent keywords that would require routing
        intent_keywords = (
            "cycling",
            "hiking",
            "diving",
            "skiing",
            "boating",
            "flight",
            "flights",
            "hotel",
            "hotels",
            "boutique",
            "accommodation",
            "stay",
            "where to stay",
            "transport",
            "train",
            "car rental",
            "activity",
            "activities",
            "things to do",
            "how",
            "what",
            "when",
            "where",
            "should",
            "recommend",
            "suggest",
            "find",
            "book",
            # Flight preference keywords (should route to flights specialist)
            "direct",
            "nonstop",
            "business",
            "first class",
            "economy",
            "cabin",
            "layover",
            # Hotel preference keywords (should route to hotels specialist)
            "star",
            "amenities",
            "breakfast",
            "gym",
            "pool",
            "spa",
        )
        has_intent_keywords = any(kw in user_text_lower for kw in intent_keywords)

        # Phase 6: Relaxed threshold from 0.92 to 0.88 for short inputs
        conf_threshold = 0.88 if is_short_input else CONFIDENCE_THRESHOLD_SKIP_ROUTER

        if (
            conf_overall >= conf_threshold
            and readiness.core_complete
            and no_typos
            and conf_level == "high"
            and is_short_input
            and not has_intent_keywords
        ):
            return cls._build_result(
                gate=GatePrecedence.HIGH_CONFIDENCE,
                destination="required_fields_node",
                reason=f"high_confidence:{conf_overall:.2f}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="required_fields",
                metadata_updates={
                    "router_path": "high_confidence_bypass",
                    "router_bypassed": True,
                },
            )
        skipped_gates.append("HIGH_CONFIDENCE")

        # Gate 4.5 (Phase 6): QUESTION_KEYWORD combo
        # "What hotels are available?" -> hotels_node
        # "Which flights should I take?" -> flights_node
        # "How do I get around?" -> transport_node
        question_keyword_result = cls._check_question_keyword_combo(user_text_lower)
        if question_keyword_result:
            intent_name, destination = question_keyword_result
            return cls._build_result(
                gate=GatePrecedence.QUESTION_KEYWORD,
                destination=destination,
                reason=f"question_keyword:{intent_name}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent=intent_name,
                metadata_updates={
                    "router_path": f"question_keyword:{intent_name}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"question_keyword:{intent_name}",
                },
            )
        skipped_gates.append("QUESTION_KEYWORD")

        # Gate 5: KEYWORD_HEURISTIC
        # Import _detect_intent_from_keywords (defined later in file)
        keyword_intent = _detect_intent_from_keywords(user_text_lower)
        if keyword_intent:
            intent_name, strategy_topic = keyword_intent
            # Map intent to destination
            destination_map = {
                "strategy": "strategy_node",
                "flights": "flights_node",
                "hotels": "hotels_node",
                "transport": "transport_node",
                "activities": "activities_node",
            }
            destination = destination_map.get(intent_name, "required_fields_node")

            return cls._build_result(
                gate=GatePrecedence.KEYWORD_HEURISTIC,
                destination=destination,
                reason=f"keyword:{intent_name}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent=intent_name,
                strategy_topic=strategy_topic,
                metadata_updates={
                    "router_path": f"keyword_heuristic:{intent_name}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"keyword:{intent_name}",
                },
            )
        skipped_gates.append("KEYWORD_HEURISTIC")

        # Gate 6 (Phase 3): SCORING_ROUTER
        # Multi-signal scoring for cases where keyword heuristic alone isn't enough
        # but combined signals are reliable enough to bypass router LLM
        scoring_result = _try_deterministic_router(user_text, state)
        if scoring_result and scoring_result.should_bypass:
            destination_map = {
                "strategy": "strategy_node",
                "flights": "flights_node",
                "hotels": "hotels_node",
                "transport": "transport_node",
                "activities": "activities_node",
            }
            destination = destination_map.get(scoring_result.intent, "required_fields_node")

            return cls._build_result(
                gate=GatePrecedence.SCORING_ROUTER,
                destination=destination,
                reason=f"scoring:{scoring_result.intent}:{scoring_result.score}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent=scoring_result.intent,
                strategy_topic=scoring_result.strategy_topic,
                metadata_updates={
                    "router_path": f"scoring_router:{scoring_result.intent}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"score:{scoring_result.score}",
                    "scoring_signals": scoring_result.signals,
                },
            )
        skipped_gates.append("SCORING_ROUTER")

        # Gate 99: ROUTER_LLM (default fallback)
        record_gate("ROUTER_LLM", True, "no_gate_matched_fallback")
        return cls._build_result(
            gate=GatePrecedence.ROUTER_LLM,
            destination="router",
            reason="no_gate_matched",
            start_time=start_time,
            skipped=skipped_gates,
            state=state,
            metadata_updates={
                "router_path": "llm",
                "why_not_bypassed": "no_gate_matched",
            },
            gate_trace=gate_trace,
        )

    @classmethod
    def _check_question_keyword_combo(cls, text_lower: str) -> Optional[tuple[str, str]]:
        """
        Phase 6: Check for question-word + domain keyword combinations.

        Examples:
        - "What hotels are available?" -> hotels_node
        - "Which flights should I take?" -> flights_node
        - "How do I get around?" -> transport_node

        Returns:
            (intent_name, destination_node) if match, None otherwise
        """
        words = text_lower.split()
        if not words:
            return None

        # Check if starts with question word
        first_word = words[0].rstrip("?.,")
        if first_word not in QUESTION_WORDS:
            return None

        # Check for domain keywords
        for intent_name, keywords in DOMAIN_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                destination_map = {
                    "flights": "flights_node",
                    "hotels": "hotels_node",
                    "transport": "transport_node",
                    "activities": "activities_node",
                }
                return (intent_name, destination_map[intent_name])

        return None

    # Keywords that strongly indicate specialist intent (used in pre-core mode)
    SPECIALIST_PRE_CORE_KEYWORDS = {
        "hotels": {
            "hotel",
            "hotels",
            "hostel",
            "hostels",
            "boutique hotel",
            "accommodation",
            "lodging",
            "where to stay",
            "stay",
            "airbnb",
            "resort",
            "resorts",
            "motel",
            "guest house",
            "guesthouse",
            "bed and breakfast",
            "b&b",
        },
        "flights": {
            "flight",
            "flights",
            "flying",
            "fly",
            "airline",
            "airlines",
            "airport",
            "airfare",
            "plane",
            "direct flight",
            "nonstop",
            "layover",
        },
        "activities": {
            "things to do",
            "what to do",
            "activities",
            "activity",
            "tour",
            "tours",
            "excursion",
            "excursions",
            "sightseeing",
            "attractions",
            "visit",
        },
        "transport": {
            "transport",
            "transportation",
            "train",
            "trains",
            "bus",
            "buses",
            "car rental",
            "rental car",
            "drive",
            "taxi",
            "uber",
            "get around",
        },
    }

    # NOTE: INTENT_ONLY_KEYWORDS is now imported from pattern_matching.py

    @classmethod
    def _check_intent_only_input(cls, text_lower: str, ti: "TripInputs") -> Optional[str]:
        """
        Check if input is intent-only (topic keywords without extractable entities).

        Intent-only inputs like "adventure hiking outdoors" or "beach vacation"
        have no destinations, dates, origin, budget, or travelers to extract.
        We can skip the extractor LLM and route directly to required_fields.

        Args:
            text_lower: Lowercase user input
            ti: Current trip inputs

        Returns:
            Detected topic/intent if intent-only, None otherwise
        """
        # If we already have any concrete data, not intent-only
        if ti.destinations or ti.origin or ti.start_date or ti.budget or ti.adults:
            return None

        # Check for intent keywords
        words = text_lower.split()
        detected_topics = []
        for word in words:
            # Clean punctuation
            clean_word = word.strip(".,!?;:")
            if clean_word in INTENT_ONLY_KEYWORDS:
                detected_topics.append(INTENT_ONLY_KEYWORDS[clean_word])

        if not detected_topics:
            return None

        # Check for extractable entities that would require LLM
        # Use the centralized ENTITY_DETECTION_PATTERN
        if ENTITY_DETECTION_PATTERN.search(text_lower):
            # Has extractable entities, not intent-only
            return None

        # Check for known place names (simplified - could be enhanced)
        # For now, check if any word is capitalized in original (before lowercasing)
        # This is a heuristic - place names are usually capitalized
        # Since we only have text_lower, skip this check

        # Intent-only detected - return the most specific topic
        # Prefer strategy topics over general ones
        strategy_topics = {"hiking", "skiing", "diving", "cycling", "boating"}
        for topic in detected_topics:
            if topic in strategy_topics:
                _debug(f"Intent-only fast path: detected strategy topic '{topic}'")
                return topic

        # Return first detected topic
        _debug(f"Intent-only fast path: detected topic '{detected_topics[0]}'")
        return detected_topics[0]

    @classmethod
    def _is_strategy_pre_core_eligible(
        cls, text_lower: str, ti: "TripInputs", readiness: "TripReadiness"
    ) -> bool:
        """
        Check if the current input qualifies for STRATEGY_PRE_CORE_VALUE gate.

        This is used to suppress other gates (like SPECIALIST_PRE_CORE) when
        the user is asking for open-ended strategy planning without destinations.

        Conditions:
        1. Core fields are missing (not readiness.core_complete)
        2. No destination entities extracted
        3. Strategy topic detected in user text or activity_settings
        4. User did NOT ask for "questions only"

        Args:
            text_lower: Lowercase user input
            ti: Current trip inputs
            readiness: Current trip readiness state

        Returns:
            True if strategy pre-core value path should take precedence
        """
        # Guard: must have core fields missing
        if readiness.core_complete:
            return False

        # Guard: must NOT have destinations
        if ti.destinations:
            return False

        # Guard: check for "questions only" phrases
        for phrase in QUESTIONS_ONLY_PHRASES:
            if phrase in text_lower:
                return False

        # Check for strategy topic in user text or activity_settings
        if detect_strategy_topic(text_lower, ti.activity_settings):
            return True

        return False

    @classmethod
    def _check_specialist_pre_core(
        cls, text_lower: str, readiness: "TripReadiness", ti: "TripInputs"
    ) -> Optional[tuple[str, str]]:
        """
        Check if user is asking about a specialist domain before core fields are complete.

        This enables "pre-core mode" where specialists can acknowledge intent and
        ask for minimal missing fields inline, rather than always routing to required_fields.

        IMPORTANT: This gate yields to STRATEGY_PRE_CORE_VALUE when strategy topics
        are detected without destinations. The caller must check _is_strategy_pre_core_eligible
        before calling this method.

        Args:
            text_lower: Lowercase user input
            readiness: Current trip readiness state
            ti: Current trip inputs (used for strategy eligibility check)

        Returns:
            (intent_name, destination_node) if specialist keyword detected, None otherwise
        """
        # Only trigger if we have at least destination (most important core field)
        # This prevents routing to specialist when user hasn't even mentioned where they're going
        ti_has_destination = bool(readiness.ti.destinations) if hasattr(readiness, "ti") else False

        # Check for specialist keywords
        for intent_name, keywords in cls.SPECIALIST_PRE_CORE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                # CRITICAL: Yield to STRATEGY_PRE_CORE_VALUE for "activities" when
                # a strategy topic is also detected. "Plan a hiking trip with outdoor
                # activities" should go to strategy_node, not activities_node.
                if intent_name == "activities":
                    # Check if any strategy keywords are present
                    strategy_topic = detect_strategy_topic_from_text(text_lower)
                    if strategy_topic:
                        _debug(
                            "specialist_pre_core yielding to strategy_pre_core",
                            intent=intent_name,
                            strategy_topic=strategy_topic,
                        )
                        return None  # Let STRATEGY_PRE_CORE_VALUE handle it

                destination_map = {
                    "flights": "flights_node",
                    "hotels": "hotels_node",
                    "transport": "transport_node",
                    "activities": "activities_node",
                }
                _debug(
                    "specialist_pre_core triggered",
                    intent=intent_name,
                    missing_core=readiness.missing_core,
                    has_destination=ti_has_destination,
                )
                return (intent_name, destination_map[intent_name])

        return None

    # NOTE: _MONTH_TO_MONTH_PATTERN and _SINGLE_MONTH_PATTERN moved to pattern_matching.py
    # as MONTH_TO_MONTH_RANGE_PATTERN and SINGLE_MONTH_PATTERN (V26 extraction)

    @classmethod
    def text_is_compatible_with_target(cls, user_text: str, question_target: Optional[str]) -> bool:
        """
        Check if user_text looks like an answer to the given question_target.

        This is used to determine if a user is answering a pending question
        (e.g., providing dates when question_target="dates") vs making a new
        request (e.g., topic switch).

        CONSOLIDATION NOTE: For dates, this now delegates to is_text_date_compatible()
        from pattern_matching.py which is the single source of truth for date
        compatibility checks.

        Args:
            user_text: The user's input text
            question_target: The current question target ("dates", "origin", etc.)

        Returns:
            True if the text appears to be answering the question_target
        """
        if not question_target or not user_text:
            return False

        text_lower = user_text.strip().lower()
        text_stripped = user_text.strip()

        if question_target in ("dates", "start_date"):
            # Delegate to consolidated date compatibility check
            return is_text_date_compatible(user_text)

        elif question_target == "origin":
            # Check if looks like a city/place name (capitalized, no strategy keywords)
            # Avoid false positives on strategy keywords
            if not any(kw in text_lower for kw in ALL_STRATEGY_KEYWORDS):
                # Simple heuristic: short input that's capitalized or known place
                if len(text_stripped) < 50 and (
                    text_stripped[0].isupper() or is_known_place(text_stripped)
                ):
                    return True

        elif question_target == "destinations":
            # Similar to origin but allow multiple places
            if is_known_place(text_stripped):
                return True

        elif question_target == "travelers":
            # Look for number patterns
            traveler_pattern = (
                r"\b("
                r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
                r"couple|family|solo|alone|just me"
                r")\b"
            )
            if re.search(traveler_pattern, text_lower):
                return True

        elif question_target == "budget":
            # Look for currency/budget patterns
            if re.search(
                r"\b(\$|€|£|\d+|budget|cheap|luxury|mid-range|moderate|flexible)\b", text_lower
            ):
                return True

        return False

    # NOTE: Suppression predicates (bridge_suppression, compute_stage0_signature)
    # are now in app.planner.gates.suppression.SuppressionPredicates

    @classmethod
    def _check_strategy_pre_core_value(
        cls,
        text_lower: str,
        ti: "TripInputs",
        readiness: "TripReadiness",
        extraction_conf: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Optional[tuple[str, str]]:
        """
        Check if we should route to strategy_node stage 0 for value-first response.

        Fires when:
        1. Strategy topic detected (hiking, skiing, diving, cycling, boating)
        2. Core fields are missing (not readiness.core_complete)
        3. No destination entities extracted
        4. User did NOT explicitly ask for "questions only"
        5. User did NOT just answer an active question (bridge suppression)

        Returns:
            (strategy_topic, question_target) if should fire, None otherwise
        """
        # =====================================================================
        # BRIDGE SUPPRESSION: Don't fire when user just answered active question
        # =====================================================================
        if SuppressionPredicates.bridge_suppression(metadata):
            return None

        # Guard: must have core fields missing
        if readiness.core_complete:
            return None

        # Guard: must NOT have destinations (otherwise go to normal strategy flow)
        if ti.destinations:
            return None

        # Guard: check for "questions only" phrases - user wants to be asked
        for phrase in QUESTIONS_ONLY_PHRASES:
            if phrase in text_lower:
                _debug(
                    "strategy_pre_core_value bypassed: questions_only phrase detected",
                    phrase=phrase,
                )
                return None

        # Detect strategy topic from user text or activity_settings
        detected_topic = detect_strategy_topic(text_lower, ti.activity_settings)
        if not detected_topic:
            return None

        # Determine question_target with priority:
        # 1. dates (ask month/season first - helps with strategy recommendations)
        # 2. origin (logistics)
        # 3. destinations (fallback only)
        # NOTE: Always use "dates" (not "start_date") for LQA/template compatibility
        question_target = "dates"  # Default: ask about timing first (canonical form)
        if ti.start_date:
            question_target = "origin"
        if ti.start_date and ti.origin:
            question_target = "destinations"

        _debug(
            "strategy_pre_core_value triggered",
            topic=detected_topic,
            missing_core=readiness.missing_core,
            question_target=question_target,
        )

        return (detected_topic, question_target)

    @classmethod
    def _check_strategy_pre_core_value_with_dest(
        cls,
        text_lower: str,
        ti: "TripInputs",
        readiness: "TripReadiness",
        metadata: Dict[str, Any],
        turn_number: int,
        *,
        user_text: str = "",
        question_target: Optional[str] = None,
    ) -> Optional[str]:
        """
        Check if we should route to strategy_node stage 0 with destination-known mode.

        This gate fires when user provides both strategy topic AND destination
        (e.g., "diving in Maldives") but is missing other core fields.

        Fires when:
        1. Strategy topic detected (hiking, skiing, diving, cycling, boating)
        2. Core fields are missing (not readiness.core_complete)
        3. Destinations ARE present
        4. Turn 1 OR last_strategy_topic is None (fresh strategy request)
        5. No blocking date errors exist
        6. Not in date_clarify_mode
        7. User did NOT explicitly ask for "questions only"
        8. NOT (question_target set AND input is compatible with target) [OWNERSHIP]
        9. NOT (stage0 already completed for this topic+destination) [LIFECYCLE]
        10. NOT (user just answered active question) [BRIDGE SUPPRESSION]

        Returns:
            strategy_topic if should fire, None otherwise
        """
        # =====================================================================
        # BRIDGE SUPPRESSION: Don't fire when user just answered active question
        # =====================================================================
        # This is the primary suppression for the "destination answer" turn.
        # When user clicks "Patagonia" suggestion or types a destination answer,
        # we want to ask for dates next, not generate strategy content.
        # =====================================================================
        if SuppressionPredicates.bridge_suppression(metadata):
            return None

        # Guard: must have core fields missing
        if readiness.core_complete:
            return None

        # Guard: must HAVE destinations (this is the key difference from
        # _check_strategy_pre_core_value)
        if not ti.destinations:
            return None

        # =====================================================================
        # OWNERSHIP SUPPRESSION (P0 fix for stage0 loop)
        # =====================================================================
        # If question_target is set and user input looks like an answer to that
        # question, do NOT fire this gate. Let the answer-collection path handle it.
        # This prevents stage0 from trampling date/origin collection.
        # =====================================================================
        if question_target and cls.text_is_compatible_with_target(user_text, question_target):
            _debug(
                "strategy_pre_core_value_with_dest skipped: ownership suppression",
                question_target=question_target,
                user_text_preview=user_text[:50] if user_text else "",
                reason="input compatible with question_target",
            )
            return None

        # =====================================================================
        # LIFECYCLE SUPPRESSION (P0 fix for stage0 loop)
        # =====================================================================
        # If stage0 already completed for this topic+destinations combination,
        # do NOT fire again. This prevents re-running stage0 when user answers
        # the date question.
        # =====================================================================
        # Detect topic first to compute signature
        detected_topic = detect_strategy_topic(text_lower, ti.activity_settings)

        if detected_topic:
            current_sig = SuppressionPredicates.compute_stage0_signature(
                detected_topic, ti.destinations, ti.origin
            )
            completed_sig = metadata.get("stage0_completed_sig")
            if completed_sig == current_sig:
                _debug(
                    "strategy_pre_core_value_with_dest skipped: lifecycle suppression",
                    current_sig=current_sig,
                    completed_sig=completed_sig,
                    reason="stage0 already completed for this topic+destinations+origin",
                )
                return None

        # Guard: must be turn 1 or fresh strategy request (legacy check, now secondary)
        last_strategy_topic = metadata.get("last_strategy_topic")
        if turn_number > 1 and last_strategy_topic is not None:
            # Only skip if lifecycle suppression didn't already handle it
            # and this isn't a topic switch
            if detected_topic == last_strategy_topic:
                _debug(
                    "strategy_pre_core_value_with_dest skipped: not turn 1 and topic exists",
                    turn_number=turn_number,
                    last_strategy_topic=last_strategy_topic,
                )
                return None

        # Guard: no blocking date errors (dates clarification owns routing)
        if readiness.has_blocking_errors:
            _debug(
                "strategy_pre_core_value_with_dest skipped: blocking errors",
                blocking_errors=readiness.blocking_errors,
            )
            return None

        # Guard: not in date_clarify_mode
        if metadata.get("date_clarify_mode"):
            _debug("strategy_pre_core_value_with_dest skipped: date_clarify_mode")
            return None

        # Guard: check for "questions only" phrases - user wants to be asked
        for phrase in QUESTIONS_ONLY_PHRASES:
            if phrase in text_lower:
                _debug(
                    "strategy_pre_core_value_with_dest bypassed: questions_only phrase",
                    phrase=phrase,
                )
                return None

        # Detect strategy topic from user text or activity_settings
        detected_topic = detect_strategy_topic(text_lower, ti.activity_settings)
        if not detected_topic:
            return None

        _debug(
            "strategy_pre_core_value_with_dest triggered",
            topic=detected_topic,
            destinations=ti.destinations,
            missing_core=readiness.missing_core,
        )

        return detected_topic

    @classmethod
    def _check_strategy_topic_switch(
        cls,
        text_lower: str,
        ti: "TripInputs",
        readiness: "TripReadiness",
        metadata: Dict[str, Any],
        turn_number: int,
    ) -> Optional[tuple[str, str]]:
        """
        Check if user is requesting a mid-session strategy topic switch.

        This gate handles cases like "I wanna go diving in Argentina too" when
        the session already has hiking as the strategy topic.

        Triggers when:
        1. Auto-fire pending topic (deferred from previous turn due to blocking errors)
        2. Strategy keyword detected in user text
        3. User expresses intent via verb patterns ("wanna", "go", "plan", "try")
        4. Topic differs from last_strategy_topic OR explicitly re-requested
        5. Cooldown has passed OR override phrase used ("actually", "instead")

        Args:
            text_lower: Lowercase user input
            ti: Current trip inputs
            readiness: Current trip readiness state
            metadata: Session metadata containing topic switch state
            turn_number: Current turn number

        Returns:
            (new_topic, switch_reason) if topic switch should fire, None otherwise
        """
        # Check for auto-fire pending topic (from previous turn's deferred switch)
        auto_fire_topic = metadata.get("auto_fire_topic_switch")
        if auto_fire_topic:
            _debug(
                "STRATEGY_TOPIC_SWITCH: auto-firing pending topic",
                topic=auto_fire_topic,
            )
            return (auto_fire_topic, "auto_fire_pending")

        # =====================================================================
        # BRIDGE SUPPRESSION: Don't fire when user just answered active question
        # =====================================================================
        if SuppressionPredicates.bridge_suppression(metadata):
            return None

        # =====================================================================
        # TURN 1 GUARD: Topic switch is for mid-session changes, not first turn
        # =====================================================================
        # On turn 1, use STRATEGY_PRE_CORE_VALUE instead (priority 5).
        # Topic switch (priority 4) should only fire when:
        # - turn_number >= 2, OR
        # - last_strategy_topic is set (indicates prior strategy interaction)
        last_strategy_topic = metadata.get("last_strategy_topic")
        if turn_number < 2 and not last_strategy_topic:
            _debug(
                "STRATEGY_TOPIC_SWITCH: skipped on turn 1 (use STRATEGY_PRE_CORE_VALUE)",
                turn_number=turn_number,
            )
            return None

        # Detect strategy topic from user text
        detected_topic = detect_strategy_topic_from_text(text_lower)
        if not detected_topic:
            return None

        # Check for intent verb patterns - user must be expressing desire
        has_intent_verb = any(verb in text_lower for verb in TOPIC_SWITCH_INTENT_VERBS)
        if not has_intent_verb:
            _debug(
                "STRATEGY_TOPIC_SWITCH: no intent verb detected",
                topic=detected_topic,
                text_preview=text_lower[:50],
            )
            return None

        # Get last strategy topic state
        last_topic = metadata.get("last_strategy_topic")
        cooldown_until = metadata.get("topic_switch_cooldown_until_turn", 0)

        # Check if this is the same topic as before (not a switch)
        if detected_topic == last_topic:
            # Check for explicit re-request patterns
            has_override = any(phrase in text_lower for phrase in TOPIC_SWITCH_OVERRIDE_PHRASES)
            if not has_override:
                _debug(
                    "STRATEGY_TOPIC_SWITCH: same topic, no override phrase",
                    topic=detected_topic,
                    last_topic=last_topic,
                )
                return None
            # User explicitly wants to revisit the same topic
            return (detected_topic, "explicit_revisit")

        # Different topic - check cooldown
        if turn_number <= cooldown_until:
            # Check for override phrases that bypass cooldown
            has_override = any(phrase in text_lower for phrase in TOPIC_SWITCH_OVERRIDE_PHRASES)
            if not has_override:
                _debug(
                    "STRATEGY_TOPIC_SWITCH: cooldown active, no override",
                    topic=detected_topic,
                    cooldown_until=cooldown_until,
                    turn_number=turn_number,
                )
                return None
            # Override phrase detected - allow switch
            return (detected_topic, "override_cooldown")

        # New topic, cooldown expired - allow switch
        return (detected_topic, "new_topic")

    @classmethod
    def _should_prefer_date_first(cls, text_lower: str, ti: "TripInputs") -> bool:
        """
        Check if we should prefer asking about dates before destinations.

        Returns True when intent is broad (strategy topic detected) but no
        destination entities have been extracted. In these cases, asking about
        timing first helps provide better strategy recommendations.

        Args:
            text_lower: Lowercase user input
            ti: Current trip inputs

        Returns:
            True if dates should be prioritized over destinations
        """
        # If destinations already exist, use normal priority
        if ti.destinations:
            return False

        # Check if strategy topic is detected in user text or activity_settings
        detected_topic = detect_strategy_topic(text_lower, ti.activity_settings)
        if detected_topic:
            _debug(
                "prefer_date_first: strategy topic detected without destinations",
                topic=detected_topic,
            )
            return True

        return False

    @classmethod
    def _build_result(
        cls,
        gate: GatePrecedence,
        destination: str,
        reason: str,
        start_time: float,
        skipped: List[str],
        state: "GraphState",
        intent: Optional[str] = None,
        strategy_topic: Optional[str] = None,
        question_target: Optional[str] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
        gate_trace: Optional[List[Dict[str, Any]]] = None,
    ) -> GateResult:
        """Build a GateResult with timing and v5 observability fields."""
        # Late import to avoid circular dependency
        from app.plan_graph import _record_gate_latency

        eval_time_ms = (time.perf_counter() - start_time) * 1000
        _record_gate_latency(eval_time_ms)

        # P0: Store gate trace in metadata for debugging
        if gate_trace:
            state.metadata["gate_trace"] = gate_trace
            _debug(
                "GATE_TRACE",
                gate_fired=gate.name,
                destination=destination,
                gates_checked=len(gate_trace),
                trace_summary=[
                    f"{g['gate']}:{'FIRED' if g['fired'] else 'skip'}" for g in gate_trace
                ],
            )

        # v5 fields: capture state at gate evaluation time
        llm_budget_used = state.metadata.get("llm_calls_this_turn", 0)
        date_clarify_mode = bool(state.metadata.get("date_clarify_mode", False))
        lqa_reason = state.metadata.get("lqa_reason")

        return GateResult(
            gate_fired=gate,
            destination=destination,
            reason=reason,
            skipped_gates=skipped,
            eval_time_ms=eval_time_ms,
            intent=intent,
            strategy_topic=strategy_topic,
            question_target=question_target,
            metadata_updates=metadata_updates or {},
            # v5 Routing Observability fields
            lqa_reason=lqa_reason,
            llm_budget_used=llm_budget_used,
            date_clarify_mode=date_clarify_mode,
        )
