"""
Unit tests for crud_document.py -- CRDT-style merge operations and async CRUD.

Uses an async SQLite test database following the same pattern as
tests/db/test_share_and_auth_api.py.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.crud_document import (  # noqa: E402
    add_tiles_to_branch,
    apply_planner_update,
    apply_planner_update_sync,
    apply_user_patch_sync,
    get_document_data,
    get_or_create_document,
    merge_branches,
    merge_selections,
    merge_tiles,
    merge_trip_inputs,
    prune_branches_and_tiles,
    save_document_data,
    save_document_data_sync,
)
from app.db import Base  # noqa: E402
from app.db_models import PlanDocument  # noqa: E402
from app.db_models import Session as SessionModel  # noqa: E402
from app.schemas import (  # noqa: E402
    ActivitySettings,
    BookingTypes,
    BranchSelections,
    BranchTileIds,
    DocumentBranch,
    DocumentTripInputs,
    DocumentTripInputsPatch,
    PlanDocumentData,
    PlanDocumentPatch,
    StrategySection,
)
from app.schemas import Tile as TileSchema  # noqa: E402

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

TEST_DB_PATH = BACKEND_DIR / "test_crud_document_pytest.db"
TEST_DATABASE_URL = f"sqlite+pysqlite:///{TEST_DB_PATH.as_posix()}"

engine = create_engine(
    TEST_DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)
async_engine = create_async_engine(
    f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}",
    future=True,
    echo=False,
)
TestingAsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)
TestingSyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)


def setup_module(_: object) -> None:
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def teardown_module(_: object) -> None:
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    asyncio.run(async_engine.dispose())
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_row() -> SessionModel:
    """Insert a session row via the sync engine and return it."""
    from datetime import UTC, datetime, timedelta

    db = TestingSyncSessionLocal()
    sess = SessionModel(
        session_token=f"tok-{uuid.uuid4().hex}",
        last_activity_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    db.close()
    return sess


def _make_tile(tile_id: str, tile_type: str = "activity", **kw: Any) -> TileSchema:
    defaults = {"deeplink": f"https://example.com/{tile_id}", "title": tile_id}
    defaults.update(kw)
    return TileSchema(id=tile_id, type=tile_type, **defaults)


def _make_branch(
    branch_id: str = "b1",
    destination: str | None = "Tokyo",
    is_primary: bool = True,
    tile_ids: dict[str, list[str]] | None = None,
) -> DocumentBranch:
    tiles = BranchTileIds(
        stays=tile_ids.get("stays", []) if tile_ids else [],
        flights=tile_ids.get("flights", []) if tile_ids else [],
        activities=tile_ids.get("activities", []) if tile_ids else [],
    )
    return DocumentBranch(
        id=branch_id,
        label="Main",
        description="Primary branch",
        destination=destination,
        is_primary=is_primary,
        tiles=tiles,
    )


# ---------------------------------------------------------------------------
# Tests: merge_trip_inputs (pure function)
# ---------------------------------------------------------------------------


class TestMergeTripInputs:
    def test_none_incoming_returns_existing(self) -> None:
        existing = DocumentTripInputs(destination="Paris")
        result = merge_trip_inputs(existing, None)
        assert result.destination == "Paris"

    def test_empty_dict_returns_existing(self) -> None:
        existing = DocumentTripInputs(destination="Paris")
        result = merge_trip_inputs(existing, {})
        assert result.destination == "Paris"

    def test_merge_destination(self) -> None:
        existing = DocumentTripInputs(destination="Paris")
        result = merge_trip_inputs(existing, {"destination": "Tokyo"})
        assert result.destination == "Tokyo"

    def test_merge_preserves_unmentioned_fields(self) -> None:
        existing = DocumentTripInputs(destination="Paris", origin="NYC", adults=2)
        result = merge_trip_inputs(existing, {"budget": 5000})
        assert result.destination == "Paris"
        assert result.origin == "NYC"
        assert result.adults == 2
        assert result.budget == 5000

    def test_merge_with_document_trip_inputs_patch(self) -> None:
        existing = DocumentTripInputs(destination="Paris")
        patch = DocumentTripInputsPatch(origin="London")
        result = merge_trip_inputs(existing, patch)
        assert result.destination == "Paris"
        assert result.origin == "London"

    def test_explicit_null_clears_field(self) -> None:
        existing = DocumentTripInputs(destination="Paris", origin="NYC")
        result = merge_trip_inputs(existing, {}, explicit_nulls={"origin"})
        assert result.origin is None

    def test_explicit_null_resets_currency_to_default(self) -> None:
        existing = DocumentTripInputs(currency="EUR")
        result = merge_trip_inputs(existing, {}, explicit_nulls={"currency"})
        assert result.currency == "USD"

    def test_explicit_null_resets_date_flex_to_default(self) -> None:
        existing = DocumentTripInputs(date_flex=True)
        result = merge_trip_inputs(existing, {}, explicit_nulls={"date_flex"})
        assert result.date_flex is False

    def test_explicit_null_resets_booking_types_to_default(self) -> None:
        existing = DocumentTripInputs(booking_types=BookingTypes(flights="on", hotels="off"))
        result = merge_trip_inputs(existing, {}, explicit_nulls={"booking_types"})
        # Should be a fresh default BookingTypes
        assert result.booking_types.flights == "off"  # default
        assert result.booking_types.hotels == "suggested"  # default

    def test_missing_fields_recomputed(self) -> None:
        existing = DocumentTripInputs()
        result = merge_trip_inputs(existing, {"origin": "NYC"})
        assert "destination" in result.missing_fields
        assert "start_date" in result.missing_fields
        # origin is optional, not in missing_fields
        assert "origin" not in result.missing_fields

    def test_merge_booking_types_from_dict(self) -> None:
        existing = DocumentTripInputs()
        result = merge_trip_inputs(existing, {"booking_types": {"flights": "off"}})
        assert result.booking_types.flights == "off"

    def test_missing_fields_cleared_when_present(self) -> None:
        existing = DocumentTripInputs()
        result = merge_trip_inputs(existing, {"destination": "Bali", "start_date": "2025-06-01"})
        assert result.missing_fields == []


# ---------------------------------------------------------------------------
# Tests: merge_tiles (pure function)
# ---------------------------------------------------------------------------


class TestMergeTiles:
    def test_none_incoming_returns_existing(self) -> None:
        existing = {"t1": _make_tile("t1")}
        result = merge_tiles(existing, None)
        assert result is existing  # identity, not copy

    def test_merge_adds_new_tiles(self) -> None:
        existing = {"t1": _make_tile("t1")}
        incoming = {"t2": _make_tile("t2")}
        result = merge_tiles(existing, incoming)
        assert "t1" in result
        assert "t2" in result

    def test_merge_overwrites_existing_tile(self) -> None:
        existing = {"t1": _make_tile("t1", title="old")}
        incoming = {"t1": _make_tile("t1", title="new")}
        result = merge_tiles(existing, incoming)
        assert result["t1"].title == "new"

    def test_remove_ids(self) -> None:
        existing = {"t1": _make_tile("t1"), "t2": _make_tile("t2")}
        result = merge_tiles(existing, None, remove_ids=["t1"])
        assert "t1" not in result
        assert "t2" in result

    def test_remove_and_add_simultaneously(self) -> None:
        existing = {"t1": _make_tile("t1"), "t2": _make_tile("t2")}
        incoming = {"t3": _make_tile("t3")}
        result = merge_tiles(existing, incoming, remove_ids=["t1"])
        assert "t1" not in result
        assert "t2" in result
        assert "t3" in result

    def test_empty_collections(self) -> None:
        result = merge_tiles({}, {})
        assert result == {}

    def test_remove_nonexistent_id_is_noop(self) -> None:
        existing = {"t1": _make_tile("t1")}
        result = merge_tiles(existing, None, remove_ids=["nonexistent"])
        assert "t1" in result


# ---------------------------------------------------------------------------
# Tests: merge_branches (pure function)
# ---------------------------------------------------------------------------


class TestMergeBranches:
    def test_none_incoming_returns_existing(self) -> None:
        existing = [_make_branch("b1")]
        result = merge_branches(existing, None)
        assert result is existing

    def test_adds_new_branch(self) -> None:
        existing = [_make_branch("b1")]
        incoming = [_make_branch("b2", is_primary=False)]
        result = merge_branches(existing, incoming)
        assert len(result) == 2

    def test_updates_existing_branch(self) -> None:
        existing = [_make_branch("b1", destination="Paris")]
        incoming = [_make_branch("b1", destination="Tokyo")]
        result = merge_branches(existing, incoming)
        assert len(result) == 1
        assert result[0].destination == "Tokyo"

    def test_remove_ids(self) -> None:
        existing = [_make_branch("b1"), _make_branch("b2", is_primary=False)]
        result = merge_branches(existing, None, remove_ids=["b1"])
        assert len(result) == 1
        assert result[0].id == "b2"


# ---------------------------------------------------------------------------
# Tests: merge_selections (pure function)
# ---------------------------------------------------------------------------


class TestMergeSelections:
    def test_none_update_returns_existing(self) -> None:
        branches = [_make_branch("b1")]
        result = merge_selections(branches, None)
        assert result is branches

    def test_updates_selections_for_matching_branch(self) -> None:
        branches = [_make_branch("b1")]
        new_sel = BranchSelections(stay="hotel-1", flight="flight-1")
        result = merge_selections(branches, {"b1": new_sel})
        assert result[0].selections.stay == "hotel-1"
        assert result[0].selections.flight == "flight-1"

    def test_ignores_nonexistent_branch_id(self) -> None:
        branches = [_make_branch("b1")]
        new_sel = BranchSelections(stay="hotel-1")
        result = merge_selections(branches, {"nonexistent": new_sel})
        assert result[0].selections.stay is None


# ---------------------------------------------------------------------------
# Tests: prune_branches_and_tiles (pure function)
# ---------------------------------------------------------------------------


class TestPruneBranchesAndTiles:
    def test_empty_branches_noop(self) -> None:
        branches, tiles = prune_branches_and_tiles([], {}, "Tokyo")
        assert branches == []
        assert tiles == {}

    def test_matching_destination_keeps_everything(self) -> None:
        branch = _make_branch("b1", destination="Tokyo", tile_ids={"activities": ["t1"]})
        tiles = {"t1": _make_tile("t1")}
        result_b, result_t = prune_branches_and_tiles([branch], tiles, "Tokyo")
        assert len(result_b) == 1
        assert "t1" in result_t

    def test_mismatched_destination_prunes_branch_and_orphan_tiles(self) -> None:
        branch = _make_branch("b1", destination="Paris", tile_ids={"activities": ["t1"]})
        tiles = {"t1": _make_tile("t1"), "t2": _make_tile("t2")}
        result_b, result_t = prune_branches_and_tiles([branch], tiles, "Tokyo")
        assert len(result_b) == 0
        assert "t1" not in result_t
        assert "t2" not in result_t  # orphaned

    def test_case_insensitive_destination_match(self) -> None:
        branch = _make_branch("b1", destination="tokyo")
        result_b, _ = prune_branches_and_tiles([branch], {}, "TOKYO")
        assert len(result_b) == 1


# ---------------------------------------------------------------------------
# Tests: async CRUD — get_or_create_document, save, get_document_data
# ---------------------------------------------------------------------------


class TestAsyncCRUD:
    def test_get_or_create_creates_new(self) -> None:
        sess_row = _make_session_row()

        async def _run() -> PlanDocument:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                await db.commit()
                return doc

        doc = asyncio.run(_run())
        assert doc.session_id == sess_row.id
        assert doc.version == 1
        assert doc.updated_by == "planner"

    def test_get_or_create_returns_existing(self) -> None:
        sess_row = _make_session_row()

        async def _run() -> tuple[int, int]:
            async with TestingAsyncSessionLocal() as db:
                doc1 = await get_or_create_document(db, session=sess_row)
                await db.commit()
                id1 = doc1.id
            async with TestingAsyncSessionLocal() as db:
                doc2 = await get_or_create_document(db, session=sess_row)
                await db.commit()
                id2 = doc2.id
            return id1, id2

        id1, id2 = asyncio.run(_run())
        assert id1 == id2

    def test_save_document_data_increments_version(self) -> None:
        sess_row = _make_session_row()

        async def _run() -> int:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                data = PlanDocumentData(trip_inputs=DocumentTripInputs(destination="Bali"))
                doc = await save_document_data(db, doc=doc, data=data, updated_by="user")
                await db.commit()
                return doc.version

        version = asyncio.run(_run())
        assert version == 2

    def test_get_document_data_roundtrip(self) -> None:
        sess_row = _make_session_row()

        async def _run() -> PlanDocumentData:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                data = PlanDocumentData(
                    trip_inputs=DocumentTripInputs(destination="Rome", origin="NYC", adults=3)
                )
                await save_document_data(db, doc=doc, data=data, updated_by="planner")
                await db.commit()
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                return get_document_data(doc)

        result = asyncio.run(_run())
        assert result.trip_inputs.destination == "Rome"
        assert result.trip_inputs.origin == "NYC"
        assert result.trip_inputs.adults == 3


# ---------------------------------------------------------------------------
# Tests: sync save
# ---------------------------------------------------------------------------


class TestSyncSave:
    def test_save_document_data_sync(self) -> None:
        sess_row = _make_session_row()

        # Create doc via async first
        async def _create() -> int:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                await db.commit()
                return doc.id

        doc_id = asyncio.run(_create())

        # Now update via sync
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        assert doc is not None
        data = PlanDocumentData(trip_inputs=DocumentTripInputs(destination="Kyoto"))
        doc = save_document_data_sync(db, doc=doc, data=data, updated_by="user")
        db.commit()
        assert doc.version == 2
        assert doc.updated_by == "user"

        reloaded = get_document_data(doc)
        assert reloaded.trip_inputs.destination == "Kyoto"
        db.close()


# ---------------------------------------------------------------------------
# Tests: apply_user_patch_sync
# ---------------------------------------------------------------------------


class TestApplyUserPatchSync:
    def _setup_doc(self) -> tuple[int, int]:
        """Create a session + doc with initial data, return (session_id, doc_id)."""
        sess_row = _make_session_row()

        async def _create() -> int:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                data = PlanDocumentData(
                    trip_inputs=DocumentTripInputs(destination="Tokyo", origin="NYC", adults=2),
                    branches=[_make_branch("b1", destination="Tokyo")],
                )
                await save_document_data(db, doc=doc, data=data, updated_by="planner")
                await db.commit()
                return doc.id

        doc_id = asyncio.run(_create())
        return sess_row.id, doc_id

    def test_patch_updates_trip_inputs(self) -> None:
        _, doc_id = self._setup_doc()
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        patch = PlanDocumentPatch(
            version=doc.version,
            trip_inputs=DocumentTripInputsPatch(budget=3000),
        )
        doc = apply_user_patch_sync(db, doc=doc, patch=patch)
        db.commit()
        data = get_document_data(doc)
        assert data.trip_inputs.budget == 3000
        assert data.trip_inputs.destination == "Tokyo"  # preserved
        db.close()

    def test_patch_destination_change_clears_day_cards(self) -> None:
        sess_row = _make_session_row()

        async def _create() -> int:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                from app.schemas import DayCard

                data = PlanDocumentData(
                    trip_inputs=DocumentTripInputs(destination="Tokyo"),
                    day_cards=[DayCard(day_number=1, label="Day 1")],
                )
                await save_document_data(db, doc=doc, data=data, updated_by="planner")
                await db.commit()
                return doc.id

        doc_id = asyncio.run(_create())
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        patch = PlanDocumentPatch(
            version=doc.version,
            trip_inputs=DocumentTripInputsPatch(destination="Paris"),
        )
        doc = apply_user_patch_sync(db, doc=doc, patch=patch)
        db.commit()
        data = get_document_data(doc)
        assert data.trip_inputs.destination == "Paris"
        assert data.day_cards == []  # cleared on destination change
        db.close()

    def test_patch_preferred_tile_ids(self) -> None:
        _, doc_id = self._setup_doc()
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        patch = PlanDocumentPatch(version=doc.version, preferred_tile_ids=["t1", "t2"])
        doc = apply_user_patch_sync(db, doc=doc, patch=patch)
        db.commit()
        data = get_document_data(doc)
        assert data.preferred_tile_ids == ["t1", "t2"]
        db.close()


# ---------------------------------------------------------------------------
# Tests: apply_planner_update_sync
# ---------------------------------------------------------------------------


class TestApplyPlannerUpdateSync:
    def _setup_doc(self) -> tuple[SessionModel, int]:
        sess_row = _make_session_row()

        async def _create() -> int:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                data = PlanDocumentData(
                    trip_inputs=DocumentTripInputs(
                        destination="Tokyo",
                        activity_settings=ActivitySettings(categories=["diving"]),
                    ),
                )
                await save_document_data(db, doc=doc, data=data, updated_by="planner")
                await db.commit()
                return doc.id

        doc_id = asyncio.run(_create())
        return sess_row, doc_id

    def test_planner_update_sets_trip_context(self) -> None:
        _, doc_id = self._setup_doc()
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        doc = apply_planner_update_sync(
            db,
            doc=doc,
            trip_context_id=42,
            trip_inputs=DocumentTripInputs(destination="Tokyo"),
        )
        db.commit()
        data = get_document_data(doc)
        assert data.trip_context_id == 42
        db.close()

    def test_planner_update_strips_user_owned_settings(self) -> None:
        """Graph output with default activity_settings should NOT overwrite doc categories."""
        _, doc_id = self._setup_doc()
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        # Planner sends default (empty) activity_settings -- should be stripped
        doc = apply_planner_update_sync(
            db,
            doc=doc,
            trip_context_id=1,
            trip_inputs=DocumentTripInputs(
                destination="Tokyo",
                activity_settings=ActivitySettings(categories=[]),
            ),
        )
        db.commit()
        data = get_document_data(doc)
        # Doc's categories should be preserved (not overwritten to empty)
        assert data.trip_inputs.activity_settings.categories == ["diving"]
        db.close()

    def test_planner_update_extracted_settings(self) -> None:
        _, doc_id = self._setup_doc()
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        doc = apply_planner_update_sync(
            db,
            doc=doc,
            trip_context_id=1,
            trip_inputs=DocumentTripInputs(destination="Tokyo"),
            extracted_settings={"hotel_min_stars": 4, "flight_direct_only": True},
        )
        db.commit()
        data = get_document_data(doc)
        assert data.trip_inputs.hotel_settings.min_stars == 4
        assert data.trip_inputs.flight_settings.direct_only is True
        db.close()

    def test_planner_update_view_model_fields(self) -> None:
        _, doc_id = self._setup_doc()
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        sections = [
            StrategySection(id="s1", title="Diving", subtitle="Great spots"),
        ]
        doc = apply_planner_update_sync(
            db,
            doc=doc,
            trip_context_id=1,
            trip_inputs=None,
            strategy_sections=sections,
            can_expand_to_itinerary=True,
            plan_view_state="S2_STRATEGY_READY",
        )
        db.commit()
        data = get_document_data(doc)
        assert len(data.strategy_sections) == 1
        assert data.strategy_sections[0].id == "s1"
        assert data.can_expand_to_itinerary is True
        assert data.plan_view_state == "S2_STRATEGY_READY"
        db.close()

    def test_planner_update_title_cases_destination(self) -> None:
        _, doc_id = self._setup_doc()
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        doc = apply_planner_update_sync(
            db,
            doc=doc,
            trip_context_id=1,
            trip_inputs=DocumentTripInputs(destination="bali"),
        )
        db.commit()
        data = get_document_data(doc)
        assert data.trip_inputs.destination == "Bali"
        db.close()

    def test_planner_update_replace_tiles(self) -> None:
        _, doc_id = self._setup_doc()
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        # First, add some tiles
        doc = apply_planner_update_sync(
            db,
            doc=doc,
            trip_context_id=1,
            trip_inputs=None,
            tiles={"t1": _make_tile("t1"), "t2": _make_tile("t2")},
        )
        db.commit()
        # Now replace_tiles should drop t1/t2
        doc = apply_planner_update_sync(
            db,
            doc=doc,
            trip_context_id=1,
            trip_inputs=None,
            tiles={"t3": _make_tile("t3")},
            replace_tiles=True,
        )
        db.commit()
        data = get_document_data(doc)
        assert "t1" not in data.tiles
        assert "t3" in data.tiles
        db.close()

    def test_reset_trip_inputs(self) -> None:
        _, doc_id = self._setup_doc()
        db = TestingSyncSessionLocal()
        doc = db.get(PlanDocument, doc_id)
        doc = apply_planner_update_sync(
            db,
            doc=doc,
            trip_context_id=1,
            trip_inputs=DocumentTripInputs(destination="Rome"),
            reset_trip_inputs=True,
        )
        db.commit()
        data = get_document_data(doc)
        assert data.trip_inputs.destination == "Rome"
        # Previous activity_settings should be gone (reset)
        assert data.trip_inputs.activity_settings.categories == []
        db.close()


# ---------------------------------------------------------------------------
# Tests: add_tiles_to_branch (async)
# ---------------------------------------------------------------------------


class TestAddTilesToBranch:
    def test_adds_tiles_to_matching_branch(self) -> None:
        sess_row = _make_session_row()

        async def _run() -> PlanDocumentData:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                data = PlanDocumentData(
                    branches=[_make_branch("b1")],
                )
                await save_document_data(db, doc=doc, data=data, updated_by="planner")
                await db.commit()

            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                tiles = [
                    _make_tile("h1", "hotel"),
                    _make_tile("a1", "activity"),
                    _make_tile("f1", "flight"),
                ]
                doc = await add_tiles_to_branch(db, doc=doc, branch_id="b1", tiles=tiles)
                await db.commit()
                return get_document_data(doc)

        data = asyncio.run(_run())
        assert "h1" in data.tiles
        assert "a1" in data.tiles
        assert "f1" in data.tiles
        branch = data.branches[0]
        assert "h1" in branch.tiles.stays
        assert "a1" in branch.tiles.activities
        assert "f1" in branch.tiles.flights

    def test_nonexistent_branch_is_noop(self) -> None:
        sess_row = _make_session_row()

        async def _run() -> PlanDocumentData:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                data = PlanDocumentData(branches=[_make_branch("b1")])
                await save_document_data(db, doc=doc, data=data, updated_by="planner")
                await db.commit()

            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                tiles = [_make_tile("h1", "hotel")]
                doc = await add_tiles_to_branch(db, doc=doc, branch_id="nonexistent", tiles=tiles)
                await db.commit()
                return get_document_data(doc)

        data = asyncio.run(_run())
        # No tiles should be added since branch was not found
        assert "h1" not in data.tiles


# ---------------------------------------------------------------------------
# Tests: async apply_planner_update tile persistence (expand-path regression)
# ---------------------------------------------------------------------------


class TestApplyPlannerUpdateTilePersistence:
    """Documents the helper contract the expand-path fix depends on.

    These tests exercise apply_planner_update (the helper) directly, NOT the
    streaming.generate_ndjson call site -- the call-site regression itself is
    guarded end-to-end by
    test_expand_itinerary_persist_replaces_pool_after_unbookable_prune in
    tests/db/test_plan_document_api.py.

    Contract: the expand path pops dropped unbookable-specialist tile ids from the
    complete tiles pool, then persists. If the persist does NOT pass
    replace_tiles=True, merge_tiles only adds/updates keys and never removes, so a
    dropped id -- merely ABSENT from the payload -- survives in the saved doc and
    resurfaces on reload (orphan map pins / browse ghosts). These tests show
    replace_tiles=True evicts the absent id while a merge (replace_tiles=False)
    does NOT.
    """

    def _setup_doc_with_full_pool(self) -> tuple[SessionModel, int]:
        """Seed a complete activity+hotel+flight pool, return (session, doc_id)."""
        sess_row = _make_session_row()

        async def _create() -> int:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                data = PlanDocumentData(
                    trip_inputs=DocumentTripInputs(destination="Bali"),
                    tiles={
                        "spec_drop": _make_tile("spec_drop", "activity"),
                        "spec_keep": _make_tile("spec_keep", "activity"),
                        "hotel_1": _make_tile("hotel_1", "hotel"),
                        "flight_1": _make_tile("flight_1", "flight"),
                    },
                )
                await save_document_data(db, doc=doc, data=data, updated_by="planner")
                await db.commit()
                return doc.id

        doc_id = asyncio.run(_create())
        return sess_row, doc_id

    def test_replace_tiles_true_evicts_dropped_id_keeps_full_pool(self) -> None:
        """replace_tiles=True with a complete pool MINUS a dropped id removes it."""
        sess_row, doc_id = self._setup_doc_with_full_pool()

        # Mirror the expand persist: build the complete pool, pop the dropped id,
        # persist with replace_tiles=True (tiles_refreshed analog).
        full_pool_minus_dropped = {
            "spec_keep": _make_tile("spec_keep", "activity"),
            "hotel_1": _make_tile("hotel_1", "hotel"),
            "flight_1": _make_tile("flight_1", "flight"),
        }

        async def _run() -> PlanDocumentData:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                await apply_planner_update(
                    db,
                    doc=doc,
                    trip_context_id=1,
                    trip_inputs=None,
                    tiles=full_pool_minus_dropped,
                    replace_tiles=True,
                )
                await db.commit()
            # Reload from a fresh session to assert persisted state.
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                return get_document_data(doc)

        data = asyncio.run(_run())
        assert "spec_drop" not in data.tiles  # dropped id is gone on reload
        assert "spec_keep" in data.tiles
        assert "hotel_1" in data.tiles  # non-activity tiles survive the replace
        assert "flight_1" in data.tiles
        assert set(data.tiles.keys()) == {"spec_keep", "hotel_1", "flight_1"}

    def test_merge_only_leaves_dropped_id_proving_gate_matters(self) -> None:
        """Without replace_tiles (merge), the dropped id LINGERS -- the bug."""
        sess_row, doc_id = self._setup_doc_with_full_pool()

        full_pool_minus_dropped = {
            "spec_keep": _make_tile("spec_keep", "activity"),
            "hotel_1": _make_tile("hotel_1", "hotel"),
            "flight_1": _make_tile("flight_1", "flight"),
        }

        async def _run() -> PlanDocumentData:
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                await apply_planner_update(
                    db,
                    doc=doc,
                    trip_context_id=1,
                    trip_inputs=None,
                    tiles=full_pool_minus_dropped,
                    replace_tiles=False,  # the pre-fix behavior
                )
                await db.commit()
            async with TestingAsyncSessionLocal() as db:
                doc = await get_or_create_document(db, session=sess_row)
                return get_document_data(doc)

        data = asyncio.run(_run())
        # The merge keeps the dropped id around -- this is the helper behavior the
        # expand persist site avoids by passing replace_tiles=tiles_refreshed.
        assert "spec_drop" in data.tiles
