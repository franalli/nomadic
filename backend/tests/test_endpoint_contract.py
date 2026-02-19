"""Route contract lock: prevents accidental backend endpoint removal/rename."""

from fastapi.routing import APIRoute

from app.main import app

EXPECTED_ROUTES: set[tuple[str, str]] = {
    ("GET", "/health"),
    ("POST", "/api/validate-trip-input"),
    ("POST", "/api/destination-image"),
    ("POST", "/api/admin/clear-validation-cache"),
    ("POST", "/api/admin/fresh-start"),
    ("GET", "/api/admin/graph-stats"),
    ("GET", "/api/admin/planner"),
    ("POST", "/api/admin/clear-all-checkpoints"),
    ("POST", "/api/admin/clear-all-caches"),
    ("GET", "/api/admin/specialist-cache-stats"),
    ("POST", "/api/admin/clear-specialist-cache"),
    ("GET", "/api/admin/tile-cache-stats"),
    ("POST", "/api/admin/clear-tile-cache"),
    ("GET", "/api/admin/router-cache-stats"),
    ("POST", "/api/admin/clear-router-cache"),
    ("GET", "/api/admin/cache-stats"),
    ("POST", "/api/tiles/click"),
    ("POST", "/api/graph_plan/stream"),
    ("DELETE", "/api/session"),
    ("GET", "/api/chat"),
    ("DELETE", "/api/chat/last"),
    ("GET", "/api/document"),
    ("PATCH", "/api/document"),
    ("POST", "/api/document/tiles/{branch_id}"),
    ("POST", "/api/tiles/refresh"),
    ("POST", "/api/document/fill-day"),
    ("POST", "/api/expand-itinerary"),
}


def _actual_route_set() -> set[tuple[str, str]]:
    actual: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            actual.add((method, route.path))
    return actual


def test_backend_endpoint_contract_locked() -> None:
    actual = _actual_route_set()

    missing = EXPECTED_ROUTES - actual
    assert not missing, f"Missing or renamed endpoints: {sorted(missing)}"
