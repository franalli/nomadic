"""
Structured output wrapper with retry for cross-provider compatibility.

Handles Gemini JSON parse failures, parsed=None, token usage extraction.
Replaces the duplicated retry pattern in every node file.
"""

from __future__ import annotations

import logging
from typing import Type, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.planner.llm_factory import extract_token_usage

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


async def ainvoke_structured(
    llm: BaseChatModel,
    schema: Type[T],
    messages: list[BaseMessage],
    *,
    model_name: str = "unknown",
    max_retries: int = 1,
    method: str = "function_calling",
) -> tuple[T, dict]:
    """
    Invoke LLM with structured output and retry on parse failure.

    Returns (parsed_result, token_usage_dict).
    Raises ValueError if all retries are exhausted.

    Notes:
        - Do NOT use method="json_schema" with Gemini (known LangChain bug).
        - Do NOT use this for LocalExpert (31 $defs breaks schema resolution).
          LocalExpert uses raw ainvoke + extract_json_content instead.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            structured_llm = llm.with_structured_output(schema, include_raw=True, method=method)
            result = await structured_llm.ainvoke(messages)

            if isinstance(result, dict) and "parsed" in result:
                parsed = result["parsed"]
                raw = result.get("raw")
            else:
                parsed = result
                raw = result

            if parsed is None:
                raise ValueError(
                    f"Structured output returned parsed=None "
                    f"(attempt {attempt + 1}/{max_retries + 1})"
                )

            usage = extract_token_usage(raw, model=model_name)
            return parsed, usage

        except Exception as exc:
            last_error = exc
            logger.warning(
                "Structured output attempt %d/%d failed for %s: %s",
                attempt + 1,
                max_retries + 1,
                model_name,
                exc,
            )
            if attempt < max_retries:
                continue
            raise ValueError(
                f"Structured output failed after {max_retries + 1} attempts: {last_error}"
            ) from last_error

    raise ValueError(f"Structured output failed: {last_error}")  # unreachable
