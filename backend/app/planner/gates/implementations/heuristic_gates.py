"""Heuristic Gates - Precedence 100, 110, 120.

Contains pattern-matching gates that use heuristics to route
without requiring LLM calls:
- HIGH_CONFIDENCE (100): High extraction confidence bypass
- QUESTION_KEYWORD (110): Question word + domain keyword combos
- KEYWORD_HEURISTIC (120): Pure keyword-based intent detection
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

from app.config import settings
from app.pattern_matching import DOMAIN_KEYWORDS, QUESTION_WORDS
from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult

if TYPE_CHECKING:
    pass

# Confidence threshold for router bypass
CONFIDENCE_THRESHOLD_SKIP_ROUTER = settings.confidence_threshold_skip_router

# Intent keywords that indicate specific routing needs
INTENT_KEYWORDS = (
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
    # Flight preference keywords
    "direct",
    "nonstop",
    "business",
    "first class",
    "economy",
    "cabin",
    "layover",
    # Hotel preference keywords
    "star",
    "amenities",
    "breakfast",
    "gym",
    "pool",
    "spa",
)


class HighConfidenceGate(Gate):
    """Gate for high-confidence extraction bypass.

    Triggers when:
    - Extraction confidence is high (>= threshold)
    - Core fields are complete
    - No typo suggestions
    - Short input (<= 30 chars)
    - No intent keywords requiring routing

    Routes to required_fields_node to process the update.

    Precedence: 100
    """

    precedence = GatePrecedence.HIGH_CONFIDENCE
    name = "HIGH_CONFIDENCE"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if high confidence bypass should fire."""
        conf_level = ctx.extraction_conf.get("level", "medium")
        conf_overall = ctx.extraction_conf.get("overall", 0.5)
        no_typos = not ctx.extraction_conf.get("typo_suggestions", {})
        is_short_input = len(ctx.user_text.strip()) <= 30

        # Check for intent keywords that would require routing
        has_intent_keywords = any(kw in ctx.user_text_lower for kw in INTENT_KEYWORDS)

        # Relaxed threshold for short inputs
        conf_threshold = 0.88 if is_short_input else CONFIDENCE_THRESHOLD_SKIP_ROUTER

        if (
            conf_overall >= conf_threshold
            and ctx.readiness.core_complete
            and no_typos
            and conf_level == "high"
            and is_short_input
            and not has_intent_keywords
        ):
            self.record(ctx, fired=True, reason=f"high_confidence:{conf_overall:.2f}")
            return self.build_result(
                ctx,
                destination="required_fields_node",
                reason=f"high_confidence:{conf_overall:.2f}",
                intent="required_fields",
                metadata_updates={
                    "router_path": "high_confidence_bypass",
                    "router_bypassed": True,
                },
            )

        self.record(ctx, fired=False, reason="conditions_not_met")
        return None


class QuestionKeywordGate(Gate):
    """Gate for question word + domain keyword combinations.

    Examples:
    - "What hotels are available?" -> hotels_node
    - "Which flights should I take?" -> flights_node
    - "How do I get around?" -> transport_node

    Precedence: 110
    """

    precedence = GatePrecedence.QUESTION_KEYWORD
    name = "QUESTION_KEYWORD"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if question-keyword combo matches."""
        result = self._check_question_keyword_combo(ctx.user_text_lower)

        if not result:
            self.record(ctx, fired=False, reason="no_match")
            return None

        intent_name, destination = result
        self.record(ctx, fired=True, reason=f"question_keyword:{intent_name}")

        return self.build_result(
            ctx,
            destination=destination,
            reason=f"question_keyword:{intent_name}",
            intent=intent_name,
            metadata_updates={
                "router_path": f"question_keyword:{intent_name}",
                "router_bypassed": True,
                "router_bypass_reason": f"question_keyword:{intent_name}",
            },
        )

    def _check_question_keyword_combo(self, text_lower: str) -> Optional[Tuple[str, str]]:
        """
        Check for question-word + domain keyword combinations.

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


class KeywordHeuristicGate(Gate):
    """Gate for pure keyword-based intent detection.

    Uses keyword patterns to detect intent without LLM.
    Maps detected intent to appropriate node.

    Precedence: 120
    """

    precedence = GatePrecedence.KEYWORD_HEURISTIC
    name = "KEYWORD_HEURISTIC"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if keyword heuristic matches."""
        # Import here to avoid circular dependency
        from app.plan_graph import _detect_intent_from_keywords

        keyword_intent = _detect_intent_from_keywords(ctx.user_text_lower)

        if not keyword_intent:
            self.record(ctx, fired=False, reason="no_keyword_match")
            return None

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

        self.record(ctx, fired=True, reason=f"keyword:{intent_name}")

        return self.build_result(
            ctx,
            destination=destination,
            reason=f"keyword:{intent_name}",
            intent=intent_name,
            strategy_topic=strategy_topic,
            metadata_updates={
                "router_path": f"keyword_heuristic:{intent_name}",
                "router_bypassed": True,
                "router_bypass_reason": f"keyword:{intent_name}",
            },
        )
