import os
import sys
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import app.db_models as models  # noqa: E402  pylint: disable=C0413
from app.db import Base, get_db  # noqa: E402  pylint: disable=C0413
from app.main import app  # noqa: E402  pylint: disable=C0413

TEST_DB_PATH = BACKEND_DIR / "test_session_snapshot_pytest.db"
TEST_DATABASE_URL = f"sqlite+pysqlite:///{TEST_DB_PATH.as_posix()}"
engine = create_engine(
    TEST_DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_trip_with_branches(session_token: str = "session-123") -> dict:
    with TestingSessionLocal() as db:
        session = models.Session(session_token=session_token)
        db.add(session)
        db.flush()

        trip_ctx = models.TripContext(
            session_id=session.id,
            origin="AMS",
            destination_hint="Europe",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 10),
            budget_bucket="mid",
            group_size=2,
            vibes=["foodie", "culture"],
            raw_prompt="Some context",
        )
        db.add(trip_ctx)
        db.flush()

        primary_branch = models.Branch(
            trip_context_id=trip_ctx.id,
            label="Beach Escape",
            description="Relax on the coast",
            destination="Nice",
            is_primary=True,
        )
        secondary_branch = models.Branch(
            trip_context_id=trip_ctx.id,
            label="City Lights",
            description="Explore the city",
            destination="Paris",
            is_primary=False,
        )
        db.add_all([primary_branch, secondary_branch])
        db.flush()

        tile = models.Tile(
            type="hotel",
            partner="nomadic",
            partner_product_id="hotel-1",
            title="Seaside Hotel",
            subtitle="Cozy stay",
            image_url=None,
            price_estimate=120.0,
            currency="EUR",
            price_basis="per_night",
            is_estimate_only=True,
            deeplink_url="https://example.com/hotel",
            rating=4.5,
            review_count=120,
            tags=["beach"],
            location_label="Nice, France",
            meta={},
        )
        db.add(tile)
        db.flush()

        db.add(
            models.BranchTile(
                branch_id=primary_branch.id,
                tile_id=tile.id,
                position=0,
            )
        )

        db.commit()

        return {
            "session_token": session_token,
            "primary_branch_id": primary_branch.id,
            "secondary_branch_id": secondary_branch.id,
            "trip_context_id": trip_ctx.id,
        }


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def setup_module(_: object):  # noqa: D401
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def teardown_module(_: object):  # noqa: D401
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_session_snapshot_returns_branches_tiles_and_trip_context():
    seed = seed_trip_with_branches()

    response = client.get("/v1/session/snapshot", params={"session_id": seed["session_token"]})

    assert response.status_code == 200
    payload = response.json()

    assert payload["primary_branch_id"] == seed["primary_branch_id"]
    assert len(payload["branches"]) == 2
    assert payload["branches"][0]["label"] == "Beach Escape"
    assert payload["branches"][1]["destination"] == "Paris"

    assert payload["trip_context"]["origin"] == "AMS"
    assert payload["trip_context"]["budget_bucket"] == "mid"
    assert payload["trip_context"]["vibes"] == ["foodie", "culture"]
    assert payload["trip_context"]["id"] == seed["trip_context_id"]

    assert len(payload["tiles"]) == 1
    assert payload["tiles"][0]["title"] == "Seaside Hotel"


def test_session_snapshot_handles_missing_session():
    response = client.get("/v1/session/snapshot", params={"session_id": "missing"})

    assert response.status_code == 200
    payload = response.json()

    assert payload["branches"] == []
    assert payload["primary_branch_id"] is None
    assert payload["tiles"] == []
    assert payload["trip_context"] is None


def test_session_delete_wipes_state():
    seed = seed_trip_with_branches(session_token="session-reset-123")

    response = client.delete("/v1/session", params={"session_id": seed["session_token"]})

    assert response.status_code == 204

    with TestingSessionLocal() as db:
        session_row = (
            db.query(models.Session)
            .filter(models.Session.session_token == seed["session_token"])
            .first()
        )
        assert session_row is None

        trip_ctx = (
            db.query(models.TripContext)
            .filter(models.TripContext.id == seed["trip_context_id"])
            .first()
        )
        assert trip_ctx is None

        branches = (
            db.query(models.Branch)
            .filter(models.Branch.trip_context_id == seed["trip_context_id"])
            .all()
        )
        assert branches == []

    snapshot = client.get("/v1/session/snapshot", params={"session_id": seed["session_token"]})
    payload = snapshot.json()

    assert payload["branches"] == []
    assert payload["trip_context"] is None
