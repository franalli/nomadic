"""
LQA Pre-pass Node - Deterministic extraction for simple user answers.

This module contains the lqa_prepass node function which runs BEFORE the extractor
to parse simple answers to the last question asked. When successful, this enables
skipping the LLM extractor entirely, saving tokens and latency.

Extracted from plan_graph.py as part of the P2 module extraction initiative.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# P2: Module-level imports for non-circular dependencies
from app.config import settings
from app.debug_utils import _debug
from app.pattern_matching import LQA_BAIL_PATTERNS, is_traveler_detail_answer
from app.planner.nodes.confidence import high_confidence
from app.planner.parsing import (
    _LQA_FIELD_PARSERS,
    _extract_negation_alternative,
    _is_activity_preference_text,
    _is_date_like_text,
    _is_place_like_text,
)

if TYPE_CHECKING:
    from app.plan_graph import GraphState


def _clear_stale_question_and_ack(state: "GraphState", field: str, parsed: dict) -> None:
    """Clear stale last_summary after successful LQA parse and set acknowledgment.

    This prevents the infinite loop where the old question (e.g., "Budget:") gets
    echoed back even after the field was successfully parsed.
    """
    state.question_target = None

    # Generate brief acknowledgment based on field
    ack = None
    if field == "budget":
        if "budget_delta" in parsed:
            amount = int(parsed["budget_delta"])
            ack = f"Got it, ${amount:,} budget."
        elif parsed.get("budget_answered"):
            ack = "Got it, flexible budget."
    elif field == "destinations":
        dests = parsed.get("destinations_delta") or parsed.get("destinations", [])
        if dests:
            ack = f"Got it, {dests[0]}."
    elif field == "origin":
        origin = parsed.get("origin_delta") or parsed.get("origin")
        if origin:
            ack = f"Got it, from {origin}."
    elif field == "travelers":
        adults = parsed.get("adults_delta", 0)
        children = parsed.get("children_delta", 0)
        total = adults + children
        if total == 1:
            ack = "Got it, solo traveler."
        elif total > 0:
            ack = f"Got it, {total} travelers."

    # Set acknowledgment (or clear stale question if no ack)
    state.last_summary = ack


def lqa_prepass(state: "GraphState") -> "GraphState":
    """
    LQA (Last Question Answer) pre-pass node.

    Runs BEFORE extractor to deterministically parse simple answers to the
    last question asked. If successful, sets parsed_inputs and flags so
    extractor can be skipped entirely.

    Bail conditions (falls through to extractor):
    - pending_action is set (short-circuit should handle)
    - No question_target/last_question_field set
    - Input exceeds lqa_max_length
    - Multi-intent or negation patterns detected
    - Field validation fails

    Returns:
        Updated state with flags["lqa_prepass"] = True/False
    """
    # Late imports for plan_graph functions (circular dependency)
    from app.plan_graph import (
        _date_stats,
        _debug_node_entry,
        _debug_node_exit,
        _lqa_stats,
        _run_deterministic_pipeline,
        _write_trip_inputs,
        canonicalize_question_target,
        set_parse_provenance,
    )

    _, start_ns = _debug_node_entry("lqa_prepass", state)
    _lqa_stats["attempts"] += 1

    text = (state.user_text or "").strip()

    # -------------------------------------------------------------------------
    # BAIL 1: Pending action (defer to short-circuit handling in extractor)
    # -------------------------------------------------------------------------
    pending_action = state.metadata.get("pending_action")
    if pending_action:
        _lqa_stats["bails"] += 1
        _lqa_stats["bail_pending_action"] += 1
        state.flags["lqa_prepass"] = False
        state.flags["lqa_bail_reason"] = "pending_action"
        _debug("[LQA] BAIL: pending_action set", action=pending_action)
        _debug_node_exit("lqa_prepass", state, start_ns)
        return state

    # -------------------------------------------------------------------------
    # BAIL 2: No question_target (can't know what field to parse)
    # -------------------------------------------------------------------------
    raw_question_target = state.question_target or state.metadata.get("last_question_field")
    if not raw_question_target:
        _lqa_stats["bails"] += 1
        _lqa_stats["bail_no_question_target"] += 1
        state.flags["lqa_prepass"] = False
        state.flags["lqa_bail_reason"] = "no_question_target"
        _debug("[LQA] BAIL: no question_target set")
        _debug_node_exit("lqa_prepass", state, start_ns)
        return state

    # Canonicalize question_target before parsing
    question_target = canonicalize_question_target(raw_question_target)

    # -------------------------------------------------------------------------
    # V16: SUGGESTION CLICK FAST-PATH (V36 FIX: parse before bypassing)
    # -------------------------------------------------------------------------
    # If user text exactly matches a previously offered suggestion, try to
    # parse it with the appropriate LQA parser BEFORE bypassing. This fixes
    # the bug where budget suggestions like "No limit" were bypassed without
    # setting budget_answered=True, causing an infinite loop.
    last_suggestions = state.metadata.get("last_offered_suggestions", [])
    if last_suggestions:
        text_lower = text.lower().strip()
        for suggestion in last_suggestions:
            if suggestion.lower().strip() == text_lower:
                # V36 FIX: If question_target is set, try parsing the suggestion
                # This handles cases like "No limit" for budget, "Just me" for travelers
                if question_target and question_target in _LQA_FIELD_PARSERS:
                    parser = _LQA_FIELD_PARSERS[question_target]
                    parsed = parser(text, state)
                    if parsed:
                        # Successfully parsed! Set parsed_inputs and continue
                        state.parsed_inputs = parsed
                        state.flags["lqa_prepass"] = True
                        state.flags["lqa_field"] = question_target
                        _lqa_stats["successes"] += 1
                        _clear_stale_question_and_ack(state, question_target, parsed)
                        _debug(
                            "[LQA] SUGGESTION_CLICK: parsed successfully",
                            matched_suggestion=suggestion[:40],
                            question_target=question_target,
                            parsed_keys=list(parsed.keys()),
                        )
                        _debug_node_exit("lqa_prepass", state, start_ns)
                        return state

                # No parser or parsing failed - fall back to original bypass behavior
                _lqa_stats["bails"] += 1
                state.flags["lqa_prepass"] = False
                state.flags["lqa_bail_reason"] = "suggestion_click"
                _debug(
                    "[LQA] BYPASS: suggestion click detected",
                    matched_suggestion=suggestion[:40],
                )
                _debug_node_exit("lqa_prepass", state, start_ns)
                return state

    # -------------------------------------------------------------------------
    # NOT DATE-LIKE BAIL: When asking for dates but text looks like a place
    # -------------------------------------------------------------------------
    # Per test_lqa_skips_place_when_target_is_dates: when user gives a place
    # name (like "Swiss Alps") but we asked for dates, bail with "not_date_like"
    # and let the system re-ask for dates.
    # V16: Also check for activity preferences which should route to strategy
    if question_target == "dates":
        # V16: Activity preferences should go to strategy, not re-ask dates
        if _is_activity_preference_text(text):
            _lqa_stats["bails"] += 1
            state.flags["lqa_prepass"] = False
            state.flags["lqa_bail_reason"] = "activity_preference"
            _debug(
                "[LQA] BYPASS: activity preference detected, routing to strategy",
                text=text[:40],
            )
            _debug_node_exit("lqa_prepass", state, start_ns)
            return state

        if not _is_date_like_text(text) and _is_place_like_text(text):
            _lqa_stats["bails"] += 1
            _date_stats["lqa_skip_not_date_like"] += 1
            state.flags["lqa_prepass"] = False
            state.flags["lqa_bail_reason"] = "not_date_like"
            _debug(
                "[LQA] SKIP: text is place-like, asked for dates",
                target=question_target,
                text=text[:30],
            )
            _debug_node_exit("lqa_prepass", state, start_ns)
            return state

    # -------------------------------------------------------------------------
    # BAIL 3: Input too long
    # -------------------------------------------------------------------------
    if len(text) > settings.lqa_max_length:
        _lqa_stats["bails"] += 1
        _lqa_stats["bail_too_long"] += 1
        state.flags["lqa_prepass"] = False
        state.flags["lqa_bail_reason"] = "too_long"
        _debug(
            "[LQA] BAIL: input too long",
            length=len(text),
            max=settings.lqa_max_length,
        )
        _debug_node_exit("lqa_prepass", state, start_ns)
        return state

    # -------------------------------------------------------------------------
    # BAIL 4: Multi-intent or negation patterns
    # v7 Final v5: Check for traveler-detail answer BEFORE bail patterns
    # to avoid false-positive bail on comma-separated age lists like
    # "Three kids, ages 3, 6, and 12"
    # -------------------------------------------------------------------------
    if is_traveler_detail_answer(text, question_target):
        _debug(
            "[LQA] SKIP BAIL: traveler-detail answer detected",
            text=text[:50],
            question_target=question_target,
        )
        # Don't bail - let the deterministic pipeline or LQA parsers handle it
        # Store info for special_requests if we don't have a schema field
        if "ages" in text.lower():
            existing_info = state.trip_inputs.additional_info or ""
            if text.strip() not in existing_info:
                _write_trip_inputs(
                    state,
                    "lqa_prepass",
                    additional_info=f"{existing_info} {text.strip()}".strip(),
                )
    else:
        # =====================================================================
        # P4.1: NEGATION ALTERNATIVE EXTRACTION (before generic bail)
        # =====================================================================
        # Try to extract alternative from negation patterns like "not Paris, maybe Barcelona"
        # If successful, parse the alternative and treat as LQA hit
        negation_result = _extract_negation_alternative(text, state)
        if negation_result:
            alternative = negation_result.get("alternative")
            negation_type = negation_result.get("negation_type")

            if alternative and question_target and question_target in _LQA_FIELD_PARSERS:
                # Try to parse the alternative text
                parser = _LQA_FIELD_PARSERS[question_target]
                parsed = parser(alternative, state)

                if parsed:
                    # Successfully parsed alternative - treat as LQA hit
                    _lqa_stats["successes"] += 1
                    state.parsed_inputs = parsed
                    state.flags["lqa_prepass"] = True
                    state.flags["lqa_field"] = question_target
                    state.metadata["negation_alternative_extracted"] = True
                    state.metadata["negation_type"] = negation_type
                    state.metadata["extraction_confidence"] = high_confidence(
                        f"lqa:negation:{negation_type}", overall=0.92
                    )
                    state.metadata["parse_path"] = f"lqa:negation:{negation_type}"
                    _debug(
                        "[LQA] NEGATION_ALTERNATIVE: parsed successfully",
                        alternative=alternative[:40],
                        negation_type=negation_type,
                        parsed_keys=list(parsed.keys()),
                        tokens_saved="~500 (negation extracted without LLM)",
                    )
                    _debug_node_exit("lqa_prepass", state, start_ns)
                    return state
                else:
                    # Alternative found but couldn't parse - mark for extractor
                    _debug(
                        "[LQA] NEGATION_ALTERNATIVE: found but unparsable, marking for extractor",
                        alternative=alternative[:40],
                        negation_type=negation_type,
                    )
                    state.metadata["negation_alternative_raw"] = alternative
                    state.metadata["negation_type"] = negation_type
                    # Fall through to extractor (don't bail)
                    state.flags["lqa_prepass"] = False
                    state.flags["lqa_bail_reason"] = f"negation_unparsable:{negation_type}"
                    _debug_node_exit("lqa_prepass", state, start_ns)
                    return state
            elif negation_type == "simple_rejection":
                # User rejected without alternative - bail to re-ask
                _lqa_stats["bails"] += 1
                state.flags["lqa_prepass"] = False
                state.flags["lqa_bail_reason"] = "simple_rejection"
                _debug(
                    "[LQA] NEGATION: simple rejection, will re-ask",
                    text=text[:30],
                )
                _debug_node_exit("lqa_prepass", state, start_ns)
                return state

        # Standard bail pattern check
        for i, pattern in enumerate(LQA_BAIL_PATTERNS):
            if pattern.search(text):
                bail_types = ["multi_intent", "multi_intent", "negation"]
                bail_type = bail_types[i] if i < len(bail_types) else "multi_intent"
                _lqa_stats["bails"] += 1
                _lqa_stats[f"bail_{bail_type}"] += 1
                state.flags["lqa_prepass"] = False
                state.flags["lqa_bail_reason"] = bail_type
                _debug(
                    f"[LQA] BAIL: {bail_type} pattern detected",
                    pattern_idx=i,
                    text=text[:30],
                )
                _debug_node_exit("lqa_prepass", state, start_ns)
                return state

    # -------------------------------------------------------------------------
    # MVP OPTIMIZATION: DETERMINISTIC PIPELINE (runs before LQA parsers)
    # -------------------------------------------------------------------------
    # This is the highest-impact token saver. It handles:
    # - Suggestion echo: exact-match to last_suggestions
    # - Season/month dates: "next summer", "December"
    # - Travelers: "solo", "couple", "family of 4"
    # - Multi-place: "Paris and Rome"
    # - Single place (known): "Patagonia"
    #
    # On hit, returns LQA-shaped delta dict and skips extractor entirely.
    det_result = _run_deterministic_pipeline(text, state)
    if det_result:
        lqa_reason = det_result.get("lqa_reason", "deterministic:unknown")

        # Handle date ambiguity: don't set dates, trigger clarify mode
        if det_result.get("_date_clarify_mode"):
            state.flags["lqa_prepass"] = False
            state.flags["lqa_bail_reason"] = lqa_reason
            state.metadata["date_clarify_mode"] = True
            state.metadata["pending_date_text"] = det_result.get("_pending_date_text")
            # Store suggestions for season clarification (Issue 4)
            if det_result.get("_clarify_suggestions"):
                state.metadata["date_clarify_suggestions"] = det_result["_clarify_suggestions"]
            if det_result.get("_season_name"):
                state.metadata["date_clarify_season_name"] = det_result["_season_name"]
            set_parse_provenance(state, "deterministic")
            _debug(
                "[LQA] DETERMINISTIC: date ambiguous, triggering clarify mode",
                pending_text=det_result.get("_pending_date_text"),
                suggestions=det_result.get("_clarify_suggestions"),
            )
            _debug_node_exit("lqa_prepass", state, start_ns)
            return state

        # Build parsed_inputs from delta dict (keep delta format for compatibility)
        parsed = {}
        if "destinations_delta" in det_result:
            parsed["destinations_delta"] = det_result["destinations_delta"]
        if "origin_delta" in det_result:
            parsed["origin_delta"] = det_result["origin_delta"]
        if "start_date_delta" in det_result:
            parsed["start_date_hint"] = det_result["start_date_delta"]
        if "end_date_delta" in det_result:
            parsed["end_date_hint"] = det_result["end_date_delta"]
        if "adults_delta" in det_result:
            parsed["adults_delta"] = det_result["adults_delta"]
        if "children_delta" in det_result:
            parsed["children_delta"] = det_result["children_delta"]

        if parsed:
            _lqa_stats["hits"] += 1
            _lqa_stats["deterministic_pipeline_hits"] = (
                _lqa_stats.get("deterministic_pipeline_hits", 0) + 1
            )
            state.flags["lqa_prepass"] = True
            state.flags["lqa_field"] = lqa_reason.replace("deterministic:", "")
            state.parsed_inputs = parsed
            set_parse_provenance(state, "deterministic")
            # v7 Final v5: Record parse provenance separately
            state.metadata["parse_provenance"] = "deterministic"

            # v7 Final v5: Mark question as answered this turn for bypass
            # Use active_question_id (the question we asked) not question_id_counter
            if question_target:
                state.metadata["answered_question_target_this_turn"] = state.metadata.get(
                    "active_question_target"
                )
                state.metadata["answered_question_id_this_turn"] = state.metadata.get(
                    "active_question_id"
                )

            # Determine if we should advance question_target
            keep_target = det_result.get("_keep_question_target", False)
            if not keep_target:
                lqa_field = lqa_reason.replace("deterministic:", "")
                _clear_stale_question_and_ack(state, lqa_field, parsed)

            # Set high confidence for deterministic parsing
            state.metadata["extraction_confidence"] = high_confidence(lqa_reason, overall=0.98)
            # Canonical parse path field (consolidating lqa_reason and extraction_path)
            state.metadata["parse_path"] = lqa_reason
            state.metadata["lqa_reason"] = lqa_reason  # For gate evaluation
            state.metadata["extraction_path"] = lqa_reason  # Backward compat

            # Record multi-city signal if present
            if det_result.get("_multi_city_signal"):
                state.metadata["multi_city_signal"] = True

            _debug(
                "[LQA] DETERMINISTIC: pipeline hit",
                reason=lqa_reason,
                parsed=parsed,
                text=text[:30],
                tokens_saved="~500 (extractor_light avoided)",
            )
            _debug_node_exit("lqa_prepass", state, start_ns)
            return state

    # -------------------------------------------------------------------------
    # BAIL 5: No parser for this question_target
    # -------------------------------------------------------------------------
    parser = _LQA_FIELD_PARSERS.get(question_target)
    if not parser:
        _lqa_stats["bails"] += 1
        _lqa_stats["bail_validation_fail"] += 1
        state.flags["lqa_prepass"] = False
        state.flags["lqa_bail_reason"] = "unhandled_field"
        _debug("[LQA] BAIL: no parser for question_target", target=question_target)
        _debug_node_exit("lqa_prepass", state, start_ns)
        return state

    # -------------------------------------------------------------------------
    # ATTEMPT PARSING
    # -------------------------------------------------------------------------
    parsed = parser(text, state)
    if parsed is None:
        _lqa_stats["bails"] += 1
        _lqa_stats["bail_validation_fail"] += 1
        state.flags["lqa_prepass"] = False
        state.flags["lqa_bail_reason"] = "validation_fail"
        _debug(
            "[LQA] BAIL: validation failed",
            target=question_target,
            text=text[:30],
        )
        _debug_node_exit("lqa_prepass", state, start_ns)
        return state

    # -------------------------------------------------------------------------
    # RESTRICT FIELD UPDATES DURING DATE CLARIFY MODE
    # -------------------------------------------------------------------------
    # When question_target is "dates", only allow updates to date-related fields.
    # This prevents mixed answers like "Next year in Zermatt" from polluting
    # destination/origin state while in date clarification mode.
    if question_target == "dates":
        allowed_keys = {
            "start_date_hint",
            "end_date_hint",
            "start_date",
            "end_date",
            "date_precision",
        }
        filtered_parsed = {k: v for k, v in parsed.items() if k in allowed_keys}
        if len(filtered_parsed) != len(parsed):
            _debug(
                "[LQA] Filtered non-date fields during dates clarify",
                original_keys=list(parsed.keys()),
                filtered_keys=list(filtered_parsed.keys()),
            )
            parsed = filtered_parsed

        # If nothing left after filtering, bail
        if not parsed:
            _lqa_stats["bails"] += 1
            state.flags["lqa_prepass"] = False
            state.flags["lqa_bail_reason"] = "no_date_fields_after_filter"
            _debug("[LQA] BAIL: no date fields after filter")
            _debug_node_exit("lqa_prepass", state, start_ns)
            return state

    # -------------------------------------------------------------------------
    # SUCCESS: Set parsed_inputs and flags
    # -------------------------------------------------------------------------
    _lqa_stats["hits"] += 1
    state.flags["lqa_prepass"] = True
    state.flags["lqa_field"] = question_target
    state.parsed_inputs = parsed

    # Clear question_target and stale last_summary after successfully answering it,
    # so required_fields will ask about the next missing field instead of repeating
    _clear_stale_question_and_ack(state, question_target, parsed)

    # Set high confidence since we matched deterministically
    state.metadata["extraction_confidence"] = high_confidence("lqa_prepass", overall=0.95)

    # Record path trace for metrics
    state.metadata["extraction_path"] = f"lqa:{question_target}"

    _debug(
        "[LQA] HIT: parsed successfully",
        target=question_target,
        parsed=parsed,
        text=text[:30],
    )
    _debug_node_exit("lqa_prepass", state, start_ns)
    return state
