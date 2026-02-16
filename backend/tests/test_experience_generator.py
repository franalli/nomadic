"""
Tests for experience_generator.py — Tier 2 LLM-generated experience tiles.

Covers:
- Cache key generation (sorting, normalization, stability)
- L1 memory cache operations
- Pydantic model validation
- Tile dict conversion (deterministic IDs, required fields, tags)
- Prompt building (budget, tier1 overlap, month parsing)
- Error handling (LLM failure → empty list)
- Full generate_experiences flow with mocked LLM

Run with: pytest tests/test_experience_generator.py -v
"""

import asyncio
from threading import Thread
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Cache Key Generation
# =============================================================================


class TestCacheKeyGeneration:
    """Test experience cache key generation."""

    def test_basic_key(self):
        from app.services.experience_generator import _experience_cache_key

        key = _experience_cache_key("Bali", ["yoga", "cooking"], "2026-03")
        assert key == "experience::v2::bali::cooking|yoga::2026-03::n2"

    def test_categories_sorted_alphabetically(self):
        from app.services.experience_generator import _experience_cache_key

        key1 = _experience_cache_key("Bali", ["yoga", "cooking", "nightlife"], "2026-03")
        key2 = _experience_cache_key("Bali", ["nightlife", "yoga", "cooking"], "2026-03")
        assert key1 == key2
        assert "cooking|nightlife|yoga" in key1

    def test_destination_normalized(self):
        from app.services.experience_generator import _experience_cache_key

        key1 = _experience_cache_key("  BALI  ", ["yoga"], "2026-03")
        key2 = _experience_cache_key("bali", ["yoga"], "2026-03")
        assert key1 == key2

    def test_category_normalized(self):
        from app.services.experience_generator import _experience_cache_key

        key1 = _experience_cache_key("Bali", ["  YOGA  "], "2026-03")
        key2 = _experience_cache_key("Bali", ["yoga"], "2026-03")
        assert key1 == key2

    def test_missing_destination(self):
        from app.services.experience_generator import _experience_cache_key

        key = _experience_cache_key("", ["yoga"], "2026-03")
        assert "unknown" in key

    def test_missing_month(self):
        from app.services.experience_generator import _experience_cache_key

        key = _experience_cache_key("Bali", ["yoga"], "")
        assert "::unknown::" in key

    def test_different_categories_different_keys(self):
        from app.services.experience_generator import _experience_cache_key

        key1 = _experience_cache_key("Bali", ["yoga"], "2026-03")
        key2 = _experience_cache_key("Bali", ["cooking"], "2026-03")
        assert key1 != key2

    def test_different_months_different_keys(self):
        from app.services.experience_generator import _experience_cache_key

        key1 = _experience_cache_key("Bali", ["yoga"], "2026-03")
        key2 = _experience_cache_key("Bali", ["yoga"], "2026-08")
        assert key1 != key2


# =============================================================================
# L1 Memory Cache
# =============================================================================


