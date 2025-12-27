# backend/app/planner/streaming.py
"""
True LLM streaming utilities for user-facing nodes.

This module provides streaming-capable LLM call wrappers that yield tokens
in real-time from OpenAI's streaming API. Used by specialist and strategy
nodes when generating user-facing responses.

Streaming modes:
- true_stream: Real-time tokens from OpenAI API (🌊)
- simulated: Token-by-token with delays for templates/cached (✨)
- buffered:internal: No streaming for internal nodes (🔒)

Error handling:
- On mid-stream failure, retry with buffered fallback
- Emit complete response via simulated streaming
- Log fallback for observability
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)


class StreamingMode(str, Enum):
    """
    Streaming mode for response delivery.

    Modes:
    - TRUE_STREAM: Real-time tokens from OpenAI API (🌊)
    - SIMULATED_*: Token-by-token with delays for templates/cached (✨)
    - BUFFERED_*: No streaming for internal nodes (🔒)
    - FAST_LLM: Large chunks for already-buffered LLM responses (⚡)
    """

    # Real-time LLM streaming
    TRUE_STREAM = "true_stream"

    # Simulated streaming (token-by-token with delays)
    SIMULATED_TEMPLATE = "simulated:template"
    SIMULATED_CACHED = "simulated:cached"
    SIMULATED_DETERMINISTIC = "simulated:deterministic"
    SIMULATED_BUFFERED = "simulated:buffered"
    SIMULATED_STRATEGY = "simulated:strategy"

    # Buffered (no streaming)
    BUFFERED_INTERNAL = "buffered:internal"
    BUFFERED_POSTPROC = "buffered:postproc"

    # Fast delivery for pre-buffered LLM responses
    FAST_LLM = "fast:llm"


# Internal processing nodes that should never stream (produce state/JSON, not user-facing)
INTERNAL_PROCESSING_NODES = frozenset(
    {
        "extractor",
        "extractor:light",
        "router",
        "router:scoring",
        "lqa_prepass",
        "normalize_inputs",
        "validate_and_merge",
        "branch_postprocess",
        "tile_search",
    }
)

if TYPE_CHECKING:
    from app.plan_graph import GraphState


@dataclass
class StreamingResult:
    """Result from a streaming LLM call."""

    # Complete accumulated response text
    full_response: str
    # Whether streaming completed successfully
    success: bool
    # If failed, reason for failure
    failure_reason: Optional[str] = None
    # Whether this was a fallback to buffered mode
    used_fallback: bool = False
    # Timing information
    first_token_ms: Optional[float] = None
    total_ms: Optional[float] = None
    tokens_streamed: int = 0


@dataclass
class StreamingConfig:
    """Configuration for streaming behavior."""

    # Whether to enable true streaming (vs buffered)
    enabled: bool = True
    # Timeout for first token (ms)
    first_token_timeout_ms: float = 10000
    # Timeout for between tokens (ms)
    token_timeout_ms: float = 5000
    # Whether to retry with buffered on failure
    retry_on_failure: bool = True
    # Max retries for buffered fallback
    max_retries: int = 1


# Default streaming configuration
DEFAULT_STREAMING_CONFIG = StreamingConfig()


async def call_llm_streaming_with_accumulator(
    model: str,
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.2,
    history: Optional[List[Dict[str, str]]] = None,
    user_message: Optional[str] = None,
    top_p: Optional[float] = None,
    on_token: Optional[Callable[[str], None]] = None,
    config: Optional[StreamingConfig] = None,
) -> AsyncGenerator[Tuple[str, StreamingResult], None]:
    """
    Stream LLM tokens while accumulating the full response.

    This is the core streaming function that:
    1. Calls OpenAI with streaming enabled
    2. Yields each token as it arrives
    3. Accumulates tokens into full response
    4. Handles errors with buffered fallback

    Args:
        model: Model size identifier ("small", "medium", "large")
        prompt: The system prompt
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature
        history: Optional conversation history
        user_message: Optional current user message
        top_p: Optional nucleus sampling threshold
        on_token: Optional callback for each token
        config: Streaming configuration

    Yields:
        Tuple of (token, partial_result) where partial_result is None
        until the final yield which contains the complete StreamingResult
    """
    from app.config import get_async_openai_client, settings
    from app.debug_utils import _debug, _debug_error
    from app.plan_graph import _MODEL_MAP

    config = config or DEFAULT_STREAMING_CONFIG

    client = get_async_openai_client()
    if client is None:
        raise RuntimeError("OpenAI client is not configured")

    model_name = _MODEL_MAP.get(model, model)

    # Build messages array
    messages: List[Dict[str, str]] = [{"role": "system", "content": prompt}]

    if history:
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    if user_message:
        messages.append({"role": "user", "content": user_message})

    # Build params
    params: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": True,
    }

    if settings.openai_plan_seed is not None:
        params["seed"] = settings.openai_plan_seed

    if "gpt-4" in model_name.lower():
        params["max_tokens"] = max_tokens
        params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
    else:
        params["max_completion_tokens"] = max_tokens

    # Accumulator state
    accumulated_tokens: List[str] = []
    tokens_streamed = 0
    start_time = time.perf_counter()
    first_token_time: Optional[float] = None

    try:
        stream = await client.chat.completions.create(**params)

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                accumulated_tokens.append(token)
                tokens_streamed += 1

                if first_token_time is None:
                    first_token_time = (time.perf_counter() - start_time) * 1000

                if on_token:
                    on_token(token)

                # Yield token (result is None until final)
                yield token

        # Final yield with complete result
        total_time = (time.perf_counter() - start_time) * 1000
        full_response = "".join(accumulated_tokens)

        # StreamingResult is available but not returned here since this is a generator
        # Callers accumulate tokens themselves via the yielded values

        _debug(
            "STREAMING_LLM_COMPLETE",
            model=model_name,
            tokens_streamed=tokens_streamed,
            first_token_ms=round(first_token_time, 1) if first_token_time else None,
            total_ms=round(total_time, 1),
            response_length=len(full_response),
        )

        # Signal completion by returning (for callers to use final result)
        return

    except Exception as e:
        _debug_error(
            "STREAMING_LLM_ERROR",
            error=str(e),
            tokens_before_error=tokens_streamed,
            model=model_name,
        )

        # If retry enabled and we have partial response, try buffered fallback
        if config.retry_on_failure:
            _debug("STREAMING_FALLBACK: Retrying with buffered mode")
            try:
                from app.plan_graph import call_llm_with_timeout

                fallback_response = await call_llm_with_timeout(
                    model=model,
                    prompt=prompt,
                    timeout_seconds=30,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    history=history,
                    user_message=user_message,
                    top_p=top_p,
                )

                total_time = (time.perf_counter() - start_time) * 1000

                # Yield fallback response as single chunk
                yield fallback_response

                return

            except Exception as fallback_error:
                _debug_error(
                    "STREAMING_FALLBACK_FAILED",
                    original_error=str(e),
                    fallback_error=str(fallback_error),
                )
                raise fallback_error from e

        raise


async def stream_specialist_response(
    name: str,
    state: "GraphState",
    system_prompt: str,
    llm_config: Dict[str, Any],
    on_token: Optional[Callable[[str], None]] = None,
) -> AsyncGenerator[str, None]:
    """
    Stream a specialist node response with proper error handling.

    This is the main entry point for streaming specialist responses.
    It wraps call_llm_streaming_with_accumulator with specialist-specific
    setup and error recovery.

    Args:
        name: Specialist name (flights, hotels, etc.)
        state: Current graph state
        system_prompt: Prepared system prompt
        llm_config: LLM configuration dict
        on_token: Optional callback for each token

    Yields:
        str: Tokens as they arrive from the LLM
    """
    from app.debug_utils import _debug

    _debug(
        f"STREAMING_SPECIALIST_START:{name}",
        max_tokens=llm_config.get("max_tokens", 512),
        model=llm_config.get("model_hint", "small"),
    )

    async for token in call_llm_streaming_with_accumulator(
        model=llm_config.get("model_hint", "small"),
        prompt=system_prompt,
        max_tokens=llm_config.get("max_tokens", 512),
        temperature=llm_config.get("temperature", 0.2),
        history=state.chat_history,
        user_message=state.user_text,
        top_p=llm_config.get("top_p"),
        on_token=on_token,
    ):
        yield token


async def stream_strategy_response(
    stage: int,
    topic: str,
    state: "GraphState",
    system_prompt: str,
    llm_config: Dict[str, Any],
    on_token: Optional[Callable[[str], None]] = None,
) -> AsyncGenerator[str, None]:
    """
    Stream a strategy node response with stage-specific handling.

    Args:
        stage: Strategy stage (0, 1, or 2)
        topic: Strategy topic (hiking, diving, etc.)
        state: Current graph state
        system_prompt: Prepared system prompt
        llm_config: LLM configuration dict
        on_token: Optional callback for each token

    Yields:
        str: Tokens as they arrive from the LLM
    """
    from app.debug_utils import _debug

    _debug(
        f"STREAMING_STRATEGY_START:stage{stage}:{topic}",
        max_tokens=llm_config.get("max_tokens", 512),
        model=llm_config.get("model_hint", "small"),
    )

    async for token in call_llm_streaming_with_accumulator(
        model=llm_config.get("model_hint", "small"),
        prompt=system_prompt,
        max_tokens=llm_config.get("max_tokens", 512),
        temperature=llm_config.get("temperature", 0.2),
        history=state.chat_history,
        user_message=state.user_text,
        top_p=llm_config.get("top_p"),
        on_token=on_token,
    ):
        yield token


# =============================================================================
# STREAMING MODE DETECTION
# =============================================================================


def get_streaming_mode(
    state: "GraphState",
    response_writer: str,
    provenance: str,
) -> StreamingMode:
    """
    Determine the streaming mode for a response.

    Args:
        state: Current graph state
        response_writer: Name of the node that wrote the response
        provenance: Response generation provenance

    Returns:
        StreamingMode enum value indicating how the response should be delivered.
    """
    # Internal processing nodes - no streaming
    if response_writer in INTERNAL_PROCESSING_NODES or response_writer.startswith("extractor:"):
        return StreamingMode.BUFFERED_INTERNAL

    if response_writer == "response_polish":
        return StreamingMode.BUFFERED_POSTPROC

    # Provenance-based streaming mode
    if provenance == "llm":
        return StreamingMode.TRUE_STREAM
    elif provenance == "template":
        return StreamingMode.SIMULATED_TEMPLATE
    elif provenance == "cached":
        return StreamingMode.SIMULATED_CACHED
    elif provenance in ("deterministic", "codegen"):
        return StreamingMode.SIMULATED_DETERMINISTIC
    elif provenance in ("llm_fallback", "llm_retry"):
        return StreamingMode.SIMULATED_BUFFERED
    else:
        # Default to simulated for unknown provenance
        return StreamingMode.SIMULATED_DETERMINISTIC


def should_use_true_streaming(
    state: "GraphState",
    response_writer: str,
    provenance: str,
) -> bool:
    """
    Check if a response should use true LLM streaming.

    Returns True only for user-facing LLM responses that can stream.
    """
    mode = get_streaming_mode(state, response_writer, provenance)
    return mode == StreamingMode.TRUE_STREAM
