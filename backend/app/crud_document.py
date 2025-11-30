"""
CRUD operations for the centralized PlanDocument.
Uses CRDT-style merge for conflict resolution.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app import db_models as models
from app.schemas import (
    BranchSelections,
    DocumentBranch,
    DocumentTripInputs,
    PlanDocumentData,
    PlanDocumentPatch,
    UpdatedBy,
)
from app.schemas import (
    Tile as TileSchema,
)


def get_document(db: Session, *, session: models.Session) -> Optional[models.PlanDocument]:
    """Fetch the plan document for a session."""
    return (
        db.query(models.PlanDocument).filter(models.PlanDocument.session_id == session.id).first()
    )


def get_or_create_document(
    db: Session,
    *,
    session: models.Session,
    updated_by: UpdatedBy = "planner",
) -> models.PlanDocument:
    """Get existing document or create an empty one."""
    doc = get_document(db, session=session)
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
    db.flush()
    return doc


def get_document_data(doc: models.PlanDocument) -> PlanDocumentData:
    """Parse the JSON document into a Pydantic model."""
    return PlanDocumentData.model_validate(doc.document)


def save_document_data(
    db: Session,
    *,
    doc: models.PlanDocument,
    data: PlanDocumentData,
    updated_by: UpdatedBy,
) -> models.PlanDocument:
    """Save updated document data, incrementing version."""
    doc.document = data.model_dump()
    doc.version += 1
    doc.updated_by = updated_by
    db.flush()
    return doc


# ─────────────────────────────────────────────────────────────────────────────
# CRDT-style Merge Operations
# ─────────────────────────────────────────────────────────────────────────────


def merge_trip_inputs(
    existing: DocumentTripInputs,
    incoming: Optional[DocumentTripInputs],
    *,
    replace_destinations: bool = False,
) -> DocumentTripInputs:
    """
    Merge trip inputs: incoming values override existing values when provided.

    Args:
        existing: The current trip inputs in the document.
        incoming: New trip inputs to merge in.
        replace_destinations: If True, incoming destinations replace existing
                              ones entirely. If False (default), destinations
                              are merged (union). The planner should set this
                              to True to allow users to reduce destinations.

    Returns:
        Merged DocumentTripInputs with incoming values taking precedence.
    """
    if not incoming:
        return existing

    # Handle destinations - either replace or merge based on flag
    if replace_destinations:
        # Replace: use incoming destinations directly (allows reducing the list)
        # Always use incoming.destinations, even if it's an empty list
        merged_destinations = incoming.destinations
    else:
        # Merge: union of both lists (for user patches that add destinations)
        existing_destinations = set(existing.destinations or [])
        incoming_destinations = set(incoming.destinations or [])
        merged_destinations = list(existing_destinations | incoming_destinations)
        if not merged_destinations:
            merged_destinations = existing.destinations

    # For other fields, incoming takes precedence when it's not None
    # Use explicit None checks so that 0, False, empty string can be set
    return DocumentTripInputs(
        destinations=merged_destinations,
        origin=incoming.origin if incoming.origin is not None else existing.origin,
        start_date=incoming.start_date if incoming.start_date is not None else existing.start_date,
        end_date=incoming.end_date if incoming.end_date is not None else existing.end_date,
        traveler_count=(
            incoming.traveler_count
            if incoming.traveler_count is not None
            else existing.traveler_count
        ),
        budget=incoming.budget if incoming.budget is not None else existing.budget,
        missing_fields=(
            incoming.missing_fields
            if incoming.missing_fields is not None
            else existing.missing_fields
        ),
    )


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


# ─────────────────────────────────────────────────────────────────────────────
# High-Level Operations
# ─────────────────────────────────────────────────────────────────────────────


def apply_user_patch(
    db: Session,
    *,
    doc: models.PlanDocument,
    patch: PlanDocumentPatch,
) -> models.PlanDocument:
    """
    Apply a user-initiated patch to the document using CRDT merge.
    """
    data = get_document_data(doc)

    # Merge trip inputs
    data.trip_inputs = merge_trip_inputs(data.trip_inputs, patch.trip_inputs)

    # Merge branches
    data.branches = merge_branches(data.branches, patch.branches, patch.remove_branch_ids)

    # Merge tiles
    data.tiles = merge_tiles(data.tiles, patch.tiles, patch.remove_tile_ids)

    # Update selections
    data.branches = merge_selections(data.branches, patch.selections)

    return save_document_data(db, doc=doc, data=data, updated_by="user")


def apply_planner_update(
    db: Session,
    *,
    doc: models.PlanDocument,
    trip_context_id: int,
    trip_inputs: Optional[DocumentTripInputs],
    branches: Optional[list[DocumentBranch]] = None,
    tiles: Optional[dict[str, TileSchema]] = None,
) -> models.PlanDocument:
    """
    Apply planner-generated branches and tiles to the document.
    Planner updates replace destinations to allow users to modify their list.
    Can be called with only trip_inputs during collection phase.

    When trip_inputs change but no new branches are provided, the primary branch
    is updated to reflect the new trip parameters (destinations, origin, dates, etc).
    This ensures LLM modifications cascade to the visible branch immediately.
    """
    data = get_document_data(doc)

    # Update trip context
    data.trip_context_id = trip_context_id

    # Merge trip inputs - planner uses replace_destinations=True so users can modify destinations
    data.trip_inputs = merge_trip_inputs(data.trip_inputs, trip_inputs, replace_destinations=True)

    # Merge branches (planner branches are added/updated) - only if provided
    if branches is not None:
        data.branches = merge_branches(data.branches, branches)
    elif trip_inputs is not None and data.branches:
        # No new branches but trip_inputs changed - update the primary branch
        # to reflect the new values so UI displays updated destinations/dates/etc
        primary_idx = next(
            (i for i, b in enumerate(data.branches) if b.is_primary), 0 if data.branches else None
        )
        if primary_idx is not None:
            primary = data.branches[primary_idx]
            # Update branch parameters from trip_inputs
            # Always sync destinations, even if empty (user may have removed all)
            primary.destinations = trip_inputs.destinations
            if trip_inputs.origin is not None:
                primary.origin = trip_inputs.origin
            if trip_inputs.start_date is not None:
                primary.start_date = trip_inputs.start_date
            if trip_inputs.end_date is not None:
                primary.end_date = trip_inputs.end_date
            if trip_inputs.traveler_count is not None:
                primary.traveler_count = trip_inputs.traveler_count
            if trip_inputs.budget is not None:
                primary.budget = trip_inputs.budget
            data.branches[primary_idx] = primary

    # Merge tiles - only if provided
    if tiles is not None:
        data.tiles = merge_tiles(data.tiles, tiles)

    return save_document_data(db, doc=doc, data=data, updated_by="planner")


def add_tiles_to_branch(
    db: Session,
    *,
    doc: models.PlanDocument,
    branch_id: str,
    tiles: list[TileSchema],
    updated_by: UpdatedBy = "planner",
) -> models.PlanDocument:
    """
    Add tiles to a specific branch and update the document.
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

    return save_document_data(db, doc=doc, data=data, updated_by=updated_by)
