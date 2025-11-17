import json
import os
from typing import List, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from app.schemas import Tile, TilesSearchRequest
from app.tile_service import search_tiles

_openai_client: Optional[OpenAI] = None


class PlanRequest(BaseModel):
    user_id: Optional[str] = None
    message: str

    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget_bucket: Optional[str] = None
    group_size: Optional[int] = None
    vibes: list[str] = Field(default_factory=list)


class PlanBranch(BaseModel):
    id: str
    label: str
    description: str
    destination: str


class PlanResponse(BaseModel):
    branches: List[PlanBranch]
    tiles: List[Tile]  # tiles for the primary branch
    primary_branch_id: Optional[str] = None
    tiles_request_id: Optional[str] = None
    tiles_summary: Optional[dict] = None


def _get_openai_client() -> Optional[OpenAI]:
    global _openai_client

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key)

    return _openai_client


def _mock_branches(req: PlanRequest) -> List[PlanBranch]:
    """Return deterministic mock branches so the flow works without OpenAI."""

    base_destinations = [
        ("Barcelona food & nightlife", "Barcelona, Spain"),
        ("Lisbon city break", "Lisbon, Portugal"),
        ("Valencia beach & paella", "Valencia, Spain"),
    ]

    branches: List[PlanBranch] = []
    for idx, (label, destination) in enumerate(base_destinations, start=1):
        branches.append(
            PlanBranch(
                id=f"mock_branch_{idx}",
                label=label,
                description=f"Idea #{idx} inspired by: {req.message[:80]}",
                destination=destination,
            )
        )

    return branches


def _build_user_prompt(req: PlanRequest) -> str:
    """Compact summary of user preferences for the LLM."""
    lines = [f"User message: {req.message}"]

    if req.origin:
        lines.append(f"Origin: {req.origin}")
    if req.start_date:
        lines.append(f"Start date: {req.start_date}")
    if req.end_date:
        lines.append(f"End date: {req.end_date}")
    if req.budget_bucket:
        lines.append(f"Budget: {req.budget_bucket}")
    if req.group_size:
        lines.append(f"Group size: {req.group_size}")
    if req.vibes:
        lines.append(f"Vibes: {', '.join(req.vibes)}")

    return "\n".join(lines)


def _call_openai_for_branches(req: PlanRequest) -> List[PlanBranch]:
    if os.getenv("PLAN_FORCE_MOCK", "0") == "1":
        return _mock_branches(req)

    system_prompt = (
        "You are a travel planner.\n"
        "Given the user's trip preferences, suggest 2/3 trip branches.\n\n"
        "Each branch is one destination idea. For each branch, provide:\n"
        "- id: a short opaque id (e.g. 'branch_1')\n"
        "- label: a short friendly label (e.g. 'Beach week in Barcelona')\n"
        "- description: 1/2 sentences summarising the idea\n"
        "- destination: a concise destination string (e.g. 'Barcelona, Spain').\n\n"
        "Return ONLY JSON with this shape:\n"
        "{\n"
        '  "branches": [\n'
        '    {"id": "branch_1", "label": "...", '
        '"description": "...", "destination": "..."},\n'
        "    ...\n"
        "  ]\n"
        "}\n"
        "No extra keys, no explanations, no markdown."
    )

    user_prompt = _build_user_prompt(req)

    # Chat Completions with JSON output (simple, robust)
    # :contentReference[oaicite:1]{index=1}
    client = _get_openai_client()
    if client is None:
        return _mock_branches(req)

    model = os.getenv("OPENAI_PLAN_MODEL", "gpt-5.1-mini")

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        # Keep the planner responsive even if OpenAI fails or API keys are missing.
        print(f"OpenAI planning call failed, using mock branches: {exc}")
        return _mock_branches(req)

    raw = completion.choices[0].message.content
    if raw is None:
        raw = '{"branches": []}'
    data = json.loads(raw)

    branches_raw = data.get("branches", [])
    branches: List[PlanBranch] = []

    for b in branches_raw:
        # Defensive; ignore malformed entries
        if not all(k in b for k in ("id", "label", "destination")):
            continue
        branches.append(
            PlanBranch(
                id=str(b["id"]),
                label=str(b["label"]),
                description=str(b.get("description", "")),
                destination=str(b["destination"]),
            )
        )

    if not branches:
        # Fallback: a generic branch so endpoint never totally fails
        branches = _mock_branches(req)

    return branches


def plan_trip(req: PlanRequest) -> PlanResponse:
    """The LLM contract is minimal: returns { "branches": [...] } with
    id/label/description/destination.

    We only use branch[0] to feed search_tiles, as per your step 5 spec.

    You can later persist PlanRequest → TripContext + Branch rows and map
    branch.id to DB IDs.
    """
    # 1) Get branches from LLM
    branches = _call_openai_for_branches(req)

    # 2) For now, pick the first branch as the "primary" branch
    primary = branches[0] if branches else None

    # 3) Call existing tile search layer with that destination
    destination = primary.destination if primary else req.origin

    tiles_request = TilesSearchRequest(
        origin=req.origin,
        destination=destination,
        start_date=req.start_date,
        end_date=req.end_date,
        budget_bucket=req.budget_bucket,
        group_size=req.group_size,
        vibes=req.vibes,
    )

    tiles_response = search_tiles(tiles_request)

    return PlanResponse(
        branches=branches,
        tiles=tiles_response.tiles,
        primary_branch_id=primary.id if primary else None,
        tiles_request_id=tiles_response.request_id,
        tiles_summary=tiles_response.summary,
    )
