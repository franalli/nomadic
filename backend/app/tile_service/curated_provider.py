"""
Curated Provider - Serves curated content for hero destinations.

This provider returns high-quality, pre-verified tiles for demo destinations
including curated flights, hotels, and activities.

Usage:
    provider = CuratedProvider("dubai")
    tiles = provider.search(context)
"""

import uuid
from typing import Any, Dict, List, Optional

from app.config import settings
from app.data.demo_curation import DEMO_MANIFEST
from app.placeholders import get_placeholder_image
from app.schemas import Tile

from .models import SearchContext
from .provider_base import Provider

# =============================================================================
# Filtering Helpers
# =============================================================================


def _within_budget(tile: Tile, hotel_limit: float, activity_limit: float) -> bool:
    """Check if tile is within budget allocation."""
    if tile.type == "hotel" and tile.price_estimate:
        return tile.price_estimate <= hotel_limit
    if tile.type == "activity" and tile.price_estimate:
        return tile.price_estimate <= activity_limit
    return True


def _matches_skill(tile: Tile, user_skill: Optional[str]) -> bool:
    """Check if activity skill level matches user's skill or below."""
    if tile.type != "activity" or not user_skill:
        return True
    tile_skill = (tile.meta or {}).get("skill_level") or (tile.meta or {}).get(
        "difficulty", "beginner"
    )
    if not tile_skill:
        return True
    skill_order = ["beginner", "intermediate", "advanced"]
    try:
        tile_idx = skill_order.index(tile_skill.lower())
        user_idx = skill_order.index(user_skill.lower())
        return tile_idx <= user_idx
    except ValueError:
        return True  # Unknown skill level, don't filter


def _matches_stars(tile: Tile, min_stars: int) -> bool:
    """Check if hotel meets minimum star rating."""
    if tile.type != "hotel" or min_stars <= 0:
        return True
    stars = (tile.meta or {}).get("stars", 0)
    if not stars:
        # Check rating as fallback (4.0+ = 4 stars, etc.)
        rating = tile.rating or 0
        stars = int(rating)
    return stars >= min_stars


