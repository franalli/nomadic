"""
Provider-agnostic LLM factory.

Provider is inferred from the model string prefix:
  - "gemini*"  → ChatGoogleGenerativeAI (langchain-google-genai)
  - everything else → ChatOpenAI (langchain-openai)

All imports are lazy so unused providers add zero startup cost.
"""

from __future__ import annotations

import re

from langchain_core.language_models.chat_models import BaseChatModel


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

    token_usage: dict = {}

    # Path 1: LangChain 0.2+ usage_metadata — works for both OpenAI and Gemini
    # usage_metadata is dict[str, Any] in modern LangChain but older Gemini versions
    # may return an attribute-style object; support both via get() with getattr() fallback.
    if hasattr(raw_response, "usage_metadata") and raw_response.usage_metadata:
        um = raw_response.usage_metadata
        if isinstance(um, dict):
            token_usage = {
                "prompt_tokens": um.get("input_tokens", 0),
                "completion_tokens": um.get("output_tokens", 0),
                "total_tokens": um.get("total_tokens", 0),
            }
        else:
            token_usage = {
                "prompt_tokens": getattr(um, "input_tokens", 0),
                "completion_tokens": getattr(um, "output_tokens", 0),
                "total_tokens": getattr(um, "total_tokens", 0),
            }
    # Path 2: OpenAI response_metadata fallback (older LangChain versions)
    elif hasattr(raw_response, "response_metadata"):
        token_usage = raw_response.response_metadata.get("token_usage", {})

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
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
    if fence_match:
        content = fence_match.group(1).strip()

    return content
