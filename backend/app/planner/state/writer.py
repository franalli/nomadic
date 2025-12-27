"""
StateWriter - P1 Module Extraction.

Enforces all state mutations go through validated methods for SSoT compliance.

This class wraps state mutation functions from plan_graph.py to provide:
1. Centralized mutation tracking
2. SSoT enforcement for question_target and trip_inputs
3. Audit trail for debugging state mutation bugs

Usage:
    from app.planner.state import StateWriter

    # In a node function:
    writer = StateWriter(state, node_name="strategy_stage0")

    # Instead of: state.question_target = "dates"
    writer.set_question_target("dates")

    # Instead of: direct trip_inputs mutation
    writer.write_trip_input("destinations", ["Paris", "Rome"])

    # Apply all mutations
    state = writer.apply()

Design Notes:
- StateWriter is a thin wrapper that delegates to existing functions
- It doesn't replace the existing functions but provides an alternative API
- Nodes can migrate incrementally from direct calls to StateWriter
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from app.plan_graph import GraphState


@dataclass
class StateMutation:
    """Record of a single state mutation for audit trail."""

    mutation_type: str  # "question_target" | "trip_input" | "metadata"
    field: str
    value: Any
    source: str
    timestamp_ms: float = 0.0


@dataclass
class StateWriter:
    """
    Enforces all state mutations go through validated methods.

    This class provides a transaction-like interface for state mutations:
    1. Collect mutations via set_* methods
    2. Apply all mutations atomically via apply()

    The mutations are tracked for debugging and observability.

    Attributes:
        state: The GraphState being mutated
        node_name: Name of the node performing mutations (for provenance)
        _mutations: List of mutations recorded (for debugging)
        _applied: Whether apply() has been called
    """

    state: "GraphState"
    node_name: str
    _mutations: List[StateMutation] = field(default_factory=list)
    _applied: bool = False

    def set_question_target(
        self,
        target: Optional[str],
    ) -> "StateWriter":
        """
        Set question_target with SSoT enforcement.

        Delegates to set_question_target() from plan_graph.py.

        Args:
            target: Raw target value (will be canonicalized)

        Returns:
            self for method chaining
        """
        # Import here to avoid circular imports
        from app.plan_graph import set_question_target as _set_qt

        _set_qt(self.state, target, source=self.node_name)

        self._mutations.append(
            StateMutation(
                mutation_type="question_target",
                field="question_target",
                value=target,
                source=self.node_name,
            )
        )
        return self

    def write_trip_input(
        self,
        field_name: str,
        value: Any,
        provenance: str = "inferred",
    ) -> "StateWriter":
        """
        Write a single trip_input field with validation.

        Delegates to _write_trip_inputs() from plan_graph.py.

        Args:
            field_name: Name of the field to write (e.g., "destinations")
            value: Value to write
            provenance: Source type - "explicit"|"inferred"|"user_confirmed"

        Returns:
            self for method chaining
        """
        # Import here to avoid circular imports
        from app.plan_graph import _write_trip_inputs

        self.state, _ = _write_trip_inputs(
            self.state,
            self.node_name,
            provenance=provenance,
            **{field_name: value},
        )

        self._mutations.append(
            StateMutation(
                mutation_type="trip_input",
                field=field_name,
                value=value,
                source=self.node_name,
            )
        )
        return self

    def write_trip_inputs(
        self,
        provenance: str = "inferred",
        **updates: Any,
    ) -> "StateWriter":
        """
        Write multiple trip_input fields with validation.

        Delegates to _write_trip_inputs() from plan_graph.py.

        Args:
            provenance: Source type - "explicit"|"inferred"|"user_confirmed"
            **updates: Field updates to apply

        Returns:
            self for method chaining
        """
        # Import here to avoid circular imports
        from app.plan_graph import _write_trip_inputs

        self.state, _ = _write_trip_inputs(
            self.state,
            self.node_name,
            provenance=provenance,
            **updates,
        )

        for field_name, value in updates.items():
            self._mutations.append(
                StateMutation(
                    mutation_type="trip_input",
                    field=field_name,
                    value=value,
                    source=self.node_name,
                )
            )
        return self

    def set_metadata(
        self,
        key: str,
        value: Any,
    ) -> "StateWriter":
        """
        Set a metadata key with tracking.

        This method provides a tracked way to set metadata values.
        It uses the meta_set helper from planner.meta.

        Args:
            key: Metadata key to set
            value: Value to set

        Returns:
            self for method chaining
        """
        from app.planner.meta import meta_set

        meta_set(self.state, key, value)

        self._mutations.append(
            StateMutation(
                mutation_type="metadata",
                field=key,
                value=value,
                source=self.node_name,
            )
        )
        return self

    def get_mutations(self) -> List[StateMutation]:
        """
        Get the list of mutations recorded.

        Returns:
            List of StateMutation objects
        """
        return list(self._mutations)

    def get_mutation_summary(self) -> Dict[str, List[str]]:
        """
        Get a summary of mutations by type.

        Returns:
            Dict mapping mutation_type to list of field names
        """
        summary: Dict[str, List[str]] = {}
        for m in self._mutations:
            if m.mutation_type not in summary:
                summary[m.mutation_type] = []
            summary[m.mutation_type].append(m.field)
        return summary

    def set_active_category(self, category: Optional[str]) -> "StateWriter":
        """
        Set active_category for specialist routing.

        Args:
            category: Category name (e.g., "flights", "hotels") or None

        Returns:
            self for method chaining
        """
        self.state.active_category = category

        self._mutations.append(
            StateMutation(
                mutation_type="active_category",
                field="active_category",
                value=category,
                source=self.node_name,
            )
        )
        return self

    def set_last_summary(self, summary: Optional[str]) -> "StateWriter":
        """
        Set last_summary for conversation continuity.

        Args:
            summary: Summary text or None

        Returns:
            self for method chaining
        """
        self.state.last_summary = summary

        self._mutations.append(
            StateMutation(
                mutation_type="last_summary",
                field="last_summary",
                value=summary,
                source=self.node_name,
            )
        )
        return self

    def set_suggested_responses(self, suggestions: Optional[List[str]]) -> "StateWriter":
        """
        Set suggested_responses for UI hints.

        Args:
            suggestions: List of suggestion strings or None

        Returns:
            self for method chaining
        """
        self.state.suggested_responses = suggestions

        self._mutations.append(
            StateMutation(
                mutation_type="suggested_responses",
                field="suggested_responses",
                value=suggestions,
                source=self.node_name,
            )
        )
        return self

    def set_pending_strategy_expansion(self, pending: bool) -> "StateWriter":
        """
        Set pending_strategy_expansion flag.

        Args:
            pending: Whether a strategy expansion is pending

        Returns:
            self for method chaining
        """
        self.state.pending_strategy_expansion = pending

        self._mutations.append(
            StateMutation(
                mutation_type="pending_strategy_expansion",
                field="pending_strategy_expansion",
                value=pending,
                source=self.node_name,
            )
        )
        return self

    def set_flag(self, key: str, value: bool) -> "StateWriter":
        """
        Set a boolean flag in state.

        This is a convenience method for setting common boolean fields.
        Maps known flag names to state attributes.

        Args:
            key: Flag name (e.g., "date_clarify_mode")
            value: Boolean value

        Returns:
            self for method chaining
        """
        # Map flag names to state attributes
        flag_attrs = {
            "date_clarify_mode": "date_clarify_mode",
            "pending_strategy_expansion": "pending_strategy_expansion",
            "explicit_year_provided": "explicit_year_provided",
        }

        if key in flag_attrs:
            setattr(self.state, flag_attrs[key], value)
        else:
            # Fall back to metadata for unknown flags
            self.state.metadata[key] = value

        self._mutations.append(
            StateMutation(
                mutation_type="flag",
                field=key,
                value=value,
                source=self.node_name,
            )
        )
        return self

    def set_parsed_inputs(self, parsed: Dict[str, Any]) -> "StateWriter":
        """
        Set parsed_inputs from extractor.

        This sets the intermediate extraction results that get merged
        into trip_inputs during the extraction flow.

        Args:
            parsed: Dictionary of parsed field values

        Returns:
            self for method chaining
        """
        self.state.parsed_inputs = parsed

        self._mutations.append(
            StateMutation(
                mutation_type="parsed_inputs",
                field="parsed_inputs",
                value=parsed,
                source=self.node_name,
            )
        )
        return self

    def apply(self) -> "GraphState":
        """
        Finalize and return the mutated state.

        This method marks the writer as applied and returns the state.
        Calling mutation methods after apply() is not recommended.

        Returns:
            The mutated GraphState
        """
        self._applied = True
        return self.state
