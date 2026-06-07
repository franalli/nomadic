"""Regression tests for ``_merge_tiles`` specialist-tile preservation.

Context (confirmed by a 9-agent audit): specialist activity tiles
(``source_agent == "vertical_specialist"``) are the ONLY carrier of the Viator
image + Book-on-Viator deeplink for Tier-1 activities (diving dives, etc.). They
are injected in-place into ``state["tiles"]["activities"]`` by
``_inject_specialist_tiles_into_state``; ``search_tiles`` emits none.

Before this fix, a same-turn ``search_tiles`` round made ``_merge_tiles``
wholesale-replace the activities list with provider results that contain ZERO
specialist tiles -- silently dropping the partner stamp. The subsequent cheap
``/api/expand-itinerary`` rebuild (no re-enrichment) then matched activity->tile
by id, found no match for the dropped specialist tile, and fell back to a Google
Maps link + Unsplash placeholder. That was the reported symptom.

The fix unions-forward dropped specialist tiles whose topic is STILL present in
``state["strategy_sections"]``. The topic-scoping prevents resurrecting an
explicitly-removed specialist's content (the removal-inert / activity-modify
plan-erase bug class): a removed section is gone, so its tiles are not preserved.
"""

from __future__ import annotations

from typing import Any

from app.planner.middleware import _merge_tiles


def _diving_specialist_tile(tile_id: str, title: str) -> dict[str, Any]:
    """A specialist activity tile shaped like _specialist_content_to_tiles output:
    source_agent == "vertical_specialist" with meta.specialist_type == "diving"
    and a Viator-style image + deeplink (the partner stamp we must preserve)."""
    return {
        "id": tile_id,
        "type": "activity",
        "title": title,
        "subtitle": "Diving activity",
        "image_url": "https://viator-cdn.example.com/diving.jpg",
        "deeplink": "https://www.viator.com/tours/diving",
        "source_agent": "vertical_specialist",
        "partner": "vertical_specialist",
        "meta": {"specialist_type": "diving", "category": "diving"},
    }


def _diving_section() -> dict[str, Any]:
    return {"specialist_type": "diving", "feasibility_status": "feasible"}


def _general_tile(tile_id: str, title: str) -> dict[str, Any]:
    """A generic (non-specialist) activity tile from search_tiles -- no
    source_agent stamp, no specialist meta."""
    return {
        "id": tile_id,
        "type": "activity",
        "title": title,
        "source": "google_places",
    }


def test_preserves_active_specialist_tiles_dropped_by_search() -> None:
    """PRESERVATION: with a live diving section, two diving specialist tiles that
    the fresh search results omit must be unioned forward, and the fresh general
    tiles must also be present."""
    state = {
        "strategy_sections": [_diving_section()],
        "tiles": {
            "activities": [
                _diving_specialist_tile("spec_diving_menjangan", "Menjangan Island"),
                _diving_specialist_tile("spec_diving_sanur", "Sanur Underwater Temple"),
                _general_tile("gp_museum", "Local Museum"),
            ],
        },
    }
    # search_tiles result wholesale-replaces activities with general tiles only
    # (contains NO specialist tiles -- search_tiles never emits them).
    result = {
        "activities": [
            _general_tile("gp_beach", "Beach Walk"),
            _general_tile("gp_market", "Night Market"),
        ],
    }

    updates = _merge_tiles(state, result)
    acts = {t["id"]: t for t in updates["tiles"]["activities"]}

    # Both diving specialist tiles survived (unioned forward).
    assert "spec_diving_menjangan" in acts
    assert "spec_diving_sanur" in acts
    # Their Viator partner stamp is intact (the whole point).
    assert acts["spec_diving_menjangan"]["deeplink"] == "https://www.viator.com/tours/diving"
    assert acts["spec_diving_menjangan"]["image_url"].startswith("https://viator-cdn")
    assert acts["spec_diving_menjangan"]["source_agent"] == "vertical_specialist"
    # Fresh general tiles are present too (refresh never dropped).
    assert "gp_beach" in acts
    assert "gp_market" in acts


def test_does_not_resurrect_removed_specialist_tiles() -> None:
    """NO RESURRECTION (the guard): same inputs, but the diving section has been
    removed from strategy_sections. The diving specialist tiles must NOT be
    carried forward -- removed content is not resurrected."""
    state = {
        # Diving section removed (e.g. "no diving") -- only a non-diving section
        # remains. Topic-scoping keys preservation off live sections.
        "strategy_sections": [
            {"specialist_type": "hiking", "feasibility_status": "feasible"},
        ],
        "tiles": {
            "activities": [
                _diving_specialist_tile("spec_diving_menjangan", "Menjangan Island"),
                _diving_specialist_tile("spec_diving_sanur", "Sanur Underwater Temple"),
                _general_tile("gp_museum", "Local Museum"),
            ],
        },
    }
    result = {
        "activities": [
            _general_tile("gp_beach", "Beach Walk"),
        ],
    }

    updates = _merge_tiles(state, result)
    ids = {t["id"] for t in updates["tiles"]["activities"]}

    # Removed-topic specialist tiles are dropped (not resurrected).
    assert "spec_diving_menjangan" not in ids
    assert "spec_diving_sanur" not in ids
    # The fresh search results are present.
    assert "gp_beach" in ids


def test_fresh_result_wins_on_id_collision() -> None:
    """RIGHT-WINS: when a fresh search result shares an id with an existing
    specialist tile, the fresh one wins -- the specialist tile is not unioned
    forward (no duplicate, no clobber of the fresh copy)."""
    state = {
        "strategy_sections": [_diving_section()],
        "tiles": {
            "activities": [
                _diving_specialist_tile("spec_diving_menjangan", "Menjangan Island (stale)"),
            ],
        },
    }
    # Fresh result carries the SAME id as the existing specialist tile.
    result = {
        "activities": [
            {
                "id": "spec_diving_menjangan",
                "type": "activity",
                "title": "Menjangan Island (fresh)",
                "source": "google_places",
            },
        ],
    }

    updates = _merge_tiles(state, result)
    acts = updates["tiles"]["activities"]
    matching = [t for t in acts if t["id"] == "spec_diving_menjangan"]

    # Exactly one tile with that id -- no duplicate.
    assert len(matching) == 1
    # The fresh copy won (right-wins by id).
    assert matching[0]["title"] == "Menjangan Island (fresh)"
    assert matching[0].get("source") == "google_places"
