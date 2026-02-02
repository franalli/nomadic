"""
Tests for router extraction caching (L1 memory only).

CRITICAL TESTS: Context-dependency detection to prevent cross-conversation pollution.

Tests cover:
- Cache key generation with date sensitivity
- Context-dependency detection (the critical feature)
- L1 memory cache operations
- Thread safety
"""

from app.services.router_cache import (
    _is_self_contained_query,
    _router_cache_key,
    clear_cache,
    get_cache_stats,
    get_cached_extraction,
    reset_stats,
    set_cached_extraction,
)


class TestRouterCacheKeyGeneration:
    """Tests for cache key generation."""

    def test_different_dates_different_keys(self):
        """CRITICAL: Keys must differ when today_date differs.

        This is essential because "next Friday" means different dates
        depending on when you ask.
        """
        key1 = _router_cache_key("plan a trip to bali", "2025-03-01")
        key2 = _router_cache_key("plan a trip to bali", "2025-03-02")
        assert key1 != key2

    def test_normalized_text(self):
        """Test text normalization (lowercase, stripped)."""
        key1 = _router_cache_key("  PLAN A TRIP TO BALI  ", "2025-03-01")
        key2 = _router_cache_key("plan a trip to bali", "2025-03-01")
        assert key1 == key2

    def test_key_length(self):
        """Test that key is SHA256 truncated to 32 chars."""
        key = _router_cache_key("test", "2025-03-01")
        assert len(key) == 32
        assert all(c in "0123456789abcdef" for c in key)

    def test_same_input_same_key(self):
        """Test deterministic key generation."""
        key1 = _router_cache_key("test query", "2025-03-01")
        key2 = _router_cache_key("test query", "2025-03-01")
        assert key1 == key2


class TestContextDependencyDetection:
    """
    CRITICAL TESTS: Context-dependent queries must NOT be cached.

    These tests prevent the bug where:
    - User A asks "I want to go to Bali" then "Show me diving there"
    - "Show me diving there" gets cached with destination=Bali
    - User B asks "I want to go to Thailand" then "Show me diving there"
    - User B gets destination=Bali from cache (WRONG!)
    """

    def test_context_word_there(self):
        """Test 'there' is detected as context-dependent."""
        extraction = {"destination": "Bali"}
        assert not _is_self_contained_query("Show me diving there", extraction)
        assert not _is_self_contained_query("I want to go there", extraction)
        assert not _is_self_contained_query("Book a hotel there", extraction)

    def test_context_word_that(self):
        """Test 'that' is detected as context-dependent."""
        extraction = {"destination": "Bali"}
        assert not _is_self_contained_query("I want that one", extraction)
        assert not _is_self_contained_query("Book that hotel", extraction)

    def test_context_word_this(self):
        """Test 'this' is detected as context-dependent."""
        extraction = {"destination": "Bali"}
        assert not _is_self_contained_query("Add this to my trip", extraction)
        assert not _is_self_contained_query("I like this option", extraction)

    def test_context_word_it(self):
        """Test 'it' is detected as context-dependent."""
        extraction = {"destination": "Bali"}
        assert not _is_self_contained_query("Book it now", extraction)
        assert not _is_self_contained_query("I want it", extraction)

    def test_context_word_them(self):
        """Test 'them' is detected as context-dependent."""
        extraction = {"destination": "Bali"}
        assert not _is_self_contained_query("Show them to me", extraction)
        assert not _is_self_contained_query("I want all of them", extraction)

    def test_context_word_same(self):
        """Test 'same' is detected as context-dependent."""
        extraction = {"destination": "Bali"}
        assert not _is_self_contained_query("Same dates as before", extraction)
        assert not _is_self_contained_query("Use the same hotel", extraction)

    def test_context_word_again(self):
        """Test 'again' is detected as context-dependent."""
        extraction = {"destination": "Bali"}
        assert not _is_self_contained_query("Do it again", extraction)
        assert not _is_self_contained_query("Search again", extraction)

    def test_context_word_too(self):
        """Test 'too' is detected as context-dependent."""
        extraction = {"destination": "Bali"}
        assert not _is_self_contained_query("I want hiking too", extraction)
        assert not _is_self_contained_query("Add diving too", extraction)

    def test_context_word_also(self):
        """Test 'also' is detected as context-dependent."""
        extraction = {"destination": "Bali"}
        assert not _is_self_contained_query("Also add surfing", extraction)
        assert not _is_self_contained_query("I also want to dive", extraction)

    def test_all_context_words_comprehensive(self):
        """Comprehensive test of all context-dependent words."""
        context_queries = [
            "Show me diving there",
            "I want that one",
            "Add this to my trip",
            "Book it now",
            "Show them to me",
            "Same dates as before",
            "Do it again",
            "I want hiking too",
            "Also add surfing",
        ]

        extraction = {"destination": "Bali"}

        for query in context_queries:
            assert not _is_self_contained_query(query, extraction), f"Should reject: {query}"

    def test_no_false_positives_weather(self):
        """Test 'weather' doesn't trigger 'the' false positive."""
        # "weather" contains "the" but shouldn't be flagged
        extraction = {"destination": "Bali"}
        # This query IS self-contained if it mentions a destination
        assert _is_self_contained_query("What's the weather in Bali February", extraction)

    def test_no_false_positives_together(self):
        """Test 'together' doesn't trigger 'the' false positive."""
        extraction = {"destination": "Bali"}
        assert _is_self_contained_query("Plan a trip to Bali together with my family", extraction)

    def test_valid_self_contained_queries(self):
        """Test valid self-contained queries are allowed."""
        valid_queries = [
            "I want to go to Bali for diving",
            "Plan a trip to Thailand February 1-14",
            "Show me hotels in Dubai",
            "Skiing in Chamonix next week",
            "Book a diving trip to the Maldives",
            "I want to explore Rome in March",
        ]

        extraction = {"destination": "Bali"}

        for query in valid_queries:
            assert _is_self_contained_query(query, extraction), f"Should allow: {query}"

    def test_requires_destination(self):
        """Test that queries without destination are not cached."""
        # Even if query looks self-contained, no destination = no cache
        extraction_without_dest = {}
        assert not _is_self_contained_query("I want to go diving", extraction_without_dest)

        extraction_with_none = {"destination": None}
        assert not _is_self_contained_query("I want to go diving", extraction_with_none)

        extraction_with_empty = {"destination": ""}
        assert not _is_self_contained_query("I want to go diving", extraction_with_empty)


