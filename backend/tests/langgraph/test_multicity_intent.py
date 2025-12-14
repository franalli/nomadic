import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.plan_graph import _normalize_multi_city_intent  # noqa: E402


@pytest.mark.parametrize(
    "text, expected",
    [
        ("one trip", "multi_city"),
        ("multi-city", "multi_city"),
        ("do it all together", "multi_city"),
        ("visit both", "multi_city"),
        ("compare destinations", "separate"),
        ("separate trips", "separate"),
        ("make them separate", None),
        (None, None),
        ("", None),
    ],
)
def test_normalize_multi_city_intent(text: str | None, expected: str | None) -> None:
    assert _normalize_multi_city_intent(text) == expected
