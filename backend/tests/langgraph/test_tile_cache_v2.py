"""
Tests for Tile Cache V2 Implementation.

Verifies:
- Cache wiring: tile_search uses ensure_tiles/set_tile_cached
- Expanded cache key: end_date, adults, children now included
- Budget filtering: client-side filtering, not in cache key
- Version migration: v1 entries discarded after v2 bump
"""

import hashlib
from unittest.mock import MagicMock, patch

import pytest


class TestTileCacheWiring:
    """Tests for tile cache integration with tile_search node."""

    @pytest.mark.asyncio
    async def test_tile_search_calls_api_and_caches_results(self):
        """tile_search calls search_tiles API and caches the results."""
        from app.plan_graph import (
            GraphState,
            TripInputs,
            clear_tile_cache,
            tile_search,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()
        tile_cache = TileCache.get_instance()
        initial_size = len(tile_cache._cache)

        state = GraphState(
            session_id="test-session",
            user_text="show me hotels",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                start_date="2025-03-15",
                end_date="2025-03-20",
                origin="New York",
                adults=2,
                children=0,
                booking_types={"hotels": True},
            ),
            branches=[{"id": "branch_0", "destinations": ["Paris"]}],
            metadata={},
        )

        # Mock search_tiles to return a tile
        mock_tile = MagicMock()
        mock_tile.id = "hotel_paris_1"
        mock_tile.type = "hotel"
        mock_tile.model_dump.return_value = {
            "id": "hotel_paris_1",
            "type": "hotel",
            "name": "Paris Grand Hotel",
            "price_estimate": 150,
        }

        with patch("app.plan_graph.search_tiles") as mock_search:
            mock_search.return_value = MagicMock(tiles=[mock_tile])

            await tile_search(state)

            # API should be called and results cached
            assert mock_search.called, "search_tiles should be called"
            assert len(tile_cache._cache) > initial_size, "Results should be cached"

    @pytest.mark.asyncio
    async def test_tile_search_caches_api_results(self):
        """tile_search caches results after API call via set_tile_cached."""
        from app.plan_graph import (
            GraphState,
            TripInputs,
            clear_tile_cache,
            get_tile_cache_stats,
            tile_search,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()
        tile_cache = TileCache.get_instance()
        initial_size = len(tile_cache._cache)

        state = GraphState(
            session_id="test-session-cache",
            user_text="show me hotels",
            trip_inputs=TripInputs(
                destinations=["Rome"],
                start_date="2025-04-01",
                end_date="2025-04-07",
                origin="London",
                adults=2,
                children=1,
                booking_types={"hotels": True},
            ),
            branches=[{"id": "branch_0", "destinations": ["Rome"]}],
            metadata={},
        )

        # Mock search_tiles to return a hotel tile
        mock_tile = MagicMock()
        mock_tile.id = "hotel_rome_1"
        mock_tile.type = "hotel"
        mock_tile.model_dump.return_value = {
            "id": "hotel_rome_1",
            "type": "hotel",
            "name": "Rome Grand Hotel",
            "price_estimate": 150,
        }

        with patch("app.plan_graph.search_tiles") as mock_search:
            mock_search.return_value = MagicMock(tiles=[mock_tile])

            await tile_search(state)

            # Cache should now have entries
            stats = get_tile_cache_stats()
            assert stats["cache_size"] > initial_size, "Cache should have new entries"

    def test_set_and_get_tile_cache_direct(self):
        """set_tile_cached stores tiles that can be retrieved with matching key."""
        from app.plan_graph import (
            clear_tile_cache,
            set_tile_cached,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()

        # Store tiles with specific parameters
        set_tile_cached(
            intent="hotel",
            destinations=["Tokyo"],
            start_date="2025-05-01",
            end_date="2025-05-07",
            origin="Los Angeles",
            adults=2,
            children=0,
            result={
                "hotel_tokyo_1": {
                    "id": "hotel_tokyo_1",
                    "type": "hotel",
                    "name": "Tokyo Palace",
                    "price_estimate": 200,
                }
            },
        )

        tile_cache = TileCache.get_instance()

        # Compute matching key (v3: includes settings_hash, defaults to "default")
        query_str = "hotel|Tokyo|2025-05-01|2025-05-07|Los Angeles|2|0|default"
        query_hash = hashlib.md5(query_str.encode()).hexdigest()[:16]
        key = tile_cache.compute_key(
            session_id="global",
            tile_type="hotel",
            query_hash=query_hash,
        )

        result = tile_cache.get(key, None)
        assert result is not None, "Should retrieve cached tiles with matching key"
        assert "hotel_tokyo_1" in result, "Should contain the cached tile"


class TestTileCacheKeyExpansion:
    """Tests for expanded cache key (v2: includes end_date, adults, children)."""

    def test_traveler_change_triggers_cache_miss(self):
        """Changing adults count causes cache miss (different cache key)."""
        from app.plan_graph import (
            clear_tile_cache,
            set_tile_cached,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()

        # Cache with 2 adults
        set_tile_cached(
            intent="hotel",
            destinations=["Barcelona"],
            start_date="2025-06-01",
            end_date="2025-06-07",
            origin="Madrid",
            adults=2,
            children=0,
            result={"hotel_1": {"id": "hotel_1", "type": "hotel", "price_estimate": 300}},
        )

        # Query with 3 adults - should miss
        tile_cache = TileCache.get_instance()

        # Compute key for 3 adults (v3: includes settings_hash)
        query_str_3_adults = "hotel|Barcelona|2025-06-01|2025-06-07|Madrid|3|0|default"
        query_hash_3 = hashlib.md5(query_str_3_adults.encode()).hexdigest()[:16]
        key_3_adults = tile_cache.compute_key(
            session_id="global",
            tile_type="hotel",
            query_hash=query_hash_3,
        )

        result = tile_cache.get(key_3_adults, None)
        assert result is None, "Different adults count should cause cache miss"

        # Compute key for 2 adults - should hit (v3: includes settings_hash)
        query_str_2_adults = "hotel|Barcelona|2025-06-01|2025-06-07|Madrid|2|0|default"
        query_hash_2 = hashlib.md5(query_str_2_adults.encode()).hexdigest()[:16]
        key_2_adults = tile_cache.compute_key(
            session_id="global",
            tile_type="hotel",
            query_hash=query_hash_2,
        )

        result = tile_cache.get(key_2_adults, None)
        assert result is not None, "Same adults count should cause cache hit"

    def test_end_date_change_triggers_cache_miss(self):
        """Changing end_date causes cache miss (different cache key)."""
        from app.plan_graph import (
            clear_tile_cache,
            set_tile_cached,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()

        # Cache with end_date 2025-07-07
        set_tile_cached(
            intent="hotel",
            destinations=["Amsterdam"],
            start_date="2025-07-01",
            end_date="2025-07-07",
            origin="Berlin",
            adults=2,
            children=0,
            result={"hotel_ams_1": {"id": "hotel_ams_1", "type": "hotel"}},
        )

        tile_cache = TileCache.get_instance()

        # Query with different end_date - should miss (v3: includes settings_hash)
        query_str_diff_end = "hotel|Amsterdam|2025-07-01|2025-07-10|Berlin|2|0|default"
        query_hash_diff = hashlib.md5(query_str_diff_end.encode()).hexdigest()[:16]
        key_diff_end = tile_cache.compute_key(
            session_id="global",
            tile_type="hotel",
            query_hash=query_hash_diff,
        )

        result = tile_cache.get(key_diff_end, None)
        assert result is None, "Different end_date should cause cache miss"

        # Query with same end_date - should hit (v3: includes settings_hash)
        query_str_same_end = "hotel|Amsterdam|2025-07-01|2025-07-07|Berlin|2|0|default"
        query_hash_same = hashlib.md5(query_str_same_end.encode()).hexdigest()[:16]
        key_same_end = tile_cache.compute_key(
            session_id="global",
            tile_type="hotel",
            query_hash=query_hash_same,
        )

        result = tile_cache.get(key_same_end, None)
        assert result is not None, "Same end_date should cause cache hit"

    def test_children_change_triggers_cache_miss(self):
        """Changing children count causes cache miss (different cache key)."""
        from app.plan_graph import (
            clear_tile_cache,
            set_tile_cached,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()

        # Cache with 0 children
        set_tile_cached(
            intent="hotel",
            destinations=["Vienna"],
            start_date="2025-08-01",
            end_date="2025-08-05",
            origin="Prague",
            adults=2,
            children=0,
            result={"hotel_vienna_1": {"id": "hotel_vienna_1", "type": "hotel"}},
        )

        tile_cache = TileCache.get_instance()

        # Query with 2 children - should miss (v3: includes settings_hash)
        query_str_2_children = "hotel|Vienna|2025-08-01|2025-08-05|Prague|2|2|default"
        query_hash_2c = hashlib.md5(query_str_2_children.encode()).hexdigest()[:16]
        key_2_children = tile_cache.compute_key(
            session_id="global",
            tile_type="hotel",
            query_hash=query_hash_2c,
        )

        result = tile_cache.get(key_2_children, None)
        assert result is None, "Different children count should cause cache miss"

    def test_budget_change_uses_cached_tiles(self):
        """Budget is NOT in cache key - budget change should still hit cache."""
        from app.plan_graph import (
            clear_tile_cache,
            set_tile_cached,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()

        # Cache tiles (budget not part of cache key)
        set_tile_cached(
            intent="hotel",
            destinations=["Dublin"],
            start_date="2025-09-01",
            end_date="2025-09-05",
            origin="Edinburgh",
            adults=2,
            children=0,
            result={
                "hotel_dublin_1": {"id": "hotel_dublin_1", "type": "hotel", "price_estimate": 200}
            },
        )

        tile_cache = TileCache.get_instance()

        # Query with same parameters (budget change doesn't affect cache key)
        # Budget is filtered client-side, not part of cache key (v3: includes settings_hash)
        query_str = "hotel|Dublin|2025-09-01|2025-09-05|Edinburgh|2|0|default"
        query_hash = hashlib.md5(query_str.encode()).hexdigest()[:16]
        key = tile_cache.compute_key(
            session_id="global",
            tile_type="hotel",
            query_hash=query_hash,
        )

        result = tile_cache.get(key, None)
        assert (
            result is not None
        ), "Budget change should still hit cache (budget filtered client-side)"


class TestTileBudgetFiltering:
    """Tests for client-side budget filtering."""

    def test_filter_tiles_removes_expensive_tiles(self):
        """Tiles exceeding budget allocation are filtered out."""
        from app.plan_graph import filter_tiles_by_budget

        tiles = {
            "hotel_1": {"id": "hotel_1", "type": "hotel", "price_estimate": 400},
            "hotel_2": {"id": "hotel_2", "type": "hotel", "price_estimate": 200},
            "hotel_3": {"id": "hotel_3", "type": "hotel", "price_estimate": 100},
        }

        # Budget $500, hotels get 40% = $200 limit
        filtered = filter_tiles_by_budget(tiles, budget=500)

        assert "hotel_1" not in filtered, "Expensive hotel should be filtered"
        assert "hotel_2" in filtered, "Hotel at limit should be included"
        assert "hotel_3" in filtered, "Cheap hotel should be included"

    def test_filter_tiles_respects_vertical_allocations(self):
        """Different verticals have different budget allocations."""
        from app.plan_graph import filter_tiles_by_budget

        tiles = {
            "hotel_1": {
                "id": "hotel_1",
                "type": "hotel",
                "price_estimate": 350,
            },  # 40% of 1000 = 400, OK
            "flight_1": {
                "id": "flight_1",
                "type": "flight",
                "price_estimate": 350,
            },  # 30% of 1000 = 300, OVER
            "activity_1": {
                "id": "activity_1",
                "type": "activity",
                "price_estimate": 250,
            },  # 30% of 1000 = 300, OK
        }

        # Budget $1000
        filtered = filter_tiles_by_budget(tiles, budget=1000)

        assert "hotel_1" in filtered, "Hotel within 40% allocation should be included"
        assert "flight_1" not in filtered, "Flight exceeding 30% allocation should be filtered"
        assert "activity_1" in filtered, "Activity within 30% allocation should be included"

    def test_filter_tiles_preserves_tiles_without_price(self):
        """Tiles without price info are preserved (not filtered)."""
        from app.plan_graph import filter_tiles_by_budget

        tiles = {
            "hotel_1": {"id": "hotel_1", "type": "hotel", "price_estimate": None},
            "hotel_2": {"id": "hotel_2", "type": "hotel"},  # No price field at all
        }

        filtered = filter_tiles_by_budget(tiles, budget=50)  # Very low budget

        assert "hotel_1" in filtered, "Tile with None price should be preserved"
        assert "hotel_2" in filtered, "Tile without price field should be preserved"

    def test_filter_tiles_uses_live_price_fallback(self):
        """Uses live_price when price_estimate is not available."""
        from app.plan_graph import filter_tiles_by_budget

        tiles = {
            "hotel_1": {"id": "hotel_1", "type": "hotel", "live_price": 500},  # Only live_price
            "hotel_2": {
                "id": "hotel_2",
                "type": "hotel",
                "price_estimate": 100,
                "live_price": 500,
            },  # Both
        }

        # Budget $500, hotels get 40% = $200 limit
        filtered = filter_tiles_by_budget(tiles, budget=500)

        assert "hotel_1" not in filtered, "Should use live_price when price_estimate missing"
        assert "hotel_2" in filtered, "Should prefer price_estimate over live_price"

    def test_filter_tiles_returns_all_when_no_budget(self):
        """When budget is None or 0, all tiles are returned."""
        from app.plan_graph import filter_tiles_by_budget

        tiles = {
            "hotel_1": {"id": "hotel_1", "type": "hotel", "price_estimate": 10000},
        }

        filtered_none = filter_tiles_by_budget(tiles, budget=None)
        filtered_zero = filter_tiles_by_budget(tiles, budget=0)

        assert "hotel_1" in filtered_none, "No budget constraint should return all tiles"
        assert "hotel_1" in filtered_zero, "Zero budget should return all tiles"

    def test_filter_tiles_handles_empty_dict(self):
        """Empty tiles dict returns empty dict."""
        from app.plan_graph import filter_tiles_by_budget

        filtered = filter_tiles_by_budget({}, budget=1000)
        assert filtered == {}, "Empty input should return empty output"


class TestTileCacheVersionMigration:
    """Tests for version-based cache invalidation."""

    def test_tile_cache_version_is_2(self):
        """Verify NODE_LOGIC_VERSION['tile'] is 2."""
        from app.plan_graph import NODE_LOGIC_VERSION

        assert NODE_LOGIC_VERSION.get("tile") == 2, "Tile cache version should be 2"

    def test_v2_cache_key_includes_expanded_fields(self):
        """Verify cache key computation includes end_date, adults, children."""
        from app.plan_graph import (
            clear_tile_cache,
            set_tile_cached,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()

        # Set cache with specific values
        set_tile_cached(
            intent="hotel",
            destinations=["Miami"],
            start_date="2025-10-01",
            end_date="2025-10-10",
            origin="Atlanta",
            adults=3,
            children=2,
            result={"hotel_miami": {"id": "hotel_miami", "type": "hotel"}},
        )

        tile_cache = TileCache.get_instance()

        # Compute expected key with all v2 fields (v3: includes settings_hash)
        query_str = "hotel|Miami|2025-10-01|2025-10-10|Atlanta|3|2|default"
        query_hash = hashlib.md5(query_str.encode()).hexdigest()[:16]
        key = tile_cache.compute_key(
            session_id="global",
            tile_type="hotel",
            query_hash=query_hash,
        )

        result = tile_cache.get(key, None)
        assert result is not None, "Cache key with v2 fields should find entry"

        # Try with v1-style key (missing end_date, adults, children)
        query_str_v1 = "hotel|Miami|2025-10-01|Atlanta"
        query_hash_v1 = hashlib.md5(query_str_v1.encode()).hexdigest()[:16]
        key_v1 = tile_cache.compute_key(
            session_id="global",
            tile_type="hotel",
            query_hash=query_hash_v1,
        )

        result_v1 = tile_cache.get(key_v1, None)
        assert result_v1 is None, "v1-style key should not find v2 entry"


class TestSetTileCachedIntegration:
    """Tests for set_tile_cached and TileCache integration."""

    def test_set_tile_cached_creates_entry_in_framework_cache(self):
        """set_tile_cached creates entries in the TileCache framework."""
        from app.plan_graph import (
            clear_tile_cache,
            set_tile_cached,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()
        tile_cache = TileCache.get_instance()

        assert len(tile_cache._cache) == 0, "Cache should be empty initially"

        set_tile_cached(
            intent="hotel",
            destinations=["Sydney"],
            start_date="2025-11-01",
            end_date="2025-11-07",
            origin="Melbourne",
            adults=2,
            children=0,
            result={"hotel_sydney": {"id": "hotel_sydney", "type": "hotel"}},
        )

        assert len(tile_cache._cache) == 1, "Cache should have one entry"

    def test_set_tile_cached_stores_extra_metadata(self):
        """set_tile_cached stores extra metadata with the cache entry."""
        from app.plan_graph import (
            clear_tile_cache,
            set_tile_cached,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()
        tile_cache = TileCache.get_instance()

        set_tile_cached(
            intent="flight",
            destinations=["Cairo"],
            start_date="2025-12-01",
            end_date="2025-12-07",
            origin="Dubai",
            adults=2,
            children=1,
            result={"flight_cairo": {"id": "flight_cairo", "type": "flight"}},
        )

        # Get the cached entry directly (v3: includes settings_hash)
        query_str = "flight|Cairo|2025-12-01|2025-12-07|Dubai|2|1|default"
        query_hash = hashlib.md5(query_str.encode()).hexdigest()[:16]
        key = tile_cache.compute_key(
            session_id="global",
            tile_type="flight",
            query_hash=query_hash,
        )

        # The cache should contain the entry with extra metadata
        assert key in tile_cache._cache, "Key should exist in cache"
        entry = tile_cache._cache[key]
        assert entry.get("extra", {}).get("intent") == "flight", "Should store intent in extra"
        assert entry.get("extra", {}).get("adults") == 2, "Should store adults in extra"
        assert entry.get("extra", {}).get("children") == 1, "Should store children in extra"

    def test_cache_entries_respect_version_isolation(self):
        """Cache entries include version info for isolation."""
        from app.plan_graph import (
            CACHE_SCHEMA_VERSION,
            NODE_LOGIC_VERSION,
            clear_tile_cache,
            set_tile_cached,
        )
        from app.planner.cache.framework import TileCache

        clear_tile_cache()
        tile_cache = TileCache.get_instance()

        set_tile_cached(
            intent="activity",
            destinations=["Lisbon"],
            start_date="2025-09-01",
            end_date="2025-09-05",
            origin="Porto",
            adults=3,
            children=0,
            result={"activity_lisbon": {"id": "activity_lisbon", "type": "activity"}},
        )

        # Verify version info is included (v3: includes settings_hash)
        query_str = "activity|Lisbon|2025-09-01|2025-09-05|Porto|3|0|default"
        query_hash = hashlib.md5(query_str.encode()).hexdigest()[:16]
        key = tile_cache.compute_key(
            session_id="global",
            tile_type="activity",
            query_hash=query_hash,
        )

        entry = tile_cache._cache[key]
        assert entry.get("schema_version") == CACHE_SCHEMA_VERSION, "Should include schema version"
        assert (
            entry.get("logic_version") == NODE_LOGIC_VERSION["tile"]
        ), "Should include logic version"
