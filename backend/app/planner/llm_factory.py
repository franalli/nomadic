"""
Provider-agnostic LLM factory.

Provider is inferred from the model string prefix:
  - "gemini*"  → ChatGoogleGenerativeAI (langchain-google-genai)
  - everything else → ChatOpenAI (langchain-openai)

All imports are lazy so unused providers add zero startup cost.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from langchain_core.language_models.chat_models import BaseChatModel

from app.services.spend_guard import reserve_llm_spend_or_raise


def get_llm_by_model(
    model: str,
    *,
    temperature: float = 0,
    max_tokens: int | None = None,
    streaming: bool = False,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> BaseChatModel:
    """Return a LangChain chat model for *model*, auto-detecting the provider."""
    # Reserve estimated cost before constructing/using a paid provider client.
    reserve_llm_spend_or_raise(model=model, max_tokens=max_tokens, source="get_llm_by_model")

    if model.startswith("gemini"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs: dict = dict(
            model=model,
            temperature=temperature,
            thinking_budget=0,  # Disable thinking tokens
            include_thoughts=False,  # Don't return reasoning in response
        )
        if max_tokens is not None:
            # 30% headroom for tokenizer differences between Gemini and OpenAI
            kwargs["max_output_tokens"] = int(max_tokens * 1.3)
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        return ChatGoogleGenerativeAI(**kwargs)

    # Default: OpenAI (covers gpt-*, o1-*, ft:gpt-*)
    from langchain_openai import ChatOpenAI

    kwargs = dict(model=model, temperature=temperature, streaming=streaming)
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return ChatOpenAI(**kwargs)


def extract_token_usage(raw_response: object, *, model: str | None = None) -> dict:
    """
    Provider-agnostic token usage extraction from a LangChain response.

    Handles:
    - include_raw=True wrapper: {"raw": AIMessage, "parsed": ...} → unwraps automatically
    - LangChain 0.2+ usage_metadata (works for both OpenAI and Gemini)
    - OpenAI response_metadata["token_usage"] fallback (older LangChain)

    Returns dict with prompt_tokens, completion_tokens, total_tokens (+ model if provided).
    Returns {} if no usage info is available.
    """
    # Unwrap include_raw=True result dict
    if isinstance(raw_response, dict) and "raw" in raw_response:
        raw_response = raw_response["raw"]

    if raw_response is None:
        return {}

    def _to_int(value: object) -> int | None:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
        return None

    token_usage: dict = {}

    # Path 1: LangChain 0.2+ usage_metadata — works for both OpenAI and Gemini.
    # Guard against MagicMock/placeholder attributes that should not override
    # valid response_metadata.token_usage fallback.
    usage_metadata = getattr(raw_response, "usage_metadata", None)
    if usage_metadata is not None:
        if isinstance(usage_metadata, Mapping):
            prompt = _to_int(usage_metadata.get("input_tokens"))
            completion = _to_int(usage_metadata.get("output_tokens"))
            total = _to_int(usage_metadata.get("total_tokens"))
        else:
            prompt = _to_int(getattr(usage_metadata, "input_tokens", None))
            completion = _to_int(getattr(usage_metadata, "output_tokens", None))
            total = _to_int(getattr(usage_metadata, "total_tokens", None))

        if prompt is not None or completion is not None or total is not None:
            prompt_tokens = prompt or 0
            completion_tokens = completion or 0
            token_usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total if total is not None else (prompt_tokens + completion_tokens),
            }

    # Path 2: OpenAI response_metadata fallback (older LangChain versions).
    if not token_usage:
        response_metadata = getattr(raw_response, "response_metadata", None)
        if isinstance(response_metadata, Mapping):
            fallback_usage = response_metadata.get("token_usage")
            if isinstance(fallback_usage, Mapping):
                prompt = _to_int(fallback_usage.get("prompt_tokens"))
                completion = _to_int(fallback_usage.get("completion_tokens"))
                total = _to_int(fallback_usage.get("total_tokens"))
                if prompt is not None or completion is not None or total is not None:
                    prompt_tokens = prompt or 0
                    completion_tokens = completion or 0
                    token_usage = {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": (
                            total if total is not None else (prompt_tokens + completion_tokens)
                        ),
                    }
                elif fallback_usage:
                    token_usage = dict(fallback_usage)

    if token_usage and model:
        token_usage["model"] = model

    return token_usage


def resolve_schema_refs(schema: dict) -> dict:
    """
    Resolve $ref pointers by inlining $defs, producing a flat JSON Schema that
    Gemini's function calling API accepts.

    Use for schemas with few $defs (e.g. LLMSpecialistOutput: 2).
    Do NOT use for deeply nested schemas with shared references (e.g. LocalExpertOutput:
    31 $defs) — inlining duplicates shared models and bloats the schema further.
    """
    import copy

    defs = schema.get("$defs", {})
    if not defs:
        return schema

    def _resolve(node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].split("/")[-1]
                if ref_name in defs:
                    return _resolve(copy.deepcopy(defs[ref_name]))
                return node
            return {k: _resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    resolved = _resolve(schema)
    if isinstance(resolved, dict):
        resolved.pop("$defs", None)
    return resolved


def extract_json_content(response: object) -> str:
    """
    Extract JSON string from a LangChain AIMessage response.

    Handles:
    - String content (OpenAI standard)
    - List content (Gemini multi-part)
    - Markdown code fence stripping (```json ... ```)

    Returns raw JSON string for Pydantic model_validate_json().
    """
    content = getattr(response, "content", response)

    # Handle Gemini list-of-parts response
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                parts.append(p.get("text", ""))
            elif hasattr(p, "text"):
                parts.append(p.text)
        content = "".join(parts)

    if not isinstance(content, str):
        content = str(content)

    content = content.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    # Try closed fence first, then fall back to unclosed (LLM truncation)
    fence_match = re.search(r"```(?:json)?\s*\r?\n(.*?)\r?\n\s*```", content, re.DOTALL)
    if fence_match:
        content = fence_match.group(1).strip()
    else:
        # Unclosed fence: extract everything after the opening fence marker
        # Strip trailing backticks in case the closing ``` is on the same line as content
        open_match = re.search(r"```(?:json)?\s*\r?\n(.*)", content, re.DOTALL)
        if open_match:
            content = open_match.group(1).strip().rstrip("`")

    return content
