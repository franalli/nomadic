"""
Tests for the provider-agnostic LLM factory in app.planner.llm_factory.

Covers:
- Provider detection (Gemini vs OpenAI) based on model string
- Parameter forwarding (temperature, max_tokens, streaming, timeout, max_retries)
- Gemini-specific behavior (1.3x max_tokens multiplier, thinking disabled)
- OpenAI-specific behavior (streaming forwarded)

Note: ChatOpenAI and ChatGoogleGenerativeAI are imported lazily inside
get_llm_by_model, so we patch at the source package level.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.planner.llm_factory import get_llm_by_model

# Patch targets at the source modules (lazy imports inside function body)
_OPENAI_TARGET = "langchain_openai.ChatOpenAI"
_GEMINI_TARGET = "langchain_google_genai.ChatGoogleGenerativeAI"


class TestProviderDetection:
    """Tests for model string to provider routing."""

    def test_gemini_model_uses_google_provider(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            result = get_llm_by_model("gemini-2.5-flash")
            mock_cls.assert_called_once()
            assert result is mock_cls.return_value

    def test_gpt4o_uses_openai_provider(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            result = get_llm_by_model("gpt-4o")
            mock_cls.assert_called_once()
            assert result is mock_cls.return_value

    def test_gpt4o_mini_uses_openai_provider(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            result = get_llm_by_model("gpt-4o-mini")
            mock_cls.assert_called_once()
            assert result is mock_cls.return_value

    def test_o1_model_uses_openai_provider(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("o1-preview")
            mock_cls.assert_called_once()

    def test_gemini_pro_uses_google_provider(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-pro")
            mock_cls.assert_called_once()


class TestOpenAIParameterForwarding:
    """Tests for parameter forwarding to ChatOpenAI."""

    def test_temperature_forwarded(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o", temperature=0.7)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["temperature"] == 0.7

    def test_default_temperature_is_zero(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o")
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["temperature"] == 0

    def test_max_tokens_forwarded(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o", max_tokens=500)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["max_tokens"] == 500

    def test_max_tokens_omitted_when_none(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o")
            call_kwargs = mock_cls.call_args[1]
            assert "max_tokens" not in call_kwargs

    def test_streaming_forwarded(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o", streaming=True)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["streaming"] is True

    def test_streaming_default_false(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o")
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["streaming"] is False

    def test_timeout_forwarded_when_provided(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o", timeout=30.0)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["timeout"] == 30.0

    def test_timeout_omitted_when_none(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o")
            call_kwargs = mock_cls.call_args[1]
            assert "timeout" not in call_kwargs

    def test_max_retries_forwarded_when_provided(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o", max_retries=3)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["max_retries"] == 3

    def test_max_retries_omitted_when_none(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o")
            call_kwargs = mock_cls.call_args[1]
            assert "max_retries" not in call_kwargs

    def test_model_string_forwarded(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gpt-4o-mini")
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["model"] == "gpt-4o-mini"


class TestGeminiParameterForwarding:
    """Tests for parameter forwarding to ChatGoogleGenerativeAI."""

    def test_temperature_forwarded(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash", temperature=0.5)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["temperature"] == 0.5

    def test_thinking_disabled(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash")
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["thinking_budget"] == 0
            assert call_kwargs["include_thoughts"] is False

    def test_max_tokens_multiplied_by_1_3(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash", max_tokens=100)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["max_output_tokens"] == 130  # int(100 * 1.3)

    @pytest.mark.parametrize(
        "input_tokens,expected",
        [
            (100, 130),
            (200, 260),
            (1000, 1300),
            (1, 1),  # int(1 * 1.3) = 1
            (10, 13),
        ],
    )
    def test_max_tokens_multiplier_various_values(self, input_tokens: int, expected: int):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash", max_tokens=input_tokens)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["max_output_tokens"] == expected

    def test_max_tokens_omitted_when_none(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash")
            call_kwargs = mock_cls.call_args[1]
            assert "max_output_tokens" not in call_kwargs

    def test_streaming_not_forwarded_to_gemini(self):
        """Gemini provider does not receive the streaming parameter."""
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash", streaming=True)
            call_kwargs = mock_cls.call_args[1]
            assert "streaming" not in call_kwargs

    def test_timeout_forwarded_when_provided(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash", timeout=45.0)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["timeout"] == 45.0

    def test_timeout_omitted_when_none(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash")
            call_kwargs = mock_cls.call_args[1]
            assert "timeout" not in call_kwargs

    def test_max_retries_forwarded_when_provided(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash", max_retries=2)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["max_retries"] == 2

    def test_max_retries_omitted_when_none(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash")
            call_kwargs = mock_cls.call_args[1]
            assert "max_retries" not in call_kwargs

    def test_model_string_forwarded(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model("gemini-2.5-flash")
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["model"] == "gemini-2.5-flash"


class TestAllParametersCombined:
    """Tests with all optional parameters provided at once."""

    def test_openai_all_params(self):
        with patch(_OPENAI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model(
                "gpt-4o",
                temperature=0.8,
                max_tokens=2000,
                streaming=True,
                timeout=60.0,
                max_retries=5,
            )
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs == {
                "model": "gpt-4o",
                "temperature": 0.8,
                "streaming": True,
                "max_tokens": 2000,
                "timeout": 60.0,
                "max_retries": 5,
            }

    def test_gemini_all_params(self):
        with patch(_GEMINI_TARGET) as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm_by_model(
                "gemini-2.5-flash",
                temperature=0.3,
                max_tokens=500,
                streaming=True,  # should NOT appear in kwargs
                timeout=45.0,
                max_retries=2,
            )
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs == {
                "model": "gemini-2.5-flash",
                "temperature": 0.3,
                "thinking_budget": 0,
                "include_thoughts": False,
                "max_output_tokens": 650,  # int(500 * 1.3)
                "timeout": 45.0,
                "max_retries": 2,
            }
