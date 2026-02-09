"""IATA airport code resolver — LLM-backed with state caching."""

import json
import logging

from langchain_openai import ChatOpenAI

from app.planner.state.schemas import GraphState

logger = logging.getLogger(__name__)


async def resolve_iata_codes(origin: str, destination: str, state: GraphState) -> tuple[str, str]:
    """Resolve IATA codes. Reads state first, falls back to LLM.

    Returns (origin_code, dest_code). Either may be "" if unresolvable.
    """
    origin_code = state.trip_plan.origin_iata or ""
    dest_code = state.trip_plan.destination_iata or ""

    if origin_code and dest_code:
        return origin_code, dest_code

    needs = []
    if origin and not origin_code:
        needs.append(f"origin: {origin}")
    if destination and not dest_code:
        needs.append(f"destination: {destination}")

    if not needs:
        return origin_code, dest_code

    try:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_tokens=50)
        prompt = (
            f"Return ONLY a JSON object with IATA airport codes.\n"
            f"Use the primary international airport for each city.\n"
            f"Cities: {', '.join(needs)}\n"
            f'Example: {{"origin": "SFO", "destination": "DPS"}}'
        )
        result = await llm.ainvoke([{"role": "user", "content": prompt}])
        raw = result.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if not raw:
            logger.warning("[IATA] Empty LLM response")
            return origin_code, dest_code
        codes = json.loads(raw)

        if not origin_code and "origin" in codes:
            origin_code = codes["origin"]
            state.trip_plan.origin_iata = origin_code
        if not dest_code and "destination" in codes:
            dest_code = codes["destination"]
            state.trip_plan.destination_iata = dest_code

        logger.info(f"[IATA] Resolved: {origin}→{origin_code}, {destination}→{dest_code}")
    except Exception as e:
        logger.warning(f"[IATA] LLM resolution failed: {e}")

    return origin_code, dest_code
