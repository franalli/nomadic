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

import asyncio
import time
from dataclasses import dataclass, field
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

    # Real-time LLM streaming (tokens streamed during graph execution)
    TRUE_STREAM = "true_stream"
    REAL_LLM = "real:llm"  # Tokens streamed in real-time from LLM during graph execution

    # Simulated streaming (token-by-token with delays)
    SIMULATED_TEMPLATE = "simulated:template"
    SIMULATED_LLM_FALLBACK = "simulated:llm_fallback"  # Fallback when LLM didn't stream
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

# =============================================================================
# CONSISTENT STREAMING PARAMETERS
# =============================================================================
# Used for both real and simulated streaming to ensure consistent visual feel
STREAMING_PARAMS = {
    "base_delay_ms": 15,  # Minimum delay between tokens (simulated only)
    "max_delay_ms": 35,  # Maximum delay between tokens (simulated only)
    "jitter_ms": 8,  # Random jitter range (simulated only)
    "chunk_size": 1,  # Single tokens for consistency
}


# =============================================================================
# STREAMING CONTEXT REGISTRY
# =============================================================================
# Store streaming contexts by thread_id to avoid serialization issues.
# LangGraph's checkpointer cannot serialize asyncio.Queue objects, so we
# keep the contexts in a module-level registry instead of state.metadata.
_STREAMING_CONTEXT_REGISTRY: Dict[str, "StreamingContext"] = {}


def register_streaming_context(thread_id: str, ctx: "StreamingContext") -> None:
    """Register a streaming context for a thread."""
    _STREAMING_CONTEXT_REGISTRY[thread_id] = ctx


def get_streaming_context(thread_id: Optional[str]) -> Optional["StreamingContext"]:
    """Get the streaming context for a thread."""
    if thread_id is None:
        return None
    return _STREAMING_CONTEXT_REGISTRY.get(thread_id)


def unregister_streaming_context(thread_id: str) -> None:
    """Remove a streaming context from the registry."""
    _STREAMING_CONTEXT_REGISTRY.pop(thread_id, None)


# =============================================================================
# STREAMING CONTEXT
# =============================================================================
@dataclass
class StreamingContext:
    """
    Context for real-time token streaming during graph execution.

    This context is stored in a module-level registry (not state.metadata)
    to avoid serialization issues with LangGraph's checkpointer.

    Usage:
        # In run_turn_streaming:
        ctx = StreamingContext()
        register_streaming_context(thread_id, ctx)

        # In specialist/strategy nodes:
        thread_id = state.metadata.get("thread_id")
        ctx = get_streaming_context(thread_id)
        if ctx:
            await ctx.emit("token")

        # Consuming tokens:
        async for token in ctx.tokens():
            yield {"type": "token", "data": token}

        # Cleanup:
        unregister_streaming_context(thread_id)
    """

    # Queue for tokens - None signals end of stream
    token_queue: asyncio.Queue[Optional[str]] = field(default_factory=lambda: asyncio.Queue())
    # Whether streaming is currently active
    is_streaming: bool = False
    # Count of tokens emitted
    tokens_emitted: int = 0
    # Whether the stream has been finalized
    _finalized: bool = field(default=False, repr=False)

    async def emit(self, token: str) -> None:
        """Emit a token to the streaming queue."""
        if self._finalized:
            return
        self.is_streaming = True
        self.tokens_emitted += 1
        await self.token_queue.put(token)

    async def finalize(self) -> None:
        """Signal end of streaming."""
        if not self._finalized:
            self._finalized = True
            self.is_streaming = False
            await self.token_queue.put(None)

    async def tokens(self, timeout: float = 0.1) -> AsyncGenerator[str, None]:
        """
        Async generator that yields tokens from the queue.

        Args:
            timeout: How long to wait for each token (seconds)

        Yields:
            Tokens as they arrive, stops when None is received
        """
        while True:
            try:
                token = await asyncio.wait_for(self.token_queue.get(), timeout=timeout)
                if token is None:
                    break
                yield token
            except asyncio.TimeoutError:
                # No token available, check if we should continue
                if self._finalized and self.token_queue.empty():
                    break
                continue


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


# =============================================================================
# JSON FIELD STREAMING
# =============================================================================


