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
    ("POST", "/api/admin/clear-l1-l2-caches"),
    ("GET", "/api/admin/specialist-cache-stats"),
    ("POST", "/api/admin/clear-specialist-cache"),
    ("GET", "/api/admin/tile-cache-stats"),
    ("POST", "/api/admin/clear-tile-cache"),
    ("GET", "/api/admin/router-cache-stats"),
    ("POST", "/api/admin/clear-router-cache"),
    ("GET", "/api/admin/cache-stats"),
    ("GET", "/api/admin/spend-guard-stats"),
    ("POST", "/api/admin/clear-spend-guard"),
    ("POST", "/api/tiles/click"),
    ("POST", "/api/tiles/refresh"),
    ("POST", "/api/graph_plan/stream"),
    ("DELETE", "/api/session"),
    ("GET", "/api/chat"),
    ("DELETE", "/api/chat/last"),
    ("POST", "/api/share"),
    ("POST", "/api/share/fork/{slug}"),
    ("GET", "/api/shared/{slug}"),
    ("GET", "/api/auth/google/url"),
    ("POST", "/api/auth/google/callback"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/trips"),
    ("POST", "/api/trips/{trip_id}/resume"),
    ("GET", "/api/document"),
    ("PATCH", "/api/document"),
    ("POST", "/api/document/tiles/{branch_id}"),
    ("POST", "/api/document/validate-arrangement"),
    ("POST", "/api/document/apply-arrangement"),
    ("POST", "/api/document/remove-block"),
    ("POST", "/api/document/restore-snapshot"),
    ("POST", "/api/document/insert-activity-block"),
    ("POST", "/api/document/fill-day"),
    ("POST", "/api/expand-itinerary"),
    ("POST", "/api/activities/browse"),
    ("GET", "/api/media/google-places-photo"),
    ("GET", "/api/media/google-places-photo-url"),
    ("GET", "/api/specialist/{section_id}/enrichment"),
}

REMOVED_ROUTES: set[tuple[str, str]] = {
    ("POST", "/api/suggestions/click"),
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

    resurrected = REMOVED_ROUTES & actual
    assert not resurrected, f"Removed endpoints reappeared unexpectedly: {sorted(resurrected)}"
