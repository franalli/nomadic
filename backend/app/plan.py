import json
import os
from typing import List, Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from app.crud_trip import (
    create_branches_for_context,
    create_trip_context,
    get_or_create_session,
    snapshot_tiles_for_branch,
)
from app.schemas import (
    PlanBranch,
    PlanRequest,
    PlanResponse,
    TilesSearchRequest,
)
from app.tile_service import search_tiles

_openai_client: Optional[OpenAI] = None
_DEFAULT_PLAN_MODELS: List[str] = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
]


def _get_openai_client() -> Optional[OpenAI]:
    global _openai_client

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key)

    return _openai_client


def _mock_branch_specs(req: PlanRequest) -> List[dict]:
    """Return deterministic mock branches so the flow works without OpenAI."""

    base_destinations = [
        ("Barcelona food & nightlife", "Barcelona, Spain"),
        ("Lisbon city break", "Lisbon, Portugal"),
        ("Valencia beach & paella", "Valencia, Spain"),
    ]

    branches: List[dict] = []
    for idx, (label, destination) in enumerate(base_destinations, start=1):
        branches.append(
            {
                "label": label,
                "description": f"Idea #{idx} inspired by: {req.message[:80]}",
                "destination": destination,
            }
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


def _plan_model_candidates() -> List[str]:
    """Return preferred OpenAI models, honoring env overrides with safe fallbacks."""

    configured_raw = os.getenv("OPENAI_PLAN_MODEL", "").strip()
    configured: List[str] = []
    if configured_raw:
        configured = [model.strip() for model in configured_raw.split(",") if model.strip()]

    candidates: List[str] = []
    for model in configured + _DEFAULT_PLAN_MODELS:
        if model not in candidates:
            candidates.append(model)

    return candidates


def _is_model_missing_error(exc: Exception) -> bool:
    """Detect the common 'model not found' error so we can retry with fallbacks."""

    message = str(exc).lower()
    return "model_not_found" in message or "does not exist" in message


def _call_openai_for_branches_raw(req: PlanRequest) -> List[dict]:
    if os.getenv("PLAN_FORCE_MOCK", "0") == "1":
        return _mock_branch_specs(req)

    system_prompt = (
        "You are a travel planner.\n"
        "Given the user's trip preferences, suggest 2–3 trip branches.\n\n"
        "Each branch is one destination idea. For each branch, provide:\n"
        "- label: a short friendly label (e.g. 'Beach week in Barcelona')\n"
        "- description: 1–2 sentences summarising the idea\n"
        "- destination: a concise destination string (e.g. 'Barcelona, Spain').\n\n"
        "Return ONLY JSON with this shape:\n"
        "{\n"
        '  "branches": [\n'
        '    {"label": "...", "description": "...", "destination": "..."},\n'
        "    ...\n"
        "  ]\n"
        "}\n"
        "No extra keys, no explanations, no markdown."
    )

    user_prompt = _build_user_prompt(req)

    client = _get_openai_client()
    if client is None:
        return _mock_branch_specs(req)

    last_error: Exception | None = None

    for model_name in _plan_model_candidates():
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # pragma: no cover - depends on OpenAI availability
            last_error = exc
            if _is_model_missing_error(exc):
                print(f"OpenAI model '{model_name}' unavailable, trying fallback: {exc}")
                continue

            print(f"OpenAI planning call failed with '{model_name}': {exc}")
            break

        raw = completion.choices[0].message.content
        data = json.loads(raw or '{"branches": []}')
        branches_raw = data.get("branches", []) or []

        cleaned: List[dict] = []
        for b in branches_raw:
            if not all(k in b for k in ("label", "destination")):
                continue
            cleaned.append(
                {
                    "label": str(b["label"]),
                    "description": str(b.get("description", "")),
                    "destination": str(b["destination"]),
                }
            )

        if cleaned:
            return cleaned

        print(f"OpenAI planning call with '{model_name}' returned no usable branches; falling back")

    if last_error is not None:
        print(f"OpenAI planning call failed, using mock branches: {last_error}")

    return _mock_branch_specs(req)


def plan_trip(db: Session, req: PlanRequest) -> PlanResponse:
    if not req.session_id:
        raise ValueError("session_id is required for planning")

    db_session = get_or_create_session(
        db,
        session_token=req.session_id,
        user_external_id=req.user_id,
    )

    trip_ctx = create_trip_context(
        db,
        session=db_session,
        req_message=req.message,
        origin=req.origin,
        start_date=req.start_date,
        end_date=req.end_date,
        budget_bucket=req.budget_bucket,
        group_size=req.group_size,
        vibes=req.vibes,
    )

    branch_specs = _call_openai_for_branches_raw(req)
    db_branches = create_branches_for_context(
        db,
        trip_context=trip_ctx,
        branch_specs=branch_specs,
        primary_index=0,
    )

    if not db_branches:
        raise ValueError("No branches generated for trip context")

    plan_branches: List[PlanBranch] = []
    for db_branch in db_branches:
        plan_branches.append(
            PlanBranch(
                id=str(db_branch.id),
                label=db_branch.label,
                description=db_branch.description or "",
                destination=db_branch.destination,
            )
        )

    primary_db_branch = db_branches[0]
    tiles_request = TilesSearchRequest(
        user_id=req.user_id,
        branch_id=primary_db_branch.id,
        origin=req.origin,
        destination=primary_db_branch.destination,
        start_date=req.start_date,
        end_date=req.end_date,
        budget_bucket=req.budget_bucket,
        group_size=req.group_size,
        vibes=req.vibes,
        session_id=req.session_id,
        trip_context_id=trip_ctx.id,
    )

    tiles_response = search_tiles(tiles_request)

    if tiles_response.tiles:
        snapshot_tiles_for_branch(
            db,
            branch=primary_db_branch,
            tiles=tiles_response.tiles,
        )

    response = PlanResponse(
        trip_context_id=trip_ctx.id,
        branches=plan_branches,
        tiles=tiles_response.tiles,
        primary_branch_id=str(primary_db_branch.id),
        tiles_request_id=(
            tiles_response.tiles_request_id
            if hasattr(tiles_response, "tiles_request_id")
            else tiles_response.request_id
        ),
        tiles_summary=tiles_response.summary,
    )

    db.commit()

    return response
