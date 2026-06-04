"""
Shared constants for the create_agent planner path.

Used by both agent.py (factory) and middleware.py (model selection).
Intentionally separate from the 7-node graph settings like
openai_plan_max_tokens / openai_plan_temperature which are tuned for
structured-output extraction, not conversational tool calling.
"""

AGENT_MAX_TOKENS: int = 4000
# Per-call timeout (seconds) for the orchestrator model. Bounds a hung provider
# request so one slow call can't stall the whole turn; ModelRetryMiddleware
# retries the timeout with backoff.
AGENT_TIMEOUT: float = 45.0
# Temperature 0 (greedy) for the orchestrator: deterministic tool selection and
# far fewer empty/no-tool model responses (the main source of intermittent
# turn failures observed at 0.4). Voice quality is unaffected for this role.
AGENT_TEMPERATURE: float = 0.0
