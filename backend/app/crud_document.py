"""
CRUD operations for the centralized PlanDocument.
Uses CRDT-style merge for conflict resolution.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app import db_models as models
from app.schemas import (
    BranchSelections,
    DocumentBranch,
    DocumentTripInputs,
    DocumentTripInputsPatch,
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
    preserve_fields: Optional[set[str]] = None,
) -> DocumentTripInputs:
    """
    Merge trip inputs: incoming values override existing values when provided.

    Works with both full DocumentTripInputs payloads and partial patches.
    """

    incoming_data = _trip_inputs_to_dict(incoming)
    if not incoming_data:
        return existing

    sentinel = object()
    preserve = preserve_fields or set()

    def _get_value(key: str):
        return incoming_data.get(key, sentinel)

    dest_value = _get_value("destinations")
    if "destinations" in preserve:
        merged_destinations = existing.destinations
    elif dest_value is sentinel:
        merged_destinations = existing.destinations
    elif replace_destinations:
        merged_destinations = dest_value or []
    else:
        existing_destinations = set(existing.destinations or [])
        incoming_destinations = set(dest_value or [])
        merged_destinations = list(existing_destinations | incoming_destinations)
        if not merged_destinations:
            merged_destinations = existing.destinations

    origin = _get_value("origin") if "origin" not in preserve else sentinel
    start_date = _get_value("start_date") if "start_date" not in preserve else sentinel
    end_date = _get_value("end_date") if "end_date" not in preserve else sentinel
    traveler_count = _get_value("traveler_count") if "traveler_count" not in preserve else sentinel
    budget = _get_value("budget") if "budget" not in preserve else sentinel
    missing_fields = _get_value("missing_fields") if "missing_fields" not in preserve else sentinel
    multi_city_intent = (
        _get_value("multi_city_intent") if "multi_city_intent" not in preserve else sentinel
    )
    vibes = _get_value("vibes") if "vibes" not in preserve else sentinel

    return DocumentTripInputs(
        destinations=merged_destinations,
        origin=origin if origin is not sentinel else existing.origin,
        start_date=start_date if start_date is not sentinel else existing.start_date,
        end_date=end_date if end_date is not sentinel else existing.end_date,
        traveler_count=(
            traveler_count if traveler_count is not sentinel else existing.traveler_count
        ),
        budget=budget if budget is not sentinel else existing.budget,
        missing_fields=(
            []
            if missing_fields is None
            else missing_fields if missing_fields is not sentinel else existing.missing_fields
        ),
        multi_city_intent=(
            multi_city_intent if multi_city_intent is not sentinel else existing.multi_city_intent
        ),
        vibes=([] if vibes is None else vibes if vibes is not sentinel else existing.vibes),
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

    When trip_inputs change (e.g., user removes a destination), the primary branch
    is updated to reflect the new values so UI displays updated destinations.
    """
    data = get_document_data(doc)

    # Merge trip inputs - use replace_destinations=True so users can remove destinations
    data.trip_inputs = merge_trip_inputs(
        data.trip_inputs, patch.trip_inputs, replace_destinations=True
    )

    # Merge branches
    data.branches = merge_branches(data.branches, patch.branches, patch.remove_branch_ids)

    # Merge tiles
    data.tiles = merge_tiles(data.tiles, patch.tiles, patch.remove_tile_ids)

    # Update selections
    data.branches = merge_selections(data.branches, patch.selections)

    # Cascade trip_inputs changes to the primary branch
    # This ensures destination removals are reflected in the branch
    if patch.trip_inputs is not None and data.branches:
        primary_idx = next(
            (i for i, b in enumerate(data.branches) if b.is_primary), 0 if data.branches else None
        )
        if primary_idx is not None:
            primary = data.branches[primary_idx]
            # Always sync destinations (including empty list for removals)
            primary.destinations = data.trip_inputs.destinations

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
            if _field_was_provided("traveler_count"):
                primary.traveler_count = data.trip_inputs.traveler_count
            if _field_was_provided("budget"):
                primary.budget = data.trip_inputs.budget
            data.branches[primary_idx] = primary

    return save_document_data(db, doc=doc, data=data, updated_by="user")


def apply_planner_update(
    db: Session,
    *,
    doc: models.PlanDocument,
    trip_context_id: int,
    trip_inputs: Optional[DocumentTripInputs],
    branches: Optional[list[DocumentBranch]] = None,
    tiles: Optional[dict[str, TileSchema]] = None,
    preserve_fields: Optional[set[str]] = None,
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
    data.trip_inputs = merge_trip_inputs(
        data.trip_inputs,
        trip_inputs,
        replace_destinations=True,
        preserve_fields=preserve_fields,
    )

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
