"""Extraction confidence utilities.

Provides standardized confidence dict structure used across extraction nodes.
"""

from typing import Any, Dict, List, Optional


def _compute_confidence_level(overall: float) -> str:
    """Compute confidence level from overall score."""
    if overall >= 0.8:
        return "high"
    elif overall >= 0.5:
        return "medium"
    return "low"


def build_extraction_confidence(
    overall: float,
    method: str,
    *,
    level: Optional[str] = None,
    grammar_matched: bool = False,
    is_english: bool = True,
    detected_language: Optional[str] = None,
    low_confidence_reasons: Optional[List[str]] = None,
    typo_suggestions: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build standardized extraction confidence dict.

    Args:
        overall: Confidence score 0.0-1.0
        method: Extraction method name (e.g., "lqa_prepass", "llm", "initial_extraction")
        level: Confidence level ("high", "medium", "low"). Auto-computed if not provided.
        grammar_matched: Whether input matched grammar patterns
        is_english: Whether input is in English
        detected_language: Detected language code if not English
        low_confidence_reasons: List of reasons for low confidence
        typo_suggestions: Dict mapping original -> suggested corrections

    Returns:
        Standardized confidence dict for state.metadata["extraction_confidence"]
    """
    return {
        "overall": overall,
        "level": level if level is not None else _compute_confidence_level(overall),
        "method": method,
        "grammar_matched": grammar_matched,
        "is_english": is_english,
        "detected_language": detected_language,
        "low_confidence_reasons": low_confidence_reasons or [],
        "typo_suggestions": typo_suggestions or {},
    }


# Convenience constructors for common patterns
def high_confidence(method: str, overall: float = 0.95) -> Dict[str, Any]:
    """Build high-confidence result for deterministic parsing.

    Args:
        method: Method name for trace
        overall: Confidence score (default 0.95)

    Returns:
        Confidence dict with grammar_matched=True
    """
    return build_extraction_confidence(
        overall=overall,
        method=method,
        level="high",
        grammar_matched=True,
    )


def low_confidence_error(method: str, reason: str) -> Dict[str, Any]:
    """Build low-confidence result for error cases.

    Args:
        method: Method name for trace (e.g., "llm_timeout", "llm_error")
        reason: Error reason to include in low_confidence_reasons

    Returns:
        Confidence dict with overall=0.0
    """
    return build_extraction_confidence(
        overall=0.0,
        method=method,
        level="low",
        low_confidence_reasons=[reason],
    )
