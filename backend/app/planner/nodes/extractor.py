"""
Extractor Node - Structured data extraction from user text.

This module contains the extractor node function which extracts structured data
from user text using LLM. All trip input extraction (destinations, origin, dates,
travelers, budget, activities, settings) is performed by the LLM for robust
natural language understanding.

SHORT-CIRCUITS (bypasses LLM entirely via short_circuit_responder):
- Greetings: "hi", "hello", "hey" -> random greeting + destination question
- Acknowledgments: "ok", "thanks", "got it" -> continue flow
- Confirmations: "yes"/"no" with pending_action -> execute or clear action
- Off-topic: weather, math, general knowledge -> redirect to travel

Extracted from plan_graph.py as part of the P2 module extraction initiative.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict

# P2: Module-level imports for non-circular dependencies
from app.config import settings
from app.debug_utils import _debug, _debug_error
from app.graph_plan_utils import jloads_safe
from app.pattern_matching import text_is_compatible_with_target
from app.planner.node_utils import ti_short, today_iso
from app.planner.nodes.confidence import (
    build_extraction_confidence,
    high_confidence,
    low_confidence_error,
)

if TYPE_CHECKING:
    from app.plan_graph import GraphState


async def extractor(state: "GraphState") -> "GraphState":
    """
    Extract structured data from user text using LLM.

    All trip input extraction (destinations, origin, dates, travelers, budget,
    activities, settings) is performed by the LLM for robust natural language
    understanding.

    SHORT-CIRCUITS (bypasses LLM entirely via short_circuit_responder):
    - Greetings: "hi", "hello", "hey" -> random greeting + destination question
    - Acknowledgments: "ok", "thanks", "got it" -> continue flow
    - Confirmations: "yes"/"no" with pending_action -> execute or clear action
    - Off-topic: weather, math, general knowledge -> redirect to travel
    """
    # Late imports for plan_graph functions (circular dependency)
    from app.plan_graph import (
        _apply_typo_corrections,
        _debug_node_entry,
        _debug_node_exit,
        _detect_short_circuit,
        _detect_strategy_topic_from_text,
        _estimate_prompt_tokens,
        _extractor_stats,
        _get_core_fields_state,
        _get_extractor_cached,
        _get_node_llm_config,
        _increment_llm_calls,
        _is_dense_input,
        _is_generate_plan_trigger,
        _record_llm_time,
        _record_node_tokens,
        _set_extractor_cached,
        _try_initial_message_extraction,
        _try_strategy_bootstrap_bypass,
        _write_trip_inputs,
        call_llm_with_timeout,
        load_prompt,
        set_parse_provenance,
    )

    _, start_ns = _debug_node_entry("extractor", state)

    text = state.user_text
    parsed: Dict[str, Any] = {}

    # Check for generate plan trigger
    if _is_generate_plan_trigger(text):
        state.flags["generate_requested"] = True
        state.flags["generate_plan"] = True
        _debug("Generate plan trigger detected")
        state.parsed_inputs = parsed
        _debug_node_exit("extractor", state, start_ns)
        return state

    # =========================================================================
    # SHORT-CIRCUIT DETECTION
    # Keep lightweight short-circuits for greetings, acknowledgments, etc.
    # These save LLM tokens for trivial inputs.
    # =========================================================================
    short_circuit = _detect_short_circuit(text, state)
    if short_circuit:
        sc_type = short_circuit["type"]
        _debug(f"Short-circuit detected: {sc_type}", input=text[:30] if len(text) > 30 else text)

        state.flags["short_circuit"] = sc_type
        state.flags["short_circuit_response"] = short_circuit.get("response")
        state.flags["short_circuit_action"] = short_circuit.get("action")

        # If short-circuit extracted parsed data, merge it
        sc_parsed = short_circuit.get("parsed")
        if sc_parsed:
            parsed.update(sc_parsed)
            _debug("Short-circuit parsed data", parsed=sc_parsed)

        # For confirmations that trigger actions, handle them
        if short_circuit.get("action") == "generate_plan":
            state.flags["generate_requested"] = True
            state.flags["generate_plan"] = True
            # Track user request type for suggestion filtering
            if short_circuit.get("user_request_type"):
                state.metadata["user_request_type"] = short_circuit["user_request_type"]
            _debug("Short-circuit triggered generate_plan")
        elif short_circuit.get("action") == "apply_typo_corrections":
            # Apply the stored typo corrections to trip_inputs
            typo_corrections = (sc_parsed or {}).get("typo_corrections", {})
            if typo_corrections:
                _apply_typo_corrections(state, typo_corrections)
            state.metadata.pop("pending_action", None)
            state.metadata.pop("pending_typo_corrections", None)
            _debug("Short-circuit applied typo corrections", corrections=typo_corrections)
        elif short_circuit.get("action") == "clear_pending":
            state.metadata.pop("pending_action", None)
            state.metadata.pop("pending_typo_corrections", None)
            _debug("Short-circuit cleared pending_action")

        state.parsed_inputs = parsed
        _debug_node_exit("extractor", state, start_ns)
        return state

    # =========================================================================
    # STRATEGY BOOTSTRAP BYPASS: Skip extractor LLM for strategy pre-core
    # =========================================================================
    # When user enters a simple strategy prompt like "Plan a hiking trip",
    # we can deterministically detect the topic and bypass the extractor LLM,
    # routing directly to strategy_node stage0. This saves one LLM call.
    #
    # Safety gates to avoid bad routing:
    # 1. Feature flag enabled (settings.enable_strategy_bootstrap_bypass)
    # 2. No question_target (first turn or open-ended)
    # 3. Core fields are empty (destinations, dates not set)
    # 4. Strategy topic detected in text
    # 5. No place-like entities detected (avoid missing destination in "Hiking in Alps")
    # 6. Short text (< 150 chars) - dense prompts need full extraction
    # 7. No constraint tokens (dates, budget, travelers)
    # 8. No multi-intent (multiple specialists or topics)
    # =========================================================================
    bypass_result = _try_strategy_bootstrap_bypass(text, state)
    if bypass_result:
        # Bypass succeeded - set strategy_topic and route to STRATEGY_PRE_CORE_VALUE
        state.strategy_topic = bypass_result["topic"]
        state.flags["strategy_bootstrap_bypass"] = True
        state.flags["strategy_bootstrap_active"] = True  # BUG FIX: explicit boolean
        state.flags["fast_path"] = True
        state.flags["fast_path_field"] = "strategy_bootstrap"
        set_parse_provenance(state, "deterministic")  # Parse provenance
        # Response generation provenance will be set by the strategy node

        # Set minimal trip_shape fields deterministically
        if bypass_result.get("trip_style"):
            _write_trip_inputs(
                state, "extractor", trip_style=bypass_result["trip_style"]
            )  # Ignore fields_changed
        if bypass_result.get("activity_categories"):
            _write_trip_inputs(
                state, "extractor", activity_categories=bypass_result["activity_categories"]
            )  # Ignore fields_changed

        # Record bypass observability
        state.metadata["bypass_variant"] = bypass_result.get("variant", "bypass")
        state.metadata["bypass_observability"] = {
            "bypass_attempted": True,
            "bypass_taken": True,
            "bypass_reject_reasons": [],
            "place_detected_by": bypass_result.get("place_detected_by", "none"),
            "constraint_tokens": bypass_result.get("constraint_tokens", {}),
            "invariant_check_passed": True,
        }

        # Set question_target to dates for stage0
        state.metadata["question_target"] = "dates"

        _debug(
            "Strategy bootstrap bypass: skipping extractor LLM",
            topic=bypass_result["topic"],
            trip_style=bypass_result.get("trip_style"),
        )

        state.parsed_inputs = parsed
        _debug_node_exit("extractor", state, start_ns)
        return state

    # =========================================================================
    # NOTE: Fast-path extraction is now handled by lqa_prepass node which runs
    # BEFORE extractor. If we reach here, either LQA wasn't applicable or it
    # bailed, so we proceed directly to initial message extraction or LLM.
    # =========================================================================

    # =========================================================================
    # PHASE 6: ZERO-LLM INITIAL MESSAGE EXTRACTION
    # Handle simple initial messages like "I want to go to Paris" or
    # "2 adults, Paris, next month" without LLM even when question_target is not set.
    # Saves ~1145 tokens on first turn for simple requests.
    # =========================================================================
    initial_result = _try_initial_message_extraction(text, state)
    if initial_result:
        init_fields = initial_result["fields"]
        init_parsed = initial_result["parsed"]
        _debug(
            f"Zero-LLM initial extraction success: {init_fields}",
            parsed=init_parsed,
            input=text[:50] if len(text) > 50 else text,
        )

        # Set fast-path flag for routing (reuse same routing path)
        state.flags["fast_path"] = True
        state.flags["fast_path_field"] = init_fields[0] if init_fields else "multi"

        # Merge parsed data
        parsed.update(init_parsed)

        # Set high confidence since we matched deterministically
        state.metadata["extraction_confidence"] = high_confidence(
            "initial_extraction", overall=0.92
        )

        # Record path trace for metrics
        state.metadata["extraction_path"] = f"initial:{','.join(init_fields)}"

        # Set strategy_topic from user text before returning (for topic-aware suggestions)
        if not state.strategy_topic and text:
            state.strategy_topic = _detect_strategy_topic_from_text(text)
            if state.strategy_topic:
                _debug(
                    "Strategy topic set from user text (initial extraction path)",
                    topic=state.strategy_topic,
                )

        state.parsed_inputs = parsed
        _debug_node_exit("extractor", state, start_ns)
        return state

    # =========================================================================
    # LLM-BASED EXTRACTION (Light or Full mode)
    # Light mode: Core fields only (~128 tokens) - used for early/simple turns
    # Full mode: All fields (~400 tokens) - used for dense input or near-ready
    # =========================================================================

    # =========================================================================
    # v7 Final v5: TOPIC SWITCH BYPASS (skip extractor entirely)
    # =========================================================================
    # When user says "I wanna go diving" but question_target is "budget",
    # skip extractor entirely and let the gate route to STRATEGY_TOPIC_SWITCH.
    # This saves ~3,755 tokens on off-target strategy requests.
    #
    # Conservative order:
    # 1. First try deterministic parse for current question_target
    # 2. Only if that fails AND text looks like topic switch AND text is
    #    NOT compatible with target -> skip extractor
    # =========================================================================
    question_target = state.question_target or state.metadata.get("question_target")
    if question_target and question_target in ("budget", "dates", "travelers", "adults"):
        # Check if text is compatible with the current question target
        is_compatible = text_is_compatible_with_target(text, question_target)

        if not is_compatible:
            # Check if this looks like a strategy topic switch
            text_lower = text.lower()
            strategy_keywords = {
                "diving": ["diving", "scuba", "snorkel"],
                "hiking": ["hiking", "trek", "hike"],
                "skiing": ["skiing", "ski", "snowboard"],
                "cycling": ["cycling", "bike", "biking"],
                "boating": ["boating", "sailing", "boat"],
            }
            detected_topic = None
            for topic, keywords in strategy_keywords.items():
                if any(kw in text_lower for kw in keywords):
                    detected_topic = topic
                    break

            # Check for intent verbs
            has_intent_verb = any(
                verb in text_lower
                for verb in ("want", "wanna", "go", "plan", "try", "do", "add", "also")
            )

            if detected_topic and has_intent_verb:
                _debug(
                    "EXTRACTOR TOPIC_SWITCH_BYPASS: skipping extractor (off-target strategy)",
                    question_target=question_target,
                    detected_topic=detected_topic,
                    is_compatible=is_compatible,
                )
                _extractor_stats["skipped_topic_switch"] = (
                    _extractor_stats.get("skipped_topic_switch", 0) + 1
                )
                state.metadata["extractor_skipped_reason"] = "topic_switch_bypass"
                state.strategy_topic = detected_topic
                # Set minimal parsed_inputs to allow gate evaluation
                state.parsed_inputs = parsed
                state.metadata["extraction_path"] = "topic_switch_bypass"
                _debug_node_exit("extractor", state, start_ns)
                return state

    # Determine extraction mode
    is_dense, dense_reason = _is_dense_input(text, state)
    extractor_mode = "full" if is_dense else "light"

    # Record path trace for metrics
    state.metadata["extraction_path"] = f"llm:{extractor_mode}"
    state.metadata["extractor_mode"] = extractor_mode
    state.metadata["extractor_mode_reason"] = dense_reason

    # =========================================================================
    # EXTRACTOR CACHE CHECK (60s TTL, turn-level dedup)
    # Key: (session_id, user_text, core_fields_hash, mode)
    # Saves ~500-1000 tokens when user sends identical message
    # =========================================================================
    session_id = state.session_id or "unknown"
    core_fields_hash = _get_core_fields_state(state.trip_inputs)

    cached_extraction = _get_extractor_cached(
        session_id, text, core_fields_hash, extractor_mode, state
    )
    if cached_extraction is not None:
        _debug(
            "EXTRACTOR_CACHE_HIT: Using cached extraction",
            mode=extractor_mode,
            cache_key_prefix=f"{session_id[:8]}...",
            tokens_saved="~500-1000 (LLM call avoided)",
        )
        # Restore cached state
        state.parsed_inputs = cached_extraction.get("parsed", {})
        state.metadata["extraction_confidence"] = cached_extraction.get("confidence", {})
        state.metadata["extraction_path"] = f"cache:{extractor_mode}"
        _debug_node_exit("extractor", state, start_ns)
        return state

    # Select config and prompt based on mode
    if extractor_mode == "light":
        llm_config = _get_node_llm_config("extractor_light")
        prompt_name = "extractor_light"
        _debug(
            "Extractor using LIGHT mode",
            reason=dense_reason,
            max_tokens=llm_config["max_tokens"],
        )
    else:
        llm_config = _get_node_llm_config("extractor")
        prompt_name = "extractor"
        _debug(
            "Extractor using FULL mode",
            reason=dense_reason,
            max_tokens=llm_config["max_tokens"],
        )

    today_str = state.metadata.get("today_iso") or today_iso()

    try:
        prompt = load_prompt(prompt_name)

        # Light mode uses simpler template (no trip_inputs context needed)
        if extractor_mode == "light":
            tpl = prompt.replace("{today}", today_str).replace("{user_text}", text)
        else:
            tpl = (
                prompt.replace("{today}", today_str)
                .replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
                .replace("{user_text}", text)
            )

        tokens = _estimate_prompt_tokens(tpl, state.parsed_inputs)
        _record_node_tokens(
            state, f"extractor:{extractor_mode}", tokens, model=llm_config["model_hint"]
        )

        import time as _time

        _llm_start = _time.perf_counter()
        out = await call_llm_with_timeout(
            model=llm_config["model_hint"],
            prompt=tpl,
            timeout_seconds=settings.llm_timeout_extractor,
            max_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
        )
        _record_llm_time(state, (_time.perf_counter() - _llm_start) * 1000)
        _increment_llm_calls(state)
        extracted = jloads_safe(out)

        # Map LLM output to parsed_inputs format
        if extracted.get("destinations_delta"):
            parsed["destinations_delta"] = extracted["destinations_delta"]
        if extracted.get("origin_delta"):
            parsed["origin_delta"] = extracted["origin_delta"]
        if extracted.get("start_date_hint"):
            parsed["start_date_hint"] = extracted["start_date_hint"]
        if extracted.get("end_date_hint"):
            parsed["end_date_hint"] = extracted["end_date_hint"]
        if extracted.get("duration_days"):
            parsed["duration_days"] = extracted["duration_days"]
        if extracted.get("adults_delta") is not None:
            parsed["adults_delta"] = extracted["adults_delta"]
        if extracted.get("children_delta") is not None:
            parsed["children_delta"] = extracted["children_delta"]
        if extracted.get("requires_assistance_delta") is not None:
            parsed["requires_assistance_delta"] = extracted["requires_assistance_delta"]
        if extracted.get("budget_delta"):
            parsed["budget_delta"] = extracted["budget_delta"]
        if extracted.get("multi_city_intent_delta"):
            parsed["multi_city_intent_delta"] = extracted["multi_city_intent_delta"]
        if extracted.get("category_activation"):
            parsed["category_activation"] = extracted["category_activation"]
        if extracted.get("flight_settings_delta"):
            parsed["flight_settings_delta"] = extracted["flight_settings_delta"]
        if extracted.get("hotel_settings_delta"):
            parsed["hotel_settings_delta"] = extracted["hotel_settings_delta"]
        if extracted.get("transport_settings_delta"):
            parsed["transport_settings_delta"] = extracted["transport_settings_delta"]
        if extracted.get("activity_categories_delta"):
            # Map to inferred_activity_categories for normalize_inputs
            parsed["inferred_activity_categories"] = extracted["activity_categories_delta"]
        if extracted.get("strategy_hint"):
            parsed["strategy_hint"] = extracted["strategy_hint"]

        # Store LLM-reported confidence in metadata
        confidence_score = extracted.get("confidence", 0.8)
        confidence_reasons = extracted.get("confidence_reasons") or []

        state.metadata["extraction_confidence"] = build_extraction_confidence(
            overall=confidence_score,
            method="llm",
            low_confidence_reasons=confidence_reasons,
        )

        # Cache the extraction result for future identical requests (60s TTL)
        _set_extractor_cached(
            session_id,
            text,
            core_fields_hash,
            extractor_mode,
            {
                "parsed": parsed,
                "confidence": state.metadata["extraction_confidence"],
            },
        )

        confidence_level = state.metadata["extraction_confidence"]["level"]
        _debug(
            "Extraction confidence calculated",
            overall=f"{confidence_score:.2f}",
            level=confidence_level,
            method="llm",
            grammar_matched=False,
            reasons=confidence_reasons[:3] if confidence_reasons else None,
        )

    except TimeoutError:
        _debug("Extractor LLM timeout, using empty parsed_inputs")
        state.metadata["extraction_confidence"] = low_confidence_error("llm_timeout", "llm_timeout")
    except Exception as e:
        _debug_error("Extractor LLM error", error=str(e))
        state.metadata["extraction_confidence"] = low_confidence_error("llm_error", "llm_error")

    state.parsed_inputs = parsed

    # =========================================================================
    # EARLY STRATEGY_TOPIC DETECTION
    # Set strategy_topic from activity_settings or user text keywords so
    # templates can use topic-aware suggestions on first turn.
    # =========================================================================
    if not state.strategy_topic:
        # First try to derive from activity_settings categories
        categories = getattr(state.trip_inputs.activity_settings, "categories", None) or []
        for cat in categories:
            detected = _detect_strategy_topic_from_text(cat)
            if detected:
                state.strategy_topic = detected
                _debug(
                    "Strategy topic set from activity_settings",
                    topic=detected,
                    category=cat,
                )
                break

        # If still not set, check user text for topic keywords (with word boundaries)
        if not state.strategy_topic and text:
            state.strategy_topic = _detect_strategy_topic_from_text(text)
            if state.strategy_topic:
                _debug(
                    "Strategy topic set from user text",
                    topic=state.strategy_topic,
                )

    _debug_node_exit("extractor", state, start_ns)
    return state
