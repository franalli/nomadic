"""
Nodes Package - P2 Module Extraction.

This package contains node functions for the LangGraph planner.

Phase 2 creates the package structure and exports common utilities.
Full node extraction will be completed in subsequent phases.

Exports:
    node_decorator: Decorator for node functions with standard logging
    NodeContext: Context object passed to node functions

Usage:
    from app.planner.nodes import node_decorator, NodeContext
"""

from app.planner.nodes.base import NodeContext, node_decorator

__all__ = [
    "NodeContext",
    "node_decorator",
]