class CuratedProvider(Provider):
    """
    Returns curated tiles for demo destinations.

    Strategy:
    - Hotels: Always use curated content (4K images, accurate logic hooks)
    - Activities: Use curated content filtered by specialist type
    - Flights: Use curated flight data for demo destinations
    """

    name = "curated"

    def __init__(self, destination_key: str):
        """
        Initialize with a destination key.

        Args:
            destination_key: Lowercase destination name (e.g., "dubai", "rome")
        """
        self.destination_key = destination_key.lower().strip()
        self.manifest = DEMO_MANIFEST.get(self.destination_key, {})

    def search(self, ctx: SearchContext) -> List[Tile]:
        """
        Search for curated tiles.

        Returns curated hotels and activities, with optional live flights.
        Applies budget/skill/stars filters from trip settings.
        """
        tiles: List[Tile] = []

        # Get specialist type from context (if available)
        specialist_type = getattr(ctx, "specialist_type", None) or "general"

        # Curated Hotels
        if "hotel" in ctx.verticals or not ctx.verticals:
            for hotel in self.manifest.get("curated_hotels", []):
                tile = self._hotel_to_tile(hotel, ctx)
                tiles.append(tile)

        # Curated Activities (filtered by specialist)
        if "activity" in ctx.verticals or not ctx.verticals:
            specialist_content = self.manifest.get("specialist_content", {})

            # Get specialist-specific activities
            specialist_activities = specialist_content.get(specialist_type, [])
            for activity in specialist_activities:
                tile = self._activity_to_tile(activity, ctx, specialist_type)
                tiles.append(tile)

            # Also include general activities (unless specialist is general)
            if specialist_type != "general":
                general_activities = specialist_content.get("general", [])
                for activity in general_activities:
                    tile = self._activity_to_tile(activity, ctx, "general")
                    tiles.append(tile)

        # =================================================================
        # Apply Filters from Trip Settings
        # =================================================================

        # Budget filter from configured allocation percentages.
        if ctx.budget:
            hotel_limit = ctx.budget * settings.budget_allocation_hotels
            activity_limit = ctx.budget * settings.budget_allocation_activities
            tiles = [t for t in tiles if _within_budget(t, hotel_limit, activity_limit)]

        # Skill level filter from activity_settings
        activity_settings = getattr(ctx, "activity_settings", None) or {}
        if isinstance(activity_settings, dict):
            skill_level = activity_settings.get("skill_level")
        else:
            skill_level = None
        if skill_level:
            tiles = [t for t in tiles if _matches_skill(t, skill_level)]

        # Star rating filter from hotel_settings
        hotel_settings = getattr(ctx, "hotel_settings", None) or {}
        if isinstance(hotel_settings, dict):
            min_stars = hotel_settings.get("min_stars", 0)
        else:
            min_stars = 0
        if min_stars and min_stars > 0:
            tiles = [t for t in tiles if _matches_stars(t, min_stars)]

        return tiles

    def _hotel_to_tile(self, hotel: Dict[str, Any], ctx: SearchContext) -> Tile:
        """Convert curated hotel data to a Tile."""
        hotel_id = hotel.get("id") or f"curated_hotel_{uuid.uuid4().hex[:8]}"

        # Use curated image or fallback to deterministic placeholder
        image_url = hotel.get("image") or get_placeholder_image(
            category="hotel",
            seed=hotel_id,
        )

        return Tile(
            id=hotel_id,
            type="hotel",
            partner="curated",
            partner_product_id=hotel_id,
            title=hotel.get("name", "Hotel"),
            subtitle=hotel.get("location", self.destination_key.title()),
            image_url=image_url,
            price_estimate=hotel.get("price_estimate"),
            currency=hotel.get("currency", ctx.currency or "USD"),
            price_basis="per_night",
            is_estimate_only=True,
            deeplink_url=hotel.get("booking_url", "#"),
            rating=float(hotel.get("rating", 0)),
            location_label=hotel.get("location"),
            tags=hotel.get("amenities", []),
            availability_status="available",
            meta={
                "logic_hook": hotel.get("logic_hook"),
                "amenities": hotel.get("amenities", []),
                "distance_to_dive_sites": hotel.get("distance_to_dive_sites"),
                "curated": True,
                "description": hotel.get("description"),
            },
            source="curated",
            source_agent="curated_provider",
        )

    def _activity_to_tile(
        self,
        activity: Dict[str, Any],
        ctx: SearchContext,
        specialist_type: str,
    ) -> Tile:
        """Convert curated activity data to a Tile."""
        activity_id = activity.get("id") or f"curated_activity_{uuid.uuid4().hex[:8]}"

        # Build tags from activity properties
        tags = list(activity.get("tags", []))  # Category tags from curated data
        if activity.get("skill_level"):
            tags.append(activity["skill_level"])
        if activity.get("duration_hours"):
            tags.append(f"{activity['duration_hours']}h")
        if specialist_type and specialist_type != "general":
            tags.append(specialist_type)

        # Use curated image or fallback to deterministic placeholder
        image_url = activity.get("image") or get_placeholder_image(
            category="activity",
            seed=activity_id,
        )

        return Tile(
            id=activity_id,
            type="activity",
            partner="curated",
            partner_product_id=activity_id,
            title=activity.get("title", "Activity"),
            subtitle=activity.get("location", self.destination_key.title()),
            image_url=image_url,
            price_estimate=activity.get("price_estimate"),
            currency=activity.get("currency", ctx.currency or "USD"),
            price_basis="per_person",
            is_estimate_only=True,
            deeplink_url=activity.get("booking_url", "#"),
            location_label=activity.get("location"),
            tags=tags,
            availability_status="available",
            meta={
                "logic_hook": activity.get("logic_hook"),
                "skill_level": activity.get("skill_level"),
                "duration_hours": activity.get("duration_hours"),
                "highlights": activity.get("highlights", []),
                "curated": True,
                "description": activity.get("description"),
                "specialist_type": specialist_type,
            },
            source="curated",
            source_agent=f"{specialist_type}_specialist" if specialist_type else "curated_provider",
        )

    def get_hero_image(self) -> Optional[str]:
        """Get the hero image URL for this destination."""
        return self.manifest.get("hero_image")

    def get_hero_image_alt(self) -> Optional[str]:
        """Get the hero image alt text for this destination."""
        return self.manifest.get("hero_image_alt")

    def get_tagline(self) -> Optional[str]:
        """Get the destination tagline."""
        return self.manifest.get("tagline")

    def get_logistics(self) -> Dict[str, Any]:
        """Get logistics tips for this destination."""
        return self.manifest.get("logistics", {})
