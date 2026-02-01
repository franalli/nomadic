"""
Curated Provider - Serves curated content for hero destinations.

This provider returns high-quality, pre-verified tiles for demo destinations
while optionally fetching live flight prices from Amadeus to prove the engine is real.

Usage:
    provider = CuratedProvider("dubai")
    tiles = provider.search(context)
"""

import uuid
from typing import Any, Dict, List, Optional

from app.data.demo_curation import DEMO_MANIFEST
from app.placeholders import get_placeholder_image
from app.schemas import Tile

from .models import SearchContext
from .provider_base import Provider


class CuratedProvider(Provider):
    """
    Returns curated tiles for demo destinations.

    Strategy:
    - Hotels: Always use curated content (4K images, accurate logic hooks)
    - Activities: Use curated content filtered by specialist type
    - Flights: Fetch LIVE from Amadeus (proves engine is real)
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

        # Flights - TODO: Integrate with AmadeusFlightProvider for live data
        # For now, skip flights in curated provider - they'll come from Amadeus
        # if "flight" in ctx.verticals or not ctx.verticals:
        #     pass  # Live flights from Amadeus

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
        tags = []
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


def is_curated_destination(destination: str) -> bool:
    """Check if a destination has curated content available."""
    return destination.lower().strip() in DEMO_MANIFEST


def get_curated_provider(destination: str) -> Optional[CuratedProvider]:
    """
    Get a curated provider for a destination if available.

    Returns:
        CuratedProvider instance or None if not a hero destination
    """
    dest_key = destination.lower().strip()
    if dest_key in DEMO_MANIFEST:
        return CuratedProvider(dest_key)
    return None
