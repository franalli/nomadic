"""Suppression Predicates for Gate Evaluation.

This module provides centralized suppression logic used by gate evaluators
to prevent gates from firing in specific situations. These predicates
ensure consistent behavior across different gate checks.

Suppression Types:
    - Bridge Suppression: Prevents strategy gates when user just answered
      an active question (allows next core field collection first)
    - Lifecycle Suppression: Prevents stage0 from re-firing after completion
    - Ownership Suppression: Prevents strategy from trampling question_target
      collection paths
    - Date Mode Suppression: Prevents gates when in date clarification mode

Usage:
    from app.planner.gates.suppression import SuppressionPredicates

    # In gate evaluation
    if SuppressionPredicates.bridge_suppression(metadata):
        return None  # Skip this gate
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    pass


class SuppressionPredicates:
    """Centralized suppression logic for gate evaluation.

    All suppression predicates are static methods that can be called
    without instantiation. Each returns a boolean indicating whether
    the gate should be suppressed.
    """

    # =========================================================================
    # Bridge Suppression
    # =========================================================================

    @staticmethod
    def bridge_suppression(metadata: Dict[str, Any]) -> bool:
        """Check if bridge suppression applies.

        Bridge suppression prevents strategy gates from firing when the user
        just answered the currently active question. This allows the system
        to collect the next core field before generating strategy content.

        This creates a "bridge" between answering a question (e.g., providing
        destination) and asking the next question (e.g., asking for dates),
        preventing strategy content from interrupting the flow.

        Args:
            metadata: State metadata dictionary.

        Returns:
            True if the gate should be suppressed (user just answered active question).
        """
        answered_target = metadata.get("answered_question_target_this_turn")
        answered_qid = metadata.get("answered_question_id_this_turn")
        active_target = metadata.get("active_question_target")
        active_qid = metadata.get("active_question_id")

        # Need all four values to determine bridge suppression
        if not answered_target or answered_qid is None or active_qid is None:
            return False

        # Suppress if user answered the active question
        return answered_target == active_target and answered_qid == active_qid

    @staticmethod
    def bridge_suppression_reason(metadata: Dict[str, Any]) -> Optional[str]:
        """Get the reason for bridge suppression if active.

        Args:
            metadata: State metadata dictionary.

        Returns:
            Reason string if suppressed, None otherwise.
        """
        if SuppressionPredicates.bridge_suppression(metadata):
            answered_target = metadata.get("answered_question_target_this_turn")
            return f"active_question_answered:{answered_target}"
        return None

    # =========================================================================
    # Lifecycle Suppression
    # =========================================================================

    @staticmethod
    def lifecycle_suppression(
        metadata: Dict[str, Any],
        current_signature: Optional[str],
    ) -> bool:
        """Check if lifecycle suppression applies.

        Lifecycle suppression prevents stage0 from re-firing after it has
        already completed for a given topic+destinations+origin combination.
        This prevents the strategy loop bug where stage0 keeps firing.

        Args:
            metadata: State metadata dictionary.
            current_signature: Signature for current topic+destinations+origin.

        Returns:
            True if the gate should be suppressed (stage0 already completed).
        """
        if not current_signature:
            return False

        completed_sig = metadata.get("stage0_completed_sig")
        return completed_sig is not None and completed_sig == current_signature

    @staticmethod
    def lifecycle_suppression_reason(
        metadata: Dict[str, Any],
        current_signature: Optional[str],
    ) -> Optional[str]:
        """Get the reason for lifecycle suppression if active.

        Args:
            metadata: State metadata dictionary.
            current_signature: Signature for current topic+destinations+origin.

        Returns:
            Reason string if suppressed, None otherwise.
        """
        if SuppressionPredicates.lifecycle_suppression(metadata, current_signature):
            return f"stage0_already_completed:{current_signature[:12]}"
        return None

    @staticmethod
    def compute_stage0_signature(
        topic: str,
        destinations: List[str],
        origin: Optional[str] = None,
    ) -> str:
        """Compute a stable signature for stage0 lifecycle tracking.

        This signature is used to track whether stage0 has already fired
        for a given topic+destinations+origin combination. Format is
        "{topic}:{8-char-hash}" for compact storage.

        Args:
            topic: Strategy topic (hiking, diving, etc.).
            destinations: List of destination strings.
            origin: Origin location or None.

        Returns:
            Signature string like "hiking:abc12345".
        """
        # Create stable string representation
        dest_str = "|".join(sorted(d.lower().strip() for d in destinations)) if destinations else ""
        origin_str = origin.lower().strip() if origin else ""
        combined = f"{dest_str}|{origin_str}"
        combined_hash = hashlib.md5(combined.encode()).hexdigest()[:8]
        return f"{topic}:{combined_hash}"

    @staticmethod
    def compute_stage1_signature(
        topic: str,
        destinations: List[str],
        origin: Optional[str] = None,
    ) -> str:
        """Compute a stable signature for stage1 lifecycle tracking.

        This signature is used to track whether stage1 has already fired
        for a given topic+destinations+origin combination. Format is
        "{topic}:s1:{8-char-hash}" for compact storage.

        Args:
            topic: Strategy topic (hiking, diving, etc.).
            destinations: List of destination strings.
            origin: Origin location or None.

        Returns:
            Signature string like "hiking:s1:abc12345".
        """
        # Create stable string representation
        dest_str = "|".join(sorted(d.lower().strip() for d in destinations)) if destinations else ""
        origin_str = origin.lower().strip() if origin else ""
        combined = f"{dest_str}|{origin_str}"
        combined_hash = hashlib.md5(combined.encode()).hexdigest()[:8]
        return f"{topic}:s1:{combined_hash}"

    # =========================================================================
    # Ownership Suppression
    # =========================================================================

    @staticmethod
    def ownership_suppression(
        question_target: Optional[str],
        user_text: str,
        text_is_compatible_fn: callable,
    ) -> bool:
        """Check if ownership suppression applies.

        Ownership suppression prevents strategy gates from firing when there
        is an active question_target and the user's input looks like an
        answer to that question. This lets the answer-collection path handle
        the input instead of strategy trampling it.

        Args:
            question_target: The currently active question target.
            user_text: The user's input text.
            text_is_compatible_fn: Function to check if text is compatible
                with the question target (e.g., GateEvaluator.text_is_compatible_with_target).

        Returns:
            True if the gate should be suppressed (input answers question_target).
        """
        if not question_target or not user_text:
            return False

        return text_is_compatible_fn(user_text, question_target)

    @staticmethod
    def ownership_suppression_reason(
        question_target: Optional[str],
        user_text: str,
        text_is_compatible_fn: callable,
    ) -> Optional[str]:
        """Get the reason for ownership suppression if active.

        Args:
            question_target: The currently active question target.
            user_text: The user's input text.
            text_is_compatible_fn: Compatibility check function.

        Returns:
            Reason string if suppressed, None otherwise.
        """
        if SuppressionPredicates.ownership_suppression(
            question_target, user_text, text_is_compatible_fn
        ):
            return f"input_compatible_with:{question_target}"
        return None

    # =========================================================================
    # Date Mode Suppression
    # =========================================================================

    @staticmethod
    def date_mode_suppression(metadata: Dict[str, Any]) -> bool:
        """Check if date clarification mode suppression applies.

        When the system is in date_clarify_mode, strategy gates should
        not fire because dates clarification owns the routing.

        Args:
            metadata: State metadata dictionary.

        Returns:
            True if the gate should be suppressed (in date clarify mode).
        """
        return bool(metadata.get("date_clarify_mode", False))

    @staticmethod
    def date_mode_suppression_reason(metadata: Dict[str, Any]) -> Optional[str]:
        """Get the reason for date mode suppression if active.

        Args:
            metadata: State metadata dictionary.

        Returns:
            Reason string if suppressed, None otherwise.
        """
        if SuppressionPredicates.date_mode_suppression(metadata):
            return "date_clarify_mode_active"
        return None

    # =========================================================================
    # Blocking Errors Suppression
    # =========================================================================

    @staticmethod
    def blocking_errors_suppression(
        has_blocking_errors: bool,
        blocking_errors: Optional[List[str]] = None,
    ) -> bool:
        """Check if blocking errors suppression applies.

        When there are blocking errors (e.g., date validation errors),
        strategy gates should not fire because error resolution owns routing.

        Args:
            has_blocking_errors: Whether blocking errors exist.
            blocking_errors: Optional list of blocking error codes.

        Returns:
            True if the gate should be suppressed (blocking errors exist).
        """
        return has_blocking_errors

    @staticmethod
    def blocking_errors_suppression_reason(
        has_blocking_errors: bool,
        blocking_errors: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Get the reason for blocking errors suppression if active.

        Args:
            has_blocking_errors: Whether blocking errors exist.
            blocking_errors: Optional list of blocking error codes.

        Returns:
            Reason string if suppressed, None otherwise.
        """
        if has_blocking_errors:
            if blocking_errors:
                return f"blocking_errors:{','.join(blocking_errors[:3])}"
            return "blocking_errors_present"
        return None

    # =========================================================================
    # Combined Suppression Check
    # =========================================================================

    @classmethod
    def should_suppress_stage0(
        cls,
        metadata: Dict[str, Any],
        current_signature: Optional[str] = None,
        question_target: Optional[str] = None,
        user_text: str = "",
        text_is_compatible_fn: Optional[callable] = None,
        has_blocking_errors: bool = False,
        blocking_errors: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """Combined suppression check for strategy stage0 gates.

        Checks all suppression predicates in order and returns the first
        one that applies. Order matters for debugging - we want to know
        the primary reason for suppression.

        Order of checks:
        1. Bridge suppression (user just answered active question)
        2. Lifecycle suppression (stage0 already completed)
        3. Date mode suppression (in date clarification mode)
        4. Blocking errors suppression (errors need resolution)
        5. Ownership suppression (input answers question_target)

        Args:
            metadata: State metadata dictionary.
            current_signature: Signature for lifecycle tracking.
            question_target: Active question target.
            user_text: User's input text.
            text_is_compatible_fn: Compatibility check function.
            has_blocking_errors: Whether blocking errors exist.
            blocking_errors: List of blocking error codes.

        Returns:
            Tuple of (should_suppress, reason). If should_suppress is False,
            reason will be an empty string.
        """
        # 1. Bridge suppression
        if reason := cls.bridge_suppression_reason(metadata):
            return True, reason

        # 2. Lifecycle suppression
        if reason := cls.lifecycle_suppression_reason(metadata, current_signature):
            return True, reason

        # 3. Date mode suppression
        if reason := cls.date_mode_suppression_reason(metadata):
            return True, reason

        # 4. Blocking errors suppression
        if reason := cls.blocking_errors_suppression_reason(has_blocking_errors, blocking_errors):
            return True, reason

        # 5. Ownership suppression (requires compatible check function)
        if text_is_compatible_fn:
            if reason := cls.ownership_suppression_reason(
                question_target, user_text, text_is_compatible_fn
            ):
                return True, reason

        return False, ""

    @classmethod
    def get_all_suppression_reasons(
        cls,
        metadata: Dict[str, Any],
        current_signature: Optional[str] = None,
        question_target: Optional[str] = None,
        user_text: str = "",
        text_is_compatible_fn: Optional[callable] = None,
        has_blocking_errors: bool = False,
        blocking_errors: Optional[List[str]] = None,
    ) -> List[str]:
        """Get all applicable suppression reasons (for debugging).

        Unlike should_suppress_stage0 which returns the first match,
        this returns ALL matching suppression reasons.

        Args:
            Same as should_suppress_stage0.

        Returns:
            List of all applicable suppression reasons.
        """
        reasons = []

        if reason := cls.bridge_suppression_reason(metadata):
            reasons.append(reason)

        if reason := cls.lifecycle_suppression_reason(metadata, current_signature):
            reasons.append(reason)

        if reason := cls.date_mode_suppression_reason(metadata):
            reasons.append(reason)

        if reason := cls.blocking_errors_suppression_reason(has_blocking_errors, blocking_errors):
            reasons.append(reason)

        if text_is_compatible_fn:
            if reason := cls.ownership_suppression_reason(
                question_target, user_text, text_is_compatible_fn
            ):
                reasons.append(reason)

        return reasons
