"""Heuristic Gates - Precedence 110.

Contains pattern-matching gates that use heuristics to route
without requiring LLM calls:
- QUESTION_KEYWORD (110): Question word + domain keyword combos + keyword heuristic fallback

Consolidated gates (removed):
- HIGH_CONFIDENCE (100): Removed - READY_NO_FIELDS handles core_complete cases
- KEYWORD_HEURISTIC (120): Merged into QUESTION_KEYWORD as fallback
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

from app.pattern_matching import DOMAIN_KEYWORDS, QUESTION_WORDS
from app.planner.gates.base import Gate, GateContext
from app.planner.gates.constants import SPECIALIST_NODE_MAP, SPECIALIST_NODE_MAP_EXTENDED
from app.planner.gates.keyword_utils import keyword_match
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult

if TYPE_CHECKING:
    pass


class QuestionKeywordGate(Gate):
    """Gate for question word + domain keyword combinations with keyword heuristic fallback.

    Primary check (question-keyword combo):
    - "What hotels are available?" -> hotels_node
    - "Which flights should I take?" -> flights_node
    - "How do I get around?" -> transport_node

    Fallback (pure keyword heuristic):
    - "hiking trip" -> strategy_node
    - "need flights" -> flights_node

    Precedence: 110
    """

    precedence = GatePrecedence.QUESTION_KEYWORD
    name = "QUESTION_KEYWORD"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if question-keyword combo or keyword heuristic matches."""
        # First check: question-word + domain keyword combo
        result = self._check_question_keyword_combo(ctx.user_text_lower)
        if result:
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

        # Fallback: pure keyword heuristic (was KEYWORD_HEURISTIC gate)
        keyword_result = self._check_keyword_heuristic(ctx.user_text_lower)
        if keyword_result:
            intent_name, destination, strategy_topic = keyword_result
            self.record(ctx, fired=True, reason=f"keyword_heuristic:{intent_name}")

            return self.build_result(
                ctx,
                destination=destination,
                reason=f"keyword_heuristic:{intent_name}",
                intent=intent_name,
                strategy_topic=strategy_topic,
                metadata_updates={
                    "router_path": f"keyword_heuristic:{intent_name}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"keyword:{intent_name}",
                },
            )

        self.record(ctx, fired=False, reason="no_match")
        return None

    # Patterns that indicate inquiry intent (expands beyond just question words at start)
    _INQUIRY_PATTERNS = frozenset(
        {
            "tell me about",
            "tell me more about",
            "want to know about",
            "wanna know about",
            "like to know about",
            "can you tell me",
            "could you tell me",
            "i'd like to know",
            "show me",
            "looking for",
        }
    )

    def _check_question_keyword_combo(self, text_lower: str) -> Optional[Tuple[str, str]]:
        """
        Check for question-word + domain keyword combinations.

        Expanded to detect:
        1. Question word at start: "What hotels are available?"
        2. Question word in first 3 words: "So what flights?"
        3. Inquiry patterns: "Tell me about hotels", "Can you show me flights?"
        4. "Looking for" pattern: "Looking for hotel recommendations"

        Returns:
            (intent_name, destination_node) if match, None otherwise
        """
        words = text_lower.split()
        if not words:
            return None

        has_question_indicator = False

        # Check 1: Question word in first 3 words
        for _, word in enumerate(words[:3]):
            clean_word = word.rstrip("?.,")
            if clean_word in QUESTION_WORDS:
                has_question_indicator = True
                break

        # Check 2: Inquiry patterns anywhere in text
        if not has_question_indicator:
            for pattern in self._INQUIRY_PATTERNS:
                if pattern in text_lower:
                    has_question_indicator = True
                    break

        if not has_question_indicator:
            return None

        # Check for domain keywords using pre-compiled patterns
        for intent_name, keywords in DOMAIN_KEYWORDS.items():
            if keyword_match(text_lower, keywords):
                return (intent_name, SPECIALIST_NODE_MAP[intent_name])

        return None

    def _check_keyword_heuristic(self, text_lower: str) -> Optional[Tuple[str, str, Optional[str]]]:
        """
        Check for pure keyword-based intent detection.

        Returns:
            (intent_name, destination_node, strategy_topic) if match, None otherwise
        """
        # Import here to avoid circular dependency
        from app.plan_graph import _detect_intent_from_keywords

        keyword_intent = _detect_intent_from_keywords(text_lower)

        if not keyword_intent:
            return None

        intent_name, strategy_topic = keyword_intent

        # Map intent to destination (use extended map that includes strategy)
        destination = SPECIALIST_NODE_MAP_EXTENDED.get(intent_name, "required_fields_node")

        return (intent_name, destination, strategy_topic)
