"""
Shared constants for the create_agent planner path.

Used by both agent.py (factory) and middleware.py (model selection).
Intentionally separate from the 7-node graph settings like
openai_plan_max_tokens / openai_plan_temperature which are tuned for
structured-output extraction, not conversational tool calling.
"""

AGENT_MAX_TOKENS: int = 1500
AGENT_TEMPERATURE: float = 0.4