class TestL1MemoryCache:
    """Test thread-safe L1 memory cache."""

    def test_cache_get_set(self):
        from app.services.experience_generator import _cache_get, _cache_set

        _cache_set("test_exp_key", [{"id": "test"}])
        result = _cache_get("test_exp_key")
        assert result is not None
        assert result[0]["id"] == "test"

    def test_cache_miss_returns_none(self):
        from app.services.experience_generator import _cache_get

        result = _cache_get("nonexistent_exp_key_xyz")
        assert result is None

    def test_concurrent_writes(self):
        from app.services.experience_generator import _cache_get, _cache_set

        errors = []

        def writer(i: int):
            try:
                for _ in range(100):
                    _cache_set(f"exp-key-{i}", [{"value": i}])
                    result = _cache_get(f"exp-key-{i}")
                    if result is None or result[0].get("value") != i:
                        errors.append(f"Thread {i}: unexpected value {result}")
            except Exception as e:
                errors.append(f"Thread {i}: {e}")

        threads = [Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Race condition errors: {errors}"


# =============================================================================
# Pydantic Models
# =============================================================================


class TestPydanticModels:
    """Test structured output models."""

    def test_experience_tile_defaults(self):
        from app.services.experience_generator import ExperienceTile

        tile = ExperienceTile(
            title="Ubud Morning Vinyasa",
            subtitle="Rice paddy views",
            category="yoga",
        )
        assert tile.duration_hours == 2.0
        assert tile.price_estimate == 40
        assert tile.time_of_day == "morning"
        assert tile.skill_level == "beginner"

    def test_experience_tile_custom_values(self):
        from app.services.experience_generator import ExperienceTile

        tile = ExperienceTile(
            title="Advanced Rock Climbing",
            subtitle="Cliff face challenge",
            category="climbing",
            duration_hours=4.0,
            price_estimate=80,
            time_of_day="afternoon",
            skill_level="advanced",
        )
        assert tile.duration_hours == 4.0
        assert tile.price_estimate == 80

    def test_experience_output_list(self):
        from app.services.experience_generator import ExperienceOutput, ExperienceTile

        output = ExperienceOutput(
            activities=[
                ExperienceTile(title="A", subtitle="B", category="yoga"),
                ExperienceTile(title="C", subtitle="D", category="cooking"),
            ]
        )
        assert len(output.activities) == 2

    def test_experience_output_empty(self):
        from app.services.experience_generator import ExperienceOutput

        output = ExperienceOutput(activities=[])
        assert len(output.activities) == 0


# =============================================================================
# Tile Conversion
# =============================================================================


class TestTileConversion:
    """Test ExperienceTile → tile dict conversion."""

    @pytest.fixture(autouse=True)
    def _clear_unsplash_memory(self):
        from app.services.unsplash import clear_memory_cache

        clear_memory_cache()
        yield
        clear_memory_cache()

    @patch("app.services.unsplash.get_image_url_sync", return_value="https://img.test/photo.jpg")
    def test_basic_conversion(self, _mock_unsplash):
        from app.services.experience_generator import ExperienceTile, _experience_to_tile_dict

        tile = ExperienceTile(
            title="Ubud Morning Vinyasa",
            category="yoga",
            duration_hours=1.5,
            price_estimate=25,
            time_of_day="morning",
            skill_level="beginner",
        )

        result = _experience_to_tile_dict(tile, "Bali", 0)

        assert result["id"] == "exp_bali_yoga_0"
        assert result["type"] == "activity"
        assert result["partner"] == "experience_generator"
        assert result["source_agent"] == "experience_generator"
        assert result["title"] == "Ubud Morning Vinyasa"
        assert result["subtitle"] == "Morning Yoga"  # Derived from time_of_day + category
        assert result["price_estimate"] == 25.0
        assert result["currency"] == "USD"
        assert result["is_estimate_only"] is True
        assert result["image_url"] == "https://img.test/photo.jpg"

    @patch("app.services.unsplash.get_image_url_sync", return_value="https://img.test/photo.jpg")
    def test_deterministic_ids(self, _mock_unsplash):
        from app.services.experience_generator import ExperienceTile, _experience_to_tile_dict

        tile = ExperienceTile(title="A", subtitle="B", category="yoga")

        result1 = _experience_to_tile_dict(tile, "Bali", 0)
        result2 = _experience_to_tile_dict(tile, "Bali", 0)

        assert result1["id"] == result2["id"]
        assert result1["id"] == "exp_bali_yoga_0"

    @patch("app.services.unsplash.get_image_url_sync", return_value="https://img.test/photo.jpg")
    def test_different_indices_different_ids(self, _mock_unsplash):
        from app.services.experience_generator import ExperienceTile, _experience_to_tile_dict

        tile = ExperienceTile(title="A", subtitle="B", category="yoga")

        result0 = _experience_to_tile_dict(tile, "Bali", 0)
        result1 = _experience_to_tile_dict(tile, "Bali", 1)

        assert result0["id"] != result1["id"]

    @patch("app.services.unsplash.get_image_url_sync", return_value="https://img.test/photo.jpg")
    def test_tags_include_experience(self, _mock_unsplash):
        from app.services.experience_generator import ExperienceTile, _experience_to_tile_dict

        tile = ExperienceTile(title="A", subtitle="B", category="cooking")
        result = _experience_to_tile_dict(tile, "Bali", 0)

        assert "experience" in result["tags"]
        assert "activity" in result["tags"]
        assert "cooking" in result["tags"]

    @patch("app.services.unsplash.get_image_url_sync", return_value="https://img.test/photo.jpg")
    def test_meta_fields(self, _mock_unsplash):
        from app.services.experience_generator import ExperienceTile, _experience_to_tile_dict

        tile = ExperienceTile(
            title="A",
            subtitle="B",
            category="nightlife",
            time_of_day="evening",
            skill_level="intermediate",
            duration_hours=3.0,
        )
        result = _experience_to_tile_dict(tile, "Bali", 0)

        assert result["meta"]["category"] == "nightlife"
        assert result["meta"]["time_of_day"] == "evening"
        assert result["meta"]["skill_level"] == "intermediate"
        assert result["meta"]["duration_hours"] == 3.0

    @patch("app.services.unsplash.get_image_url_sync", return_value="https://img.test/photo.jpg")
    def test_multi_word_destination_normalized(self, _mock_unsplash):
        from app.services.experience_generator import ExperienceTile, _experience_to_tile_dict

        tile = ExperienceTile(title="A", subtitle="B", category="yoga")
        result = _experience_to_tile_dict(tile, "Ho Chi Minh City", 0)

        assert result["id"] == "exp_ho_chi_minh_city_yoga_0"

    @patch("app.services.unsplash.get_image_url_sync", return_value="https://img.test/photo.jpg")
    def test_unsplash_called_with_category(self, mock_unsplash):
        from app.services.experience_generator import ExperienceTile, _experience_to_tile_dict

        tile = ExperienceTile(title="A", subtitle="B", category="yoga")
        _experience_to_tile_dict(tile, "Bali", 2)

        mock_unsplash.assert_called_once_with("Bali", variant=2, activities=["yoga"])


# =============================================================================
# Prompt Building
# =============================================================================


class TestPromptBuilding:
    """Test user prompt construction."""

    def test_basic_prompt(self):
        from app.services.experience_generator import _build_user_prompt

        prompt = _build_user_prompt("Bali", ["yoga", "cooking"], "2026-03")

        assert "Bali" in prompt
        assert "yoga" in prompt
        assert "cooking" in prompt
        assert "March 2026" in prompt
        assert "2 activities per category" in prompt

    def test_budget_included(self):
        from app.services.experience_generator import _build_user_prompt

        prompt = _build_user_prompt("Bali", ["yoga", "cooking"], "2026-03", budget=2000)
        assert "Budget" in prompt
        assert "$" in prompt

    def test_no_budget_no_budget_line(self):
        from app.services.experience_generator import _build_user_prompt

        prompt = _build_user_prompt("Bali", ["yoga"], "2026-03", budget=None)
        assert "Budget" not in prompt

    def test_tier1_overlap_note(self):
        from app.services.experience_generator import _build_user_prompt

        prompt = _build_user_prompt("Bali", ["yoga"], "2026-03", tier1_specialists=["diving"])
        assert "diving" in prompt
        assert "overlap" in prompt

    def test_no_tier1_no_overlap_note(self):
        from app.services.experience_generator import _build_user_prompt

        prompt = _build_user_prompt("Bali", ["yoga"], "2026-03", tier1_specialists=None)
        assert "overlap" not in prompt

    def test_month_parsing_invalid(self):
        from app.services.experience_generator import _build_user_prompt

        prompt = _build_user_prompt("Bali", ["yoga"], "bad-month")
        assert "bad-month" in prompt  # Falls back to raw string


# =============================================================================
# Generate Experiences (mocked LLM)
# =============================================================================


class TestGenerateExperiences:
    """Test the main generate_experiences function with mocked dependencies."""

    def _clear_l1(self):
        from app.services.experience_generator import clear_experience_cache

        clear_experience_cache()

    @pytest.mark.asyncio
    async def test_empty_destination_returns_empty(self):
        from app.services.experience_generator import generate_experiences

        result = await generate_experiences("", ["yoga"], "2026-03")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_categories_returns_empty(self):
        from app.services.experience_generator import generate_experiences

        result = await generate_experiences("Bali", [], "2026-03")
        assert result == []

    @pytest.mark.asyncio
    async def test_l1_cache_hit(self):
        from app.services.experience_generator import (
            _cache_set,
            _experience_cache_key,
            generate_experiences,
        )

        cache_key = _experience_cache_key("CacheTest", ["yoga"], "2099-01")
        fake_tiles = [{"id": "cached_tile", "title": "Cached"}]
        _cache_set(cache_key, fake_tiles)

        result = await generate_experiences("CacheTest", ["yoga"], "2099-01")
        assert len(result) == 1
        assert result[0]["id"] == "cached_tile"

    @pytest.mark.asyncio
    @patch("app.db._get_async_session_factory")
    @patch("app.services.unsplash.prefetch_destination_images", new_callable=AsyncMock)
    @patch("app.services.unsplash.get_image_url_sync", return_value="https://img.test/photo.jpg")
    async def test_full_flow_mocked_llm(self, _mock_img, _mock_prefetch, mock_db_factory):
        from app.services.experience_generator import (
            ExperienceOutput,
            ExperienceTile,
            generate_experiences,
        )

        self._clear_l1()

        # Mock DB session factory (L2 miss)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_db_factory.return_value = MagicMock(return_value=mock_session)

        # Mock LLM structured output — one response per category
        fake_yoga = ExperienceOutput(
            activities=[
                ExperienceTile(
                    title="Ubud Morning Vinyasa",
                    category="yoga",
                    time_of_day="morning",
                    price_estimate=25,
                ),
                ExperienceTile(
                    title="Seminyak Sunset Yoga",
                    category="yoga",
                    time_of_day="evening",
                    price_estimate=30,
                ),
            ]
        )
        fake_cooking = ExperienceOutput(
            activities=[
                ExperienceTile(
                    title="Balinese Cooking Class",
                    category="cooking",
                    time_of_day="morning",
                    price_estimate=45,
                ),
                ExperienceTile(
                    title="Warung Night Tour",
                    category="cooking",
                    time_of_day="evening",
                    price_estimate=35,
                ),
            ]
        )

        # Batch mode: single LLM call returns all tiles across categories
        fake_batch = ExperienceOutput(activities=fake_yoga.activities + fake_cooking.activities)
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke = AsyncMock(return_value=fake_batch)

        with patch("app.services.experience_generator.get_llm_by_model") as mock_get_llm:
            mock_instance = MagicMock()
            mock_instance.with_structured_output.return_value = mock_structured_llm
            mock_get_llm.return_value = mock_instance

            result = await generate_experiences(
                destination="Bali",
                categories=["yoga", "cooking"],
                month="2099-06",
            )

        assert len(result) == 4
        # Check tile structure
        for tile in result:
            assert "id" in tile
            assert tile["type"] == "activity"
            assert tile["source_agent"] == "experience_generator"
            assert "experience" in tile["tags"]
            assert tile["currency"] == "USD"
            assert tile["is_estimate_only"] is True
            assert "meta" in tile

        # Check deterministic IDs
        assert result[0]["id"] == "exp_bali_yoga_0"
        assert result[1]["id"] == "exp_bali_yoga_1"
        assert result[2]["id"] == "exp_bali_cooking_2"
        assert result[3]["id"] == "exp_bali_cooking_3"

        # Check titles preserved
        assert result[0]["title"] == "Ubud Morning Vinyasa"
        assert result[2]["title"] == "Balinese Cooking Class"

        self._clear_l1()

    @pytest.mark.asyncio
    @patch("app.db._get_async_session_factory")
    async def test_llm_failure_returns_empty(self, mock_db_factory):
        from app.services.experience_generator import (
            generate_experiences,
        )

        self._clear_l1()

        # Mock DB session (L2 miss)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_db_factory.return_value = MagicMock(return_value=mock_session)

        # Mock LLM that raises
        with patch("app.services.experience_generator.get_llm_by_model") as mock_get_llm:
            mock_instance = MagicMock()
            mock_structured = AsyncMock()
            mock_structured.ainvoke = AsyncMock(side_effect=Exception("API timeout"))
            mock_instance.with_structured_output.return_value = mock_structured
            mock_get_llm.return_value = mock_instance

            result = await generate_experiences(
                destination="Bali",
                categories=["yoga"],
                month="2099-07",
            )

        assert result == []
        self._clear_l1()

    @pytest.mark.asyncio
    @patch("app.db._get_async_session_factory")
    @patch("app.services.unsplash.get_image_url_sync", return_value="https://img.test/photo.jpg")
    async def test_llm_returns_empty_activities(self, _mock_img, mock_db_factory):
        from app.services.experience_generator import (
            ExperienceOutput,
            generate_experiences,
        )

        self._clear_l1()

        # Mock DB session (L2 miss)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_db_factory.return_value = MagicMock(return_value=mock_session)

        # Mock LLM returning empty activities
        fake_parsed = ExperienceOutput(activities=[])
        fake_raw = MagicMock()
        fake_raw.response_metadata = {}

        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke = AsyncMock(return_value=fake_parsed)

        with patch("app.services.experience_generator.get_llm_by_model") as mock_get_llm:
            mock_instance = MagicMock()
            mock_instance.with_structured_output.return_value = mock_structured_llm
            mock_get_llm.return_value = mock_instance

            result = await generate_experiences(
                destination="Bali",
                categories=["yoga"],
                month="2099-08",
            )

        assert result == []
        self._clear_l1()

    @pytest.mark.asyncio
    @patch("app.services.experience_generator._generate_experiences_impl", new_callable=AsyncMock)
    async def test_singleflight_dedupes_inflight_generation(self, mock_impl):
        from app.services.experience_generator import generate_experiences

        async def _slow_impl(*_args, **_kwargs):
            await asyncio.sleep(0.02)
            return [{"id": "exp_bali_yoga_0", "meta": {"category": "yoga"}}]

        mock_impl.side_effect = _slow_impl

        task_one = asyncio.create_task(
            generate_experiences(
                destination="Bali",
                categories=["yoga"],
                month="2099-09",
            )
        )
        await asyncio.sleep(0.005)
        task_two = asyncio.create_task(
            generate_experiences(
                destination="Bali",
                categories=["yoga"],
                month="2099-09",
            )
        )

        first, second = await asyncio.gather(task_one, task_two)

        assert mock_impl.await_count == 1
        assert first == second

    @pytest.mark.asyncio
    @patch("app.services.experience_generator._generate_experiences_impl", new_callable=AsyncMock)
    async def test_singleflight_waiter_hydrates_state_metadata(self, mock_impl):
        from app.services.experience_generator import generate_experiences

        class _State:
            def __init__(self):
                self.metadata = {}

        async def _slow_impl(*_args, **_kwargs):
            await asyncio.sleep(0.02)
            return [{"id": "exp_bali_yoga_0", "meta": {"category": "yoga"}}]

        mock_impl.side_effect = _slow_impl

        owner = asyncio.create_task(
            generate_experiences(
                destination="Bali",
                categories=["yoga"],
                month="2099-10",
                state=None,
            )
        )
        await asyncio.sleep(0.005)

        state = _State()
        waiter_result = await generate_experiences(
            destination="Bali",
            categories=["yoga"],
            month="2099-10",
            state=state,
        )
        owner_result = await owner

        assert mock_impl.await_count == 1
        assert waiter_result == owner_result
        assert "generated_tier2_categories" in state.metadata
        assert "Bali" in state.metadata["generated_tier2_categories"]
        assert "yoga" in state.metadata["generated_tier2_categories"]["Bali"]
        assert (
            state.metadata["generated_tier2_categories"]["Bali"]["yoga"][0]["id"]
            == "exp_bali_yoga_0"
        )

    @pytest.mark.asyncio
    async def test_l1_cache_hit_marks_generation_source_as_cache(self):
        from app.services.experience_generator import (
            _cache_set,
            _experience_cache_key,
            generate_experiences,
        )

        class _State:
            def __init__(self):
                self.metadata = {}

        cache_key = _experience_cache_key("CacheMeta", ["yoga"], "2099-11")
        cached_tiles = [{"id": "cached_tile", "meta": {"category": "yoga"}}]
        _cache_set(cache_key, cached_tiles)

        state = _State()
        result = await generate_experiences("CacheMeta", ["yoga"], "2099-11", state=state)

        assert result == cached_tiles
        assert state.metadata.get("tier2_generation_source_internal") == "cache"

    @pytest.mark.asyncio
    @patch("app.db._get_async_session_factory")
    @patch("app.services.unsplash.prefetch_destination_images", new_callable=AsyncMock)
    @patch("app.services.unsplash.get_image_url_sync", return_value="https://img.test/photo.jpg")
    async def test_llm_path_marks_generation_source_as_llm(
        self,
        _mock_img,
        _mock_prefetch,
        mock_db_factory,
    ):
        from app.services.experience_generator import (
            ExperienceOutput,
            ExperienceTile,
            generate_experiences,
        )

        class _State:
            def __init__(self):
                self.metadata = {}

        self._clear_l1()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_db_factory.return_value = MagicMock(return_value=mock_session)

        fake_batch = ExperienceOutput(
            activities=[
                ExperienceTile(
                    title="Ubud Morning Vinyasa",
                    category="yoga",
                    time_of_day="morning",
                    price_estimate=25,
                )
            ]
        )
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke = AsyncMock(return_value=fake_batch)

        with patch("app.services.experience_generator.get_llm_by_model") as mock_get_llm:
            mock_instance = MagicMock()
            mock_instance.with_structured_output.return_value = mock_structured_llm
            mock_get_llm.return_value = mock_instance

            state = _State()
            result = await generate_experiences(
                destination="Bali",
                categories=["yoga"],
                month="2099-12",
                state=state,
            )

        assert len(result) == 1
        assert state.metadata.get("tier2_generation_source_internal") == "llm"
        self._clear_l1()
