"""
Node Base Utilities - P2 Module Extraction.

This module provides common utilities for node functions:
- NodeContext: Dataclass containing node execution context
- node_decorator: Decorator that provides logging and instrumentation

These utilities are designed to be used when extracting nodes from plan_graph.py.
The decorator wraps node functions with standard logging and entry/exit instrumentation.

Usage:
    from app.planner.nodes import node_decorator, NodeContext

    @node_decorator("my_node")
    async def my_node(state: GraphState, ctx: NodeContext) -> GraphState:
        ctx.log("Processing request")
        # Node implementation
        return state
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Dict, List

if TYPE_CHECKING:
    from app.plan_graph import GraphState


@dataclass
class NodeContext:
    """
    Context object passed to node functions for instrumentation and utilities.

    Provides:
    - Node name for logging
    - Entry timestamp for duration tracking
    - Log buffer for node-scoped debug messages
    - Helper methods for common operations

    This is created by the node_decorator and passed to the decorated function.
    """

    node_name: str
    entry_time_ns: int = field(default_factory=lambda: time.perf_counter_ns())
    log_buffer: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def log(self, message: str, **kwargs: Any) -> None:
        """
        Log a message to the node's log buffer.

        Messages are collected and can be emitted at the end of node execution.

        Args:
            message: Log message
            **kwargs: Additional key-value pairs to include
        """
        extras = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        full_message = f"[{self.node_name}] {message} {extras}".strip()
        self.log_buffer.append(full_message)

    def elapsed_ms(self) -> float:
        """
        Get elapsed time since node entry in milliseconds.

        Returns:
            Elapsed time in milliseconds
        """
        return (time.perf_counter_ns() - self.entry_time_ns) / 1_000_000

    def set_meta(self, key: str, value: Any) -> None:
        """
        Set a metadata value for this node context.

        Args:
            key: Metadata key
            value: Metadata value
        """
        self.metadata[key] = value

    def get_meta(self, key: str, default: Any = None) -> Any:
        """
        Get a metadata value from this node context.

        Args:
            key: Metadata key
            default: Default value if key not found

        Returns:
            Metadata value or default
        """
        return self.metadata.get(key, default)


def node_decorator(node_name: str):
    """
    Decorator that wraps a node function with logging and instrumentation.

    Provides:
    - Entry/exit logging with timing
    - NodeContext injection for node-scoped utilities
    - Error handling with debug output

    Usage:
        @node_decorator("strategy_node")
        async def strategy_node(state: GraphState, ctx: NodeContext) -> GraphState:
            ctx.log("Starting strategy generation")
            # Node implementation
            return state

    Args:
        node_name: Name of the node for logging and instrumentation

    Returns:
        Decorated function
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(state: "GraphState") -> "GraphState":
            from app.debug_utils import _debug, safe_debug_error

            # Create context for this node execution
            ctx = NodeContext(node_name=node_name)

            _debug(
                "NODE_ENTRY",
                node=node_name,
                user_text=state.user_text[:50] if state.user_text else None,
            )

            try:
                # Call the decorated function with context
                result = await func(state, ctx)

                _debug(
                    "NODE_EXIT",
                    node=node_name,
                    elapsed_ms=round(ctx.elapsed_ms(), 2),
                    log_count=len(ctx.log_buffer),
                )

                # Emit buffered logs
                for log_msg in ctx.log_buffer:
                    _debug(log_msg)

                return result

            except Exception as e:
                safe_debug_error(
                    f"Node {node_name} failed",
                    error=str(e)[:200],
                    elapsed_ms=round(ctx.elapsed_ms(), 2),
                )
                raise

        return wrapper

    return decorator