class TestL1MemoryCache:
    """Tests for L1 memory cache operations."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_cache()
        reset_stats()

    def test_self_contained_query_cached(self):
        """Test that self-contained queries are cached."""
        extraction = {"destination": "Bali", "start_date": "2025-03-01"}

        set_cached_extraction("I want to go to Bali March 1", "2025-02-01", extraction)

        result = get_cached_extraction("I want to go to Bali March 1", "2025-02-01")
        assert result is not None
        assert result["destination"] == "Bali"

        stats = get_cache_stats()
        assert stats["hits"] >= 1

    def test_context_dependent_query_not_cached(self):
        """CRITICAL: Context-dependent queries must NOT be cached."""
        extraction = {"destination": "Bali", "start_date": "2025-03-01"}

        # Try to cache a context-dependent query
        set_cached_extraction("Show me diving there", "2025-02-01", extraction)

        # Should NOT be in cache
        result = get_cached_extraction("Show me diving there", "2025-02-01")
        assert result is None

        stats = get_cache_stats()
        assert stats["skipped_context_dependent"] >= 1

    def test_miss_returns_none(self):
        """Test that cache miss returns None."""
        result = get_cached_extraction("nonexistent query", "2025-02-01")
        assert result is None

        stats = get_cache_stats()
        assert stats["misses"] >= 1

    def test_stats_tracking(self):
        """Test that stats are properly tracked."""
        stats_before = get_cache_stats()
        initial_misses = stats_before["misses"]

        # Trigger a miss
        get_cached_extraction("test query miss", "2025-02-01")

        stats_after = get_cache_stats()
        assert stats_after["misses"] == initial_misses + 1

    def test_clear_returns_count(self):
        """Test that clear returns the count of cleared entries."""
        # Add some entries
        set_cached_extraction("Test query 1 Bali", "2025-02-01", {"destination": "Bali"})
        set_cached_extraction("Test query 2 Dubai", "2025-02-01", {"destination": "Dubai"})

        count = clear_cache()
        assert count >= 2

        # Cache should be empty
        stats = get_cache_stats()
        assert stats["size"] == 0


class TestCacheDateSensitivity:
    """Tests for date-sensitive caching behavior."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_cache()
        reset_stats()

    def test_same_query_different_dates_cached_separately(self):
        """Test that same query on different days caches separately."""
        extraction = {"destination": "Bali", "start_date": "2025-03-07"}

        # Cache on day 1
        set_cached_extraction("I want to go to Bali next Friday", "2025-03-01", extraction)

        # Different date should be cache miss
        result = get_cached_extraction("I want to go to Bali next Friday", "2025-03-02")
        assert result is None

        # Same date should be cache hit
        result = get_cached_extraction("I want to go to Bali next Friday", "2025-03-01")
        assert result is not None
        assert result["destination"] == "Bali"


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_access(self):
        """Test that concurrent access doesn't cause errors."""
        import threading

        clear_cache()
        errors = []

        def access_cache(thread_id):
            try:
                for i in range(50):
                    # Mix of reads and writes
                    query = f"Thread {thread_id} query {i} to Bali"
                    extraction = {"destination": "Bali", "thread": thread_id}

                    set_cached_extraction(query, "2025-02-01", extraction)
                    get_cached_extraction(query, "2025-02-01")
                    get_cache_stats()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=access_cache, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_concurrent_clear(self):
        """Test that concurrent clears don't cause errors."""
        import threading

        errors = []

        def clear_repeatedly():
            try:
                for _ in range(100):
                    clear_cache()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=clear_repeatedly) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"
