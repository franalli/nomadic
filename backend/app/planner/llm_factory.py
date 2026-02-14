"""
Provider-agnostic LLM factory.

Provider is inferred from the model string prefix:
  - "gemini*"  → ChatGoogleGenerativeAI (langchain-google-genai)
  - everything else → ChatOpenAI (langchain-openai)

All imports are lazy so unused providers add zero startup cost.
"""

from __future__ import annotations

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