async def call_llm_streaming_with_json_field(
    model: str,
    prompt: str,
    stream_field: str,
    streaming_ctx: Optional[StreamingContext] = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
    history: Optional[List[Dict[str, str]]] = None,
    user_message: Optional[str] = None,
    top_p: Optional[float] = None,
    timeout_seconds: float = 30.0,
) -> str:
    """
    Stream LLM response, emitting tokens only when inside the specified JSON field.

    This function enables real-time streaming of the assistant_message field
    while still accumulating the full JSON response for delta extraction.

    The flow:
    1. Start streaming from OpenAI
    2. Detect when we're inside the specified field (e.g., "assistant_message": "...")
    3. Emit those tokens to streaming_ctx in real-time
    4. Accumulate full response
    5. Return complete JSON string for parsing

    Args:
        model: Model size identifier ("small", "medium", "large")
        prompt: The system prompt
        stream_field: JSON field name to stream (e.g., "assistant_message")
        streaming_ctx: Optional streaming context for emitting tokens
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature
        history: Optional conversation history
        user_message: Optional current user message
        top_p: Optional nucleus sampling threshold
        timeout_seconds: Timeout for the entire call

    Returns:
        Complete accumulated response string (full JSON)

    Example:
        # Stream assistant_message to frontend while accumulating full JSON
        full_json = await call_llm_streaming_with_json_field(
            model="small",
            prompt=system_prompt,
            stream_field="assistant_message",
            streaming_ctx=ctx,
            ...
        )
        # Parse the complete JSON after streaming completes
        j = json.loads(full_json)
        # Apply deltas from j to state
    """
    from app.debug_utils import _debug, _debug_error

    accumulated: List[str] = []
    field_marker = f'"{stream_field}":'
    field_content_start: Optional[int] = None  # Position after opening quote
    last_streamed_pos: int = 0  # Last position we streamed from
    tokens_streamed_to_ctx = 0

    def find_unescaped_quote(s: str, start: int) -> int:
        """Find the position of the next unescaped quote after start position."""
        i = start
        while i < len(s):
            if s[i] == '"':
                # Check if escaped by counting preceding backslashes
                num_backslashes = 0
                j = i - 1
                while j >= 0 and s[j] == "\\":
                    num_backslashes += 1
                    j -= 1
                # Quote is escaped only if preceded by odd number of backslashes
                if num_backslashes % 2 == 0:
                    return i
            i += 1
        return -1  # Not found

    try:
        async for token in call_llm_streaming_with_accumulator(
            model=model,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            history=history,
            user_message=user_message,
            top_p=top_p,
        ):
            accumulated.append(token)
            full_so_far = "".join(accumulated)

            # Phase 1: Looking for field marker and opening quote
            if field_content_start is None:
                marker_idx = full_so_far.find(field_marker)
                if marker_idx != -1:
                    # Find the opening quote after the marker
                    search_start = marker_idx + len(field_marker)
                    # Skip whitespace
                    while (
                        search_start < len(full_so_far) and full_so_far[search_start] in " \t\n\r"
                    ):
                        search_start += 1
                    if search_start < len(full_so_far) and full_so_far[search_start] == '"':
                        # Found opening quote, content starts after it
                        field_content_start = search_start + 1
                        last_streamed_pos = field_content_start

            # Phase 2: Streaming field content (only if we're actively in the field)
            # field_content_start is None = haven't found field yet
            # field_content_start >= 0 = actively streaming from this position
            # field_content_start == -1 = done, field complete
            if field_content_start is not None and field_content_start >= 0:
                # Look for closing quote
                closing_quote_pos = find_unescaped_quote(full_so_far, last_streamed_pos)

                if closing_quote_pos != -1:
                    # Found closing quote - stream everything up to it
                    content_to_stream = full_so_far[last_streamed_pos:closing_quote_pos]
                    if content_to_stream and streaming_ctx:
                        await streaming_ctx.emit(content_to_stream)
                        tokens_streamed_to_ctx += 1
                    # Field complete - stop looking
                    field_content_start = -1  # Mark as done (not None, so we don't re-search)
                else:
                    # No closing quote yet - stream new content
                    # But be careful: the last few chars might be part of an escape sequence
                    # or a partial quote, so buffer a bit
                    safe_end = len(full_so_far)
                    # Don't stream the last char if it's a backslash (might be start of escape)
                    if safe_end > last_streamed_pos and full_so_far[safe_end - 1] == "\\":
                        safe_end -= 1

                    if safe_end > last_streamed_pos:
                        content_to_stream = full_so_far[last_streamed_pos:safe_end]
                        if content_to_stream and streaming_ctx:
                            await streaming_ctx.emit(content_to_stream)
                            tokens_streamed_to_ctx += 1
                        last_streamed_pos = safe_end

        full_response = "".join(accumulated)

        _debug(
            "STREAMING_JSON_FIELD_COMPLETE",
            field=stream_field,
            tokens_streamed=tokens_streamed_to_ctx,
            response_length=len(full_response),
        )

        return full_response

    except Exception as e:
        _debug_error(
            "STREAMING_JSON_FIELD_ERROR",
            error=str(e),
            field=stream_field,
            tokens_before_error=len(accumulated),
        )

        # Fallback to buffered call
        from app.plan_graph import call_llm_with_timeout

        _debug("STREAMING_JSON_FIELD_FALLBACK: Using buffered mode")
        fallback_response = await call_llm_with_timeout(
            model=model,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            temperature=temperature,
            history=history,
            user_message=user_message,
            top_p=top_p,
        )

        # For fallback, simulate streaming the extracted field
        if streaming_ctx and fallback_response:
            try:
                import json

                j = json.loads(fallback_response)
                field_content = j.get(stream_field, "")
                if field_content:
                    # Emit the field content in chunks
                    for word in field_content.split():
                        await streaming_ctx.emit(word + " ")
            except Exception:
                pass  # Best effort streaming on fallback

        return fallback_response
