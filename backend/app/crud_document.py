"""
CRUD operations for the centralized PlanDocument.
Uses CRDT-style merge for conflict resolution.
Most recent update wins regardless of source (user or LLM).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app import db_models as models
from app.debug_utils import _debug

# normalize_destinations removed - single destination only
from app.schemas import (
    ActivitySettings,
    BookingTypes,
    BranchSelections,
    DayCard,
    DocumentBranch,
    DocumentTripInputs,
    DocumentTripInputsPatch,
    FlightSettings,
    HotelSettings,
    PlanDocumentData,
    PlanDocumentPatch,
    PlanViewState,
    StrategySection,
    TransportSettings,
    UpdatedBy,
)
from app.schemas import (
    Tile as TileSchema,
)

# =============================================================================
# Async functions (for async endpoints and LangGraph)
# =============================================================================


async def get_document(
    db: AsyncSession, *, session: models.Session
) -> Optional[models.PlanDocument]:
    """Fetch the plan document for a session (async)."""
    stmt = select(models.PlanDocument).filter(models.PlanDocument.session_id == session.id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_document(
    db: AsyncSession,
    *,
    session: models.Session,
    updated_by: UpdatedBy = "planner",
) -> models.PlanDocument:
    """Get existing document or create an empty one (async)."""
    doc = await get_document(db, session=session)
    if doc:
        return doc

    empty_data = PlanDocumentData().model_dump()
    doc = models.PlanDocument(
        session_id=session.id,
        version=1,
        updated_by=updated_by,
        document=empty_data,
    )
    db.add(doc)
    await db.flush()
    return doc


def get_document_data(doc: models.PlanDocument) -> PlanDocumentData:
    """Parse the JSON document into a Pydantic model."""
    raw_data = dict(doc.document) if doc.document else {}
    return PlanDocumentData.model_validate(raw_data)


def save_document_data_sync(
    db: Session,
    *,
    doc: models.PlanDocument,
    data: PlanDocumentData,
    updated_by: UpdatedBy,
) -> models.PlanDocument:
    """Save updated document data, incrementing version (sync)."""
    doc.document = data.model_dump()
    doc.version += 1
    doc.updated_by = updated_by
    db.flush()
    return doc


async def save_document_data(
    db: AsyncSession,
    *,
    doc: models.PlanDocument,
    data: PlanDocumentData,
    updated_by: UpdatedBy,
) -> models.PlanDocument:
    """Save updated document data, incrementing version (async)."""
    doc.document = data.model_dump()
    doc.version += 1
    doc.updated_by = updated_by
    await db.flush()
    return doc


# ─────────────────────────────────────────────────────────────────────────────
# CRDT-style Merge Operations
# ─────────────────────────────────────────────────────────────────────────────


def _trip_inputs_to_dict(
    incoming: DocumentTripInputs | DocumentTripInputsPatch | dict | None,
) -> dict[str, Any]:
    """Normalize incoming trip input payloads to a plain dict."""

    if incoming is None:
        return {}

    if isinstance(incoming, DocumentTripInputs):
        return incoming.model_dump()

    if isinstance(incoming, DocumentTripInputsPatch):
        return incoming.model_dump(exclude_unset=True)

    if isinstance(incoming, dict):
        return dict(incoming)

    if hasattr(incoming, "model_dump"):
        return incoming.model_dump(exclude_unset=True)

    return {}


def merge_trip_inputs(
    existing: DocumentTripInputs,
    incoming: Optional[DocumentTripInputs | DocumentTripInputsPatch | dict],
    *,
    replace_destinations: bool = False,
    explicit_nulls: Optional[set[str]] = None,
) -> DocumentTripInputs:
    """
    Merge trip inputs with most-recent-wins conflict resolution.

    Rule: The most recent update wins, regardless of whether it's from user or LLM.

    Args:
        existing: Current trip inputs state
        incoming: New values to merge
        replace_destinations: If True, replace destinations entirely (for user patches)
        explicit_nulls: Set of field names that were explicitly set to null/None.
                       When a user clicks X on a field badge, the field is in this set.
                       This allows distinguishing "not provided" from "delete this field".

    Works with both full DocumentTripInputs payloads and partial patches.
    """

    incoming_data = _trip_inputs_to_dict(incoming)
    if not incoming_data and not explicit_nulls:
        return existing

    # Start with a copy of existing
    result = existing.model_copy(deep=True)

    # Fields that can be merged (excluding meta fields)
    mergeable_fields = [
        "destination",
        "origin",
        "start_date",
        "end_date",
        "adults",
        "children",
        "requires_assistance",
        "budget",
        "currency",
        # Booking preferences (nested objects - replace entirely)
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "activity_settings",
        "transport_settings",
    ]
    booking_defaults = {
        "booking_types": BookingTypes,
        "flight_settings": FlightSettings,
        "hotel_settings": HotelSettings,
        "activity_settings": ActivitySettings,
        "transport_settings": TransportSettings,
    }

    # Ensure explicit_nulls is a set (for membership testing)
    nulls_set = explicit_nulls or set()

    for field in mergeable_fields:
        incoming_value = incoming_data.get(field)
        is_explicit_null = field in nulls_set

        # Skip if incoming doesn't have this field AND it's not explicitly nulled
        if field not in incoming_data and not is_explicit_null:
            continue

        # Handle destination (single destination, replaces old value)
        if field == "destination":
            if is_explicit_null:
                result.destination = None
            elif incoming_value is not None:
                result.destination = incoming_value
                _debug(f"Set 'destination' to '{incoming_value}'")
        elif field in booking_defaults:
            if is_explicit_null:
                # Reset booking preference to default instance
                default_factory = booking_defaults[field]
                setattr(result, field, default_factory())
                _debug(f"Reset '{field}' to default (explicit null)")
            elif incoming_value is not None:
                # Convert dict to Pydantic model if needed to avoid serialization warnings
                model_class = booking_defaults[field]
                if isinstance(incoming_value, dict):
                    incoming_value = model_class(**incoming_value)
                elif not isinstance(incoming_value, model_class):
                    incoming_value = model_class.model_validate(incoming_value)
                setattr(result, field, incoming_value)
                _debug(f"Set '{field}' to '{incoming_value}'")
        else:
            # Scalar fields: origin, start_date, end_date, adults, children,
            # requires_assistance, budget, multi_city_intent
            if is_explicit_null:
                # User explicitly deleted this field
                setattr(result, field, None)
                _debug(f"Deleted '{field}' (explicit null)")
            elif incoming_value is not None:
                setattr(result, field, incoming_value)
                _debug(f"Set '{field}' to '{incoming_value}'")

    # Handle missing_fields - always recompute based on actual values
    # ONLY include REQUIRED fields: destination, start_date
    # origin and end_date are OPTIONAL
    missing = []
    if not result.destination:
        missing.append("destination")
    if result.start_date is None:
        missing.append("start_date")
    result.missing_fields = missing

    return result


def merge_branches(
    existing: list[DocumentBranch],
    incoming: Optional[list[DocumentBranch]],
    remove_ids: Optional[list[str]] = None,
) -> list[DocumentBranch]:
    """
    CRDT-style merge for branches:
    - Incoming branches are added or update existing by id
    - remove_ids explicitly removes branches
    """
    if not incoming and not remove_ids:
        return existing

    # Build a map of existing branches
    branch_map = {b.id: b for b in existing}

    # Apply removals
    if remove_ids:
        for rid in remove_ids:
            branch_map.pop(rid, None)

    # Merge incoming (additions win)
    if incoming:
        for branch in incoming:
            branch_map[branch.id] = branch

    return list(branch_map.values())


def merge_tiles(
    existing: dict[str, TileSchema],
    incoming: Optional[dict[str, TileSchema]],
    remove_ids: Optional[list[str]] = None,
) -> dict[str, TileSchema]:
    """
    CRDT-style merge for tiles:
    - Incoming tiles are added or update existing by id
    - remove_ids explicitly removes tiles
    """
    if not incoming and not remove_ids:
        return existing

    result = dict(existing)

    # Apply removals
    if remove_ids:
        for rid in remove_ids:
            result.pop(rid, None)

    # Merge incoming (additions win)
    if incoming:
        result.update(incoming)

    return result


def merge_selections(
    branches: list[DocumentBranch],
    selections_update: Optional[dict[str, BranchSelections]],
) -> list[DocumentBranch]:
    """Update selections for specific branches."""
    if not selections_update:
        return branches

    result = []
    for branch in branches:
        if branch.id in selections_update:
            branch = branch.model_copy(update={"selections": selections_update[branch.id]})
        result.append(branch)
    return result


def prune_branches_and_tiles(
    branches: list[DocumentBranch],
    tiles: dict[str, TileSchema],
    current_destination: Optional[str],
) -> tuple[list[DocumentBranch], dict[str, TileSchema]]:
    """
    Prune branches that reference a different destination than trip_inputs.
    Also remove orphaned tiles that are no longer referenced by any remaining branch.

    Args:
        branches: Current list of branches
        tiles: Current tiles map
        current_destination: The current destination from trip_inputs

    Returns:
        Tuple of (pruned_branches, pruned_tiles)
    """
    if not branches:
        return branches, tiles

    # Filter branches: keep only those matching the current destination
    pruned_branches = []
    current_lower = current_destination.lower() if current_destination else None

    for branch in branches:
        branch_dest = branch.destination
        # Keep branch if it has no destination or matches current
        if not branch_dest or not current_lower:
            pruned_branches.append(branch)
        elif branch_dest.lower() == current_lower:
            pruned_branches.append(branch)
        else:
            _debug(
                f"Pruning branch '{branch.id}' - "
                f"destination '{branch_dest}' != current '{current_destination}'"
            )

    # If no branches were removed, tiles are unchanged
    if len(pruned_branches) == len(branches):
        return branches, tiles

    # Collect all tile IDs still referenced by remaining branches
    referenced_tile_ids: set[str] = set()
    for branch in pruned_branches:
        referenced_tile_ids.update(branch.tiles.stays)
        referenced_tile_ids.update(branch.tiles.flights)
        referenced_tile_ids.update(branch.tiles.activities)
        # Also include selections
        if branch.selections.stay:
            referenced_tile_ids.add(branch.selections.stay)
        if branch.selections.flight:
            referenced_tile_ids.add(branch.selections.flight)
        referenced_tile_ids.update(branch.selections.activities)

    # Prune orphaned tiles
    pruned_tiles = {tid: tile for tid, tile in tiles.items() if tid in referenced_tile_ids}

    removed_count = len(tiles) - len(pruned_tiles)
    if removed_count > 0:
        _debug(f"Pruned {removed_count} orphaned tiles")

    return pruned_branches, pruned_tiles


# ─────────────────────────────────────────────────────────────────────────────
# High-Level Operations
# ─────────────────────────────────────────────────────────────────────────────


def apply_user_patch_sync(
    db: Session,
    *,
    doc: models.PlanDocument,
    patch: PlanDocumentPatch,
) -> models.PlanDocument:
    """
    Apply a user-initiated patch to the document using CRDT merge (sync).

    When trip_inputs change (e.g., user removes a destination), the primary branch
    is updated to reflect the new values so UI displays updated destinations.
    """
    data = get_document_data(doc)

    # Detect fields explicitly set to null (user clicked X on field badge)
    explicit_nulls: set[str] = set()
    if isinstance(patch.trip_inputs, DocumentTripInputsPatch):
        for field_name in patch.trip_inputs.model_fields_set:
            if getattr(patch.trip_inputs, field_name, "NOT_NONE") is None:
                explicit_nulls.add(field_name)
                _debug(f"apply_user_patch_sync: '{field_name}' set to null")

    # Merge trip inputs with replace_destinations=True
    data.trip_inputs = merge_trip_inputs(
        data.trip_inputs,
        patch.trip_inputs,
        replace_destinations=True,
        explicit_nulls=explicit_nulls if explicit_nulls else None,
    )

    # Merge branches
    data.branches = merge_branches(data.branches, patch.branches, patch.remove_branch_ids)

    # Merge tiles
    data.tiles = merge_tiles(data.tiles, patch.tiles, patch.remove_tile_ids)

    # Update selections
    data.branches = merge_selections(data.branches, patch.selections)

    # Prune branches referencing different destination, and clean up orphaned tiles
    if patch.trip_inputs is not None and data.branches:
        data.branches, data.tiles = prune_branches_and_tiles(
            data.branches,
            data.tiles,
            data.trip_inputs.destination,
        )

    # Cascade trip_inputs changes to the primary branch
    # This ensures destination changes are reflected in the branch
    if patch.trip_inputs is not None and data.branches:
        primary_idx = next(
            (i for i, b in enumerate(data.branches) if b.is_primary), 0 if data.branches else None
        )
        if primary_idx is not None:
            primary = data.branches[primary_idx]
            # Always sync destination
            primary.destination = data.trip_inputs.destination

            # Sync other fields only if they were explicitly provided in the patch
            def _field_was_provided(field_name: str) -> bool:
                if isinstance(patch.trip_inputs, DocumentTripInputsPatch):
                    return field_name in patch.trip_inputs.model_fields_set
                return True  # Full DocumentTripInputs payloads are treated as explicit

            if _field_was_provided("origin"):
                primary.origin = data.trip_inputs.origin
            if _field_was_provided("start_date"):
                primary.start_date = data.trip_inputs.start_date
            if _field_was_provided("end_date"):
                primary.end_date = data.trip_inputs.end_date
            if _field_was_provided("adults"):
                primary.adults = data.trip_inputs.adults
            if _field_was_provided("children"):
                primary.children = data.trip_inputs.children
            if _field_was_provided("requires_assistance"):
                primary.requires_assistance = data.trip_inputs.requires_assistance
            if _field_was_provided("budget"):
                primary.budget = data.trip_inputs.budget
            if _field_was_provided("currency"):
                primary.currency = data.trip_inputs.currency
            data.branches[primary_idx] = primary

    return save_document_data_sync(db, doc=doc, data=data, updated_by="user")


async def apply_user_patch(
    db: AsyncSession,
    *,
    doc: models.PlanDocument,
    patch: PlanDocumentPatch,
) -> models.PlanDocument:
    """
    Apply a user-initiated patch to the document using CRDT merge (async).

    When trip_inputs change (e.g., user removes a destination), the primary branch
    is updated to reflect the new values so UI displays updated destinations.
    """
    data = get_document_data(doc)

    # Detect fields explicitly set to null (user clicked X on field badge)
    explicit_nulls: set[str] = set()
    if isinstance(patch.trip_inputs, DocumentTripInputsPatch):
        for field_name in patch.trip_inputs.model_fields_set:
            if getattr(patch.trip_inputs, field_name, "NOT_NONE") is None:
                explicit_nulls.add(field_name)
                _debug(f"apply_user_patch: Field '{field_name}' explicitly set to null")

    # Merge trip inputs with replace_destinations=True
    data.trip_inputs = merge_trip_inputs(
        data.trip_inputs,
        patch.trip_inputs,
        replace_destinations=True,
        explicit_nulls=explicit_nulls if explicit_nulls else None,
    )

    # Merge branches
    data.branches = merge_branches(data.branches, patch.branches, patch.remove_branch_ids)

    # Merge tiles
    data.tiles = merge_tiles(data.tiles, patch.tiles, patch.remove_tile_ids)

    # Update selections
    data.branches = merge_selections(data.branches, patch.selections)

    # Prune branches referencing different destination, and clean up orphaned tiles
    if patch.trip_inputs is not None and data.branches:
        data.branches, data.tiles = prune_branches_and_tiles(
            data.branches,
            data.tiles,
            data.trip_inputs.destination,
        )

    # Cascade trip_inputs changes to the primary branch
    # This ensures destination changes are reflected in the branch
    if patch.trip_inputs is not None and data.branches:
        primary_idx = next(
            (i for i, b in enumerate(data.branches) if b.is_primary), 0 if data.branches else None
        )
        if primary_idx is not None:
            primary = data.branches[primary_idx]
            # Always sync destination
            primary.destination = data.trip_inputs.destination

            # Sync other fields only if they were explicitly provided in the patch
            def _field_was_provided(field_name: str) -> bool:
                if isinstance(patch.trip_inputs, DocumentTripInputsPatch):
                    return field_name in patch.trip_inputs.model_fields_set
                return True  # Full DocumentTripInputs payloads are treated as explicit

            if _field_was_provided("origin"):
                primary.origin = data.trip_inputs.origin
            if _field_was_provided("start_date"):
                primary.start_date = data.trip_inputs.start_date
            if _field_was_provided("end_date"):
                primary.end_date = data.trip_inputs.end_date
            if _field_was_provided("adults"):
                primary.adults = data.trip_inputs.adults
            if _field_was_provided("children"):
                primary.children = data.trip_inputs.children
            if _field_was_provided("requires_assistance"):
                primary.requires_assistance = data.trip_inputs.requires_assistance
            if _field_was_provided("budget"):
                primary.budget = data.trip_inputs.budget
            if _field_was_provided("currency"):
                primary.currency = data.trip_inputs.currency
            data.branches[primary_idx] = primary

    # Update preferences (heart-selected tiles) if provided
    if patch.preferred_tile_ids is not None:
        data.preferred_tile_ids = patch.preferred_tile_ids

    return await save_document_data(db, doc=doc, data=data, updated_by="user")


async def apply_planner_update(
    db: AsyncSession,
    *,
    doc: models.PlanDocument,
    trip_context_id: int,
    trip_inputs: Optional[DocumentTripInputs],
    branches: Optional[list[DocumentBranch]] = None,
    tiles: Optional[dict[str, TileSchema]] = None,
    # ViewModel fields - persisted for session restoration
    plan_view_state: Optional[PlanViewState] = None,
    strategy_sections: Optional[list[StrategySection]] = None,
    executed_strategy_topics: Optional[list[str]] = None,
    pending_strategy_topics: Optional[list[str]] = None,
    day_cards: Optional[list[DayCard]] = None,
    can_expand_to_itinerary: Optional[bool] = None,
    # NL-extracted settings that should bypass the user-owned field strip.
    # These are settings the user explicitly requested via chat (e.g. "5 star hotels").
    extracted_settings: Optional[dict[str, Any]] = None,
) -> models.PlanDocument:
    """
    Apply planner-generated branches, tiles, and viewModel state to the document (async).

    Most recent update wins - no field protection needed.
    Also persists viewModel fields (strategy_sections, day_cards, etc.) for session restoration.

    When trip_inputs change but no new branches are provided, the primary branch
    is updated to reflect the new trip parameters (destinations, origin, dates, etc).
    """
    # Refresh doc from DB to pick up concurrent writes (e.g., pill PATCHes
    # that committed during the graph run).  Without this, activity_settings
    # categories set via PATCH would be clobbered by the stale base doc.
    await db.refresh(doc)
    data = get_document_data(doc)

    # Update trip context
    data.trip_context_id = trip_context_id

    if trip_inputs:
        _debug(f"apply_planner_update: Incoming trip_inputs = {trip_inputs.model_dump()}")

    # User-owned settings fields — document is SSoT (set via PATCH from frontend
    # sheets). Graph output carries Pydantic defaults for these fields (e.g.
    # activity_settings=ActivitySettings(categories=[])) which must NOT overwrite
    # the user's PATCH values. Strip them so merge_trip_inputs preserves doc values.
    _USER_OWNED_SETTINGS = {
        "activity_settings",
        "hotel_settings",
        "flight_settings",
        "transport_settings",
        "booking_types",
    }
    cleaned_inputs: dict | None = None
    if trip_inputs:
        cleaned_inputs = _trip_inputs_to_dict(trip_inputs)
        for field in _USER_OWNED_SETTINGS:
            # Preserve activity_settings when it carries non-empty categories
            # (e.g. from NL extraction or prior-turn state). Other settings
            # are always stripped — document (via db.refresh) is SSoT.
            if field == "activity_settings":
                val = cleaned_inputs.get(field)
                if isinstance(val, dict) and val.get("categories"):
                    continue  # Non-empty categories — keep
            cleaned_inputs.pop(field, None)

    # Merge trip inputs - graph-owned fields only (user-owned stripped above)
    data.trip_inputs = merge_trip_inputs(
        data.trip_inputs,
        cleaned_inputs,
        replace_destinations=True,
    )

    # Deep-merge NL-extracted settings into the document's user-owned fields.
    # Unlike Pydantic defaults (which are stripped), these are values the user
    # explicitly requested via chat (e.g. "5 star hotels" → hotel_min_stars=5).
    if extracted_settings:
        if extracted_settings.get("hotel_min_stars") is not None:
            if data.trip_inputs.hotel_settings is None:
                data.trip_inputs.hotel_settings = HotelSettings()
            data.trip_inputs.hotel_settings.min_stars = extracted_settings["hotel_min_stars"]
        if extracted_settings.get("flight_direct_only") is not None:
            if data.trip_inputs.flight_settings is None:
                data.trip_inputs.flight_settings = FlightSettings()
            data.trip_inputs.flight_settings.direct_only = extracted_settings["flight_direct_only"]
        if extracted_settings.get("flight_cabin_class"):
            if data.trip_inputs.flight_settings is None:
                data.trip_inputs.flight_settings = FlightSettings()
            data.trip_inputs.flight_settings.cabin_class = extracted_settings["flight_cabin_class"]
        if extracted_settings.get("activity_skill_level"):
            if data.trip_inputs.activity_settings is None:
                data.trip_inputs.activity_settings = ActivitySettings()
            data.trip_inputs.activity_settings.skill_level = extracted_settings[
                "activity_skill_level"
            ]
        if extracted_settings.get("flights_toggle"):
            if data.trip_inputs.booking_types is None:
                data.trip_inputs.booking_types = BookingTypes()
            data.trip_inputs.booking_types.flights = extracted_settings["flights_toggle"]

    # Title-case destination for consistent display
    if data.trip_inputs.destination:
        data.trip_inputs.destination = data.trip_inputs.destination.title()

    # Merge branches (planner branches are added/updated) - only if provided
    if branches is not None:
        data.branches = merge_branches(data.branches, branches)
    elif trip_inputs is not None and data.branches:
        # No new branches but trip_inputs changed - update the primary branch
        # to reflect the new values so UI displays updated destination/dates/etc
        primary_idx = next(
            (i for i, b in enumerate(data.branches) if b.is_primary), 0 if data.branches else None
        )
        if primary_idx is not None:
            primary = data.branches[primary_idx]
            # Update branch parameters from trip_inputs
            # Always sync destination
            primary.destination = trip_inputs.destination
            if trip_inputs.origin is not None:
                primary.origin = trip_inputs.origin
            if trip_inputs.start_date is not None:
                primary.start_date = trip_inputs.start_date
            if trip_inputs.end_date is not None:
                primary.end_date = trip_inputs.end_date
            if trip_inputs.adults is not None:
                primary.adults = trip_inputs.adults
            if trip_inputs.children is not None:
                primary.children = trip_inputs.children
            if trip_inputs.requires_assistance is not None:
                primary.requires_assistance = trip_inputs.requires_assistance
            if trip_inputs.budget is not None:
                primary.budget = trip_inputs.budget
            if trip_inputs.currency is not None:
                primary.currency = trip_inputs.currency
            data.branches[primary_idx] = primary

    # Merge tiles - only if provided
    if tiles is not None:
        data.tiles = merge_tiles(data.tiles, tiles)

    # Persist viewModel fields for session restoration on refresh
    if plan_view_state is not None:
        data.plan_view_state = plan_view_state
    if strategy_sections is not None:
        data.strategy_sections = strategy_sections
    if executed_strategy_topics is not None:
        data.executed_strategy_topics = executed_strategy_topics
    if pending_strategy_topics is not None:
        data.pending_strategy_topics = pending_strategy_topics
    if day_cards is not None:
        data.day_cards = day_cards
    if can_expand_to_itinerary is not None:
        data.can_expand_to_itinerary = can_expand_to_itinerary

    return await save_document_data(db, doc=doc, data=data, updated_by="planner")


def apply_planner_update_sync(
    db: Session,
    *,
    doc: models.PlanDocument,
    trip_context_id: int,
    trip_inputs: Optional[DocumentTripInputs],
    branches: Optional[list[DocumentBranch]] = None,
    tiles: Optional[dict[str, TileSchema]] = None,
    # ViewModel fields - persisted for session restoration
    plan_view_state: Optional[PlanViewState] = None,
    strategy_sections: Optional[list[StrategySection]] = None,
    executed_strategy_topics: Optional[list[str]] = None,
    pending_strategy_topics: Optional[list[str]] = None,
    day_cards: Optional[list[DayCard]] = None,
    can_expand_to_itinerary: Optional[bool] = None,
) -> models.PlanDocument:
    """Apply planner-generated branches, tiles, and viewModel state to the document (sync).

    Mirrors apply_planner_update() but for sync SQLAlchemy sessions.
    Also persists viewModel fields (strategy_sections, day_cards, etc.) for session restoration.
    """
    db.refresh(doc)
    data = get_document_data(doc)

    # Update trip context
    data.trip_context_id = trip_context_id

    # User-owned settings fields — document is SSoT (set via PATCH from frontend
    # sheets). Strip them so merge_trip_inputs preserves doc values.
    _USER_OWNED_SETTINGS = {
        "activity_settings",
        "hotel_settings",
        "flight_settings",
        "transport_settings",
        "booking_types",
    }
    cleaned_inputs: dict | None = None
    if trip_inputs:
        cleaned_inputs = _trip_inputs_to_dict(trip_inputs)
        for field in _USER_OWNED_SETTINGS:
            # Preserve activity_settings when it carries non-empty categories
            # (e.g. from NL extraction or prior-turn state). Other settings
            # are always stripped — document (via db.refresh) is SSoT.
            if field == "activity_settings":
                val = cleaned_inputs.get(field)
                if isinstance(val, dict) and val.get("categories"):
                    continue  # Non-empty categories — keep
            cleaned_inputs.pop(field, None)

    # Merge trip inputs - graph-owned fields only (user-owned stripped above)
    data.trip_inputs = merge_trip_inputs(
        data.trip_inputs,
        cleaned_inputs,
        replace_destinations=True,
    )

    # Title-case destination for consistent display
    if data.trip_inputs.destination:
        data.trip_inputs.destination = data.trip_inputs.destination.title()

    # Merge branches (planner branches are added/updated) - only if provided
    if branches is not None:
        data.branches = merge_branches(data.branches, branches)
    elif trip_inputs is not None and data.branches:
        # No new branches but trip_inputs changed - update the primary branch
        primary_idx = next(
            (i for i, b in enumerate(data.branches) if b.is_primary), 0 if data.branches else None
        )
        if primary_idx is not None:
            primary = data.branches[primary_idx]
            primary.destination = trip_inputs.destination
            if trip_inputs.origin is not None:
                primary.origin = trip_inputs.origin
            if trip_inputs.start_date is not None:
                primary.start_date = trip_inputs.start_date
            if trip_inputs.end_date is not None:
                primary.end_date = trip_inputs.end_date
            if trip_inputs.adults is not None:
                primary.adults = trip_inputs.adults
            if trip_inputs.children is not None:
                primary.children = trip_inputs.children
            if trip_inputs.requires_assistance is not None:
                primary.requires_assistance = trip_inputs.requires_assistance
            if trip_inputs.budget is not None:
                primary.budget = trip_inputs.budget
            if trip_inputs.currency is not None:
                primary.currency = trip_inputs.currency
            data.branches[primary_idx] = primary

    # Merge tiles - only if provided
    if tiles is not None:
        data.tiles = merge_tiles(data.tiles, tiles)

    # Persist viewModel fields for session restoration on refresh
    if plan_view_state is not None:
        data.plan_view_state = plan_view_state
    if strategy_sections is not None:
        data.strategy_sections = strategy_sections
    if executed_strategy_topics is not None:
        data.executed_strategy_topics = executed_strategy_topics
    if pending_strategy_topics is not None:
        data.pending_strategy_topics = pending_strategy_topics
    if day_cards is not None:
        data.day_cards = day_cards
    if can_expand_to_itinerary is not None:
        data.can_expand_to_itinerary = can_expand_to_itinerary

    return save_document_data_sync(db, doc=doc, data=data, updated_by="planner")


async def add_tiles_to_branch(
    db: AsyncSession,
    *,
    doc: models.PlanDocument,
    branch_id: str,
    tiles: list[TileSchema],
    updated_by: UpdatedBy = "planner",
) -> models.PlanDocument:
    """
    Add tiles to a specific branch and update the document (async).
    Used when fetching tiles for a non-primary branch.
    """
    data = get_document_data(doc)

    # Find the branch
    branch_idx = next((i for i, b in enumerate(data.branches) if b.id == branch_id), None)
    if branch_idx is None:
        return doc  # Branch not found, no-op

    branch = data.branches[branch_idx]

    # Add tiles to document
    tiles_dict = {t.id: t for t in tiles}
    data.tiles = merge_tiles(data.tiles, tiles_dict)

    # Categorize tile IDs by type
    for tile in tiles:
        if tile.type == "hotel" and tile.id not in branch.tiles.stays:
            branch.tiles.stays.append(tile.id)
        elif tile.type == "flight" and tile.id not in branch.tiles.flights:
            branch.tiles.flights.append(tile.id)
        elif tile.type == "activity" and tile.id not in branch.tiles.activities:
            branch.tiles.activities.append(tile.id)

    data.branches[branch_idx] = branch

    return await save_document_data(db, doc=doc, data=data, updated_by=updated_by)
