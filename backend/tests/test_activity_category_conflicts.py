"""Direct tests for shared activity category conflict matching."""

import pytest

from app.services.activity_category_conflicts import has_category_conflict


@pytest.mark.parametrize(
    ("specialist_category", "product_title"),
    [
        ("diving", "Sunset Snorkeling Cruise"),
        ("hiking", "Old Town Food Tour"),
    ],
)
def test_has_category_conflict_matches_known_partner_titles(
    specialist_category: str, product_title: str
) -> None:
    assert has_category_conflict(specialist_category, product_title) is True


def test_has_category_conflict_normalizes_category_case() -> None:
    assert has_category_conflict("DIVING", "Private snorkelling charter") is True


def test_has_category_conflict_returns_false_without_specialist_category() -> None:
    assert has_category_conflict(None, "Sunset Snorkeling Cruise") is False


def test_has_category_conflict_returns_false_for_non_conflicting_title_case() -> None:
    assert has_category_conflict("sailing", "Sunset Harbor Lesson") is False
