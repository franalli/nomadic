"""
Provider-agnostic LLM factory.

Provider is inferred from the model string prefix:
  - "gemini*"  → ChatGoogleGenerativeAI (langchain-google-genai)
  - everything else → ChatOpenAI (langchain-openai)

All imports are lazy so unused providers add zero startup cost.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

from langchain_core.language_models.chat_models import BaseChatModel

from app.services.spend_guard import reserve_llm_spend_or_raise

# Suppress known-benign Gemini schema warnings from LangChain's internal
# schema reprocessing. Our gemini_safe_schema() pipeline already strips
# unsupported keys, but LangChain re-derives them internally.
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)


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


# Keys accepted by Gemini's function-calling schema format.
# Sourced from langchain_google_genai._function_utils._ALLOWED_SCHEMA_FIELDS_SET.
_GEMINI_ALLOWED_SCHEMA_KEYS = frozenset(
    {
        "type",
        "type_",
        "description",
        "enum",
        "format",
        "items",
        "properties",
        "required",
        "nullable",
        "anyOf",
        "default",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "title",
    }
)


def strip_unsupported_schema_keys(node: object) -> object:
    """Recursively strip JSON Schema keys unsupported by Gemini function calling.

    Gemini's schema format accepts a strict subset of JSON Schema. Keys like
    ``additionalProperties`` and ``parameters`` cause SDK warnings and are
    silently dropped. Strip them proactively so structured output doesn't rely
    on Gemini's lenient parsing.

    The ``properties`` key is special: its children are field-name → schema
    mappings. Field names must be preserved (not filtered against the allowlist);
    only the schema *within* each field is recursively stripped.

    Safe to compose with ``resolve_schema_refs()``:
        ``strip_unsupported_schema_keys(resolve_schema_refs(schema))``
    """
    if isinstance(node, dict):
        result = {}
        for k, v in node.items():
            if k not in _GEMINI_ALLOWED_SCHEMA_KEYS:
                continue
            if k == "properties" and isinstance(v, dict):
                # properties is a map of field_name → schema_object.
                # Preserve field names; only strip within each field's schema.
                result[k] = {
                    field_name: strip_unsupported_schema_keys(field_schema)
                    for field_name, field_schema in v.items()
                }
            else:
                result[k] = strip_unsupported_schema_keys(v)
        return result
    if isinstance(node, list):
        return [strip_unsupported_schema_keys(item) for item in node]
    return node


def gemini_safe_schema(node: object) -> object:
    """Convert Pydantic anyOf-nullable patterns to Gemini-native nullable format.

    Pydantic v2 renders ``Optional[T]`` as ``{"anyOf": [{"type": T}, {"type": "null"}]}``.
    Gemini silently drops ``anyOf``, erasing all type info for those fields.
    This converts them to ``{"type": T, "nullable": true}`` which Gemini enforces.

    Safe for OpenAI too — ``nullable`` is valid in non-strict function-calling schemas.

    Compose after ``strip_unsupported_schema_keys``:
        ``gemini_safe_schema(strip_unsupported_schema_keys(resolve_schema_refs(schema)))``
    """
    if isinstance(node, dict):
        if "anyOf" in node:
            any_of = node["anyOf"]
            if isinstance(any_of, list) and len(any_of) == 2:
                non_null = [
                    b for b in any_of if not (isinstance(b, dict) and b.get("type") == "null")
                ]
                null_branch = [b for b in any_of if isinstance(b, dict) and b.get("type") == "null"]
                if len(non_null) == 1 and len(null_branch) == 1:
                    # Optional[T] pattern — merge non-null branch + nullable
                    merged = dict(gemini_safe_schema(non_null[0]))
                    merged["nullable"] = True
                    # Preserve sibling keys (description, default, etc.)
                    for k, v in node.items():
                        if k != "anyOf" and k not in merged:
                            merged[k] = gemini_safe_schema(v)
                    return merged
        # Regular dict — recurse into values
        return {k: gemini_safe_schema(v) for k, v in node.items()}
    if isinstance(node, list):
        return [gemini_safe_schema(item) for item in node]
    return node


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
